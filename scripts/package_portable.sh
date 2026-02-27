#!/bin/bash
set -euo pipefail

# Package Sosie into a portable zip that runs on a fresh macOS without Python installed.
# Usage: bash scripts/package_portable.sh [output.zip]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_ZIP="${1:-sosie-portable.zip}"

# Resolve to absolute path if relative
case "$OUTPUT_ZIP" in
    /*) ;;
    *) OUTPUT_ZIP="$PROJECT_DIR/$OUTPUT_ZIP" ;;
esac

STAGING_DIR="$(mktemp -d)"
BUNDLE_DIR="$STAGING_DIR/sosie"

echo "=== Sosie Portable Packager ==="
echo "Project:  $PROJECT_DIR"
echo "Output:   $OUTPUT_ZIP"
echo "Staging:  $STAGING_DIR"
echo ""

# ── Validate prerequisites ──────────────────────────────────────────────────

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "ERROR: .venv not found. Create a virtual environment first."
    exit 1
fi

if [ ! -f "$PROJECT_DIR/web/dist/index.html" ]; then
    echo "ERROR: web/dist not built. Run 'cd web && npm run build' first."
    exit 1
fi

# Resolve the real Python binary
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3.11"
REAL_PYTHON_LINK="$(readlink -f "$VENV_PYTHON" 2>/dev/null || python3 -c "import os; print(os.path.realpath('$VENV_PYTHON'))")"
if [ ! -f "$REAL_PYTHON_LINK" ]; then
    echo "ERROR: Cannot resolve real Python binary from $VENV_PYTHON"
    exit 1
fi

# Determine Python framework/prefix paths
PYTHON_PREFIX="$(dirname "$(dirname "$REAL_PYTHON_LINK")")"
PYTHON_VERSION="3.11"
STDLIB_DIR="$PYTHON_PREFIX/lib/python$PYTHON_VERSION"

# For framework Python, use Python.app binary (the real executable, not the stub)
# The stub at bin/python3.11 tries to re-exec Resources/Python.app which breaks portability
PYTHON_APP_BINARY="$PYTHON_PREFIX/Resources/Python.app/Contents/MacOS/Python"
if [ -f "$PYTHON_APP_BINARY" ]; then
    REAL_PYTHON="$PYTHON_APP_BINARY"
    echo "Using framework Python.app binary (GUI-capable)"
else
    REAL_PYTHON="$REAL_PYTHON_LINK"
    echo "Using standard Python binary"
fi

# Find the Python shared library (framework dylib)
PYTHON_DYLIB=""
DYLIB_INSTALL_NAME=""
# Check framework layout first (use PYTHON_PREFIX, not path from binary)
FRAMEWORK_DYLIB="$PYTHON_PREFIX/Python"
if [ -f "$FRAMEWORK_DYLIB" ]; then
    PYTHON_DYLIB="$FRAMEWORK_DYLIB"
    # Get the install name from the binary (skip the header line with tail -n +2)
    DYLIB_INSTALL_NAME="$(otool -L "$REAL_PYTHON" | tail -n +2 | grep -o '/Library/Frameworks/Python.framework[^ ]*' | head -1)"
fi

# Fallback: check for libpython
if [ -z "$PYTHON_DYLIB" ]; then
    for candidate in \
        "$PYTHON_PREFIX/lib/libpython${PYTHON_VERSION}.dylib" \
        "$PYTHON_PREFIX/lib/libpython${PYTHON_VERSION}m.dylib"; do
        if [ -f "$candidate" ]; then
            PYTHON_DYLIB="$candidate"
            DYLIB_INSTALL_NAME="$(otool -L "$REAL_PYTHON" | grep -o "[^ ]*libpython[^ ]*" | head -1)"
            break
        fi
    done
fi

if [ -z "$PYTHON_DYLIB" ]; then
    echo "ERROR: Cannot find Python shared library."
    echo "  Checked: $FRAMEWORK_DYLIB"
    echo "  Checked: $PYTHON_PREFIX/lib/libpython${PYTHON_VERSION}.dylib"
    exit 1
fi

echo "Python binary:  $REAL_PYTHON"
echo "Python prefix:  $PYTHON_PREFIX"
echo "Python dylib:   $PYTHON_DYLIB ($(du -h "$PYTHON_DYLIB" | cut -f1))"
echo "Dylib name:     $DYLIB_INSTALL_NAME"
echo "Stdlib:         $STDLIB_DIR ($(du -sh "$STDLIB_DIR" | cut -f1))"
echo ""

# ── Step 1: Copy project to staging ─────────────────────────────────────────

echo "[1/8] Copying project to staging directory..."
rsync -a \
    --exclude='.git' \
    --exclude='web/node_modules' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='data/' \
    --exclude='.mypy_cache' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.egg-info' \
    "$PROJECT_DIR/" "$BUNDLE_DIR/"

echo "  Project copied ($(du -sh "$BUNDLE_DIR" | cut -f1))"

# ── Step 2: Replace Python symlinks with real binary ─────────────────────────

echo "[2/8] Installing Python binary with PYTHONHOME wrapper..."
rm -f "$BUNDLE_DIR/.venv/bin/python" \
      "$BUNDLE_DIR/.venv/bin/python3" \
      "$BUNDLE_DIR/.venv/bin/python3.11"

# Install real binary as a hidden file
cp "$REAL_PYTHON" "$BUNDLE_DIR/.venv/bin/.python3.11"
chmod 755 "$BUNDLE_DIR/.venv/bin/.python3.11"

# Create wrapper script that sets PYTHONHOME so the bundled stdlib is found
cat > "$BUNDLE_DIR/.venv/bin/python3.11" << 'WRAPPER'
#!/bin/bash
# Portable Python wrapper — sets PYTHONHOME to the bundled installation
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONHOME="$SCRIPT_DIR/.."
exec "$SCRIPT_DIR/.python3.11" "$@"
WRAPPER
chmod 755 "$BUNDLE_DIR/.venv/bin/python3.11"

# Recreate convenience symlinks (relative)
cd "$BUNDLE_DIR/.venv/bin"
ln -sf python3.11 python3
ln -sf python3.11 python
cd "$PROJECT_DIR"

echo "  Binary installed ($(du -h "$BUNDLE_DIR/.venv/bin/.python3.11" | cut -f1))"

# ── Step 3: Copy Python shared library ───────────────────────────────────────

echo "[3/8] Installing Python shared library..."
mkdir -p "$BUNDLE_DIR/.venv/lib"
cp "$PYTHON_DYLIB" "$BUNDLE_DIR/.venv/lib/libpython${PYTHON_VERSION}.dylib"
chmod 644 "$BUNDLE_DIR/.venv/lib/libpython${PYTHON_VERSION}.dylib"

echo "  Dylib installed ($(du -h "$BUNDLE_DIR/.venv/lib/libpython${PYTHON_VERSION}.dylib" | cut -f1))"

# ── Step 4: Rewrite dylib load path ─────────────────────────────────────────

echo "[4/8] Rewriting dylib references..."
if [ -n "$DYLIB_INSTALL_NAME" ]; then
    install_name_tool -change \
        "$DYLIB_INSTALL_NAME" \
        "@executable_path/../lib/libpython${PYTHON_VERSION}.dylib" \
        "$BUNDLE_DIR/.venv/bin/.python3.11"
    echo "  Binary: $DYLIB_INSTALL_NAME → @executable_path/../lib/libpython${PYTHON_VERSION}.dylib"
else
    echo "  WARNING: Could not determine dylib install name. Binary may not find libpython."
fi

# Also fix the dylib's own install name (id)
install_name_tool -id \
    "@executable_path/../lib/libpython${PYTHON_VERSION}.dylib" \
    "$BUNDLE_DIR/.venv/lib/libpython${PYTHON_VERSION}.dylib" 2>/dev/null || true

echo "  Dylib references updated"

# ── Step 5: Copy Python stdlib ───────────────────────────────────────────────

echo "[5/8] Copying Python standard library..."
# Copy stdlib files, excluding large unnecessary packages
rsync -a \
    --exclude='test/' \
    --exclude='tests/' \
    --exclude='idlelib/' \
    --exclude='tkinter/' \
    --exclude='turtledemo/' \
    --exclude='ensurepip/' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "$STDLIB_DIR/" "$BUNDLE_DIR/.venv/lib/python${PYTHON_VERSION}/" \
    --ignore-existing  # Don't overwrite site-packages content

# Copy lib-dynload (C extension modules for stdlib)
if [ -d "$STDLIB_DIR/lib-dynload" ]; then
    rsync -a "$STDLIB_DIR/lib-dynload/" "$BUNDLE_DIR/.venv/lib/python${PYTHON_VERSION}/lib-dynload/"
fi

echo "  Stdlib installed ($(du -sh "$BUNDLE_DIR/.venv/lib/python${PYTHON_VERSION}/" | cut -f1) total with site-packages)"

# ── Step 6: Remove pyvenv.cfg ────────────────────────────────────────────────

echo "[6/8] Removing pyvenv.cfg (making standalone installation)..."
rm -f "$BUNDLE_DIR/.venv/pyvenv.cfg"

# ── Step 7: Codesign modified binaries ───────────────────────────────────────

echo "[7/8] Ad-hoc codesigning..."
codesign --force --sign - "$BUNDLE_DIR/.venv/bin/.python3.11" 2>/dev/null && \
    echo "  Signed .python3.11" || echo "  WARNING: codesign failed for .python3.11"

codesign --force --sign - "$BUNDLE_DIR/.venv/lib/libpython${PYTHON_VERSION}.dylib" 2>/dev/null && \
    echo "  Signed libpython${PYTHON_VERSION}.dylib" || echo "  WARNING: codesign failed for dylib"

# ── Step 8: Verify the bundle ────────────────────────────────────────────────

echo "[8/8] Verifying bundle..."
VERIFY_OUTPUT="$("$BUNDLE_DIR/.venv/bin/python3.11" -c "
import sys
print(f'executable: {sys.executable}')
print(f'prefix:     {sys.prefix}')
print(f'version:    {sys.version}')
# Quick import test
import json, os, pathlib, sqlite3, ssl, hashlib
print('stdlib imports: OK')
" 2>&1)" && VERIFY_OK=true || VERIFY_OK=false

echo "$VERIFY_OUTPUT" | sed 's/^/  /'

if [ "$VERIFY_OK" = false ]; then
    echo ""
    echo "ERROR: Bundle verification failed. The zip may not work on target machine."
    echo "Staging directory preserved at: $STAGING_DIR"
    exit 1
fi

# ── Create zip ───────────────────────────────────────────────────────────────

echo ""
echo "Creating zip archive..."
cd "$STAGING_DIR"
zip -r -q "$OUTPUT_ZIP" sosie/

# Cleanup
rm -rf "$STAGING_DIR"

ZIP_SIZE="$(du -h "$OUTPUT_ZIP" | cut -f1)"
echo ""
echo "=== Done ==="
echo "Output: $OUTPUT_ZIP ($ZIP_SIZE)"
echo ""
echo "To use on target Mac:"
echo "  1. unzip $(basename "$OUTPUT_ZIP")"
echo "  2. cd sosie"
echo "  3. cp .env.example .env  # Edit with your API keys"
echo "  4. .venv/bin/python app.py --browser --db-dir ./data"
