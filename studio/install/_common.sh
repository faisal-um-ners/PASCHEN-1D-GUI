# Shared helpers for the macOS / Linux installer and launchers (sourced, not executed).
# Finds a Python 3.10-3.13 interpreter (PASCHEN-1D + Numba support range) that can create venvs.

studio_python_ok() {
  # $1 = interpreter; succeeds if it is 3.10-3.13 and has venv + ensurepip
  "$1" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' >/dev/null 2>&1 || return 1
  "$1" -c 'import venv, ensurepip' >/dev/null 2>&1 || return 1
  return 0
}

pick_python() {
  local cands=() v d exe c base
  shopt -s nullglob
  [ -n "${PYTHON:-}" ] && cands+=("$PYTHON")
  cands+=(python3.12 python3.11 python3.13 python3.10)
  for v in 3.12 3.11 3.13 3.10; do
    cands+=("/Library/Frameworks/Python.framework/Versions/$v/bin/python3"
            "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" "/usr/bin/python$v")
    for d in "$HOME"/.pyenv/versions/$v.*/bin/python; do cands+=("$d"); done
  done
  if command -v conda >/dev/null 2>&1; then
    base=$(conda info --base 2>/dev/null || true)
    [ -n "$base" ] && cands+=("$base/bin/python3")
  fi
  for d in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" \
           "/opt/miniconda3" "/opt/anaconda3" "/opt/homebrew/Caskroom/miniforge/base"; do
    cands+=("$d/bin/python3")
  done
  cands+=(python3 python)
  shopt -u nullglob
  for c in "${cands[@]}"; do
    exe=""
    if [ -x "$c" ]; then exe="$c"; else exe=$(command -v "$c" 2>/dev/null || true); fi
    [ -z "$exe" ] && continue
    if studio_python_ok "$exe"; then echo "$exe"; return 0; fi
  done
  return 1
}

no_python_help() {
  echo
  echo "  No suitable Python was found. PASCHEN-1D needs Python 3.10 – 3.13 (3.12 recommended)."
  case "$(uname -s)" in
    Darwin)
      echo "  Install one of these, then run this installer again:"
      echo "    • python.org installer:  https://www.python.org/downloads/macos/   (choose 3.12)"
      echo "    • or Homebrew:           brew install python@3.12"
      echo "    • or Miniforge/conda:    https://github.com/conda-forge/miniforge" ;;
    *)
      echo "  Install Python 3.12 with venv support, e.g."
      echo "    Ubuntu/Debian:  sudo apt install python3.12 python3.12-venv"
      echo "    Fedora:         sudo dnf install python3.12"
      echo "    or Miniforge:   https://github.com/conda-forge/miniforge" ;;
  esac
  echo "  You can also point the installer at a specific interpreter:  PYTHON=/path/to/python3 $0"
  echo
}

venv_ok() {
  # $1 = studio dir; succeeds if .venv exists, has a supported Python and the studio installed
  local py="$1/.venv/bin/python"
  [ -x "$py" ] || return 1
  "$py" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' >/dev/null 2>&1 || return 1
  "$py" -c 'import paschen_studio, PySide6, numba, scipy, matplotlib' >/dev/null 2>&1 || return 1
  return 0
}
