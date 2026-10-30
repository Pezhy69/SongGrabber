#!/usr/bin/env bash
# SongGrabber entfernen. Deine Musik bleibt immer erhalten.
set -eu
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/SongGrabber"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/SongGrabber"

rm -f "$APPS/songgrabber.desktop" "$ICONS/songgrabber.png" "$HOME/.local/bin/songgrabber"
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/songgrabber.desktop"
rm -rf "$DEST"
echo "SongGrabber wurde entfernt. Deine Musik ist unverändert."
if [ -d "$CONF" ]; then
  read -r -p "Auch Einstellungen, Bibliotheks-Zwischenspeicher und Abos löschen ($CONF)? [j/N] " a
  case "${a:-n}" in [jJyY]*) rm -rf "$CONF"; echo "Einstellungen gelöscht." ;; esac
fi
