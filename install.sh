#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Sosie Installer — macOS & Linux
#
# Everything is installed inside ~/sosie (no system packages modified):
#   ~/sosie/.deps/python/   — standalone Python
#   ~/sosie/.deps/node/     — standalone Node.js
#   ~/sosie/.venv/          — Python virtual environment
#   ~/sosie/web/dist/       — built frontend
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tengso/sosie-releases/main/install.sh | bash
#
# Environment variables (all optional):
#   SOSIE_DIR   — install directory (default: ~/sosie)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SOSIE_DIR="${SOSIE_DIR:-$HOME/sosie}"
RELEASES_REPO="tengso/sosie-releases"
DEPS_DIR="$SOSIE_DIR/.deps"
PYTHON_MAJOR="3.12"
NODE_MAJOR="20"
TOTAL_STEPS=6

# ── Colors & helpers ─────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

step_num=0
step() {
    step_num=$((step_num + 1))
    printf "\n${BLUE}${BOLD}[%d/%d]${RESET} ${BOLD}%s${RESET}\n" "$step_num" "$TOTAL_STEPS" "$1"
}

info()    { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
warn()    { printf "  ${YELLOW}⚠${RESET} %s\n" "$1"; }
fail()    { printf "\n${RED}${BOLD}Error:${RESET} %s\n" "$1"; exit 1; }

command_exists() { command -v "$1" &>/dev/null; }

# ── Detect platform ──────────────────────────────────────────────────────────

detect_platform() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)      fail "Unsupported OS: $OS. Use install.ps1 for Windows." ;;
    esac

    # Map to python-build-standalone triple & Node.js platform
    case "$OS-$ARCH" in
        macos-arm64)
            PYTHON_TRIPLE="aarch64-apple-darwin"
            NODE_PLAT="darwin-arm64"
            ;;
        macos-x86_64)
            PYTHON_TRIPLE="x86_64-apple-darwin"
            NODE_PLAT="darwin-x64"
            ;;
        linux-x86_64)
            PYTHON_TRIPLE="x86_64-unknown-linux-gnu"
            NODE_PLAT="linux-x64"
            ;;
        linux-aarch64)
            PYTHON_TRIPLE="aarch64-unknown-linux-gnu"
            NODE_PLAT="linux-arm64"
            ;;
        *)
            fail "Unsupported platform: $OS $ARCH"
            ;;
    esac

    info "Platform: $OS $ARCH"
}

# ── Install standalone Python ────────────────────────────────────────────────

ensure_python() {
    local python_dir="$DEPS_DIR/python"
    local python_bin="$python_dir/bin/python3"

    if [[ -x "$python_bin" ]]; then
        local ver
        ver="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [[ -n "$ver" ]]; then
            info "Python $ver found (local)"
            PYTHON_CMD="$python_bin"
            return
        fi
    fi

    info "Downloading standalone Python ${PYTHON_MAJOR}..."
    mkdir -p "$DEPS_DIR"

    # Query python-build-standalone for the latest release with our Python version
    local release_json
    release_json="$(curl -sfL "https://api.github.com/repos/indygreg/python-build-standalone/releases?per_page=5")"

    local download_url
    download_url="$(printf '%s' "$release_json" \
        | grep -o "https://[^\"]*cpython-${PYTHON_MAJOR}\.[0-9]*+[0-9]*-${PYTHON_TRIPLE}-install_only\.tar\.gz" \
        | head -1)"

    if [[ -z "$download_url" ]]; then
        fail "Could not find Python ${PYTHON_MAJOR} standalone build for ${PYTHON_TRIPLE}.
  Please install Python >= ${PYTHON_MAJOR} manually and re-run."
    fi

    info "Downloading from $(basename "$download_url")..."

    # Clean previous install
    rm -rf "$python_dir"

    # Download and extract (extracts to "python/" directory)
    curl -#fSL "$download_url" | tar xz -C "$DEPS_DIR"

    if [[ ! -x "$python_bin" ]]; then
        fail "Python installation failed — binary not found at $python_bin"
    fi

    local installed_ver
    installed_ver="$("$python_bin" --version 2>&1 | awk '{print $2}')"
    info "Python $installed_ver installed to $python_dir"
    PYTHON_CMD="$python_bin"
}

# ── Install standalone Node.js ───────────────────────────────────────────────

ensure_node() {
    local node_dir="$DEPS_DIR/node"
    local node_bin="$node_dir/bin/node"
    local npm_bin="$node_dir/bin/npm"

    if [[ -x "$node_bin" ]]; then
        local ver
        ver="$("$node_bin" -v | sed 's/^v//')"
        local major="${ver%%.*}"
        if [[ "$major" -ge "$NODE_MAJOR" ]]; then
            info "Node.js v${ver} found (local)"
            NODE_BIN_DIR="$node_dir/bin"
            return
        fi
        warn "Node.js v${ver} too old, upgrading..."
    fi

    info "Downloading Node.js ${NODE_MAJOR} LTS..."
    mkdir -p "$DEPS_DIR"

    # Get latest v20.x version from Node.js index
    local node_version
    node_version="$(curl -sfL "https://nodejs.org/dist/index.json" \
        | grep -o "\"v${NODE_MAJOR}\.[0-9]*\.[0-9]*\"" \
        | head -1 \
        | tr -d '"')"

    if [[ -z "$node_version" ]]; then
        fail "Could not determine latest Node.js ${NODE_MAJOR}.x version."
    fi

    local archive_name="node-${node_version}-${NODE_PLAT}"
    local download_url="https://nodejs.org/dist/${node_version}/${archive_name}.tar.xz"

    info "Downloading ${archive_name}..."

    # Clean previous install
    rm -rf "$node_dir"

    # Download and extract
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    curl -#fSL "$download_url" | tar xJ -C "$tmp_dir"
    mv "$tmp_dir/${archive_name}" "$node_dir"
    rm -rf "$tmp_dir"

    if [[ ! -x "$node_bin" ]]; then
        fail "Node.js installation failed — binary not found at $node_bin"
    fi

    info "Node.js $(${node_bin} -v | sed 's/^v//') installed to $node_dir"
    NODE_BIN_DIR="$node_dir/bin"
}

# ── Resolve latest version ───────────────────────────────────────────────────

resolve_version() {
    # Get the latest release tag from the releases repo
    local latest
    latest="$(curl -sfL "https://api.github.com/repos/${RELEASES_REPO}/releases/latest" \
        | grep -o '"tag_name"\s*:\s*"[^"]*"' \
        | head -1 \
        | sed 's/.*"\([^"]*\)"/\1/')"

    if [[ -z "$latest" ]]; then
        # Fallback: list tags
        latest="$(curl -sfL "https://api.github.com/repos/${RELEASES_REPO}/tags?per_page=1" \
            | grep -o '"name"\s*:\s*"[^"]*"' \
            | head -1 \
            | sed 's/.*"\([^"]*\)"/\1/')"
    fi

    if [[ -z "$latest" ]]; then
        fail "Could not determine latest Sosie version from GitHub."
    fi

    SOSIE_VERSION="$latest"
    REPO_TARBALL="https://github.com/${RELEASES_REPO}/archive/refs/tags/${SOSIE_VERSION}.tar.gz"
    info "Latest version: $SOSIE_VERSION"
}

# ── Download / update source code ────────────────────────────────────────────

download_source() {
    # Preserve user data directories
    local preserve=(".env" ".venv" ".deps" "data")

    local tmp_dir
    tmp_dir="$(mktemp -d)"

    info "Downloading Sosie $SOSIE_VERSION..."
    curl -#fSL "$REPO_TARBALL" | tar xz -C "$tmp_dir"

    # Find the extracted directory (GitHub names it {repo}-{tag_without_leading_v})
    local extracted_dir
    extracted_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -1)"

    if [[ -z "$extracted_dir" ]] || [[ ! -d "$extracted_dir" ]]; then
        rm -rf "$tmp_dir"
        fail "Failed to download source code from GitHub."
    fi

    if [[ -f "$SOSIE_DIR/app.py" ]]; then
        # Existing install — update in place
        info "Existing install found — updating source code..."

        # Sync new files, preserving user directories
        local exclude_args=""
        for item in "${preserve[@]}"; do
            exclude_args="$exclude_args --exclude=$item"
        done

        # Use rsync if available, otherwise manual copy
        if command_exists rsync; then
            rsync -a --delete $exclude_args "$extracted_dir/" "$SOSIE_DIR/"
        else
            # Manual approach: remove old source files, copy new ones
            for item in "$SOSIE_DIR"/* "$SOSIE_DIR"/.[!.]*; do
                [[ -e "$item" ]] || continue
                local base="$(basename "$item")"
                local skip=false
                for p in "${preserve[@]}"; do
                    [[ "$base" == "$p" ]] && skip=true
                done
                if ! $skip; then
                    rm -rf "$item"
                fi
            done
            for item in "$extracted_dir"/* "$extracted_dir"/.[!.]*; do
                [[ -e "$item" ]] || continue
                local base="$(basename "$item")"
                local skip=false
                for p in "${preserve[@]}"; do
                    [[ "$base" == "$p" ]] && skip=true
                done
                if ! $skip; then
                    cp -a "$item" "$SOSIE_DIR/"
                fi
            done
        fi

        rm -rf "$tmp_dir"
        info "Source code updated to $SOSIE_VERSION"
    else
        # Fresh install
        mkdir -p "$SOSIE_DIR"

        # Move contents to install dir
        cp -a "$extracted_dir"/* "$extracted_dir"/.[!.]* "$SOSIE_DIR/" 2>/dev/null || true
        rm -rf "$tmp_dir"

        info "Downloaded $SOSIE_VERSION to $SOSIE_DIR"
    fi
}

# ── Python virtual environment ───────────────────────────────────────────────

setup_venv() {
    local venv_dir="$SOSIE_DIR/.venv"

    if [[ ! -d "$venv_dir" ]]; then
        "$PYTHON_CMD" -m venv "$venv_dir"
        info "Virtual environment created"
    else
        info "Virtual environment exists"
    fi

    # Use venv's pip directly (no need to activate)
    local pip_cmd="$venv_dir/bin/pip"

    # Upgrade pip quietly
    "$pip_cmd" install --upgrade pip --quiet 2>/dev/null || true

    # Install requirements
    info "Installing Python dependencies (this may take a few minutes)..."
    "$pip_cmd" install -r "$SOSIE_DIR/requirements.txt" --quiet

    # macOS extras (pywebview + Cocoa bindings)
    if [[ "$OS" == "macos" ]] && [[ -f "$SOSIE_DIR/requirements-macos.txt" ]]; then
        info "Installing macOS desktop dependencies..."
        "$pip_cmd" install -r "$SOSIE_DIR/requirements-macos.txt" --quiet
    fi

    info "Python dependencies installed"
}

# ── Build frontend ───────────────────────────────────────────────────────────

build_frontend() {
    local web_dir="$SOSIE_DIR/web"
    local npm_cmd="$NODE_BIN_DIR/npm"
    local node_cmd="$NODE_BIN_DIR/node"

    if [[ ! -d "$web_dir" ]]; then
        warn "web/ directory not found, skipping frontend build"
        return
    fi

    # Ensure local node/npm are on PATH for the build
    export PATH="$NODE_BIN_DIR:$PATH"

    info "Installing npm dependencies..."
    "$npm_cmd" install --prefix "$web_dir" --silent 2>/dev/null || "$npm_cmd" install --prefix "$web_dir"

    info "Building frontend..."
    "$npm_cmd" run build --prefix "$web_dir"

    info "Frontend built"
}

# ── Environment file ─────────────────────────────────────────────────────────

setup_env() {
    local env_file="$SOSIE_DIR/.env"
    local example="$SOSIE_DIR/.env.example"

    if [[ -f "$env_file" ]]; then
        info ".env already exists — not overwriting"
    elif [[ -f "$example" ]]; then
        cp "$example" "$env_file"
        info ".env created from .env.example"
    else
        cat > "$env_file" << 'EOF'
# Sosie Environment Configuration
# Fill in at least one API key to use AI features

# Required: Google API Key (for Gemini agents)
GOOGLE_API_KEY=

# Required: OpenAI API Key (for embeddings)
OPENAI_API_KEY=
EOF
        info ".env created with template"
    fi
}

# ── Launcher script ──────────────────────────────────────────────────────────

create_launcher() {
    local bin_dir="$HOME/.local/bin"
    local launcher="$bin_dir/sosie"

    mkdir -p "$bin_dir"

    cat > "$launcher" << LAUNCHER
#!/usr/bin/env bash
# Sosie launcher — auto-generated by install.sh
SOSIE_DIR="${SOSIE_DIR}"
export PATH="\$SOSIE_DIR/.deps/node/bin:\$SOSIE_DIR/.deps/python/bin:\$PATH"
source "\$SOSIE_DIR/.venv/bin/activate"
exec python "\$SOSIE_DIR/app.py" "\$@"
LAUNCHER
    chmod +x "$launcher"
    info "Launcher created at $launcher"

    # Ensure ~/.local/bin is on PATH
    if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
        local rc_file=""
        if [[ -f "$HOME/.zshrc" ]]; then
            rc_file="$HOME/.zshrc"
        elif [[ -f "$HOME/.bashrc" ]]; then
            rc_file="$HOME/.bashrc"
        elif [[ -f "$HOME/.bash_profile" ]]; then
            rc_file="$HOME/.bash_profile"
        fi

        if [[ -n "$rc_file" ]]; then
            local path_line='export PATH="$HOME/.local/bin:$PATH"'
            if ! grep -qF '.local/bin' "$rc_file" 2>/dev/null; then
                printf '\n# Added by Sosie installer\n%s\n' "$path_line" >> "$rc_file"
                info "Added ~/.local/bin to PATH in $(basename "$rc_file")"
            fi
        fi

        export PATH="$bin_dir:$PATH"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    printf "\n${BOLD}  ╔══════════════════════════════════════╗${RESET}\n"
    printf "${BOLD}  ║       Sosie Installer                ║${RESET}\n"
    printf "${BOLD}  ║       Document Q&A + Deep Research   ║${RESET}\n"
    printf "${BOLD}  ╚══════════════════════════════════════╝${RESET}\n"
    printf "\n  Install directory: ${BOLD}%s${RESET}\n" "$SOSIE_DIR"
    printf "  All dependencies stay inside this directory.\n"

    step "Detecting platform"
    detect_platform

    step "Installing Python & Node.js"
    ensure_python
    ensure_node

    step "Downloading Sosie"
    resolve_version
    download_source

    step "Setting up Python environment"
    setup_venv

    step "Building frontend"
    build_frontend

    step "Finishing up"
    setup_env
    create_launcher

    # ── Success ──────────────────────────────────────────────────────────
    printf "\n${GREEN}${BOLD}  ✅ Sosie installed successfully!${RESET}\n\n"
    printf "  ${BOLD}Next steps:${RESET}\n"
    printf "  1. Edit API keys:    ${YELLOW}nano %s/.env${RESET}\n" "$SOSIE_DIR"
    printf "  2. Run Sosie:        ${YELLOW}sosie --browser${RESET}\n"
    printf "     or with GUI:      ${YELLOW}sosie${RESET}  (macOS only)\n"
    printf "     or headless:      ${YELLOW}sosie --headless --db-dir ./data${RESET}\n"
    printf "\n  Docs: ${BLUE}https://github.com/${RELEASES_REPO}#readme${RESET}\n\n"

    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        printf "  ${YELLOW}Note:${RESET} Restart your terminal or run:\n"
        printf "    ${YELLOW}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}\n\n"
    fi
}

main
