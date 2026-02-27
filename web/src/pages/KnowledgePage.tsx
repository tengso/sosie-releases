import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  FileText,
  CheckCircle,
  Clock,
  AlertCircle,
  FolderOpen,
  Plus,
  Trash2,
  Loader2,
  Search,
  Upload,
  CloudUpload,
  ChevronRight,
  Layers,
  X,
  Eye,
  List,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { api, formatBytes, formatRelativeTime, DocumentRoot, RootStatus, ModeInfo, type Document } from '../api/client'

// ── Document list sub-component ──
function DocumentList({
  documents,
  selectedId,
  onSelect,
}: {
  documents: Document[]
  selectedId?: string
  onSelect: (doc: Document) => void
}) {
  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-center">
        <FileText className="w-12 h-12 text-surface-500 mb-3" />
        <p className="text-surface-500">No documents found</p>
      </div>
    )
  }

  return (
    <div className="divide-y divide-surface-700/50">
      {documents.map((doc) => (
        <button
          key={doc.doc_id}
          onClick={() => onSelect(doc)}
          className={`w-full text-left px-4 py-3 hover:bg-surface-700/50 transition-colors flex items-center gap-3 ${
            selectedId === doc.doc_id ? 'bg-primary-600/20' : ''
          }`}
        >
          <FileText className="w-5 h-5 text-surface-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-surface-200 truncate">{doc.filename}</p>
            <p className="text-xs text-surface-500 truncate">{doc.path}</p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-xs text-surface-400">{formatBytes(doc.size)}</p>
            <p className="text-xs text-surface-500">{formatRelativeTime(doc.updated_at)}</p>
            {doc.embedding_model && (
              <p className="text-xs text-primary-400/70">{doc.embedding_model}</p>
            )}
          </div>
          <ChevronRight className="w-4 h-4 text-surface-500" />
        </button>
      ))}
    </div>
  )
}

// ── Document detail panel ──
function DocumentDetailPanel({ docId, onClose }: { docId: string; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<'preview' | 'chunks'>('preview')

  const { data: doc, isLoading } = useQuery({
    queryKey: ['document', docId],
    queryFn: () => api.documents.get(docId),
  })

  const { data: chunksData } = useQuery({
    queryKey: ['document', docId, 'chunks'],
    queryFn: () => api.documents.getChunks(docId),
    enabled: !!doc,
  })

  const fileUrl = `/api/documents/file?path=${encodeURIComponent(docId)}`

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="p-6 text-center">
        <p className="text-surface-500">Document not found</p>
      </div>
    )
  }

  const isPdf = doc.filename.toLowerCase().endsWith('.pdf')

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-surface-700/50 flex items-center justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-surface-100 truncate">{doc.filename}</h2>
          <p className="text-sm text-surface-500 truncate">{doc.path}</p>
        </div>
        <button
          onClick={onClose}
          className="p-2 hover:bg-surface-700 rounded-lg transition-colors"
        >
          <X className="w-5 h-5 text-surface-400" />
        </button>
      </div>

      {/* Tabs */}
      <div className="px-6 py-2 border-b border-surface-700/50 flex gap-2">
        <button
          onClick={() => setActiveTab('preview')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'preview'
              ? 'bg-primary-600/20 text-primary-400'
              : 'text-surface-400 hover:bg-surface-700 hover:text-surface-200'
          }`}
        >
          <Eye className="w-4 h-4" />
          Preview
        </button>
        <button
          onClick={() => setActiveTab('chunks')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'chunks'
              ? 'bg-primary-600/20 text-primary-400'
              : 'text-surface-400 hover:bg-surface-700 hover:text-surface-200'
          }`}
        >
          <List className="w-4 h-4" />
          Chunks ({chunksData?.total ?? 0})
        </button>
      </div>

      {/* Content */}
      {activeTab === 'preview' ? (
        <div className="flex-1 overflow-hidden">
          {isPdf ? (
            <iframe
              src={fileUrl}
              className="w-full h-full border-0"
              title={doc.filename}
            />
          ) : (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <FileText className="w-16 h-16 text-surface-500 mx-auto mb-4" />
                <p className="text-surface-400">Preview not available for this file type</p>
                <a
                  href={fileUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-4 inline-block px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg text-sm transition-colors"
                >
                  Download File
                </a>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* Info */}
          <div className="grid grid-cols-2 gap-4 mb-4 p-4 bg-surface-800/50 rounded-lg border border-surface-700/50">
            <div>
              <p className="text-xs text-surface-500 uppercase tracking-wide">Size</p>
              <p className="text-sm font-medium text-surface-200">{formatBytes(doc.size)}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 uppercase tracking-wide">Pages</p>
              <p className="text-sm font-medium text-surface-200">{doc.page_count ?? 'N/A'}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 uppercase tracking-wide">Chunks</p>
              <p className="text-sm font-medium text-surface-200">{doc.chunk_count}</p>
            </div>
            <div>
              <p className="text-xs text-surface-500 uppercase tracking-wide">Status</p>
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                doc.status === 'active' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
              }`}>
                {doc.status}
              </span>
            </div>
            <div>
              <p className="text-xs text-surface-500 uppercase tracking-wide">Embedding Model</p>
              <p className="text-sm font-medium text-surface-200">{doc.embedding_model ?? 'N/A'}</p>
            </div>
          </div>

          {/* Chunks list */}
          <h3 className="text-sm font-medium text-surface-300 mb-3 flex items-center gap-2">
            <Layers className="w-4 h-4" />
            Document Chunks
          </h3>
          <div className="space-y-3">
            {chunksData?.chunks.map((chunk) => (
              <div
                key={chunk.chunk_id}
                className="p-3 bg-surface-800/50 rounded-lg border border-surface-700/50"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-surface-400">
                    Chunk {chunk.index + 1}
                  </span>
                  <span className={`text-xs ${chunk.has_embedding ? 'text-emerald-400' : 'text-surface-500'}`}>
                    {chunk.has_embedding ? '✓ Embedded' : 'No embedding'}
                  </span>
                </div>
                {chunk.heading && (
                  <p className="text-xs font-medium text-surface-300 mb-1">{chunk.heading}</p>
                )}
                <p className="text-sm text-surface-400 line-clamp-3">{chunk.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Knowledge Page ──
export default function KnowledgePage() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()

  // Root management state
  const [isPickingFolder, setIsPickingFolder] = useState(false)
  const [folderError, setFolderError] = useState<string | null>(null)
  const [rootToRemove, setRootToRemove] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Document browser state
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const limit = 50

  // Collapsible sections
  const [sourcesExpanded, setSourcesExpanded] = useState(true)
  const [expandedRoots, setExpandedRoots] = useState<Record<string, boolean>>({})

  // Extract docId from path
  const pathMatch = location.pathname.match(/^\/knowledge\/(.+)$/)
  const docId = pathMatch ? decodeURIComponent(pathMatch[1]) : undefined

  // Fetch mode (local vs remote)
  const { data: modeInfo } = useQuery<ModeInfo>({
    queryKey: ['settings', 'mode'],
    queryFn: api.settings.getMode,
    staleTime: Infinity,
  })
  const isRemote = modeInfo?.mode === 'remote'

  const { data: stats } = useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: api.dashboard.getStats,
    refetchInterval: 10000,
  })

  // Fetch document roots
  const { data: roots = [], refetch: refetchRoots } = useQuery({
    queryKey: ['settings', 'roots'],
    queryFn: api.settings.getRoots,
  })

  // Fetch roots indexing status
  const { data: rootsStatus = [] } = useQuery({
    queryKey: ['settings', 'roots', 'status'],
    queryFn: api.settings.getRootsStatus,
    refetchInterval: (query) => {
      const data = query.state.data as RootStatus[] | undefined
      const hasActivity = data?.some(r => r.status === 'indexing' || r.status === 'pending' || r.status === 'scanning' || r.pending_count > 0)
      return hasActivity ? 2000 : 5000
    },
  })

  // Fetch documents
  const { data: docsData, isLoading: docsLoading } = useQuery({
    queryKey: ['documents', search, page],
    queryFn: () => api.documents.list({ limit, offset: page * limit, search: search || undefined }),
  })

  // Mutations
  const addRootMutation = useMutation({
    mutationFn: (root: DocumentRoot) => api.settings.addRoot(root),
    onSuccess: async () => {
      await refetchRoots()
      queryClient.invalidateQueries({ queryKey: ['settings', 'roots', 'status'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setFolderError(null)
    },
    onError: (error: Error) => {
      setFolderError(error.message)
    },
  })

  const removeRootMutation = useMutation({
    mutationFn: (path: string) => api.settings.removeRoot(path),
    onSuccess: async () => {
      await refetchRoots()
      queryClient.invalidateQueries({ queryKey: ['settings', 'roots', 'status'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setFolderError(null)
    },
    onError: (error: Error) => {
      setFolderError(`Failed to remove: ${error.message}`)
    },
  })

  const toggleRootMutation = useMutation({
    mutationFn: ({ path, enabled }: { path: string; enabled: boolean }) => api.settings.toggleRoot(path, enabled),
    onSuccess: async () => {
      await refetchRoots()
      queryClient.invalidateQueries({ queryKey: ['settings', 'roots', 'status'] })
    },
    onError: (error: Error) => {
      setFolderError(`Failed to toggle: ${error.message}`)
    },
  })

  const handlePickFolder = async () => {
    setIsPickingFolder(true)
    setFolderError(null)
    try {
      const response = await fetch('/api/settings/pick-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const result = await response.json()
      if (result.success && result.path) {
        await addRootMutation.mutateAsync({
          path: result.path,
          include_exts: ['.pdf', '.docx', '.doc'],
          exclude_dirs: ['.git', 'node_modules'],
          enabled: true,
        })
      } else if (result.error) {
        setFolderError(result.error)
      }
    } catch (error: any) {
      setFolderError(error.message || 'Failed to open folder picker')
    } finally {
      setIsPickingFolder(false)
    }
  }

  const handleUploadFiles = useCallback(async (files: FileList | File[]) => {
    const fileArray = Array.from(files)
    if (fileArray.length === 0) return
    setIsUploading(true)
    setFolderError(null)
    try {
      const result = await api.settings.uploadFiles(fileArray)
      if (result.success) {
        queryClient.invalidateQueries({ queryKey: ['settings', 'roots', 'status'] })
        queryClient.invalidateQueries({ queryKey: ['dashboard'] })
        queryClient.invalidateQueries({ queryKey: ['documents'] })
      }
    } catch (error: any) {
      setFolderError(error.message || 'Upload failed')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [queryClient])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (e.dataTransfer.files.length > 0) {
      handleUploadFiles(e.dataTransfer.files)
    }
  }, [handleUploadFiles])

  const handleSelectDocument = (doc: Document) => {
    navigate(`/knowledge/${encodeURIComponent(doc.doc_id)}`)
  }

  const handleCloseDetail = () => {
    navigate('/knowledge')
  }

  const hasProcessingJobs = (stats?.pending_jobs ?? 0) + (stats?.running_jobs ?? 0) > 0
  const hasErrors = (stats?.failed_jobs ?? 0) > 0

  // If a document is selected, show split view
  if (docId) {
    return (
      <div className="flex h-full">
        <div className="w-1/2 border-r border-surface-700/50 flex flex-col bg-surface-900">
          <div className="px-6 py-4 border-b border-surface-700/50">
            <h1 className="text-xl font-semibold text-surface-100 mb-3">Knowledge</h1>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
              <input
                type="text"
                placeholder="Search documents..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(0) }}
                className="w-full pl-10 pr-4 py-2 bg-surface-800 border border-surface-600 rounded-lg text-sm text-surface-200 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {docsLoading ? (
              <div className="flex items-center justify-center h-64">
                <div className="animate-spin w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full" />
              </div>
            ) : (
              <DocumentList
                documents={docsData?.documents ?? []}
                selectedId={docId}
                onSelect={handleSelectDocument}
              />
            )}
          </div>
          {docsData && docsData.total > limit && (
            <div className="px-6 py-3 border-t border-surface-700/50 flex items-center justify-between">
              <p className="text-sm text-surface-500">
                {page * limit + 1}-{Math.min((page + 1) * limit, docsData.total)} of {docsData.total}
              </p>
              <div className="flex gap-2">
                <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-3 py-1 text-sm bg-surface-700 hover:bg-surface-600 text-surface-300 rounded disabled:opacity-50">Previous</button>
                <button onClick={() => setPage(p => p + 1)} disabled={(page + 1) * limit >= docsData.total} className="px-3 py-1 text-sm bg-surface-700 hover:bg-surface-600 text-surface-300 rounded disabled:opacity-50">Next</button>
              </div>
            </div>
          )}
        </div>
        <div className="w-1/2 bg-surface-900">
          <DocumentDetailPanel docId={docId} onClose={handleCloseDetail} />
        </div>
      </div>
    )
  }

  // Default view: sources management + document browser
  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-surface-100">Knowledge</h1>
        <p className="text-surface-400 mt-1">Manage your document sources and browse indexed content.</p>
      </div>

      {/* Status Banner */}
      {(hasErrors || hasProcessingJobs) && (
        <div className={`mb-6 p-4 rounded-xl border ${
          hasErrors
            ? 'bg-red-500/10 border-red-500/30'
            : 'bg-amber-500/10 border-amber-500/30'
        }`}>
          <div className="flex items-center gap-3">
            {hasErrors ? (
              <>
                <AlertCircle className="w-5 h-5 text-red-400" />
                <span className="text-red-400 font-medium">{stats?.failed_jobs} document(s) failed to process</span>
              </>
            ) : (
              <>
                <Clock className="w-5 h-5 text-amber-400 animate-pulse" />
                <span className="text-amber-400 font-medium">Processing {(stats?.pending_jobs ?? 0) + (stats?.running_jobs ?? 0)} document(s)...</span>
              </>
            )}
          </div>
        </div>
      )}

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-5">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-xl bg-primary-500/10">
              <FileText className="w-6 h-6 text-primary-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-surface-100">{stats?.documents ?? 0}</p>
              <p className="text-sm text-surface-500">Documents indexed</p>
            </div>
          </div>
        </div>
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-5">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-xl bg-emerald-500/10">
              <FolderOpen className="w-6 h-6 text-emerald-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-surface-100">{formatBytes(stats?.storage_bytes ?? 0)}</p>
              <p className="text-sm text-surface-500">Total size</p>
            </div>
          </div>
        </div>
      </div>

      {/* Document Sources — collapsible */}
      <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 mb-6">
        <button
          onClick={() => setSourcesExpanded(!sourcesExpanded)}
          className="w-full flex items-center justify-between p-5 hover:bg-surface-700/30 transition-colors rounded-t-2xl"
        >
          <div className="flex items-center gap-3">
            {isRemote ? <CloudUpload className="w-5 h-5 text-surface-400" /> : <FolderOpen className="w-5 h-5 text-surface-400" />}
            <h2 className="text-lg font-semibold text-surface-100">
              {isRemote ? 'Upload Documents' : 'Document Sources'}
            </h2>
          </div>
          {sourcesExpanded ? <ChevronUp className="w-5 h-5 text-surface-400" /> : <ChevronDown className="w-5 h-5 text-surface-400" />}
        </button>

        {sourcesExpanded && (
          <div className="px-5 pb-5">
            {isRemote ? (
              /* ── Remote mode: Upload files ── */
              <>
                <div className="flex items-center justify-between mb-3">
                  <p className="text-sm text-surface-500">Upload documents to index them for AI-powered search.</p>
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                    className="flex items-center gap-2 px-3 py-1.5 bg-primary-600 hover:bg-primary-500 disabled:bg-surface-600 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
                  >
                    <Upload className="w-4 h-4" />
                    {isUploading ? 'Uploading...' : 'Choose Files'}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    accept=".pdf,.txt,.md,.rst,.py,.js,.ts,.docx,.doc"
                    onChange={(e) => e.target.files && handleUploadFiles(e.target.files)}
                  />
                </div>

                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => !isUploading && fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
                    isDragging
                      ? 'border-primary-400 bg-primary-500/10'
                      : 'border-surface-600 hover:border-surface-500 hover:bg-surface-700/30'
                  }`}
                >
                  {isUploading ? (
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 className="w-8 h-8 text-primary-400 animate-spin" />
                      <p className="text-sm text-surface-300">Uploading and indexing...</p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-3">
                      <CloudUpload className={`w-8 h-8 ${isDragging ? 'text-primary-400' : 'text-surface-500'}`} />
                      <p className="text-sm text-surface-300">{isDragging ? 'Drop files here' : 'Drag & drop files here, or click to browse'}</p>
                      <p className="text-xs text-surface-500">Supported: PDF, TXT, MD, RST, PY, JS, TS, DOCX, DOC</p>
                    </div>
                  )}
                </div>

                {folderError && (
                  <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl">
                    <p className="text-sm text-red-400">{folderError}</p>
                  </div>
                )}

                {rootsStatus.length > 0 && (
                  <div className="mt-4 space-y-2">
                    {rootsStatus.map((status) => {
                      const isAllReady = status.status === 'ready' && status.pending_count === 0 && status.processing_count === 0
                      const statusInfo = {
                        scanning: { icon: Search, color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30', label: 'Scanning...', animate: false },
                        pending: { icon: Clock, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', label: `${status.indexed_count} indexed, ${status.pending_count} pending`, animate: true },
                        indexing: { icon: Loader2, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', label: `${status.indexed_count} indexed, ${status.processing_count} processing...`, animate: true },
                        ready: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', label: isAllReady ? `All ${status.indexed_count} files ready` : `${status.indexed_count} files indexed`, animate: false },
                      }[status.status]
                      const StatusIcon = statusInfo.icon
                      return (
                        <div key={status.path} className="flex items-center gap-2 px-3 py-2 bg-surface-700/30 rounded-lg">
                          <StatusIcon className={`w-4 h-4 ${statusInfo.color} ${statusInfo.animate ? 'animate-spin' : ''}`} />
                          <span className={`text-sm ${statusInfo.color}`}>{statusInfo.label}</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
            ) : (
              /* ── Local mode: Folder picker ── */
              <>
                <div className="flex items-center justify-between mb-3">
                  <p className="text-sm text-surface-500">Add folders containing documents to index them.</p>
                  <button
                    onClick={handlePickFolder}
                    disabled={isPickingFolder || addRootMutation.isPending}
                    className="flex items-center gap-2 px-3 py-1.5 bg-primary-600 hover:bg-primary-500 disabled:bg-surface-600 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
                  >
                    <Plus className="w-4 h-4" />
                    {isPickingFolder ? 'Selecting...' : 'Add Folder'}
                  </button>
                </div>

                {folderError && (
                  <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl">
                    <p className="text-sm text-red-400">{folderError}</p>
                  </div>
                )}

                <div className="space-y-2">
                  {roots.length === 0 ? (
                    <div className="text-sm text-surface-500 py-4 text-center">
                      No folders configured. Add a folder to start indexing documents.
                    </div>
                  ) : (
                    roots.map((root) => {
                      const normalizedRootPath = root.path.replace(/\/+$/, '')
                      const status = rootsStatus.find(s => s.path.replace(/\/+$/, '') === normalizedRootPath)
                      const isAllReady = status && status.status === 'ready' && status.pending_count === 0 && status.processing_count === 0
                      const statusInfo = status ? {
                        scanning: { icon: Search, color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30', label: 'Scanning...', animate: false },
                        pending: { icon: Clock, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', label: `${status.indexed_count} indexed, ${status.pending_count} pending`, animate: true },
                        indexing: { icon: Loader2, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', label: `${status.indexed_count} indexed, ${status.processing_count} processing...`, animate: true },
                        ready: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', label: isAllReady ? `✓ All ${status.indexed_count} files ready` : `${status.indexed_count} files indexed`, animate: false },
                      }[status.status] : { icon: Clock, color: 'text-surface-400', bg: 'bg-surface-600', border: 'border-surface-500', label: 'Loading...', animate: false }
                      const StatusIcon = statusInfo.icon
                      const isEnabled = root.enabled !== false

                      return (
                        <div
                          key={root.path}
                          className={`flex items-center justify-between px-4 py-3 rounded-xl group ${
                            isEnabled ? 'bg-surface-700/50' : 'bg-surface-700/20 opacity-60'
                          }`}
                        >
                          <div className="flex items-center gap-3 flex-1 min-w-0">
                            <button
                              onClick={() => toggleRootMutation.mutate({ path: root.path, enabled: !isEnabled })}
                              disabled={toggleRootMutation.isPending}
                              className="flex-shrink-0 focus:outline-none"
                              title={isEnabled ? 'Disable folder' : 'Enable folder'}
                            >
                              <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                                isEnabled
                                  ? 'bg-primary-500 border-primary-500'
                                  : 'bg-transparent border-surface-500 hover:border-surface-400'
                              }`}>
                                {isEnabled && (
                                  <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                              </div>
                            </button>
                            <div className="min-w-0">
                              <p className="text-sm font-mono text-surface-200 truncate">{root.path}</p>
                              <p className="text-xs text-surface-500 mt-0.5">
                                Extensions: {root.include_exts.join(', ')}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            {isEnabled && (
                              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border ${statusInfo.bg} ${statusInfo.border} ${statusInfo.color}`}>
                                <StatusIcon className={`w-3.5 h-3.5 ${statusInfo.animate ? 'animate-spin' : ''}`} />
                                {statusInfo.label}
                              </span>
                            )}
                            {!isEnabled && (
                              <span className="text-xs px-2.5 py-1 rounded-lg border bg-surface-600/50 border-surface-500/50 text-surface-400">
                                Disabled
                              </span>
                            )}
                            <button
                              onClick={() => setRootToRemove(root.path)}
                              disabled={removeRootMutation.isPending}
                              className="p-1.5 text-surface-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                              title="Remove folder"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Document Browser — grouped by root */}
      <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-700/50">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-surface-100">Indexed Documents</h2>
            <span className="text-sm text-surface-500">{docsData?.total ?? 0} documents</span>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
            <input
              type="text"
              placeholder="Search documents..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0) }}
              className="w-full pl-10 pr-4 py-2 bg-surface-800 border border-surface-600 rounded-lg text-sm text-surface-200 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>

        <div className="max-h-[600px] overflow-y-auto">
          {docsLoading ? (
            <div className="flex items-center justify-center h-48">
              <div className="animate-spin w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full" />
            </div>
          ) : (
            (() => {
              const documents = docsData?.documents ?? []
              // Group documents by their matching root
              const rootPaths = roots.map(r => r.path.replace(/\/+$/, ''))
              const groups: Record<string, Document[]> = {}
              for (const doc of documents) {
                const matchedRoot = rootPaths.find(rp => doc.path.startsWith(rp))
                const key = matchedRoot ?? 'Other'
                if (!groups[key]) groups[key] = []
                groups[key].push(doc)
              }
              // Sort: known roots first (in order), then "Other"
              const orderedKeys = rootPaths.filter(rp => groups[rp]?.length > 0)
              if (groups['Other']?.length > 0) orderedKeys.push('Other')

              if (documents.length === 0) {
                return (
                  <div className="flex flex-col items-center justify-center h-48 text-center">
                    <FileText className="w-12 h-12 text-surface-500 mb-3" />
                    <p className="text-surface-500">No documents found</p>
                  </div>
                )
              }

              return orderedKeys.map(rootKey => {
                const groupDocs = groups[rootKey]
                const isExpanded = expandedRoots[rootKey] !== false
                const folderName = rootKey === 'Other' ? 'Other' : rootKey.split('/').pop() || rootKey
                return (
                  <div key={rootKey}>
                    <button
                      onClick={() => setExpandedRoots(prev => ({ ...prev, [rootKey]: !isExpanded }))}
                      className="w-full flex items-center gap-2 px-5 py-2.5 bg-surface-800/80 border-b border-surface-700/50 hover:bg-surface-700/50 transition-colors sticky top-0 z-10"
                    >
                      <FolderOpen className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                      <span className="text-sm font-medium text-surface-200 truncate flex-1 text-left" title={rootKey}>
                        {folderName}
                      </span>
                      <span className="text-xs text-surface-500 flex-shrink-0">{groupDocs.length} file{groupDocs.length !== 1 ? 's' : ''}</span>
                      <ChevronDown className={`w-3.5 h-3.5 text-surface-500 flex-shrink-0 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
                    </button>
                    {isExpanded && (
                      <DocumentList
                        documents={groupDocs}
                        onSelect={handleSelectDocument}
                      />
                    )}
                  </div>
                )
              })
            })()
          )}
        </div>

        {docsData && docsData.total > limit && (
          <div className="px-5 py-3 border-t border-surface-700/50 flex items-center justify-between">
            <p className="text-sm text-surface-500">
              {page * limit + 1}-{Math.min((page + 1) * limit, docsData.total)} of {docsData.total}
            </p>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-3 py-1 text-sm bg-surface-700 hover:bg-surface-600 text-surface-300 rounded disabled:opacity-50">Previous</button>
              <button onClick={() => setPage(p => p + 1)} disabled={(page + 1) * limit >= docsData.total} className="px-3 py-1 text-sm bg-surface-700 hover:bg-surface-600 text-surface-300 rounded disabled:opacity-50">Next</button>
            </div>
          </div>
        )}
      </div>

      {/* Remove Root Confirmation Modal */}
      {rootToRemove && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-surface-800 rounded-2xl border border-surface-700 p-6 max-w-md mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-3 rounded-xl bg-red-500/20">
                <AlertCircle className="w-6 h-6 text-red-400" />
              </div>
              <h3 className="text-lg font-semibold text-surface-100">Remove Folder?</h3>
            </div>
            <p className="text-surface-400 mb-2">
              Are you sure you want to remove this folder?
            </p>
            <p className="text-sm font-mono text-surface-300 bg-surface-700/50 p-2 rounded-lg mb-4 break-all">
              {rootToRemove}
            </p>
            <p className="text-surface-500 text-sm mb-6">
              Documents from this folder will be deactivated from the index.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setRootToRemove(null)}
                className="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-xl text-sm font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  removeRootMutation.mutate(rootToRemove)
                  setRootToRemove(null)
                }}
                disabled={removeRootMutation.isPending}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
              >
                {removeRootMutation.isPending ? 'Removing...' : 'Yes, Remove'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
