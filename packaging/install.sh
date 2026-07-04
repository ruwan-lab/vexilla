#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Vexilla install script
#
# Installs:
#   1. vexilla Python package into /usr/lib/vexilla/venv
#   2. systemd service unit
#   3. KB data files
#   4. Creates the vexilla user and state directories
#
# Usage:
#   curl -fsSL https://get.vexilla.dev/install.sh | sh
#   # or from a local checkout:
#   ./packaging/install.sh
# ═══════════════════════════════════════════════════════════════════

echo "🚩 Installing Vexilla..."

# ── Configuration ──────────────────────────────────────────────────
PREFIX="${PREFIX:-/usr}"
LIB_DIR="${LIB_DIR:-${PREFIX}/lib/vexilla}"
SHARE_DIR="${SHARE_DIR:-${PREFIX}/share/vexilla}"
DATA_DIR="${DATA_DIR:-/var/lib/vexilla}"
CONFIG_DIR="${CONFIG_DIR:-/etc/vexilla}"
SERVICE_DIR="${SERVICE_DIR:-/etc/systemd/system}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Dependencies check ─────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || {
    echo "✗ python3 is required but not installed."
    echo "  Install it: sudo apt install python3 python3-venv"
    exit 1
}

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || echo "0.0")
if [ "$(echo "$PYTHON_VERSION" | tr -d '(), ' | cut -d, -f1)" -lt 3 ] || \
   [ "$(echo "$PYTHON_VERSION" | tr -d '(), ' | cut -d, -f1)" -eq 3 -a \
     "$(echo "$PYTHON_VERSION" | tr -d '(), ' | cut -d, -f2)" -lt 11 ]; then
    echo "✗ Python 3.11+ is required."
    exit 1
fi

# ── Create user (if not exists) ────────────────────────────────────
if ! id -u vexilla >/dev/null 2>&1; then
    echo "  Creating vexilla system user..."
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin vexilla
fi

# ── Create directories ─────────────────────────────────────────────
echo "  Creating directories..."
sudo install -d -o vexilla -g vexilla -m 0750 "${LIB_DIR}"
sudo install -d -o vexilla -g vexilla -m 0750 "${SHARE_DIR}"
sudo install -d -o vexilla -g vexilla -m 0750 "${DATA_DIR}"
sudo install -d -o root -g root -m 0755 "${CONFIG_DIR}"
sudo install -d -o root -g root -m 0755 "${SERVICE_DIR}"

# ── Install Python package ─────────────────────────────────────────
echo "  Installing Python package..."
sudo python3 -m venv "${LIB_DIR}/venv"
sudo "${LIB_DIR}/venv/bin/pip" install --quiet --upgrade pip

# If running from a local checkout, install in editable mode
if [ -f "${PROJECT_ROOT}/pyproject.toml" ]; then
    sudo "${LIB_DIR}/venv/bin/pip" install --quiet -e "${PROJECT_ROOT}"
else
    # Otherwise install from PyPI
    sudo "${LIB_DIR}/venv/bin/pip" install --quiet vexilla
fi

# Create symlink for the binary
sudo ln -sf "${LIB_DIR}/venv/bin/vexilla" "${PREFIX}/bin/vexilla"

# ── Install knowledge base ─────────────────────────────────────────
if [ -f "${PROJECT_ROOT}/data/kb.db" ]; then
    echo "  Installing knowledge base..."
    sudo install -m 0644 "${PROJECT_ROOT}/data/kb.db" "${SHARE_DIR}/kb.db"
else
    echo "  Building knowledge base..."
    sudo "${LIB_DIR}/venv/bin/python3" -m vexilla.kb.build.pipeline
    sudo cp "${PROJECT_ROOT}/data/kb.db" "${SHARE_DIR}/kb.db"
fi

# ── Install systemd service ────────────────────────────────────────
echo "  Installing systemd service..."
if [ -f "${PROJECT_ROOT}/packaging/vexilla.service" ]; then
    sudo install -m 0644 "${PROJECT_ROOT}/packaging/vexilla.service" \
        "${SERVICE_DIR}/vexilla.service"
else
    echo "⚠  vexilla.service not found in packaging/. Skipping."
fi

# ── Config file (example) ──────────────────────────────────────────
if [ ! -f "${CONFIG_DIR}/config.toml" ]; then
    if [ -f "${PROJECT_ROOT}/packaging/config.toml.example" ]; then
        sudo install -m 0644 "${PROJECT_ROOT}/packaging/config.toml.example" \
            "${CONFIG_DIR}/config.toml"
    fi
fi

# ── Enable and start ───────────────────────────────────────────────
echo "  Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable vexilla.service
sudo systemctl restart vexilla.service || {
    echo "⚠  Service failed to start. Check: journalctl -u vexilla.service"
}

# ── Done ───────────────────────────────────────────────────────────
echo "✓ Vexilla installed!"
echo "  Dashboard: http://127.0.0.1:8787"
echo "  Logs:      journalctl -u vexilla.service -f"
echo "  Status:    sudo systemctl status vexilla.service"
