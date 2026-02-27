const API_BASE = '/api'

export interface DashboardStats {
  documents: number
  chunks: number
  embeddings: number
  pending_jobs: number
  running_jobs: number
  failed_jobs: number
  completed_jobs: number
  storage_bytes: number
}

export interface JobInfo {
  job_id: number
  doc_id: string
  filename: string
  status: string
  operation: string  // upsert, delete, move
  created_at: number
  started_at: number | null
  completed_at: number | null
  error_msg: string | null
}

export interface SystemHealth {
  database_ok: boolean
  vector_index_ok: boolean
  vector_count: number
  db_size_bytes: number
  watcher_running: boolean
}

export interface RootInfo {
  root_id: number
  path: string
  doc_count: number
  chunk_count: number
  created_at: string
}

export interface IndexOverview {
  roots: RootInfo[]
  total_documents: number
  total_chunks: number
  total_vectors: number
  recent_documents: Array<{
    doc_id: string
    filename: string
    path: string
    status: string
    updated_at: number
    root_path: string
    chunk_count: number
  }>
}

export interface ActivityItem {
  type: string
  message: string
  timestamp: number
  doc_id: string | null
  filename: string | null
}

export interface Document {
  doc_id: string
  filename: string
  path: string
  size: number
  status: string
  created_at: number
  updated_at: number
  embedding_model: string | null
}

export interface DocumentDetail extends Document {
  content_hash: string
  page_count: number | null
  needs_ocr: boolean
  chunk_count: number
  embedding_model: string | null
}

export interface Chunk {
  chunk_id: number
  index: number
  page_start: number
  page_end: number
  tokens: number
  heading: string | null
  text: string
  has_embedding: boolean
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Request failed' }))
    throw new Error(error.error || `HTTP ${response.status}`)
  }
  
  return response.json()
}

export interface ModeInfo {
  mode: 'local' | 'remote'
  uploads_dir: string | null
}

export interface UploadResult {
  success: boolean
  files: Array<{ name: string; path: string; size: number }>
  message: string
}

export interface DocumentRoot {
  path: string
  include_exts: string[]
  exclude_dirs: string[]
  enabled: boolean
}

export interface RootStatus {
  path: string
  status: 'scanning' | 'pending' | 'indexing' | 'ready'
  indexed_count: number
  pending_count: number
  processing_count: number
  added_at: string
  enabled: boolean
}

export interface AgentModelPreset {
  model_id: string
  display_name: string
}

export interface EmbeddingPreset {
  model_id: string
  dimensions: number
  api_base: string | null
  api_key_env: string
}

export interface ModelSettings {
  agent_model: string
  embedding_model: string
  embedding_dimensions: number
  embedding_api_base: string | null
  embedding_api_key_env: string
  agent_model_presets: AgentModelPreset[]
  embedding_presets: EmbeddingPreset[]
  has_indexed_docs: boolean
}

export interface ModelUpdateResponse {
  success: boolean
  reindexing: boolean
  agent_model: string
  embedding_model: string
}

export interface KnowledgeRootsResponse {
  available_roots: Array<{ path: string; enabled: boolean }>
  agents: Array<{ name: string; display_name: string }>
  knowledge_roots: Record<string, string[] | null> | null
}

export interface AgentFeatures {
  has_sources_panel: boolean
  has_progress_panel: boolean
  has_depth_selector: boolean
}

export interface AgentInfo {
  name: string
  display_name: string
  description: string
  category: 'chat' | 'research'
  icon: string
  color: string
  avatar_url?: string
  features: AgentFeatures
  tools: string[]
  model: string
  default_model: string
  model_env: string
}

export const api = {
  settings: {
    getMode: () => fetchJson<ModeInfo>(`${API_BASE}/settings/mode`),
    getRoots: () => fetchJson<DocumentRoot[]>(`${API_BASE}/settings/roots`),
    addRoot: (root: DocumentRoot) => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/settings/roots`, {
      method: 'POST',
      body: JSON.stringify(root),
    }),
    removeRoot: (path: string) => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/settings/roots?path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),
    pickFolder: () => fetchJson<{ success: boolean; path: string | null; message?: string }>(`${API_BASE}/settings/pick-folder`, {
      method: 'POST',
    }),
    uploadFiles: async (files: File[], subfolder?: string): Promise<UploadResult> => {
      const formData = new FormData()
      for (const file of files) {
        formData.append('file', file)
      }
      if (subfolder) {
        formData.append('subfolder', subfolder)
      }
      const response = await fetch(`${API_BASE}/settings/upload`, {
        method: 'POST',
        body: formData,
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ error: 'Upload failed' }))
        throw new Error(error.error || `HTTP ${response.status}`)
      }
      return response.json()
    },
    getRootsStatus: () => fetchJson<RootStatus[]>(`${API_BASE}/settings/roots/status`),
    toggleRoot: (path: string, enabled: boolean) => fetchJson<{ success: boolean; enabled: boolean }>(`${API_BASE}/settings/roots`, {
      method: 'PATCH',
      body: JSON.stringify({ path, enabled }),
    }),
    getModels: () => fetchJson<ModelSettings>(`${API_BASE}/settings/models`),
    updateModels: (payload: { agent_model?: string; embedding_model?: string }) =>
      fetchJson<ModelUpdateResponse>(`${API_BASE}/settings/models`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }),
    getKnowledgeRoots: () => fetchJson<KnowledgeRootsResponse>(`${API_BASE}/settings/knowledge-roots`),
    updateKnowledgeRoots: (knowledgeRoots: Record<string, string[] | null> | null) =>
      fetchJson<{ success: boolean; knowledge_roots: Record<string, string[] | null> | null }>(`${API_BASE}/settings/knowledge-roots`, {
        method: 'PUT',
        body: JSON.stringify({ knowledge_roots: knowledgeRoots }),
      }),
  },
  
  dashboard: {
    getStats: () => fetchJson<DashboardStats>(`${API_BASE}/dashboard/stats`),
    getJobs: (status?: string, limit = 50) => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      params.set('limit', String(limit))
      return fetchJson<JobInfo[]>(`${API_BASE}/dashboard/jobs?${params}`)
    },
    getHealth: () => fetchJson<SystemHealth>(`${API_BASE}/dashboard/health`),
    getActivity: (limit = 50) => fetchJson<ActivityItem[]>(`${API_BASE}/dashboard/activity?limit=${limit}`),
    getIndexOverview: () => fetchJson<IndexOverview>(`${API_BASE}/dashboard/index-overview`),
    reconcile: () => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/dashboard/reconcile`, { method: 'POST' }),
    retryErrors: () => fetchJson<{ success: boolean; retried: number }>(`${API_BASE}/dashboard/retry-errors`, { method: 'POST' }),
    syncVectors: () => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/dashboard/sync-vectors`, { method: 'POST' }),
    rebuildEmbeddings: () => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/dashboard/rebuild-embeddings`, { method: 'POST' }),
    reinitializeDatabase: () => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/dashboard/reinitialize`, { method: 'POST' }),
  },
  
  agents: {
    list: () => fetchJson<AgentInfo[]>(`${API_BASE}/agents`),
  },
  
  documents: {
    list: (params: { limit?: number; offset?: number; search?: string } = {}) => {
      const searchParams = new URLSearchParams()
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.offset) searchParams.set('offset', String(params.offset))
      if (params.search) searchParams.set('search', params.search)
      return fetchJson<{ documents: Document[]; total: number }>(`${API_BASE}/documents?${searchParams}`)
    },
    get: (docId: string) => fetchJson<DocumentDetail>(`${API_BASE}/documents/detail?path=${encodeURIComponent(docId)}`),
    getChunks: (docId: string, limit = 100) => fetchJson<{ chunks: Chunk[]; total: number }>(`${API_BASE}/documents/chunks?path=${encodeURIComponent(docId)}&limit=${limit}`),
    getFileUrl: (docId: string) => `${API_BASE}/documents/file?path=${encodeURIComponent(docId)}`,
    deleteFile: (docPath: string) => fetchJson<{ success: boolean; message: string }>(`${API_BASE}/documents/file?path=${encodeURIComponent(docPath)}`, {
      method: 'DELETE',
    }),
    getContext: (docPath: string, chunkId: string, window = 2) => fetchJson<{
      status: string
      file_path: string
      context: Array<{ chunk_id: string; content: string; is_target: boolean; position: number }>
      total_chunks_in_doc: number
    }>(`${API_BASE}/documents/context?path=${encodeURIComponent(docPath)}&chunk_id=${encodeURIComponent(chunkId)}&window=${window}`),
  },
  
  chat: {
    send: async function* (message: string, agent = 'qa', sessionId?: string) {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, agent, session_id: sessionId }),
      })
      
      if (!response.ok) {
        throw new Error(`Chat request failed: ${response.status}`)
      }
      
      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')
      
      const decoder = new TextDecoder()
      let buffer = ''
      
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') return
            try {
              yield JSON.parse(data)
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }
    },
    getSessions: () => fetchJson<{ sessions: Array<{ id: string; created_at: number }> }>(`${API_BASE}/chat/sessions`),
    getSession: (sessionId: string) => fetchJson<{ messages: Array<{ role: string; content: string }> }>(`${API_BASE}/chat/sessions/${sessionId}`),
  },
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export function formatTimestamp(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString()
}

export function formatRelativeTime(timestamp: number): string {
  const now = Date.now() / 1000
  const diff = now - timestamp
  
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}
