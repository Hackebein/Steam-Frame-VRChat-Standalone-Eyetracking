# Steam Frame NSD Helper and Eye Tracking for standalone VRChat

Fixes OSC startup for standalone VRChat on Steam Frame and sends native eye gaze
and blinking. Everything runs on the headset and starts automatically with VRChat.

## Install

Enable Developer Mode on the Frame, then run as the SteamOS user:

```bash
curl -fL https://github.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/archive/refs/heads/main.tar.gz -o frame-nsd.tar.gz &&
tar -xzf frame-nsd.tar.gz &&
bash Steam-Frame-VRChat-Standalone-Eyetracking-main/install.sh
```

Launch VRChat, enable **Action Menu → Options → OSC → Enabled**.
After installing or updating, fully close and reopen VRChat.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/main/uninstall.sh | bash
```

or

```bash
bash ~/.local/share/frame-vrchat-tracking/uninstall.sh
```

## Build from source

```bash
curl -fL https://github.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/archive/refs/heads/main.tar.gz -o frame-nsd.tar.gz &&
tar -xzf frame-nsd.tar.gz &&
bash Steam-Frame-VRChat-Standalone-Eyetracking-main/build.sh
```

Run `bash install.sh` to install the rebuilt binaries.

---

Tested on Frame with SteamOS 0.4.5, Lepton 3.0.5, and VRChat 2026.3.3.
