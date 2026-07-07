#!/usr/bin/env python3
"""
Sit/Stand Pomodoro Timer for the macOS menu bar.

Displays "Stand in X minutes" / "Sit in X minutes" as text in the menu bar,
alternating sit/stand states Monday-Friday within a configured time window.
Emits a short beep on every sit<->stand transition.
"""

# Hide the Dock icon / Cmd+Tab entry so this behaves like a pure menu-bar
# utility, matching the Linux tray-only behavior. Must happen before rumps
# creates the underlying NSApplication.
try:
    from Foundation import NSBundle
    _info = NSBundle.mainBundle().infoDictionary()
    _info["LSUIElement"] = "1"
except Exception:
    pass

import rumps

import json
import os
import subprocess
import struct
import math
import wave
import tempfile
import threading
import tkinter as tk
from datetime import datetime, timedelta

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
        try:
            subprocess.Popen(
                ["afplay", self._wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Schedule / status logic (identical to the Linux version)
# ---------------------------------------------------------------------------

def _parse_hhmm(value):
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _next_start_datetime(now, start_h, start_m):
    """Find the next datetime (possibly today) that is a weekday at start time."""
    candidate = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
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
        label: full display text, e.g. "Stand in 5 minutes"
        seconds_remaining: float
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

    next_start = _next_start_datetime(now, start_h, start_m)
    remaining = (next_start - now).total_seconds()
    label = f"Stand in {format_duration(remaining)}"
    return {"state": "outside", "label": label, "seconds_remaining": remaining}


# ---------------------------------------------------------------------------
# Preferences window (Tkinter, run in its own thread on demand)
# ---------------------------------------------------------------------------

class PreferencesDialog:
    _lock = threading.Lock()
    _open = False

    @classmethod
    def open(cls, cfg, on_save):
        with cls._lock:
            if cls._open:
                return
            cls._open = True
        thread = threading.Thread(target=cls._run, args=(cfg, on_save), daemon=True)
        thread.start()

    @classmethod
    def _run(cls, cfg, on_save):
        root = tk.Tk()
        root.title("Sit/Stand Timer Preferences")
        root.resizable(False, False)

        start_h, start_m = cfg["start_time"].split(":")
        end_h, end_m = cfg["end_time"].split(":")

        v_start_h = tk.StringVar(value=start_h)
        v_start_m = tk.StringVar(value=start_m)
        v_end_h = tk.StringVar(value=end_h)
        v_end_m = tk.StringVar(value=end_m)
        v_sit = tk.StringVar(value=str(cfg["sit_minutes"]))
        v_stand = tk.StringVar(value=str(cfg["stand_minutes"]))

        def spin(var, frm, to, width=4):
            return tk.Spinbox(root, from_=frm, to=to, width=width, textvariable=var, wrap=True)

        pad = {"padx": 10, "pady": 6}

        tk.Label(root, text="Start time (H / M):").grid(row=0, column=0, sticky="w", **pad)
        spin(v_start_h, 0, 23).grid(row=0, column=1, **pad)
        spin(v_start_m, 0, 59).grid(row=0, column=2, **pad)

        tk.Label(root, text="End time (H / M):").grid(row=1, column=0, sticky="w", **pad)
        spin(v_end_h, 0, 23).grid(row=1, column=1, **pad)
        spin(v_end_m, 0, 59).grid(row=1, column=2, **pad)

        tk.Label(root, text="Sit duration (min):").grid(row=2, column=0, sticky="w", **pad)
        spin(v_sit, 1, 240).grid(row=2, column=1, **pad)

        tk.Label(root, text="Stand duration (min):").grid(row=3, column=0, sticky="w", **pad)
        spin(v_stand, 1, 240).grid(row=3, column=1, **pad)

        note = tk.Label(root, text="Runs Monday-Friday. Saved automatically.", fg="gray")
        note.grid(row=4, column=0, columnspan=3, pady=(0, 4))

        def save_current(*_args):
            try:
                new_cfg = {
                    "start_time": f"{int(v_start_h.get()):02d}:{int(v_start_m.get()):02d}",
                    "end_time": f"{int(v_end_h.get()):02d}:{int(v_end_m.get()):02d}",
                    "sit_minutes": int(v_sit.get()),
                    "stand_minutes": int(v_stand.get()),
                }
            except ValueError:
                return  # ignore transient invalid/empty states while typing
            save_config(new_cfg)
            on_save(new_cfg)

        for var in (v_start_h, v_start_m, v_end_h, v_end_m, v_sit, v_stand):
            var.trace_add("write", save_current)

        def on_close():
            save_current()
            root.destroy()

        close_btn = tk.Button(root, text="Close", command=on_close)
        close_btn.grid(row=5, column=0, columnspan=3, pady=(4, 10))
        root.protocol("WM_DELETE_WINDOW", on_close)

        root.mainloop()
        with PreferencesDialog._lock:
            PreferencesDialog._open = False


# ---------------------------------------------------------------------------
# Menu bar app
# ---------------------------------------------------------------------------

class SitStandMenuBarApp(rumps.App):
    def __init__(self):
        super().__init__("Sit/Stand Timer", quit_button=None)
        self.cfg = load_config()
        self.beeper = Beeper()
        self._last_state = None
        self.menu = ["Preferences", "Quit"]

        self.timer = rumps.Timer(self.tick, 1)
        self.timer.start()
        self.tick(None)

    @rumps.clicked("Preferences")
    def show_preferences(self, _sender):
        PreferencesDialog.open(self.cfg, self._on_config_changed)

    @rumps.clicked("Quit")
    def quit_app(self, _sender):
        rumps.quit_application()

    def _on_config_changed(self, new_cfg):
        self.cfg = new_cfg
        self.tick(None)

    def tick(self, _sender):
        now = datetime.now()
        status = get_status(now, self.cfg)
        self.title = status["label"]

        current_state = status["state"]
        if (
            self._last_state is not None
            and self._last_state != current_state
            and self._last_state != "outside"
            and current_state != "outside"
        ):
            self.beeper.play()
        self._last_state = current_state


if __name__ == "__main__":
    SitStandMenuBarApp().run()
