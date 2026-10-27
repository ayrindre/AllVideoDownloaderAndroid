#!/usr/bin/env bash
# Fetch the Android FFmpeg/FFprobe CLI executables that replace the Windows
# .exe files the desktop build downloads at runtime.
#
# Source: hzw1199/Android-FFmpeg-Prebuilt (LGPL-2.1, arm64-v8a, minSdk 28).
# The CLI executables are self-contained PIE binaries that only link against
# Android system libraries (libc, libm, libz, libandroid, mediandk...).
#
# Blob SHAs are pinned for reproducibility. GitHub's git-blobs API serves
# files up to 100 MB as base64 — no package manager / NDK build required.
set -euo pipefail

REPO="hzw1199/Android-FFmpeg-Prebuilt"
REF="main"
VERSION_DIR="ffmpeg-9.0"
DEST="$(dirname "$0")/../src/assets/bin/arm64-v8a"
mkdir -p "$DEST"

# sha:path — update together when bumping the FFmpeg version
FFMPEG_SHA="602b24c9e967863ff608a685eaaad10ea6711758"
FFPROBE_SHA="8877951d7e7fca19bc04c5b9fa113b5e2339b5f2"

fetch_blob() {
    local sha="$1"
    local out="$2"
    if [[ -s "$out" ]]; then
        echo "  • $(basename "$out") already present ($(du -h "$out" | cut -f1))"
        return
    fi
    echo "  • fetching $(basename "$out") (blob ${sha:0:10}…)"
    curl -fsSL "https://api.github.com/repos/$REPO/git/blobs/$sha" \
        | python3 -c "import json,sys,base64; sys.stdout.buffer.write(base64.b64decode(json.load(sys.stdin)['content']))" \
        > "$out"
    chmod +x "$out"
}

echo "FFmpeg bootstrap (Android arm64-v8a, $VERSION_DIR)"
fetch_blob "$FFMPEG_SHA" "$DEST/ffmpeg"
fetch_blob "$FFPROBE_SHA" "$DEST/ffprobe"

# sanity: ELF 64-bit, AArch64 (machine type 183), PIE
python3 - "$DEST/ffmpeg" "$DEST/ffprobe" <<'PY'
import sys
for path in sys.argv[1:]:
    with open(path, "rb") as fh:
        head = fh.read(20)
    assert head[:4] == b"\x7fELF", f"{path}: not an ELF"
    assert head[4] == 2, f"{path}: not 64-bit"
    machine = int.from_bytes(head[18:20], "little")
    assert machine == 183, f"{path}: not AArch64 (machine {machine})"
    print(f"  ✓ {path}: valid arm64 ELF")
PY
echo "FFmpeg bootstrap complete."
