# Sit/Stand Timer — macOS Implementation Guide

This is the MacBook Pro counterpart to the Ubuntu version. The scheduling logic and beep are identical — only the menu bar integration, preferences window, and autostart mechanism differ, since macOS has no GTK/AppIndicator stack.

Use `sitstand_timer_macos.py` on the Mac (not the Linux `sitstand_timer.py` file).

---

## 1. Install prerequisites

**Xcode Command Line Tools** (needed for Python tooling in general):
```bash
xcode-select --install
```

**Homebrew**, if you don't already have it (skip if `brew --version` already works):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Python 3 + Tkinter**, via Homebrew (recommended over the Apple-provided system Python, which Apple discourages installing packages into):
```bash
brew install python
brew install python-tk
```

`python-tk` is important and easy to miss — Homebrew's `python` formula does **not** bundle Tkinter by default, so without this the Preferences window will fail with a `ModuleNotFoundError: No module named 'tkinter'`.

**Confirm the install and note the path** (you'll need this exact path later):
```bash
which python3
python3 --version
```
On Apple Silicon Macs this is typically `/opt/homebrew/bin/python3`; on Intel Macs, `/usr/local/bin/python3`.

**rumps** (the menu bar app framework — installs `pyobjc` frameworks as a dependency, which may take a minute):
```bash
python3 -m pip install rumps
```

## 2. Place the script

```bash
mkdir -p ~/Applications/SitStand
cp sitstand_timer_macos.py ~/Applications/SitStand/
```
(Adjust the source path to wherever you saved the downloaded file. `~/Applications` is just a convenient convention — any folder works.)

## 3. Test it manually first

```bash
python3 ~/Applications/SitStand/sitstand_timer_macos.py
```
(Use the exact `python3` path from Step 1 if `python3` alone doesn't resolve to your Homebrew install — check with `which python3` again if unsure.)

You should see text like `Stand in 45 minutes` appear directly in your menu bar within a second or two — no Dock icon, no Cmd+Tab entry, just the menu bar text (matching the Linux tray-only behavior). Click it to see **Preferences** and **Quit**.

Try Preferences — a small window with Start/End time and Sit/Stand duration fields should appear; changes save as you edit them, same as the Linux version. Closing the window (the red close button) just hides it; the app keeps running.

Press `Ctrl+C` in the terminal to stop it once you've confirmed it works, then move on to autostart.

## 4. Set up autostart (LaunchAgent)

macOS uses `launchd` instead of a `.desktop` file. Create a plist (replace `YOUR_USERNAME` and the `python3` path with your actual values from Step 1):

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.YOUR_USERNAME.sitstandtimer.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.YOUR_USERNAME.sitstandtimer</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>/Users/YOUR_USERNAME/Applications/SitStand/sitstand_timer_macos.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/sitstand-timer.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/sitstand-timer.err</string>
</dict>
</plist>
EOF
```

Load it (starts it immediately and registers it for future logins):
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.YOUR_USERNAME.sitstandtimer.plist
```

Confirm it's running:
```bash
launchctl list | grep sitstandtimer
```

Log out and back in (or reboot) once to confirm it comes up cleanly on its own.

## 5. Configure your schedule

Click the menu bar text → **Preferences**, and set your actual Start/End times and Sit/Stand durations. Settings are shared in the same file format as the Linux version, at `~/.config/sitstand-timer/config.json` — same schema, so you could copy a config over from the Linux machine if you want matching settings.

---

## Troubleshooting

**Nothing appears in the menu bar**
- Run it manually (Step 3) and read the terminal output for errors.
- Check `/tmp/sitstand-timer.err` if it's running via LaunchAgent (that's where stderr is redirected per the plist above).

**`ModuleNotFoundError: No module named 'tkinter'`**
- Run `brew install python-tk` and try again. If you're on a Python version other than the current Homebrew default, you may need `brew install python-tk@3.12` (match the version from `python3 --version`).

**`ModuleNotFoundError: No module named 'rumps'`**
- Confirm you installed rumps into the *same* Python you're running the script with: `python3 -m pip show rumps`. If empty, re-run `python3 -m pip install rumps` using the exact `python3` from `which python3`.

**A Dock icon / Python rocket ship appears anyway**
- This means the `LSUIElement` trick at the top of the script didn't take effect, usually because the `pyobjc-framework-Cocoa` package (a dependency of `rumps`) isn't installed. Run `python3 -m pip install pyobjc-framework-Cocoa` explicitly and retry.

**No sound plays**
- `afplay` ships with every Mac, so this is almost always a system volume/mute issue rather than a missing tool. Confirm with: `afplay /System/Library/Sounds/Ping.aiff` — if that's silent, it's a system audio setting, not the app.

**Preferences window doesn't visually update / feels laggy**
- Each keystroke in a spin box saves immediately (same "live" behavior as the Linux version) — this is expected, not a bug.

**I want to stop it permanently**
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.YOUR_USERNAME.sitstandtimer.plist
rm ~/Library/LaunchAgents/com.YOUR_USERNAME.sitstandtimer.plist
```
Optionally also remove `~/.config/sitstand-timer/` (settings) and `~/Applications/SitStand/` (the script).
