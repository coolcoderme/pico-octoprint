#!/usr/bin/env bash
# Idempotent dev-environment setup for the pico-octoprint MicroPython firmware.
#
# There is no hardware Pico in the Cloud Agent VM, so this installs the host
# MicroPython toolchain used to develop the firmware:
#   - micropython            : Unix port runtime, to run/exercise firmware logic
#   - micropython-mpremote   : the tool the README uses to copy firmware to a Pico
#   - mpy-cross (venv)        : cross-compiler, a compile/build check for the .py
#   - ruff (venv)            : linter for the firmware source
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
  micropython \
  micropython-mpremote \
  python3-venv

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet "mpy-cross~=1.22.0" ruff

echo "Toolchain versions:"
micropython -c "import sys; print('  micropython', '.'.join(str(x) for x in sys.implementation.version))"
mpremote --version | sed 's/^/  mpremote /'
mpy-cross --version 2>&1 | sed 's/^/  /'
ruff --version | sed 's/^/  /'
echo "Dev environment ready."
