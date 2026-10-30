#!/usr/bin/env bash
# SongGrabber für Linux installieren (oder aktualisieren).
#   ./install.sh            – fragt nach dem Passwort für die Systempakete
#   ./install.sh --yes      – ohne Rückfragen (z. B. für Tests)
#   ./install.sh --no-deps  – Systempakete überspringen (wenn schon vorhanden)
# Installiert wird nur für dich: ~/.local/share/SongGrabber, Startmenü-Eintrag und Befehl „songgrabber“.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SRC/main.py" ] || SRC="$(cd "$SRC/../.." && pwd)"          # aus dem Quellcode (packaging/linux) gestartet
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/SongGrabber"
YES=0; DEPS=1
for a in "$@"; do
  case "$a" in
    --yes|-y) YES=1 ;;
    --no-deps) DEPS=0 ;;
    --prefix=*) DEST="${a#--prefix=}" ;;
  esac
done

say()  { printf '\033[1;35m♪\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && [ -z "${SG_ALLOW_ROOT:-}" ] && die "Bitte nicht mit sudo starten – SongGrabber wird für deinen Benutzer installiert (das Passwort wird nur für die Systempakete abgefragt)."

# ---------------------------------------------------------------- Systempakete
SUDO="sudo"; command -v sudo >/dev/null || SUDO=""
install_deps() {
  if command -v apt-get >/dev/null; then
    local web="gir1.2-webkit2-4.1"
    apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1 || web="gir1.2-webkit2-4.0"
    $SUDO apt-get update -qq || true
    $SUDO apt-get install -y python3 python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 "$web" \
      ffmpeg libpulse0 xdg-utils xclip libchromaprint-tools \
      gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
  elif command -v dnf >/dev/null; then
    $SUDO dnf install -y python3 python3-pip python3-gobject gtk3 webkit2gtk4.1 pulseaudio-libs xdg-utils xclip \
      gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-libav chromaprint-tools || true
    command -v ffmpeg >/dev/null || $SUDO dnf install -y ffmpeg-free || $SUDO dnf install -y ffmpeg || true
  elif command -v pacman >/dev/null; then
    $SUDO pacman -S --needed --noconfirm python python-pip python-gobject gtk3 webkit2gtk-4.1 ffmpeg libpulse \
      xdg-utils xclip chromaprint gst-plugins-good gst-plugins-bad gst-libav
  elif command -v zypper >/dev/null; then
    $SUDO zypper --non-interactive install python3 python3-pip python3-gobject python3-gobject-Gdk \
      typelib-1_0-WebKit2-4_1 ffmpeg libpulse0 xdg-utils xclip chromaprint-fpcalc \
      gstreamer-plugins-good gstreamer-plugins-bad gstreamer-plugins-libav || true
  else
    warn "Unbekannte Linux-Version – bitte selbst installieren: Python 3, PyGObject, WebKit2GTK 4.1, ffmpeg, GStreamer-Plugins."
  fi
}

say "SongGrabber wird installiert nach $DEST"
if [ "$DEPS" -eq 1 ]; then
  if [ "$YES" -eq 0 ]; then
    echo "Benötigte Systempakete (Python, WebKit, ffmpeg, GStreamer) werden jetzt installiert – dafür kann dein Passwort nötig sein."
    read -r -p "Weiter? [J/n] " ans; case "${ans:-j}" in [nN]*) die "Abgebrochen." ;; esac
  fi
  install_deps
fi

command -v python3 >/dev/null || die "Python 3 fehlt."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python 3.9 oder neuer wird benötigt."
command -v ffmpeg >/dev/null || warn "ffmpeg fehlt – ohne ffmpeg kann SongGrabber nicht umwandeln."

# ---------------------------------------------------------------- Programm kopieren
mkdir -p "$DEST"
for f in main.py agcore ui assets LIZENZEN.txt LICENSE README.md requirements.txt tools integration; do
  [ -e "$SRC/$f" ] && { rm -rf "${DEST:?}/$f"; cp -r "$SRC/$f" "$DEST/"; }
done
mkdir -p "$DEST/bin"

# ---------------------------------------------------------------- Python-Umgebung
if [ ! -x "$DEST/venv/bin/python" ]; then
  say "Python-Umgebung wird eingerichtet …"
  python3 -m venv --system-site-packages "$DEST/venv" || die "python3-venv fehlt (Paket „python3-venv“)."
fi
say "Bibliotheken werden installiert (pywebview, mutagen, soundcard, numpy, yt-dlp …)"
"$DEST/venv/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$DEST/venv/bin/python" -m pip install --quiet --upgrade -r "$DEST/requirements.txt" \
  || die "Installation der Python-Bibliotheken fehlgeschlagen."
"$DEST/venv/bin/python" -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null \
  || warn "PyGObject (GTK) nicht gefunden – das Fenster kann so nicht starten. Bitte „python3-gi“ installieren."

# ---------------------------------------------------------------- Start, Startmenü, Symbol
cat > "$DEST/songgrabber" <<EOF
#!/bin/sh
export PATH="$DEST/venv/bin:\$PATH"
exec "$DEST/venv/bin/python" "$DEST/main.py" "\$@"
EOF
chmod +x "$DEST/songgrabber"
mkdir -p "$HOME/.local/bin"
ln -sf "$DEST/songgrabber" "$HOME/.local/bin/songgrabber"

ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
mkdir -p "$ICONS"
if command -v python3 >/dev/null && "$DEST/venv/bin/python" -c "import PIL" 2>/dev/null; then
  "$DEST/venv/bin/python" -c "from PIL import Image; Image.open('$DEST/assets/icon.png').resize((256,256)).save('$ICONS/songgrabber.png')"
else
  cp "$DEST/assets/icon.png" "$ICONS/songgrabber.png"
fi

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/songgrabber.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SongGrabber
GenericName=Audio-Grabber & Musik-Player
Comment=Musik von YouTube, CD, Platte und Kassette holen – mit Tags, Cover und Songtext
Exec="$DEST/songgrabber" %F
Icon=songgrabber
Terminal=false
Categories=AudioVideo;Audio;Player;Music;
MimeType=audio/mpeg;audio/flac;audio/x-flac;audio/wav;audio/x-wav;audio/ogg;audio/x-vorbis+ogg;audio/opus;audio/mp4;audio/x-m4a;audio/aac;audio/x-mpegurl;video/mp4;video/x-matroska;video/webm;
Actions=Play;

[Desktop Action Play]
Name=Mit SongGrabber abspielen
Exec="$DEST/songgrabber" --play %F
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
cp "$SRC/packaging/linux/uninstall.sh" "$DEST/uninstall.sh" 2>/dev/null || cp "$SRC/uninstall.sh" "$DEST/uninstall.sh" 2>/dev/null || true
chmod +x "$DEST/uninstall.sh" 2>/dev/null || true

VER="$("$DEST/venv/bin/python" -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$DEST/agcore/paths.py').read()).group(1))")"
say "Fertig! SongGrabber $VER ist installiert."
echo "   Starten: im Startmenü „SongGrabber“ – oder im Terminal: songgrabber"
echo "   Entfernen: $DEST/uninstall.sh"
groups | grep -qwE 'cdrom|optical' || echo "   Tipp für Audio-CDs: sudo usermod -aG cdrom \$USER   (danach neu anmelden)"
