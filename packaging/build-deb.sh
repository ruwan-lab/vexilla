#!/usr/bin/env bash
# Build a .deb package from the source tree.
# Requires: build-essential, devscripts, debhelper
#
# Usage:
#   ./packaging/build-deb.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Building .deb package for vexilla..."

# Ensure we're starting clean
rm -rf debian/.debhelper debian/vexilla debian/vexilla.debhelper.log

# Copy packaging/debian/* to debian/
if [ -d debian ]; then
    echo "Warning: debian/ directory exists; packaging/debian/ may conflict"
fi
cp -r packaging/debian .

# Generate a changelog if missing
if [ ! -f debian/changelog ]; then
    cat > debian/changelog <<'EOF'
vexilla (0.1.0-1) unstable; urgency=medium

  * Initial release.

 -- Vexilla contributors <vexilla-dev@example.com>  Thu, 03 Jul 2026 00:00:00 +0000
EOF
fi

# Install build dependencies
sudo apt-get update -qq
sudo apt-get install -y -qq devscripts debhelper dh-python python3-all python3-setuptools 2>/dev/null || true

# Build the package
dpkg-buildpackage -us -uc -b

echo "==> .deb package built successfully!"
ls -la ../vexilla_*.deb
