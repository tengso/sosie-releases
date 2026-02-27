# Sosie - AI Coding Agent Guidelines

This document provides essential context for AI coding agents working on the Sosie project.

## Project Overview

Sosie is a document Q&A application that indexes local documents and provides AI-powered chat and deep research capabilities. It consists of:

- **Python backend** - File watching, document indexing, vector search, AI agents
- **React frontend** - TypeScript/Vite web UI with TailwindCSS
- **Desktop app** - PyWebView wrapper for native experience

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Web Frontend  │────▶│  Indexer API    │────▶│  Vector Store   │
│   (port 3000*)  │     │  (port 8001)    │     │  (SQLite)       │
└─────────────────┘     │  FastAPI+uvicorn│     └─────────────────┘
                        │                 │
                        │  /api/run_sse ──┼───▶┌─────────────────┐
                        │  /api/apps/*  ──┼───▶│  Agent API      │
                        │  (httpx proxy)  │    │  (port 8000)    │
                        └─────────────────┘    │  (Google ADK)   │
                                               └─────────────────┘

* Port 3000 is Vite dev server; in production, frontend is served from port 8001
* All frontend requests use relative /api URLs; the indexer proxies agent routes
* SSE streaming uses async httpx with StreamingResponse (no buffering)
```

## Key Directories

| Path | Purpose |
|------|---------|
| `src/indexer/` | Document parsing, chunking, embedding, vector store |
| `src/watcher/` | File system monitoring with debouncing |
| `src/agents/` | Google ADK agents (doc_qa_agent, deep_research_agent) |
| `src/agent_server.py` | ADK API server wrapper |
| `src/cli.py` | CLI entry point for all commands |
| `web/src/` | React frontend (Vite + TypeScript + TailwindCSS) |
| `app.py` | Desktop app entry point (PyWebView) |

## Running the Application

### Development Mode (3 terminals)

```bash
# Terminal 1: Indexer service (port 8001)
python -m src.cli indexer --db-dir ./data

# Terminal 2: Agent API (port 8000)
python -m src.cli api-server

# Terminal 3: Frontend dev server (port 3000)
cd web && npm run dev
```

### Desktop/Production Mode

```bash
# All-in-one with GUI
python app.py

# Browser mode
python app.py --browser

# Headless (services only)
python app.py --headless

# Custom database location
python app.py --db-dir ./data
```

## Code Conventions

### Python

- Use type hints for all function signatures
- Follow existing import organization (stdlib, third-party, local)
- Exception handling: use custom exceptions from `src/indexer/exceptions.py`
- Logging: use `logging` module, not print statements
- Database: SQLite with proper connection management

### TypeScript/React

- Functional components with hooks
- State management: Zustand stores in `web/src/stores/`
- Styling: TailwindCSS utility classes
- Icons: Lucide React
- Environment detection: `import.meta.env.DEV` for dev vs production

### Frontend API Calls

```typescript
// All API calls use relative URLs — proxied by Vite (dev) or indexer (production)
const AGENT_BASE = '/api'       // Agent API (SSE, sessions)
const API_BASE = '/api'         // Indexer API (documents, settings, dashboard)
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `src/indexer/process.py` | Main indexing pipeline |
| `src/indexer/store.py` | Vector store operations |
| `src/indexer/api_server.py` | FastAPI app + uvicorn server for indexer |
| `src/indexer/parsers/` | Document type parsers (PDF, Word, text) |
| `src/agents/doc_qa_agent/` | Q&A agent definition |
| `src/agents/deep_research_agent/` | Research agent definition |
| `web/src/pages/ChatPage.tsx` | Chat UI with source sidebar |
| `web/src/pages/ResearchPage.tsx` | Research UI with progress sidebar |
| `web/src/stores/chatStore.ts` | Chat state management (sessions, messages, sources) |
| `src/indexer/mcp_config.py` | MCP server configuration I/O and presets |
| `src/agents/common/mcp_loader.py` | Load MCP tools for agents |

## Agents (Google ADK)

Agents are defined in `src/agents/` using Google's Agent Development Kit:

```python
from google.adk import Agent

agent = Agent(
    name="agent_name",
    model="gemini-2.0-flash",
    instruction="...",
    tools=[tool1, tool2],
)
```

Available tools are defined in `src/agents/tools/`:
- `search_chunks` - Semantic search in indexed documents
- `find_docs` - Find documents by query
- `list_docs` - List available documents
- `multi_search` - Multiple parallel searches

## Database Files

All databases are SQLite, typically stored in `./data/`:

| File | Purpose |
|------|---------|
| `watcher.db` | File system state tracking |
| `vectors.db` | Document chunks and embeddings |
| `sessions.db` | Chat/research session history |

## Testing

```bash
# Run tests
pytest

# Type checking
mypy src/

# Frontend linting
cd web && npm run lint
```

## Building

```bash
# Build frontend
cd web && npm run build

# Build desktop app
python scripts/build.py

# Build with distribution package
python scripts/build.py --dist
```

## Common Tasks

### Adding a New Document Parser

1. Create parser in `src/indexer/parsers/newtype.py`
2. Inherit from `BaseParser`
3. Implement `supported_extensions()`, `supported_mimetypes()`, `parse()`
4. Register in `src/indexer/parsers/__init__.py`

### Adding a New Agent Tool

1. Add tool function in `src/agents/tools/`
2. Import and add to agent's `tools` list in agent definition

### Adding a New Frontend Page

1. Create component in `web/src/pages/`
2. Add route in `web/src/App.tsx`
3. Add navigation in `web/src/components/Layout.tsx`

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for embeddings |
| `GOOGLE_API_KEY` | Required for Gemini agents |

## Gotchas

1. **SSE Streaming**: The agent API uses Server-Sent Events. Both dev and production use relative `/api` URLs. In dev, Vite proxies to port 8000. In production, the indexer's async httpx proxy streams SSE via `StreamingResponse`. The indexer runs on uvicorn (async) so SSE doesn't block other requests.

2. **React Focus**: Use `setTimeout(() => ref.current?.focus(), 0)` after state changes to ensure DOM is updated.

3. **CORS**: In dev mode, rely on Vite proxy. In production, backend has CORS headers.

4. **PyInstaller**: Hidden imports are specified in `sosie.spec`. Add new dependencies there if packaging fails.

5. **Database Paths**: Use `--db-dir` option to specify custom database locations. Default is platform-specific app data directory.
