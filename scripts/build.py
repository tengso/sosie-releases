#!/usr/bin/env python3
"""
Cross-platform build script for Sosie desktop application.

Usage:
    python scripts/build.py          # Build for current platform
    python scripts/build.py --clean  # Clean build artifacts first
    python scripts/build.py --dist   # Create distribution package
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Project paths
ROOT = Path(__file__).parent.parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"


def run(cmd: list, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and print output."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check)


def clean():
    """Remove build artifacts."""
    print("\n=== Cleaning build artifacts ===")
    
    dirs_to_remove = [
        DIST_DIR,
        BUILD_DIR,
        ROOT / "__pycache__",
        ROOT / "src" / "__pycache__",
    ]
    
    for d in dirs_to_remove:
        if d.exists():
            print(f"Removing {d}")
            shutil.rmtree(d)
    
    # Remove .spec generated files
    for f in ROOT.glob("*.spec"):
        if f.name != "sosie.spec":
            print(f"Removing {f}")
            f.unlink()


def build_frontend():
    """Build the React frontend."""
    print("\n=== Building frontend ===")
    
    if not (WEB_DIR / "package.json").exists():
        print("No frontend found, skipping...")
        return
    
    # Check if node_modules exists
    if not (WEB_DIR / "node_modules").exists():
        print("Installing npm dependencies...")
        run(["npm", "install"], cwd=WEB_DIR)
    
    # Build
    print("Building frontend...")
    run(["npm", "run", "build"], cwd=WEB_DIR)
    
    print(f"Frontend built to {WEB_DIR / 'dist'}")


def ensure_assets():
    """Ensure icon assets exist."""
    print("\n=== Checking assets ===")
    
    ASSETS_DIR.mkdir(exist_ok=True)
    
    # Check for icons
    icons = {
        "darwin": "icon.icns",
        "win32": "icon.ico",
        "linux": "icon.png",
    }
    
    icon_file = icons.get(sys.platform)
    if icon_file and not (ASSETS_DIR / icon_file).exists():
        print(f"Warning: {icon_file} not found in assets/")
        print("  The app will be built without a custom icon.")
        print(f"  Add {ASSETS_DIR / icon_file} for a custom icon.")


def build_app():
    """Build the desktop application with PyInstaller."""
    print("\n=== Building desktop application ===")
    
    # Check PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Build command - note: --target-architecture is not valid with .spec files
    # The target architecture should be set in the spec file itself
    # -y flag overwrites output directory without confirmation
    cmd = [sys.executable, "-m", "PyInstaller", "-y", "sosie.spec"]
    
    run(cmd)
    
    print(f"\nBuild complete! Output in {DIST_DIR}")


def create_dmg():
    """Create macOS DMG installer."""
    print("\n=== Creating DMG installer ===")
    
    app_path = DIST_DIR / "Sosie.app"
    dmg_path = DIST_DIR / "Sosie.dmg"
    
    if not app_path.exists():
        print("Error: Sosie.app not found. Run build first.")
        return
    
    # Try create-dmg first
    try:
        run([
            "create-dmg",
            "--volname", "Sosie",
            "--window-pos", "200", "120",
            "--window-size", "600", "400",
            "--icon-size", "100",
            "--icon", "Sosie.app", "150", "190",
            "--app-drop-link", "450", "190",
            str(dmg_path),
            str(app_path),
        ], check=False)
    except FileNotFoundError:
        # Fallback to hdiutil
        print("create-dmg not found, using hdiutil...")
        run([
            "hdiutil", "create",
            "-volname", "Sosie",
            "-srcfolder", str(app_path),
            "-ov",
            "-format", "UDZO",
            str(dmg_path),
        ])
    
    print(f"DMG created: {dmg_path}")


def create_windows_installer():
    """Create Windows installer using NSIS or Inno Setup."""
    print("\n=== Creating Windows installer ===")
    
    exe_path = DIST_DIR / "Sosie" / "Sosie.exe"
    
    if not exe_path.exists():
        print("Error: Sosie.exe not found. Run build first.")
        return
    
    # Create simple zip for now
    zip_path = DIST_DIR / "Sosie-windows.zip"
    print(f"Creating {zip_path}...")
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", DIST_DIR / "Sosie")
    print(f"Windows package created: {zip_path}")
    
    print("\nFor a proper installer, install NSIS or Inno Setup and create an installer script.")


def create_linux_package():
    """Create Linux AppImage or deb package."""
    print("\n=== Creating Linux package ===")
    
    app_dir = DIST_DIR / "Sosie"
    
    if not app_dir.exists():
        print("Error: Sosie directory not found. Run build first.")
        return
    
    # Create tar.gz
    tar_path = DIST_DIR / "Sosie-linux.tar.gz"
    print(f"Creating {tar_path}...")
    run(["tar", "-czvf", str(tar_path), "-C", str(DIST_DIR), "Sosie"])
    print(f"Linux package created: {tar_path}")
    
    print("\nFor AppImage, install appimagetool and create an AppDir structure.")


def create_distribution():
    """Create distribution package for current platform."""
    print("\n=== Creating distribution package ===")
    
    if sys.platform == "darwin":
        create_dmg()
    elif sys.platform == "win32":
        create_windows_installer()
    else:
        create_linux_package()


def main():
    parser = argparse.ArgumentParser(description="Build Sosie desktop application")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    parser.add_argument("--no-frontend", action="store_true", help="Skip frontend build")
    parser.add_argument("--dist", action="store_true", help="Create distribution package")
    parser.add_argument("--dist-only", action="store_true", help="Only create distribution (skip build)")
    args = parser.parse_args()
    
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version}")
    
    if args.clean:
        clean()
    
    if not args.dist_only:
        if not args.no_frontend:
            build_frontend()
        
        ensure_assets()
        build_app()
    
    if args.dist or args.dist_only:
        create_distribution()
    
    print("\n=== Done! ===")


if __name__ == "__main__":
    main()
