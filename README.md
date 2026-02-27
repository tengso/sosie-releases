# You-Work

A document Q&A and deep research system powered by AI agents.

## Features

- **Document Indexing**: Automatically watches and indexes documents (PDF, Word, Markdown, text files)
- **Q&A Agent**: Ask questions about your indexed documents
- **Deep Research Agent**: Comprehensive multi-query research across your document corpus
- **Web Interface**: Modern React-based UI for chat, research, and document management
- **CLI Tools**: Command-line interface for all operations

## Install

One-liner that downloads everything into `~/sosie` — no system packages modified:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/tengso/sosie-releases/main/install.sh | bash

# Windows (PowerShell)
irm https://raw.githubusercontent.com/tengso/sosie-releases/main/install.ps1 | iex
```

This automatically installs standalone Python 3.12, Node.js 20, builds the frontend, and creates a `sosie` launcher command. Everything lives inside `~/sosie/`:

```
~/sosie/
├── .deps/python/   ← standalone Python
├── .deps/node/     ← standalone Node.js
├── .venv/          ← Python virtual environment
├── .env            ← API keys (edit this after install)
└── ...             ← source code & built frontend
```

After install, edit your API keys and run:

```bash
nano ~/sosie/.env        # add GOOGLE_API_KEY, OPENAI_API_KEY
sosie --browser          # open in browser
sosie                    # native window (macOS)
```

To customize the install directory: `SOSIE_DIR=~/my-path bash <(curl -fsSL ...)`

---

## Quick Start (Manual)

### 1. Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Web frontend dependencies
cd web
npm install
cd ..
```

### 2. Set Environment Variables

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=your-api-key
# Optional proxy
# HTTPS_PROXY=http://proxy:port
```

### 3. Running the Application

#### Option A: Desktop App Mode (Recommended)

Run everything with a single command:

```bash
# Run with native window
python app.py

# Run in browser mode (opens http://localhost:8001)
python app.py --browser

# Run headless (services only, no GUI)
python app.py --headless

# Specify custom database directory
python app.py --db-dir ./data

# Custom port numbers
python app.py --port 9001 --agent-port 9000

# Remote mode (bind 0.0.0.0, enable file uploads)
python app.py --headless --remote --db-dir ./data
```

**Command-Line Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--headless` | Run without GUI (services only) | off |
| `--browser` | Open in browser instead of native window | off |
| `--remote` | Remote mode: bind `0.0.0.0`, enable file uploads | off |
| `--port PORT` | Indexer API port | `8001` |
| `--agent-port PORT` | Agent API port | `8000` |
| `--db-dir DIR` | Database/data directory | platform app data dir |

This starts all services automatically:
- Indexer API on port 8001 (also serves the web frontend)
- Agent API on port 8000

#### Remote Mode

When running with `--remote`, the backend binds to `0.0.0.0` so it can be accessed from other machines. An uploads directory is automatically created at `{db-dir}/uploads/` and registered as a document root. Users can upload files through the web UI, which are automatically indexed.

```bash
# Example: run on a server with custom ports
python app.py --headless --remote --port 9001 --agent-port 9000 --db-dir ./data
```

#### Option B: Development Mode

For frontend development with hot-reload, run 3 terminals:

**Terminal 1 - Indexer Service** (watches files, builds index, serves API on port 8001):

```bash
python -m src.cli indexer --db-dir ./data
# Optionally specify initial document roots:
python -m src.cli indexer --roots ./documents --db-dir ./data
```

**Terminal 2 - Agent API Server** (serves AI agents on port 8000):

```bash
python -m src.cli api-server
```

**Terminal 3 - Web Frontend** (Vite dev server with hot-reload on port 3000):

```bash
cd web
npm run dev
```

### 4. Access the System

| Mode | Web UI | Agent API | Indexer API |
|------|--------|-----------|-------------|
| Desktop App (`app.py`) | http://localhost:8001 | http://localhost:8000 | http://localhost:8001 |
| Development Mode | http://localhost:3000 | http://localhost:8000 | http://localhost:8001 |

**Note:** In development mode, the Vite dev server (port 3000) proxies API requests to the backend services. In desktop app mode, the frontend is served directly from the indexer and connects directly to both backend services.

## CLI Commands

### Document Management

```bash
# Add a folder to watch and index
python -m src.cli add-root /path/to/documents

# Remove a folder
python -m src.cli remove-root /path/to/documents

# List watched folders
python -m src.cli list-roots

# Resync all files
python -m src.cli resync

# Check indexing stats
python -m src.cli stats --vector-db ./data/vectors.db
```

### Chat & Research

```bash
# Interactive chat with Q&A agent
python -m src.cli chat

# Single message chat (for scripting)
python -m src.cli chat -m "What documents do I have?"

# Deep research (interactive)
python -m src.cli research

# Deep research with depth option
python -m src.cli research --depth deep
```

### Research Depth Options

| Depth | Description |
|-------|-------------|
| `quick` | 1-2 searches, brief summary |
| `standard` | 3-5 searches, detailed findings (default) |
| `deep` | 6+ searches, comprehensive report |

## Project Structure

```
you-work/
├── src/
│   ├── agents/           # AI agents (doc_qa_agent, deep_research_agent)
│   ├── indexer/          # Document indexing and vector search
│   ├── watcher/          # File system watcher
│   └── cli.py            # CLI entry point
├── web/                  # React frontend
├── data/                 # Database files (auto-created)
└── requirements.txt      # Python dependencies
```

## Supported File Types

| Category | Extensions |
|----------|------------|
| **Documents** | `.pdf`, `.docx`, `.doc` |
| **Text/Markdown** | `.txt`, `.md`, `.markdown`, `.rst` |
| **Code** | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.c`, `.cpp`, `.h`, `.hpp`, `.go`, `.rs`, `.rb`, `.php`, `.swift`, `.kt`, `.scala` |
| **Shell** | `.sh`, `.bash`, `.zsh` |
| **Config/Data** | `.yaml`, `.yml`, `.json`, `.xml` |
| **Web** | `.html`, `.css`, `.sql` |

## Building Standalone Executables

Build a standalone desktop application for distribution:

```bash
# Install build dependencies
pip install pyinstaller pywebview

# Build frontend first
cd web && npm run build && cd ..

# Build for your platform
python scripts/build.py

# Create distribution package (DMG/ZIP/tar.gz)
python scripts/build.py --dist
```

**Output locations:**
- macOS: `dist/Sosie.app` and `dist/Sosie.dmg`
- Windows: `dist/Sosie/Sosie.exe` and `dist/Sosie-windows.zip`
- Linux: `dist/Sosie/` and `dist/Sosie-linux.tar.gz`

### CI/CD Builds

The project includes GitHub Actions workflows for automated cross-platform builds:

1. Push a version tag: `git tag v0.1.0 && git push --tags`
2. GitHub Actions builds for macOS, Windows, and Linux
3. Artifacts are uploaded as draft releases

## Installation from PyPI

```bash
# Install with pip
pip install sosie

# Run the app
sosie
```

## Development

```bash
# Clone the repo
git clone https://github.com/sosie/sosie.git
cd sosie

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# Run tests
pytest
```
