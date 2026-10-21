#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == --help ]]; then
    printf '%s\n' 'Usage: bash install.sh' 'Install or update Frame VRChat Tracking for this user.'
    exit 0
fi
[[ $# == 0 ]] || {
    printf '%s\n' 'Usage: bash install.sh' >&2
    exit 2
}
((EUID != 0)) || {
    printf '%s\n' 'Run as the SteamOS user, without sudo.' >&2
    exit 1
}
[[ "$(uname -m)" == aarch64 ]] || {
    printf '%s\n' 'This package requires an aarch64 Steam Frame.' >&2
    exit 1
}
for dependency in python3 podman systemctl ldd flock install mktemp; do
    command -v "$dependency" >/dev/null || {
        printf 'Missing command: %s\n' "$dependency" >&2
        exit 1
    }
done
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python3 - "$root/helper" <<'PY'
import ast, pathlib, sys
for name in ("daemon.py", "runtime.py"):
    ast.parse((pathlib.Path(sys.argv[1]) / name).read_text(), filename=name)
PY
export XDG_RUNTIME_DIR="/run/user/$EUID"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
systemctl --user show-environment >/dev/null
podman info --format '{{.Host.Arch}}' >/dev/null
exec 9>"$XDG_RUNTIME_DIR/frame-vrchat-tracking-install.lock"
flock -n 9 || {
    printf '%s\n' 'An install or uninstall is already running.' >&2
    exit 1
}
libraries="$(ldd "$root/helper/frame-eyes" 2>&1)" || {
    printf '%s\n' "$libraries" >&2
    exit 1
}
while IFS= read -r library; do
    [[ "$library" != *'not found'* ]] || {
        printf 'Missing library: %s\n' "$library" >&2
        exit 1
    }
done <<<"$libraries"

unit=frame-vrchat-tracking.service
parent="$HOME/.local/share"
target="$parent/frame-vrchat-tracking"
unit_dir="$HOME/.config/systemd/user"
unit_path="$unit_dir/$unit"
[[ ! -L "$target" && ! -L "$unit_path" ]] || {
    printf '%s\n' 'Installation paths must not be symbolic links.' >&2
    exit 1
}
install -d -m 755 "$parent" "$unit_dir"
work_dir="$(mktemp -d "$parent/.frame-vrchat-tracking-install.XXXXXXXX")"
keep_backup=false
cleanup() {
    if "$keep_backup"; then
        printf 'Recovery files kept in %s\n' "$work_dir" >&2
    else
        rm -rf -- "$work_dir"
    fi
}
trap cleanup EXIT
stage="$work_dir/new"
install -d -m 755 "$stage"
for name in daemon.py runtime.py frame-nsd-helper.jar; do
    install -m 644 "$root/helper/$name" "$stage/$name"
done
install -m 755 "$root/helper/frame-eyes" "$stage/frame-eyes"
for name in uninstall.sh README.md LICENSE; do
    install -m 644 "$root/$name" "$stage/$name"
done

was_active=false
was_enabled=false
had_unit=false
replaced=false
systemctl --user is-active --quiet "$unit" && was_active=true
systemctl --user is-enabled --quiet "$unit" && was_enabled=true
if [[ -f "$unit_path" ]]; then
    cp -p -- "$unit_path" "$work_dir/previous.service"
    had_unit=true
fi
rollback() {
    code=$1
    trap - ERR
    set +e
    printf '%s\n' 'Install failed; restoring the previous installation.' >&2
    systemctl --user disable --now "$unit" >/dev/null 2>&1
    if "$replaced"; then rm -rf -- "$target" || keep_backup=true; fi
    if [[ -d "$work_dir/previous" ]]; then mv -- "$work_dir/previous" "$target" || keep_backup=true; fi
    if "$had_unit"; then
        cp -- "$work_dir/previous.service" "$unit_path" || keep_backup=true
    else rm -f -- "$unit_path" || keep_backup=true; fi
    systemctl --user daemon-reload || keep_backup=true
    if "$was_enabled"; then systemctl --user enable "$unit" >/dev/null 2>&1 || keep_backup=true; fi
    if "$was_active"; then systemctl --user start "$unit" || keep_backup=true; fi
    exit "$code"
}
trap 'rollback "$?"' ERR
if "$was_active"; then systemctl --user stop "$unit"; fi
if [[ -d "$target" ]]; then
    mv -- "$target" "$work_dir/previous"
fi
mv -- "$stage" "$target"
replaced=true
install -m 644 "$root/helper/$unit" "$unit_path"
systemctl --user daemon-reload
systemctl --user enable --now "$unit"
sleep 1
systemctl --user is-active --quiet "$unit"
trap - ERR
printf '%s\n' 'Installed. Launch standalone VRChat normally and keep OSC enabled.'
