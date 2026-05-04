#!/usr/bin/env bash
# One-click installer for the Bale/LiveKit WebRTC tunnel.
#
# Usage on a server with internet access (typically the EXIT server):
#     curl -fsSL https://raw.githubusercontent.com/womanlifefreedom13/ble-ai/main/install.sh | sudo bash -s -- exit
#     curl -fsSL https://raw.githubusercontent.com/womanlifefreedom13/ble-ai/main/install.sh | sudo bash -s -- entry
#
# For an Iran server without git/curl access to GitHub, use bootstrap.sh
# (a self-extracting tarball you can transfer manually) instead.

set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "entry" && "$ROLE" != "exit" ]]; then
    cat <<EOF >&2
Usage: $0 <entry|exit>

  entry  Install the Iran-side SOCKS5 proxy.
  exit   Install the free-internet side TCP forwarder.
EOF
    exit 2
fi

REPO_URL="${REPO_URL:-https://github.com/womanlifefreedom13/ble-ai.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/ble-ai}"
CONFIG_DIR="${CONFIG_DIR:-/etc/tunnel}"
LOG_DIR="${LOG_DIR:-/var/log/tunnel}"
SERVICE_USER="${SERVICE_USER:-tunnel}"

if [[ $EUID -ne 0 ]]; then
    echo "[install] Please run as root (sudo)." >&2
    exit 1
fi

. /etc/os-release 2>/dev/null || { echo "Cannot detect distro"; exit 1; }
case "${ID:-}" in
    ubuntu|debian)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -q
        apt-get install -y python3 python3-pip python3-venv git curl
        ;;
    fedora|rhel|centos|rocky|almalinux)
        dnf install -y python3 python3-pip git curl
        ;;
    arch|manjaro)
        pacman -Sy --noconfirm python python-pip git curl
        ;;
    *)
        echo "[install] Distro '${ID:-unknown}' not auto-supported. Install python3>=3.10, git, curl manually then rerun." >&2
        exit 1
        ;;
esac

# --- User ---
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- Code ---
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "[install] Updating existing checkout in $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch --depth=1 origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
    echo "[install] Cloning $REPO_URL → $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
    git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# --- venv ---
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/tunnel/requirements.txt" -q

# --- Dirs ---
mkdir -p "$CONFIG_DIR" "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$LOG_DIR"
chown root:"$SERVICE_USER" "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"

if [[ ! -f "$CONFIG_DIR/settings.json" ]]; then
    cp "$INSTALL_DIR/tunnel/settings.example.json" "$CONFIG_DIR/settings.json"
    chmod 640 "$CONFIG_DIR/settings.json"
    chown root:"$SERVICE_USER" "$CONFIG_DIR/settings.json"
    echo "[install] Wrote example config to $CONFIG_DIR/settings.json — EDIT IT before starting the service."
fi

# --- systemd unit ---
SERVICE_NAME="tunnel-$ROLE.service"
install -m 644 "$INSTALL_DIR/systemd/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

cat <<EOF

[install] Done.

Next steps:
  1) Edit $CONFIG_DIR/settings.json with your livekit_url, room_name, and tokens.
     For Bale.ai: see README "Getting a Bale token" for how to extract a JWT.

  2) Start the service:
       sudo systemctl start $SERVICE_NAME

  3) Check logs:
       journalctl -u $SERVICE_NAME -f

  4) Status:
       systemctl status $SERVICE_NAME

EOF
