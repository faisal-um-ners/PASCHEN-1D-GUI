#!/usr/bin/env bash
# Linux (and macOS terminal): start PASCHEN-1D Studio; installs on first use.
STUDIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STUDIO_DIR" || exit 1
source "$STUDIO_DIR/install/_common.sh"
if ! venv_ok "$STUDIO_DIR"; then
  echo "First start: setting up PASCHEN-1D Studio…"
  bash "$STUDIO_DIR/install/install_mac_linux.sh" || exit 1
fi
exec "$STUDIO_DIR/.venv/bin/python" -m paschen_studio gui "$@"
