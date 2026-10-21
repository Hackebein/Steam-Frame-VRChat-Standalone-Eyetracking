#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
    printf '%s\n' 'Usage: bash uninstall.sh' 'Stop and remove Frame VRChat Tracking.'
    exit 0
fi
[[ $# == 0 ]] || {
    printf '%s\n' 'Usage: bash uninstall.sh' >&2
    exit 2
}
((EUID != 0)) || {
    printf '%s\n' 'Run as the SteamOS user, without sudo.' >&2
    exit 1
}
for dependency in python3 systemctl flock; do
    command -v "$dependency" >/dev/null || {
        printf 'Missing command: %s\n' "$dependency" >&2
        exit 1
    }
done
unit=frame-vrchat-tracking.service
target="$HOME/.local/share/frame-vrchat-tracking"
unit_path="$HOME/.config/systemd/user/$unit"
[[ ! -L "$target" && ! -L "$unit_path" ]] || {
    printf '%s\n' 'Installation paths must not be symbolic links.' >&2
    exit 1
}
systemctl --user show-environment >/dev/null
exec 9>"${XDG_RUNTIME_DIR:?Run inside the logged-in Frame session}/frame-vrchat-tracking-install.lock"
flock -n 9 || {
    printf '%s\n' 'An install or uninstall is already running.' >&2
    exit 1
}
if [[ -f "$unit_path" ]]; then
    systemctl --user disable --now "$unit"
fi
if [[ -f "$target/runtime.py" ]]; then
    if ! python3 -B "$target/runtime.py" stop-helper; then
        printf '%s\n' 'Container cleanup failed; close VRChat to end any remaining helper. Continuing local removal.' >&2
    fi
fi
rm -f -- "$unit_path"
systemctl --user daemon-reload
rm -rf -- "$target"
state="${XDG_STATE_HOME:-$HOME/.local/state}/frame-vrchat-tracking"
if [[ -d "$state" && ! -L "$state" ]]; then
    rm -f -- "$state/eyes.log" "$state/eyes.log.1"
    rmdir -- "$state" 2>/dev/null || true
fi
printf '%s\n' 'Removed Frame VRChat Tracking.'
