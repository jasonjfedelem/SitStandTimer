# Sit/Stand Pomodoro Timer — Requirements

## 1. Overview
A lightweight background application that displays a sit/stand cycle status in the Ubuntu top-bar tray (via AppIndicator), with a simple GTK configuration window. Runs Monday–Friday during a configured time window, alternating between "sit" and "stand" states, with an audible alert at each transition.

## 2. Platform
- Ubuntu 24.04 (GNOME 46)
- Requires the **AppIndicator and KStatusNotifierItem Support** GNOME Shell extension to be enabled (standard requirement for any tray icon on modern GNOME).
- Built in Python 3 using `PyGObject` (GTK3 + `AyatanaAppIndicator3`).
- This is a standalone tray indicator, separate from the existing 4-timezone clock display (which is the built-in GNOME multi-timezone clock, not something third-party apps can inject into).

## 3. Schedule Logic
- Active days: **Monday–Friday only**. No activity on Saturday/Sunday.
- Configurable:
  - **Start time** (daily) — always begins in **standing** state.
  - **End time** (daily).
  - **Sit duration** (minutes).
  - **Stand duration** (minutes).
- State is **computed live from wall-clock time** (no stored "progress"): elapsed time since today's Start → modulo (sit + stand) → determines current state and time remaining in that state. This makes the app naturally resilient to restarts, sleep/suspend, and logouts — no special resume logic needed.
- If config is edited mid-cycle, the new durations simply apply immediately to future calculations (may cause a state jump) — no special handling needed.

## 4. Tray Display Text
- **During active window:**
  - Sitting → `"Stand in X minutes"` / `"Stand in X seconds"`
  - Standing → `"Sit in X minutes"` / `"Sit in X seconds"`
- **Outside active window (incl. weekends):**
  - `"Stand in X hours"` or `"Stand in X minutes"` (counting down to next scheduled Start time, always framed as "stand" since that's the opening state)
- **Rounding rules:**
  - ≥1 hour remaining → round to nearest hour, hours-only display
  - ≥60 seconds and <1 hour remaining → round to nearest minute, minutes-only display
  - <60 seconds remaining → show exact seconds, and switch phrasing to "...in X seconds"
  - Proper singular/grammar: "1 minute" / "2 minutes", "1 second" / "5 seconds", "1 hour" / "3 hours"
- No desktop popup notifications — tray text is the only indicator besides sound.

## 5. Sound
- On every sit↔stand transition (only during the active window — no beep outside scheduled hours, and no beep when the window first opens or closes for the day):
  - Play a **0.5 second sine wave beep** at **277.18 Hz (C#4/Db4)** — closest piano note to 275 Hz.
  - Not configurable/mutable (no volume/mute setting).

## 6. Tray Interaction
- Clicking the tray indicator opens a menu with:
  - **Preferences** — opens the config window.
  - **Quit** — exits the app.

## 7. Config Window
- GTK-based, simple form with fields for:
  - Start time (hour/minute)
  - End time (hour/minute)
  - Sit duration (minutes)
  - Stand duration (minutes)
- Changes apply **immediately** (no Save button) — live-editing the in-memory config and config file.
- Config window can be closed independently; tray indicator keeps running regardless of whether the config window is open (closing the window hides it, it does not quit the app).

## 8. Persistence & Startup
- Config stored at `~/.config/sitstand-timer/config.json`.
- App auto-starts on login via a `.desktop` file in `~/.config/autostart/`.
- No manual pause/resume/skip controls.

## 9. Out of Scope
- No desktop notifications/popups.
- No manual state override or pause.
- No multi-day / weekend scheduling.
- No sound configurability.
