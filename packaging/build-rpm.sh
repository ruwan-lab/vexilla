#!/usr/bin/env bash
# Build an RPM package from the source tree.
# Requires: rpm-build, python3-devel, python3-setuptools
#
# Usage:
#   ./packaging/build-rpm.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Building RPM package for vexilla..."

# Create a source tarball
VERSION=$(python3 -c "import sys; sys.path.insert(0,'src'); from vexilla import __version__; print(__version__)" 2>/dev/null || echo "0.1.0")
TARBALL="vexilla-${VERSION}.tar.gz"
git archive --format=tar.gz --prefix="vexilla-${VERSION}/" -o "/tmp/${TARBALL}" HEAD 2>/dev/null || {
    # Fallback: create tarball from current directory
    tar czf "/tmp/${TARBALL}" \
        --exclude=.venv --exclude=.git --exclude=__pycache__ --exclude='*.pyc' \
        -C "$(pwd)/.." "$(basename "$(pwd)")"
}

# Copy spec and tarball to rpmbuild
mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS
cp "/tmp/${TARBALL}" ~/rpmbuild/SOURCES/
cp packaging/vexilla.spec ~/rpmbuild/SPECS/

# Build
rpmbuild -ba ~/rpmbuild/SPECS/vexilla.spec

echo "==> RPM package built successfully!"
find ~/rpmbuild/RPMS -name "vexilla-*.rpm" -ls
