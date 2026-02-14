# ──────────────────────────────────────────────────────────────────────────────
# Sosie Installer — Windows (PowerShell)
#
# Everything is installed inside ~/sosie (no system packages modified):
#   ~/sosie/.deps/python/   — standalone Python
#   ~/sosie/.deps/node/     — standalone Node.js
#   ~/sosie/.venv/          — Python virtual environment
#   ~/sosie/web/dist/       — built frontend
#
# Usage:
#   irm https://raw.githubusercontent.com/tengso/sosie-releases/main/install.ps1 | iex
#
# Environment variables (all optional):
#   SOSIE_DIR   — install directory (default: ~/sosie)
# ──────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$SosieDir = if ($env:SOSIE_DIR) { $env:SOSIE_DIR } else { Join-Path $HOME "sosie" }
$ReleasesRepo = "tengso/sosie-releases"
$DepsDir = Join-Path $SosieDir ".deps"
$PythonMajor = "3.12"
$NodeMajor = 20
$TotalSteps = 6
$StepNum = 0

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Step {
    param([string]$Message)
    $script:StepNum++
    Write-Host ""
    Write-Host "[$script:StepNum/$TotalSteps] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ⚠ $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "Error: $Message" -ForegroundColor Red
    exit 1
}

# ── Install standalone Python ────────────────────────────────────────────────

function Ensure-Python {
    $pythonDir = Join-Path $DepsDir "python"
    $pythonBin = Join-Path $pythonDir "python.exe"

    if (Test-Path $pythonBin) {
        try {
            $ver = & $pythonBin -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver) {
                Write-Ok "Python $ver found (local)"
                return $pythonBin
            }
        } catch {}
    }

    Write-Ok "Downloading standalone Python ${PythonMajor}..."
    New-Item -ItemType Directory -Path $DepsDir -Force | Out-Null

    # Determine architecture
    $arch = if ([System.Environment]::Is64BitOperatingSystem) {
        if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") {
            "aarch64"
        } else {
            "x86_64"
        }
    } else {
        Write-Fail "32-bit Windows is not supported."
    }
    $triple = "${arch}-pc-windows-msvc"

    # Query python-build-standalone releases
    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/indygreg/python-build-standalone/releases?per_page=5" -UseBasicParsing
    $downloadUrl = $null
    foreach ($release in $releases) {
        foreach ($asset in $release.assets) {
            if ($asset.name -match "cpython-${PythonMajor}\.\d+\+\d+-${triple}-install_only\.tar\.gz$") {
                $downloadUrl = $asset.browser_download_url
                break
            }
        }
        if ($downloadUrl) { break }
    }

    if (-not $downloadUrl) {
        Write-Fail "Could not find Python ${PythonMajor} standalone build for Windows ${arch}.`nPlease install Python >= ${PythonMajor} manually and re-run."
    }

    Write-Ok "Downloading $(Split-Path $downloadUrl -Leaf)..."

    # Clean previous install
    if (Test-Path $pythonDir) { Remove-Item $pythonDir -Recurse -Force }

    # Download and extract
    $tmpArchive = Join-Path ([System.IO.Path]::GetTempPath()) "python-standalone.tar.gz"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpArchive -UseBasicParsing

    # Extract .tar.gz (PowerShell needs tar or 7z)
    if (Get-Command tar -ErrorAction SilentlyContinue) {
        tar xzf $tmpArchive -C $DepsDir
    } else {
        Write-Fail "tar command not found. Please install Windows 10 1803+ or extract manually."
    }
    Remove-Item $tmpArchive -Force

    if (-not (Test-Path $pythonBin)) {
        Write-Fail "Python installation failed — binary not found at $pythonBin"
    }

    $installedVer = & $pythonBin --version 2>&1
    Write-Ok "$installedVer installed to $pythonDir"
    return $pythonBin
}

# ── Install standalone Node.js ───────────────────────────────────────────────

function Ensure-Node {
    $nodeDir = Join-Path $DepsDir "node"
    $nodeBin = Join-Path $nodeDir "node.exe"
    $npmCmd = Join-Path $nodeDir "npm.cmd"

    if (Test-Path $nodeBin) {
        try {
            $ver = (& $nodeBin -v) -replace '^v', ''
            $major = [int]($ver -split '\.')[0]
            if ($major -ge $NodeMajor) {
                Write-Ok "Node.js v${ver} found (local)"
                return $nodeDir
            }
            Write-Warn "Node.js v${ver} too old, upgrading..."
        } catch {}
    }

    Write-Ok "Downloading Node.js ${NodeMajor} LTS..."
    New-Item -ItemType Directory -Path $DepsDir -Force | Out-Null

    # Determine architecture
    $arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") {
        "arm64"
    } else {
        "x64"
    }

    # Get latest version from Node.js index
    $nodeIndex = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -UseBasicParsing
    $nodeVersion = ($nodeIndex | Where-Object { $_.version -match "^v${NodeMajor}\." } | Select-Object -First 1).version

    if (-not $nodeVersion) {
        Write-Fail "Could not determine latest Node.js ${NodeMajor}.x version."
    }

    $archiveName = "node-${nodeVersion}-win-${arch}"
    $downloadUrl = "https://nodejs.org/dist/${nodeVersion}/${archiveName}.zip"

    Write-Ok "Downloading ${archiveName}..."

    # Clean previous install
    if (Test-Path $nodeDir) { Remove-Item $nodeDir -Recurse -Force }

    # Download and extract
    $tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "node.zip"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpZip -UseBasicParsing

    $tmpExtract = Join-Path ([System.IO.Path]::GetTempPath()) "node-extract"
    if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract
    Move-Item (Join-Path $tmpExtract $archiveName) $nodeDir
    Remove-Item $tmpZip -Force
    Remove-Item $tmpExtract -Recurse -Force

    if (-not (Test-Path $nodeBin)) {
        Write-Fail "Node.js installation failed — binary not found at $nodeBin"
    }

    $installedVer = (& $nodeBin -v) -replace '^v', ''
    Write-Ok "Node.js v${installedVer} installed to $nodeDir"
    return $nodeDir
}

# ── Resolve latest version ───────────────────────────────────────────────────

function Resolve-Version {
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/${ReleasesRepo}/releases/latest" -UseBasicParsing
    } catch {
        Write-Fail "Could not fetch latest release from GitHub."
    }

    $script:SosieVersion = $release.tag_name
    if (-not $script:SosieVersion) {
        Write-Fail "Could not determine latest Sosie version from GitHub."
    }

    # Find the source zip asset (sosie-source.zip)
    $sourceAsset = $release.assets | Where-Object { $_.name -eq "sosie-source.zip" } | Select-Object -First 1
    if (-not $sourceAsset) {
        Write-Fail "Release $script:SosieVersion has no sosie-source.zip asset.`nPlease check https://github.com/$ReleasesRepo/releases"
    }

    $script:SourceZipUrl = $sourceAsset.browser_download_url
    Write-Ok "Latest version: $script:SosieVersion"
}

# ── Download / update source code ────────────────────────────────────────────

function Download-Source {
    $preserve = @(".env", ".venv", ".deps", "data")

    $tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "sosie-source.zip"
    $tmpExtract = Join-Path ([System.IO.Path]::GetTempPath()) "sosie-extract"

    Write-Ok "Downloading Sosie $script:SosieVersion..."
    Invoke-WebRequest -Uri $script:SourceZipUrl -OutFile $tmpZip -UseBasicParsing
    if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract

    # Find the extracted directory dynamically
    $extractedDir = Get-ChildItem $tmpExtract -Directory | Select-Object -First 1
    if (-not $extractedDir) {
        Remove-Item $tmpZip -Force
        Remove-Item $tmpExtract -Recurse -Force
        Write-Fail "Failed to download source code from GitHub."
    }
    $extractedDir = $extractedDir.FullName

    if (Test-Path (Join-Path $SosieDir "app.py")) {
        # Existing install — update in place
        Write-Ok "Existing install found — updating source code..."

        # Remove old source files (preserve user dirs)
        Get-ChildItem $SosieDir | Where-Object {
            $preserve -notcontains $_.Name
        } | Remove-Item -Recurse -Force
        Get-ChildItem $SosieDir -Force | Where-Object {
            $_.Name -match '^\.' -and $preserve -notcontains $_.Name
        } | Remove-Item -Recurse -Force

        # Copy new source files
        Get-ChildItem $extractedDir | Where-Object {
            $preserve -notcontains $_.Name
        } | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $SosieDir $_.Name) -Recurse -Force
        }
        Get-ChildItem $extractedDir -Force | Where-Object {
            $_.Name -match '^\.' -and $preserve -notcontains $_.Name
        } | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $SosieDir $_.Name) -Recurse -Force
        }

        Remove-Item $tmpZip -Force
        Remove-Item $tmpExtract -Recurse -Force
        Write-Ok "Source code updated to $script:SosieVersion"
    } else {
        # Fresh install
        New-Item -ItemType Directory -Path $SosieDir -Force | Out-Null

        Get-ChildItem $extractedDir | Copy-Item -Destination $SosieDir -Recurse -Force
        Get-ChildItem $extractedDir -Force | Where-Object { $_.Name -match '^\.' } | Copy-Item -Destination $SosieDir -Recurse -Force

        Remove-Item $tmpZip -Force
        Remove-Item $tmpExtract -Recurse -Force
        Write-Ok "Downloaded $script:SosieVersion to $SosieDir"
    }
}

# ── Python venv ──────────────────────────────────────────────────────────────

function Setup-Venv {
    param([string]$PythonBin)

    $venvDir = Join-Path $SosieDir ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $venvPip = Join-Path $venvDir "Scripts\pip.exe"

    if (-not (Test-Path $venvPython)) {
        & $PythonBin -m venv $venvDir
        Write-Ok "Virtual environment created"
    } else {
        Write-Ok "Virtual environment exists"
    }

    # Upgrade pip
    & $venvPython -m pip install --upgrade pip --quiet 2>$null

    # Install requirements
    Write-Ok "Installing Python dependencies (this may take a few minutes)..."
    & $venvPip install -r (Join-Path $SosieDir "requirements.txt") --quiet

    Write-Ok "Python dependencies installed"
}

# ── Build frontend ───────────────────────────────────────────────────────────

function Build-Frontend {
    param([string]$NodeDir)

    $webDir = Join-Path $SosieDir "web"
    $npmCmd = Join-Path $NodeDir "npm.cmd"

    if (-not (Test-Path $webDir)) {
        Write-Warn "web/ directory not found, skipping frontend build"
        return
    }

    # Add local node to PATH for this session
    $env:Path = "$NodeDir;$env:Path"

    Write-Ok "Installing npm dependencies..."
    & $npmCmd install --prefix $webDir --silent 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $npmCmd install --prefix $webDir
    }

    Write-Ok "Building frontend..."
    & $npmCmd run build --prefix $webDir

    Write-Ok "Frontend built"
}

# ── Environment file ─────────────────────────────────────────────────────────

function Setup-Env {
    $envFile = Join-Path $SosieDir ".env"
    $example = Join-Path $SosieDir ".env.example"

    if (Test-Path $envFile) {
        Write-Ok ".env already exists — not overwriting"
    } elseif (Test-Path $example) {
        Copy-Item $example $envFile
        Write-Ok ".env created from .env.example"
    } else {
        @"
# Sosie Environment Configuration
# Fill in at least one API key to use AI features

# Required: Google API Key (for Gemini agents)
GOOGLE_API_KEY=

# Required: OpenAI API Key (for embeddings)
OPENAI_API_KEY=
"@ | Set-Content $envFile -Encoding UTF8
        Write-Ok ".env created with template"
    }
}

# ── Launcher ─────────────────────────────────────────────────────────────────

function Create-Launcher {
    param([string]$NodeDir, [string]$PythonDir)

    $launcherCmd = Join-Path $SosieDir "sosie.cmd"
    @"
@echo off
set "PATH=$NodeDir;$PythonDir;%PATH%"
call "$SosieDir\.venv\Scripts\activate.bat"
python "$SosieDir\app.py" %*
"@ | Set-Content $launcherCmd -Encoding ASCII
    Write-Ok "Launcher created at $launcherCmd"

    # Add to user PATH if not already there
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$SosieDir*") {
        [System.Environment]::SetEnvironmentVariable("Path", "$SosieDir;$userPath", "User")
        $env:Path = "$SosieDir;$env:Path"
        Write-Ok "Added $SosieDir to user PATH"
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor White
    Write-Host "  ║       Sosie Installer                ║" -ForegroundColor White
    Write-Host "  ║       Document Q&A + Deep Research   ║" -ForegroundColor White
    Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor White
    Write-Host ""
    Write-Host "  Install directory: $SosieDir"
    Write-Host "  All dependencies stay inside this directory."

    Write-Step "Detecting platform"
    Write-Ok "Windows $([System.Environment]::OSVersion.Version), PowerShell $($PSVersionTable.PSVersion)"

    Write-Step "Installing Python & Node.js"
    $pythonBin = Ensure-Python
    $nodeDir = Ensure-Node

    Write-Step "Downloading Sosie"
    Resolve-Version
    Download-Source

    Write-Step "Setting up Python environment"
    Setup-Venv -PythonBin $pythonBin

    Write-Step "Building frontend"
    Build-Frontend -NodeDir $nodeDir

    Write-Step "Finishing up"
    Setup-Env
    $pythonDir = Join-Path $DepsDir "python"
    Create-Launcher -NodeDir $nodeDir -PythonDir $pythonDir

    # ── Success ──────────────────────────────────────────────────────────
    Write-Host ""
    Write-Host "  ✅ Sosie installed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "  1. Edit API keys:    " -NoNewline; Write-Host "notepad $SosieDir\.env" -ForegroundColor Yellow
    Write-Host "  2. Run Sosie:        " -NoNewline; Write-Host "sosie --browser" -ForegroundColor Yellow
    Write-Host "     or headless:      " -NoNewline; Write-Host "sosie --headless --db-dir .\data" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Docs: https://github.com/$ReleasesRepo#readme" -ForegroundColor Blue
    Write-Host ""
    Write-Host "  Note: Restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
    Write-Host ""
}

Main
