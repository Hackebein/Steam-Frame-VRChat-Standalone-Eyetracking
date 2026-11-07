# Steam Frame Eye Tracking for VRChat

## One last update

I started this because OSC wouldn't start in standalone VRChat on my Steam Frame.
I only wanted to fix OSC, but once I had a workaround, I used it to forward face tracking data, too.
That grew into this add-on, which runs on the headset and starts automatically with VRChat.

Since then, Valve has re-enabled Android Network Service Discovery (NSD) in Lepton 3.0.9 so VRChat can start OSC.
The famous Project Babble also released a [Frame Runtime](https://github.com/Project-Babble/Babble-Frame-Runtime) that offers an on-headset solution.

## Original instructions

### Install

Enable Developer Mode on the Frame, then run as the SteamOS user:

```bash
curl -fL https://github.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/archive/refs/heads/main.tar.gz -o frame-vrchat-eye-tracking.tar.gz &&
tar -xzf frame-vrchat-eye-tracking.tar.gz &&
bash Steam-Frame-VRChat-Standalone-Eyetracking-main/install.sh
```

Launch VRChat, enable **Action Menu → Options → OSC → Enabled**.
After installing or updating, fully close and reopen VRChat.

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/main/uninstall.sh | bash
```

or

```bash
bash ~/.local/share/frame-vrchat-tracking/uninstall.sh
```

### Build from source

```bash
curl -fL https://github.com/Hackebein/Steam-Frame-VRChat-Standalone-Eyetracking/archive/refs/heads/main.tar.gz -o frame-vrchat-eye-tracking.tar.gz &&
tar -xzf frame-vrchat-eye-tracking.tar.gz &&
bash Steam-Frame-VRChat-Standalone-Eyetracking-main/build.sh
```

Run `bash install.sh` to install the rebuilt binaries.

---

Tested on Frame with SteamOS 0.4.5, Lepton 3.0.5, and VRChat 2026.3.3.
