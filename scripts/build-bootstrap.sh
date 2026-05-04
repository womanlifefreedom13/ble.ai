#!/usr/bin/env bash
# Build a self-extracting bootstrap.sh that contains the entire repo as an
# embedded base64 tarball. Run this from a machine WITH internet access; transfer
# the resulting bootstrap.sh to an Iran VPS via any channel (Bale, scp, USB).
#
# Usage:  ./scripts/build-bootstrap.sh
# Output: bootstrap.sh in the repo root.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO_DIR/bootstrap.sh"
TARBALL="$(mktemp -t ble-ai-XXXXXX.tar.gz)"
trap 'rm -f "$TARBALL"' EXIT

cd "$REPO_DIR"

# Pack everything except .git, the venv, the previous bootstrap, and local secrets.
tar --exclude='./.git' \
    --exclude='./.venv' \
    --exclude='./bootstrap.sh' \
    --exclude='./bootstrap-*.sh' \
    --exclude='./*.tar.gz' \
    --exclude='./settings.json' \
    --exclude='./tunnel/settings.json' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    -czf "$TARBALL" .

PAYLOAD_B64="$(base64 < "$TARBALL" | tr -d '\n')"
SHA256="$(shasum -a 256 "$TARBALL" 2>/dev/null | awk '{print $1}' || sha256sum "$TARBALL" | awk '{print $1}')"

cat > "$OUT" <<HEADER
#!/usr/bin/env bash
# bootstrap.sh — self-extracting installer for the Bale/LiveKit WebRTC tunnel.
#
# Use this when the target server (typically inside Iran) cannot reach GitHub.
# Transfer this single file to the server (Bale chat, scp, USB), then:
#
#     sudo bash bootstrap.sh entry     # install Iran-side SOCKS5 entry
#     sudo bash bootstrap.sh exit      # install free-internet exit
#
# Embedded payload SHA-256: $SHA256
set -euo pipefail

ROLE="\${1:-}"
if [[ "\$ROLE" != "entry" && "\$ROLE" != "exit" ]]; then
    echo "Usage: sudo bash \$0 <entry|exit>" >&2
    exit 2
fi
if [[ \$EUID -ne 0 ]]; then
    echo "Please run as root (sudo)." >&2
    exit 1
fi

INSTALL_DIR="\${INSTALL_DIR:-/opt/ble-ai}"
CONFIG_DIR="\${CONFIG_DIR:-/etc/tunnel}"
LOG_DIR="\${LOG_DIR:-/var/log/tunnel}"
SERVICE_USER="\${SERVICE_USER:-tunnel}"

. /etc/os-release 2>/dev/null || { echo "Cannot detect distro"; exit 1; }
case "\${ID:-}" in
    ubuntu|debian)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -q
        apt-get install -y python3 python3-pip python3-venv
        ;;
    fedora|rhel|centos|rocky|almalinux)
        dnf install -y python3 python3-pip
        ;;
    arch|manjaro)
        pacman -Sy --noconfirm python python-pip
        ;;
    *)
        echo "Distro '\${ID:-unknown}' not auto-supported. Install python3>=3.10 manually then rerun." >&2
        exit 1
        ;;
esac

if ! id "\$SERVICE_USER" &>/dev/null; then
    useradd --system --home-dir "\$INSTALL_DIR" --shell /usr/sbin/nologin "\$SERVICE_USER"
fi

mkdir -p "\$INSTALL_DIR"
TMP_TGZ="\$(mktemp)"
trap 'rm -f "\$TMP_TGZ"' EXIT

awk '/^__PAYLOAD_BELOW__\$/{flag=1; next} flag' "\$0" | base64 -d > "\$TMP_TGZ"

ACTUAL_SHA="\$(sha256sum "\$TMP_TGZ" | awk '{print \$1}')"
if [[ "\$ACTUAL_SHA" != "$SHA256" ]]; then
    echo "Payload checksum mismatch! Expected $SHA256, got \$ACTUAL_SHA" >&2
    exit 1
fi

tar -xzf "\$TMP_TGZ" -C "\$INSTALL_DIR"
chown -R "\$SERVICE_USER:\$SERVICE_USER" "\$INSTALL_DIR"

python3 -m venv "\$INSTALL_DIR/.venv"
"\$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q
"\$INSTALL_DIR/.venv/bin/pip" install -r "\$INSTALL_DIR/tunnel/requirements.txt" -q

mkdir -p "\$CONFIG_DIR" "\$LOG_DIR"
chown root:"\$SERVICE_USER" "\$CONFIG_DIR"
chown -R "\$SERVICE_USER:\$SERVICE_USER" "\$LOG_DIR"
chmod 750 "\$CONFIG_DIR"

if [[ ! -f "\$CONFIG_DIR/settings.json" ]]; then
    cp "\$INSTALL_DIR/tunnel/settings.example.json" "\$CONFIG_DIR/settings.json"
    chmod 640 "\$CONFIG_DIR/settings.json"
    chown root:"\$SERVICE_USER" "\$CONFIG_DIR/settings.json"
    echo "[bootstrap] Wrote example config to \$CONFIG_DIR/settings.json — EDIT IT before starting."
fi

SERVICE_NAME="tunnel-\$ROLE.service"
install -m 644 "\$INSTALL_DIR/systemd/\$SERVICE_NAME" "/etc/systemd/system/\$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "\$SERVICE_NAME"

cat <<EOF

[bootstrap] Installed \$ROLE node.

Next:
  1) Edit \$CONFIG_DIR/settings.json (livekit_url, room_name, tokens).
  2) sudo systemctl start \$SERVICE_NAME
  3) journalctl -u \$SERVICE_NAME -f

EOF
exit 0

__PAYLOAD_BELOW__
HEADER

# Append the base64 payload (one big line is fine; awk reads it as one record).
printf '%s\n' "$PAYLOAD_B64" >> "$OUT"
chmod +x "$OUT"

SIZE_KB=$(( $(wc -c < "$OUT") / 1024 ))
echo "[build] Wrote $OUT (${SIZE_KB} KB, payload sha256=$SHA256)"
