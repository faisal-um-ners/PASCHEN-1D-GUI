#!/usr/bin/env bash
# Add "PASCHEN-1D Studio" to the Linux applications menu (freedesktop .desktop entry).
set -euo pipefail
STUDIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DEST"
cat > "$DEST/paschen-studio.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=PASCHEN-1D Studio
GenericName=Gas discharge simulation
Comment=Graphical workbench for the PASCHEN-1D plasma solver
Exec="$STUDIO_DIR/launch_studio.sh" %f
Icon=$STUDIO_DIR/paschen_studio/gui/assets/logo_256.png
Terminal=false
Categories=Science;Physics;Education;
StartupWMClass=PASCHEN-1D Studio
DESK
chmod +x "$DEST/paschen-studio.desktop" "$STUDIO_DIR/launch_studio.sh" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DEST" >/dev/null 2>&1 || true
echo "$DEST/paschen-studio.desktop"
