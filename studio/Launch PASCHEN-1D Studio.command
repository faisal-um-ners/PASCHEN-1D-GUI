#!/usr/bin/env bash
# macOS: double-click to start PASCHEN-1D Studio.
# The first time, it installs everything into studio/.venv (about a minute); afterwards it starts immediately.
STUDIO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$STUDIO_DIR" || exit 1
source "$STUDIO_DIR/install/_common.sh"
if ! venv_ok "$STUDIO_DIR"; then
  echo "First start: setting up PASCHEN-1D Studio…"
  bash "$STUDIO_DIR/install/install_mac_linux.sh" || { echo; read -r -p "Press Return to close." _; exit 1; }
fi
nohup "$STUDIO_DIR/.venv/bin/python" -m paschen_studio gui "$@" >/dev/null 2>&1 &
echo
echo "  PASCHEN-1D Studio is starting – you can close this Terminal window."
exit 0
