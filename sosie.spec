# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Sosie desktop application.

Build commands:
    # macOS
    pyinstaller sosie.spec --target-architecture universal2

    # Windows
    pyinstaller sosie.spec

    # Linux
    pyinstaller sosie.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Determine platform-specific settings
is_mac = sys.platform == 'darwin'
is_win = sys.platform == 'win32'
is_linux = sys.platform.startswith('linux')

# Application metadata
APP_NAME = 'Sosie'
APP_VERSION = '0.1.0'
APP_BUNDLE_ID = 'com.sosie.app'

# Paths
ROOT = Path(SPECPATH)
SRC_DIR = ROOT / 'src'
WEB_DIST = ROOT / 'web' / 'dist'

# Data files to include
datas = [
    # Source code (needed for imports)
    (str(SRC_DIR), 'src'),
    # Environment template
    (str(ROOT / '.env.example'), '.') if (ROOT / '.env.example').exists() else None,
]

# Include built web frontend if exists
if WEB_DIST.exists():
    datas.append((str(WEB_DIST), 'web/dist'))

# Filter out None entries
datas = [d for d in datas if d is not None]

# Hidden imports for dynamic imports used by the app
hiddenimports = [
    # Uvicorn
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    
    # FastAPI / Starlette
    'fastapi',
    'starlette',
    'starlette.responses',
    'starlette.routing',
    'starlette.middleware',
    
    # Database
    'sqlite3',
    'aiosqlite',
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    
    # AI/ML libraries
    'openai',
    'tiktoken',
    'tiktoken_ext',
    'tiktoken_ext.openai_public',
    'tokenizers',
    'jinja2',
    'markupsafe',
    
    # Document parsing
    'pymupdf',
    'pymupdf4llm',
    'fitz',
    'docx',
    
    # HTTP clients
    'httpx',
    'httpcore',
    'h11',
    
    # Google ADK and its runtime dependencies
    'google.adk',
    'google.adk.cli',
    'litellm',
    'litellm.main',
    'litellm.utils',
    'litellm.llms',
    'litellm.llms.openai',
    'litellm.litellm_core_utils',
    'litellm.litellm_core_utils.tokenizers',
    
    # PyWebView backends
    'webview',
]

# Platform-specific hidden imports
if is_mac:
    hiddenimports.extend([
        'webview',
        'webview.platforms',
        'webview.platforms.cocoa',
        'webview.util',
        'webview.window',
        'webview.event',
        'webview.screen',
        'webview.menu',
        'objc',
        'PyObjCTools',
        'pyobjc_core',
        'Foundation',
        'AppKit',
        'WebKit',
        'Cocoa',
        'Quartz',
        'Security',
        'UniformTypeIdentifiers',
        'pyobjc_framework_Cocoa',
        'pyobjc_framework_WebKit',
        'pyobjc_framework_Quartz',
        'pyobjc_framework_Security',
        'pyobjc_framework_UniformTypeIdentifiers',
        'bottle',
        'proxy_tools',
    ])
elif is_win:
    hiddenimports.extend([
        'webview.platforms.edgechromium',
        'webview.platforms.mshtml',
        'clr',
    ])
elif is_linux:
    hiddenimports.extend([
        'webview.platforms.gtk',
        'gi',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.WebKit2',
    ])

# Collect all submodules for packages with heavy dynamic imports
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports += collect_submodules('litellm')
hiddenimports += collect_submodules('tiktoken')
hiddenimports += collect_submodules('google.adk')

# Include litellm data files (model cost maps, etc.)
import site
site_packages = Path(site.getsitepackages()[0])
litellm_path = site_packages / 'litellm'
if litellm_path.exists():
    datas.append((str(litellm_path), 'litellm'))

# Analysis
a = Analysis(
    ['app.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'PIL',
        'scipy',
        'torch',
        'transformers',
        'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove unnecessary files to reduce bundle size
def remove_from_tree(tree, patterns):
    """Remove files matching patterns from the analysis tree."""
    result = []
    for item in tree:
        name = item[0] if isinstance(item, tuple) else item
        if not any(pattern in name for pattern in patterns):
            result.append(item)
    return result

# Patterns to exclude
exclude_patterns = [
    'tests/',
    '__pycache__',
    '.pyc',
    'test_',
    '_test.py',
]

a.datas = remove_from_tree(a.datas, exclude_patterns)

# PYZ archive
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Executable
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets/icon.icns') if is_mac and (ROOT / 'assets/icon.icns').exists()
         else (str(ROOT / 'assets/icon.ico') if is_win and (ROOT / 'assets/icon.ico').exists() else None),
)

# Collect files
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# macOS App Bundle
if is_mac:
    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon='assets/icon.icns' if Path('assets/icon.icns').exists() else None,
        bundle_identifier=APP_BUNDLE_ID,
        version=APP_VERSION,
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleIdentifier': APP_BUNDLE_ID,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.15.0',
            'NSRequiresAquaSystemAppearance': False,  # Support dark mode
        },
    )
