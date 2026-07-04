#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Vexilla uninstall script
#
# Removes:
#   1. systemd service
#   2. vexilla Python package + venv
#   3. Config and data files (with confirmation)
#   4. vexilla system user (optional)
# ═══════════════════════════════════════════════════════════════════

PREFIX="${PREFIX:-/usr}"
LIB_DIR="${LIB_DIR:-${PREFIX}/lib/vexilla}"
DATA_DIR="${DATA_DIR:-/var/lib/vexilla}"
CONFIG_DIR="${CONFIG_DIR:-/etc/vexilla}"

echo "🚩 Uninstalling Vexilla..."

# ── Stop and disable service ──────────────────────────────────────
echo "  Stopping service..."
sudo systemctl stop vexilla.service 2>/dev/null || true
sudo systemctl disable vexilla.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/vexilla.service
sudo systemctl daemon-reload

# ── Remove symlink ────────────────────────────────────────────────
sudo rm -f "${PREFIX}/bin/vexilla"

# ── Remove library files ──────────────────────────────────────────
echo "  Removing library files..."
sudo rm -rf "${LIB_DIR}"

# ── Data and config (with confirmation) ───────────────────────────
echo ""
echo "  Vexilla data directory: ${DATA_DIR}"
echo "  Vexilla config directory: ${CONFIG_DIR}"
read -p "  Remove data and config? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo rm -rf "${DATA_DIR}"
    sudo rm -rf "${CONFIG_DIR}"
    echo "  ✓ Data and config removed."
fi

# ── Remove system user (optional) ─────────────────────────────────
read -p "  Remove vexilla system user? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo userdel vexilla 2>/dev/null || true
    echo "  ✓ User removed."
fi

echo "✓ Vexilla uninstalled."
echo "  Restart your session if Vexilla was running."
