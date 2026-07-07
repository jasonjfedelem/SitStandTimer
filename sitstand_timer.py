#!/usr/bin/env python3
"""
Sit/Stand Pomodoro Timer for the GNOME top panel (Ubuntu 24.04).

Displays "Stand in X minutes" / "Sit in X minutes" in the top-bar tray,
alternating sit/stand states Monday-Friday within a configured time window.
Emits a short beep on every sit<->stand transition.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator3

import json
import os
import subprocess
import struct
import math
import wave
import tempfile
from datetime import datetime, timedelta

APP_ID = "sitstand-timer"
CONFIG_DIR = os.path.expanduser("~/.config/sitstand-timer")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "start_time": "08:00",
    "end_time": "17:00",
    "sit_minutes": 30,
    "stand_minutes": 10,
}

BEEP_FREQ_HZ = 277.18  # C#4 / Db4, closest piano note to 275 Hz
BEEP_DURATION_SEC = 0.5
BEEP_SAMPLE_RATE = 44100


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp_path, CONFIG_PATH)


# ---------------------------------------------------------------------------
# Beep generation / playback
# ---------------------------------------------------------------------------

def _generate_beep_wav():
    """Generate a 0.5s sine wave WAV file once and return its path."""
    fd, path = tempfile.mkstemp(prefix="sitstand-beep-", suffix=".wav")
    os.close(fd)

    n_samples = int(BEEP_SAMPLE_RATE * BEEP_DURATION_SEC)
    with wave.open(path, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(BEEP_SAMPLE_RATE)

        frames = bytearray()
        # Small fade in/out (5ms) to avoid audible clicks
        fade_samples = max(1, int(BEEP_SAMPLE_RATE * 0.005))
        for i in range(n_samples):
            t = i / BEEP_SAMPLE_RATE
            amplitude = 0.5
            if i < fade_samples:
                amplitude *= i / fade_samples
            elif i > n_samples - fade_samples:
                amplitude *= (n_samples - i) / fade_samples
            sample = amplitude * math.sin(2 * math.pi * BEEP_FREQ_HZ * t)
            frames += struct.pack("<h", int(sample * 32767))
        wav_file.writeframes(frames)

    return path


class Beeper:
    def __init__(self):
        self._wav_path = _generate_beep_wav()

    def play(self):
        for player in ("paplay", "aplay"):
            try:
                subprocess.Popen(
                    [player, self._wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except FileNotFoundError:
                continue


# ---------------------------------------------------------------------------
# Schedule / status logic
# ---------------------------------------------------------------------------

def _parse_hhmm(value):
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _next_start_datetime(now, start_h, start_m):
    """Find the next datetime (possibly today) that is a weekday at start time."""
    candidate = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    # Advance to the next weekday (Mon=0 ... Fri=4)
    while candidate.weekday() > 4:  # Sat=5, Sun=6
        candidate += timedelta(days=1)
    return candidate


def format_duration(seconds):
    """Return a display phrase like '5 minutes', with correct singular/plural."""
    seconds = max(0, int(round(seconds)))

    if seconds >= 3600:
        hours = max(1, round(seconds / 3600))
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit}"
    elif seconds >= 60:
        minutes = max(1, round(seconds / 60))
        if minutes >= 60:
            # Rounding pushed us into the next hour (e.g. 3599s -> "60 minutes")
            return "1 hour"
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit}"
    else:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"


def get_status(now, cfg):
    """
    Compute current status.

    Returns dict:
        state: "standing" | "sitting" | "outside"
        label: full display text for the tray, e.g. "Stand in 5 minutes"
        seconds_remaining: float, seconds left in the current state/countdown
    """
    start_h, start_m = _parse_hhmm(cfg["start_time"])
    end_h, end_m = _parse_hhmm(cfg["end_time"])
    sit_sec = cfg["sit_minutes"] * 60
    stand_sec = cfg["stand_minutes"] * 60
    cycle_sec = sit_sec + stand_sec

    is_weekday = now.weekday() <= 4
    start_today = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_today = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    in_window = is_weekday and start_today <= now < end_today

    if in_window:
        elapsed = (now - start_today).total_seconds()
        elapsed_in_cycle = elapsed % cycle_sec if cycle_sec > 0 else 0

        if elapsed_in_cycle < stand_sec:
            state = "standing"
            remaining = stand_sec - elapsed_in_cycle
            label = f"Sit in {format_duration(remaining)}"
        else:
            state = "sitting"
            remaining = cycle_sec - elapsed_in_cycle
            label = f"Stand in {format_duration(remaining)}"

        return {"state": state, "label": label, "seconds_remaining": remaining}

    # Outside the active window: count down to the next scheduled start.
    next_start = _next_start_datetime(now, start_h, start_m)
    remaining = (next_start - now).total_seconds()
    label = f"Stand in {format_duration(remaining)}"
    return {"state": "outside", "label": label, "seconds_remaining": remaining}


# ---------------------------------------------------------------------------
# Preferences window
# ---------------------------------------------------------------------------

class PreferencesWindow(Gtk.Window):
    def __init__(self, cfg, on_change):
        super().__init__(title="Sit/Stand Timer Preferences")
        self.set_border_width(12)
        self.set_resizable(False)
        self.cfg = cfg
        self.on_change = on_change
        self._loading = True

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.add(grid)

        start_h, start_m = _parse_hhmm(cfg["start_time"])
        end_h, end_m = _parse_hhmm(cfg["end_time"])

        # Start time
        grid.attach(Gtk.Label(label="Start time (standing begins):", xalign=0), 0, 0, 1, 1)
        self.start_hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.start_hour.set_value(start_h)
        self.start_min = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.start_min.set_value(start_m)
        start_box = Gtk.Box(spacing=4)
        start_box.pack_start(self.start_hour, False, False, 0)
        start_box.pack_start(Gtk.Label(label=":"), False, False, 0)
        start_box.pack_start(self.start_min, False, False, 0)
        grid.attach(start_box, 1, 0, 1, 1)

        # End time
        grid.attach(Gtk.Label(label="End time:", xalign=0), 0, 1, 1, 1)
        self.end_hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.end_hour.set_value(end_h)
        self.end_min = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.end_min.set_value(end_m)
        end_box = Gtk.Box(spacing=4)
        end_box.pack_start(self.end_hour, False, False, 0)
        end_box.pack_start(Gtk.Label(label=":"), False, False, 0)
        end_box.pack_start(self.end_min, False, False, 0)
        grid.attach(end_box, 1, 1, 1, 1)

        # Sit duration
        grid.attach(Gtk.Label(label="Sit duration (minutes):", xalign=0), 0, 2, 1, 1)
        self.sit_minutes = Gtk.SpinButton.new_with_range(1, 240, 1)
        self.sit_minutes.set_value(cfg["sit_minutes"])
        grid.attach(self.sit_minutes, 1, 2, 1, 1)

        # Stand duration
        grid.attach(Gtk.Label(label="Stand duration (minutes):", xalign=0), 0, 3, 1, 1)
        self.stand_minutes = Gtk.SpinButton.new_with_range(1, 240, 1)
        self.stand_minutes.set_value(cfg["stand_minutes"])
        grid.attach(self.stand_minutes, 1, 3, 1, 1)

        note = Gtk.Label(label="Runs Monday-Friday. Changes are saved automatically.")
        note.set_xalign(0)
        note.get_style_context().add_class("dim-label")
        grid.attach(note, 0, 4, 2, 1)

        for widget in (
            self.start_hour, self.start_min,
            self.end_hour, self.end_min,
            self.sit_minutes, self.stand_minutes,
        ):
            widget.connect("value-changed", self._on_value_changed)

        self._loading = False
        self.connect("delete-event", self._on_close)

    def _on_value_changed(self, _widget):
        if self._loading:
            return
        self.cfg["start_time"] = f"{int(self.start_hour.get_value()):02d}:{int(self.start_min.get_value()):02d}"
        self.cfg["end_time"] = f"{int(self.end_hour.get_value()):02d}:{int(self.end_min.get_value()):02d}"
        self.cfg["sit_minutes"] = int(self.sit_minutes.get_value())
        self.cfg["stand_minutes"] = int(self.stand_minutes.get_value())
        save_config(self.cfg)
        self.on_change(self.cfg)

    def _on_close(self, *_args):
        self.hide()
        return True  # Prevent destruction; keep the window around for reuse


# ---------------------------------------------------------------------------
# Tray indicator app
# ---------------------------------------------------------------------------

class SitStandApp:
    def __init__(self):
        self.cfg = load_config()
        self.beeper = Beeper()
        self.prefs_window = None
        self._last_state = None

        self.indicator = AppIndicator3.Indicator.new(
            APP_ID,
            "alarm-symbolic",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Sit/Stand Timer")

        self.menu = Gtk.Menu()

        prefs_item = Gtk.MenuItem(label="Preferences")
        prefs_item.connect("activate", self._show_preferences)
        self.menu.append(prefs_item)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._quit)
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        self._tick()
        GLib.timeout_add_seconds(1, self._tick)

    def _show_preferences(self, _widget):
        if self.prefs_window is None:
            self.prefs_window = PreferencesWindow(self.cfg, self._on_config_changed)
        self.prefs_window.show_all()
        self.prefs_window.present()

    def _on_config_changed(self, new_cfg):
        self.cfg = new_cfg
        self._tick()

    def _quit(self, _widget):
        Gtk.main_quit()

    def _tick(self):
        now = datetime.now()
        status = get_status(now, self.cfg)

        self.indicator.set_label(status["label"], "")

        current_state = status["state"]
        if (
            self._last_state is not None
            and self._last_state != current_state
            and self._last_state != "outside"
            and current_state != "outside"
        ):
            self.beeper.play()

        self._last_state = current_state
        return True  # keep the GLib timeout running


def main():
    app = SitStandApp()
    Gtk.main()


if __name__ == "__main__":
    main()
