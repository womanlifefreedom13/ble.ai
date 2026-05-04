#!/usr/bin/env bash
# Local setup for the tunnel package — installs Python deps in a venv.
# For a full system install (systemd unit + config dir), use ../install.sh instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Distro detection ---
if [ -r /etc/os-release ]; then
    . /etc/os-release
    DISTRO="${ID:-unknown}"
else
    DISTRO="unknown"
fi

# --- Python check ---
need_python() {
    if ! command -v python3 >/dev/null 2>&1; then return 1; fi
    python3 - <<'PY' || return 1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

if ! need_python; then
    echo "[setup] python3 (>=3.10) not found — attempting install for ${DISTRO}..."
    case "$DISTRO" in
        ubuntu|debian)
            sudo apt-get update -q
            sudo apt-get install -y python3 python3-pip python3-venv
            ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo dnf install -y python3 python3-pip
            ;;
        arch|manjaro)
            sudo pacman -Sy --noconfirm python python-pip
            ;;
        *)
            echo "[setup] Unknown distro '$DISTRO'. Install python3.10+ manually and rerun." >&2
            exit 1
            ;;
    esac
fi

if ! need_python; then
    echo "[setup] python3 still <3.10 after install — aborting." >&2
    exit 1
fi

# --- venv + deps ---
python3 -m venv "$REPO_DIR/.venv"
# shellcheck disable=SC1091
source "$REPO_DIR/.venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q

cat <<EOF

[setup] Done.

Activate the venv:
  source $REPO_DIR/.venv/bin/activate

Run the tunnel:
  # Iran side (entry):
  python -m tunnel entry --config $SCRIPT_DIR/settings.json

  # Free-internet side (exit):
  python -m tunnel exit  --config $SCRIPT_DIR/settings.json

For a production systemd install on this host, run:
  sudo $REPO_DIR/install.sh entry   # or 'exit'
EOF
