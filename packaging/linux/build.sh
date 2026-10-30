#!/usr/bin/env bash
# Baut das Linux-Paket: dist/SongGrabber-<Version>-linux.tar.gz
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VER="$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$ROOT/agcore/paths.py').read()).group(1))")"
NAME="SongGrabber-$VER-linux"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)/$NAME"
mkdir -p "$STAGE" "$OUT"
for f in main.py agcore ui assets LIZENZEN.txt LICENSE README.md requirements.txt tools integration; do
  cp -r "$ROOT/$f" "$STAGE/"
done
cp "$ROOT/packaging/linux/install.sh" "$ROOT/packaging/linux/uninstall.sh" "$STAGE/"
cp "$ROOT/packaging/linux/LIESMICH-Linux.txt" "$STAGE/LIESMICH.txt"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh"
tar -C "$(dirname "$STAGE")" -czf "$OUT/$NAME.tar.gz" "$NAME"
echo "$OUT/$NAME.tar.gz"
