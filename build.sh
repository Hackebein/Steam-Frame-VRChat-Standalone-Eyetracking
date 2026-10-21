#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --help && $# == 1 ]]; then
    printf '%s\n' 'Usage: bash build.sh' 'Build on aarch64 Linux with g++, curl, and tar; downloads a pinned temporary JDK.'
    exit 0
fi
[[ $# == 0 ]] || {
    printf '%s\n' 'Usage: bash build.sh' >&2
    exit 2
}
[[ "$(uname -s)" == Linux && "$(uname -m)" == aarch64 ]] || {
    printf '%s\n' 'Build on the Frame or compatible aarch64 Linux.' >&2
    exit 1
}
for dependency in g++ curl sha256sum tar install mktemp; do
    command -v "$dependency" >/dev/null || {
        printf '%s\n' "Missing command: $dependency" >&2
        exit 1
    }
done
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
mkdir -p "$work_dir/classes"

printf '%s\n' 'Downloading temporary Temurin JDK 17.0.20.1+1.'
curl -fL --retry 3 'https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.20.1_1.tar.gz' -o "$work_dir/jdk.tar.gz"
printf '%s  %s\n' '457b57af8f9c93ec39080bb8c764f559dc8c89a6da1a39d718a400b7890d3e41' "$work_dir/jdk.tar.gz" |
    sha256sum --check --status || {
    printf '%s\n' 'Temurin JDK checksum mismatch; build stopped.' >&2
    exit 1
}
mkdir -p "$work_dir/jdk"
tar -xzf "$work_dir/jdk.tar.gz" -C "$work_dir/jdk" --strip-components=1

curl -fL --retry 3 https://dl.google.com/dl/android/maven2/com/android/tools/r8/9.5.28/r8-9.5.28.jar -o "$work_dir/r8.jar"
printf '%s  %s\n' '38a9ffaaebbd17d1514e3ecbff5a85b989bb13c551b9e224c7409514eea84ff5' "$work_dir/r8.jar" |
    sha256sum --check --status || {
    printf '%s\n' 'D8 checksum mismatch; build stopped.' >&2
    exit 1
}

g++ -std=c++17 -O2 -Wall -Wextra -Werror -pthread "$root/helper/frame-eyes.cpp" -o "$work_dir/frame-eyes"
"$work_dir/jdk/bin/javac" --release 8 -g -d "$work_dir/classes" "$root/helper/FrameNsdHelper.java"
"$work_dir/jdk/bin/jar" cf "$work_dir/classes.jar" -C "$work_dir/classes" .
"$work_dir/jdk/bin/java" -cp "$work_dir/r8.jar" com.android.tools.r8.D8 --release --min-api 30 --no-desugaring --output "$work_dir/frame-nsd-helper.jar" "$work_dir/classes.jar"

install -m 755 "$work_dir/frame-eyes" "$root/helper/frame-eyes"
install -m 644 "$work_dir/frame-nsd-helper.jar" "$root/helper/frame-nsd-helper.jar"
printf '%s\n' 'Built helper/frame-eyes and helper/frame-nsd-helper.jar.'
