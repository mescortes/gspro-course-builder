#!/usr/bin/env bash
# One-time setup on Linux (Ubuntu 24.04 x86_64): headless Blender 4.2 LTS for the FBX step and the Python environment
# of the golden build (requirements-lock.txt). Also usable as the setup script of a Claude Code cloud environment
# (it runs there as root; see docs/PLAYBOOK.md, "Linux and Claude cloud sessions").
#
#   PREFIX   where Blender and the venv go (default /opt as root, else ~/.local/share/gspro-course-builder)
#   REPO     the checkout (default: the parent of this script's directory)
#
# Afterwards: BLENDER=$PREFIX/blender-<version>-linux-x64/blender, and .venv in the checkout links to the venv.
set -euo pipefail

BLENDER_VERSION=4.2.23
BLENDER_SHA256=bea0eb3146be13eae6225409a117b215184f41b7f79e799f97cb3abb8f6dc404
BLENDER_URL="https://download.blender.org/release/Blender4.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz"

if [ "$(id -u)" = 0 ]; then PREFIX=${PREFIX:-/opt}; else PREFIX=${PREFIX:-$HOME/.local/share/gspro-course-builder}; fi
REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
mkdir -p "$PREFIX"

# Blender's Linux build loads a few X11 / GL libraries even in background mode (-b).
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends ca-certificates curl xz-utils libgl1 libegl1 libxi6 libxrender1 \
    libxkbcommon0 libsm6 libxext6 libxfixes3 libxxf86vm1
fi

BL_DIR="$PREFIX/blender-${BLENDER_VERSION}-linux-x64"
if [ ! -x "$BL_DIR/blender" ]; then
  tmp="$PREFIX/blender.tar.xz.part"
  curl -fL --retry 5 --retry-delay 5 -o "$tmp" "$BLENDER_URL"
  echo "${BLENDER_SHA256}  $tmp" | sha256sum -c -
  tar -xJf "$tmp" -C "$PREFIX"
  rm -f "$tmp"
fi
"$BL_DIR/blender" -b --factory-startup --python-expr "import bpy; print('blender ok', bpy.app.version_string)" \
  | grep "blender ok"

# Python 3.12 venv with the golden package set (uv is preinstalled in Claude cloud sessions).
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
VENV="$PREFIX/gspro-venv"
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV"
uv pip install --python "$VENV/bin/python" -r "$REPO/requirements-lock.txt"
ln -sfn "$VENV" "$REPO/.venv"

echo
echo "done: BLENDER=$BL_DIR/blender, Python $VENV/bin/python (linked as $REPO/.venv)"
echo "check: COURSE= $REPO/.venv/bin/python -m pytest -q $REPO/tests --ignore=$REPO/tests/test_course.py"
