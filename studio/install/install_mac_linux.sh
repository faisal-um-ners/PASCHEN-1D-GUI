#!/usr/bin/env bash
# PASCHEN-1D Studio installer for macOS and Linux.
#
#   bash studio/install/install_mac_linux.sh
#
# Creates a private virtual environment in studio/.venv, installs the studio and
# every solver dependency into it, verifies the installation with a one-second
# simulation and adds a launcher (macOS app / Linux menu entry).
# Nothing outside the studio folder is modified (except the optional launcher).
set -euo pipefail
STUDIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$STUDIO_DIR"
# shellcheck source=_common.sh
source "$STUDIO_DIR/install/_common.sh"

echo "────────────────────────────────────────────────────────"
echo "  PASCHEN-1D Studio – installer"
echo "  folder: $STUDIO_DIR"
echo "────────────────────────────────────────────────────────"

if [ ! -f "$STUDIO_DIR/../paschen_1d.py" ]; then
  echo "  ! The studio folder is expected inside the PASCHEN-1D folder (next to paschen_1d.py)."
  echo "    It will still install; choose the PASCHEN-1D folder the first time the app starts."
fi

if [ -d .venv ] && ! venv_ok "$STUDIO_DIR"; then
  echo "  Existing .venv is incomplete or uses an unsupported Python – rebuilding it."
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  if ! PY=$(pick_python); then no_python_help; exit 1; fi
  echo "  Using $("$PY" --version 2>&1)  ($PY)"
  "$PY" -m venv .venv
fi

VPY="$STUDIO_DIR/.venv/bin/python"
echo "  Installing packages (numpy, scipy, matplotlib, numba, PySide6, …) – this takes a minute…"
"$VPY" -m pip install --upgrade pip --quiet
"$VPY" -m pip install -e "$STUDIO_DIR"
echo
"$VPY" -m paschen_studio info || true

echo
echo "  Verifying with a 1-second test simulation (also pre-compiles the Numba kernels)…"
TMPWS="$(mktemp -d 2>/dev/null || echo /tmp/paschen_studio_check)"
if "$VPY" -m paschen_studio run "$STUDIO_DIR/examples/install_check.p1d.json" -w "$TMPWS" -q >/dev/null 2>&1; then
  echo "  ✔ PASCHEN-1D runs correctly."
else
  echo "  ! The test simulation did not finish – run it by hand to see the message:"
  echo "    $VPY -m paschen_studio run $STUDIO_DIR/examples/install_check.p1d.json"
fi
rm -rf "$TMPWS" 2>/dev/null || true

case "$(uname -s)" in
  Darwin)
    bash "$STUDIO_DIR/install/make_macos_app.sh" >/dev/null 2>&1 && \
      echo "  ✔ Created 'PASCHEN-1D Studio.app' in $STUDIO_DIR (drag it to the Dock if you like)." || true
    chmod +x "$STUDIO_DIR/Launch PASCHEN-1D Studio.command" 2>/dev/null || true ;;
  Linux)
    bash "$STUDIO_DIR/install/make_linux_desktop_entry.sh" >/dev/null 2>&1 && \
      echo "  ✔ Added 'PASCHEN-1D Studio' to your applications menu." || true
    chmod +x "$STUDIO_DIR/launch_studio.sh" 2>/dev/null || true ;;
esac

echo
echo "  Done. Start the studio with any of:"
case "$(uname -s)" in
  Darwin) echo "    • double-click  studio/PASCHEN-1D Studio.app   (or 'Launch PASCHEN-1D Studio.command')" ;;
  *)      echo "    • your applications menu → PASCHEN-1D Studio, or  ./studio/launch_studio.sh" ;;
esac
echo "    • $VPY -m paschen_studio gui"
echo "    • source studio/.venv/bin/activate && paschen-studio"
echo
