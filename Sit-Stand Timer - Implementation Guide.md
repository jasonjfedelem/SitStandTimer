# Sit/Stand Timer — Implementation Guide

## What you're installing
A single Python script (`sitstand_timer.py`) that runs quietly in the background and puts a small text indicator in your top-bar tray, next to your existing clocks. No desktop app icon, no dock entry — just the tray text and a right-click menu.

---

## 1. Install prerequisites

Open a terminal and run:

```bash
sudo apt update
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gnome-shell-extension-appindicator pulseaudio-utils
```

- `python3-gi` / `gir1.2-gtk-3.0` — GTK bindings for the preferences window.
- `gir1.2-ayatanaappindicator3-0.1` — lets a plain Python script put an item in the tray.
- `gnome-shell-extension-appindicator` — GNOME 46 removed native tray support; this extension restores it. (If your 4 timezone clocks already show in the tray, you may already have this — but install it anyway, it's harmless if already present.)
- `pulseaudio-utils` — provides `paplay`, used to play the beep. Ubuntu 24.04's PipeWire audio stack supports this out of the box.

## 2. Enable the AppIndicator extension

Check if it's enabled:

```bash
gnome-extensions list | grep appindicator
```

If you see `ubuntu-appindicators@ubuntu.com` listed, enable it (safe to run even if already on):

```bash
gnome-extensions enable ubuntu-appindicators@ubuntu.com
```

If nothing is listed, open the **Extensions** app (install via `sudo apt install gnome-shell-extension-manager` if you don't have it) and enable "Ubuntu AppIndicators" from there instead.

You may need to log out and back in once for this to take full effect.

## 3. Place the script

Create a permanent home for it and copy the script there:

```bash
mkdir -p ~/.local/share/sitstand-timer
cp sitstand_timer.py ~/.local/share/sitstand-timer/
chmod +x ~/.local/share/sitstand-timer/sitstand_timer.py
```

(Adjust the source path above to wherever you saved the downloaded file.)

## 4. Test it manually first

Before wiring up autostart, run it directly so you can see any errors in the terminal:

```bash
python3 ~/.local/share/sitstand-timer/sitstand_timer.py
```

You should see a small clock-style icon and text appear in your top bar within a second or two, showing something like `Stand in 45 minutes` (or an "outside window" message if it's currently outside your configured hours). Right-click it to see **Preferences** and **Quit**.

If nothing appears, see Troubleshooting below. Once it's working, press `Ctrl+C` in the terminal to stop it, and move on to autostart.

## 5. Set up autostart

Create the autostart entry:

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/sitstand-timer.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Sit Stand Timer
Exec=python3 /home/YOUR_USERNAME/.local/share/sitstand-timer/sitstand_timer.py
X-GNOME-Autostart-enabled=true
EOF
```

**Replace `YOUR_USERNAME`** with your actual username (or replace the whole path with `$HOME/.local/share/sitstand-timer/sitstand_timer.py` — either works, but `.desktop` files don't always expand `$HOME` reliably, so a literal absolute path is safer).

Log out and back in (or just reboot) to confirm it starts automatically.

## 6. Configure your schedule

Right-click the tray indicator → **Preferences**. Set:
- **Start time** — when standing begins each weekday morning.
- **End time** — when the cycle stops for the day.
- **Sit duration** / **Stand duration** — in minutes.

Changes save immediately as you adjust the spin buttons — no Save button needed. You can close the Preferences window at any time (it just hides); the tray keeps running and picks up the new settings on its very next tick (within 1 second).

Your settings live in `~/.config/sitstand-timer/config.json` if you ever want to inspect or back them up up directly.

---

## How the display text works

| Situation | Example text |
|---|---|
| Standing, 8 min left | `Sit in 8 minutes` |
| Standing, 45 sec left | `Sit in 45 seconds` |
| Sitting, 12 min left | `Stand in 12 minutes` |
| Outside your window, hours away | `Stand in 6 hours` |
| Outside your window, close | `Stand in 12 minutes` |
| Weekend | `Stand in 44 hours` (counts down to Monday's start) |

A short beep (0.5s, C#4/Db4 ≈ 277 Hz) plays every time it switches between sitting and standing **during your active window**. No beep plays when the window opens or closes for the day, and none plays on weekends.

## A note on the last stretch before End Time

Because the sit/stand cycle runs on a fixed rhythm from your Start time, it's possible for the countdown to say something like "Stand in 20 minutes" moments before your End time hits — at which point it will immediately flip to the next-day countdown (e.g. "Stand in 15 hours"). This is expected: the app always tells you the true state of an ongoing cycle, but the cycle itself simply stops being relevant once the window closes. If this bothers you, picking a Sit/Stand duration combo that divides evenly into your Start–End window will avoid it (e.g. 8:00–17:00 with 30/10 minute cycles divides cleanly).

---

## Troubleshooting

**No icon appears in the tray at all**
- Confirm the AppIndicator extension is enabled (Step 2) and that you've logged out/in since enabling it.
- Run the script manually from a terminal (Step 4) and read any error output.

**Icon appears but shows a broken-image glyph instead of the alarm icon**
- Cosmetic only — the text label will still work. You can swap the icon name in `sitstand_timer.py` (search for `"alarm-symbolic"`) for another icon from your system's icon theme if you'd like.

**No sound plays**
- Test manually: `paplay ~/.config/sitstand-timer/*.wav` won't work directly (the beep file is a temp file, regenerated each run) — instead just check `paplay` exists: `which paplay`. If missing, re-run `sudo apt install pulseaudio-utils`.
- Check system volume isn't muted.
- If `paplay` still fails silently, install `alsa-utils` (`sudo apt install alsa-utils`) — the script automatically falls back to `aplay`.

**Preferences window changes don't seem to apply**
- Give it up to 1 second (the update loop ticks once per second).
- Check `~/.config/sitstand-timer/config.json` was actually updated (its timestamp should change when you adjust a field).

**I want to change the beep tone**
- Edit the `BEEP_FREQ_HZ` constant near the top of `sitstand_timer.py`.

**I want to stop it permanently**
```bash
rm ~/.config/autostart/sitstand-timer.desktop
pkill -f sitstand_timer.py
```
Optionally also remove `~/.config/sitstand-timer/` (your saved settings) and `~/.local/share/sitstand-timer/` (the script itself).
