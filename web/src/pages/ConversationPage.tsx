import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Send,
  Bot,
  User,
  Loader2,
  Sparkles,
  FileText,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  PanelRightClose,
  PanelRight,
  Brain,
  CheckCircle2,
  MessageSquare,
  BookOpen,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useQuery } from '@tanstack/react-query'
import { useConversationStore, type SourceChunk, type ResearchDepth } from '../stores/conversationStore'
import { useAgentStore } from '../stores/agentStore'
import { useAuthStore } from '../stores/authStore'
import { api, type AgentInfo } from '../api/client'

const AGENT_BASE = '/api'

// ── Research depth options ──
const depthOptions: { value: ResearchDepth; label: string; description: string }[] = [
  { value: 'quick', label: 'Quick', description: '1-2 searches, brief summary' },
  { value: 'standard', label: 'Standard', description: '3-5 searches, detailed findings' },
  { value: 'deep', label: 'Deep', description: '6+ searches, comprehensive report' },
]

// ── Tool display helpers ──
interface ToolCall {
  name: string
  args?: Record<string, unknown>
  status: 'running' | 'completed'
  startTime: number
}

const getToolDisplayInfo = (name: string, args?: Record<string, unknown>): { label: string; detail?: string } => {
  const query = args?.query || args?.queries || args?.search_query
  const queryStr = Array.isArray(query) ? query[0] : (typeof query === 'string' ? query : undefined)

  switch (name) {
    case 'search_documents':
    case 'search':
      return { label: 'Searching documents', detail: queryStr ? `"${queryStr}"` : undefined }
    case 'search_chunks':
      return { label: 'Searching document excerpts', detail: queryStr ? `Looking for: "${queryStr}"` : 'Analyzing content fragments' }
    case 'multi_search':
    case 'multi_search_documents':
      return { label: 'Searching multiple topics', detail: Array.isArray(query) ? `${(query as string[]).length} queries` : undefined }
    case 'find_documents':
    case 'find_docs':
      return { label: 'Finding relevant documents', detail: queryStr ? `"${queryStr}"` : undefined }
    case 'list_documents':
    case 'list_docs':
      return { label: 'Listing available documents' }
    case 'get_document_context':
    case 'context':
      return { label: 'Reading document context' }
    case 'google_search':
      return { label: 'Searching the web', detail: queryStr ? `"${queryStr}"` : undefined }
    case 'keyword_search':
      return { label: 'Keyword search', detail: queryStr ? `"${queryStr}"` : undefined }
    default:
      return { label: name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) }
  }
}

// ── Context chunk for expanded source view ──
interface ContextChunk {
  chunk_id: string
  content: string
  is_target: boolean
  position: number
}

// ── Agent icon helper ──
function getAgentIconComponent(icon?: string) {
  if (icon === 'book-open') return BookOpen
  if (icon === 'message-square') return MessageSquare
  return Bot
}

function agentBgColor(agent: AgentInfo | undefined): string {
  if (!agent) return 'from-primary-500 to-primary-600'
  if (agent.color === 'purple') return 'from-violet-600 to-purple-500'
  if (agent.color === 'blue') return 'from-emerald-500 to-teal-600'
  return 'from-primary-500 to-primary-600'
}

// Renders custom avatar image or gradient icon fallback
function AgentAvatar({ agent, avatarUrl, size = 'md', className = '' }: {
  agent: AgentInfo | undefined
  avatarUrl?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}) {
  const sizeClasses = {
    sm: 'w-8 h-8 rounded-lg',
    md: 'w-9 h-9 rounded-xl',
    lg: 'w-11 h-11 rounded-xl',
    xl: 'w-20 h-20 rounded-2xl',
  }
  const iconSizes = { sm: 'w-4 h-4', md: 'w-5 h-5', lg: 'w-5 h-5', xl: 'w-10 h-10' }
  const sz = sizeClasses[size]
  const iconSz = iconSizes[size]

  if (avatarUrl) {
    return <img src={avatarUrl} alt="" className={`${sz} object-cover flex-shrink-0 ${className}`} />
  }

  const gradient = agentBgColor(agent)
  const Icon = getAgentIconComponent(agent?.icon)
  return (
    <div className={`${sz} bg-gradient-to-br ${gradient} flex items-center justify-center flex-shrink-0 ${className}`}>
      <Icon className={`${iconSz} text-white`} />
    </div>
  )
}

// ── PDF source viewer: iframe-based, lazy-loaded ──
function PdfSourceViewer({ filePath, chunks, defaultExpanded = false }: { filePath: string; chunks: SourceChunk[]; defaultExpanded?: boolean }) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [chunkPages, setChunkPages] = useState<Record<string, number>>({})
  const [activeChunkId, setActiveChunkId] = useState<string>(chunks[0]?.chunk_id || '')
  const [pagesFetched, setPagesFetched] = useState(false)

  const chunkIdsKey = chunks.map(c => c.chunk_id).join(',')
  const pdfBaseUrl = `/api/documents/pdf-view?path=${encodeURIComponent(filePath)}&chunk_ids=${encodeURIComponent(chunkIdsKey)}`

  // Fetch page mapping when expanded
  useEffect(() => {
    if (!expanded || !chunkIdsKey) return
    fetch(`/api/documents/pdf-chunk-pages?path=${encodeURIComponent(filePath)}&chunk_ids=${encodeURIComponent(chunkIdsKey)}`)
      .then(r => r.json())
      .then(data => {
        if (data.pages) {
          setChunkPages(data.pages)
          const firstPage = data.pages[chunks[0]?.chunk_id] || 1
          if (iframeRef.current && firstPage > 1) {
            iframeRef.current.src = `${pdfBaseUrl}&_t=${Date.now()}#page=${firstPage}`
          }
        }
      })
      .catch(() => {})
      .finally(() => setPagesFetched(true))
  }, [expanded, filePath, chunkIdsKey])

  const handleGoToChunk = (chunkId: string) => {
    const page = chunkPages[chunkId] || 1
    setActiveChunkId(chunkId)
    if (iframeRef.current) {
      // Cache-bust to force Chrome PDF viewer to re-navigate to the new page
      iframeRef.current.src = `${pdfBaseUrl}&_t=${Date.now()}#page=${page}`
    }
  }

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full bg-surface-800/60 border border-surface-700/30 rounded-xl px-3.5 py-3 flex items-center justify-center gap-2 text-xs font-medium text-surface-400 hover:text-primary-400 hover:bg-surface-800/80 transition-colors"
      >
        <FileText className="w-4 h-4" />
        View PDF ({chunks.length} chunk{chunks.length !== 1 ? 's' : ''})
      </button>
    )
  }

  return (
    <div className="bg-surface-800/60 border border-surface-700/30 rounded-xl overflow-hidden">
      <iframe
        ref={iframeRef}
        src={`${pdfBaseUrl}#page=1`}
        className="w-full border-0"
        style={{ height: '500px', background: '#525659' }}
        title={`PDF: ${filePath.split('/').pop()}`}
      />
      {pagesFetched && (() => {
        // Merge chunks on the same page into a single link
        const pageMap = new Map<number, string[]>()
        for (const chunk of chunks) {
          const page = chunkPages[chunk.chunk_id] || 1
          if (!pageMap.has(page)) pageMap.set(page, [])
          pageMap.get(page)!.push(chunk.chunk_id)
        }
        if (pageMap.size <= 1) return null
        const pages = Array.from(pageMap.entries()).sort((a, b) => a[0] - b[0])
        return (
          <div className="border-t border-surface-700/20 px-3 py-2 flex flex-wrap gap-1.5">
            {pages.map(([page, cids]) => {
              const isActive = cids.includes(activeChunkId)
              return (
                <button
                  key={page}
                  onClick={() => handleGoToChunk(cids[0])}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                    isActive
                      ? 'bg-primary-500/15 text-primary-300'
                      : 'bg-surface-700/40 text-surface-400 hover:text-surface-200 hover:bg-surface-700/60'
                  }`}
                >
                  Page {page}
                </button>
              )
            })}
          </div>
        )
      })()}
    </div>
  )
}

// ── Launcher (no session active) ──
// Fallback display name from agent internal name
function fallbackDisplayName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function AgentLauncher() {
  const { data: agents } = useQuery({ queryKey: ['agents'], queryFn: api.agents.list })
  const { pickedAgents, agentOverrides } = useAgentStore()
  const { createSession, setActiveSession } = useConversationStore()

  const handleLaunch = async (agentName: string) => {
    const id = await createSession(agentName)
    setActiveSession(id)
  }

  if (pickedAgents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8">
        <Bot className="w-16 h-16 text-surface-500 mb-4" />
        <h2 className="text-xl font-medium text-surface-200 mb-2">No members in your team</h2>
        <p className="text-surface-500 max-w-md">
          Visit the <a href="/teams" className="text-primary-400 hover:text-primary-300">Teams</a> page to add members to your team.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-8">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center mb-6 shadow-glow">
        <Sparkles className="w-8 h-8 text-white" />
      </div>
      <h2 className="text-2xl font-semibold text-surface-100 mb-2">Start a conversation</h2>
      <p className="text-surface-500 mb-8 max-w-md text-center">Choose an agent to begin.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {pickedAgents.map(name => {
          const agent = agents?.find(a => a.name === name)
          const override = agentOverrides[name]
          const avatarUrl = override?.avatar_url || agent?.avatar_url
          const displayName = override?.display_name || agent?.display_name || fallbackDisplayName(name)
          return (
            <button
              key={name}
              onClick={() => handleLaunch(name)}
              className="flex items-center gap-4 p-5 bg-surface-800/50 border border-surface-700/50 rounded-2xl hover:border-primary-500/50 hover:bg-surface-700/50 transition-all text-left"
            >
              <AgentAvatar agent={agent} avatarUrl={avatarUrl} size="lg" />
              <div>
                <p className="text-sm font-semibold text-surface-100">{displayName}</p>
                {agent?.description && (
                  <p className="text-xs text-surface-500 mt-0.5 line-clamp-2">{agent.description}</p>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Main ConversationPage ──
export default function ConversationPage() {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>()
  const {
    activeSessionId,
    setActiveSession,
    getActiveSession,
    addMessage,
    updateLastMessage,
    updateMessageSources,
    setSessionDepth,
  } = useConversationStore()

  const authUser = useAuthStore(s => s.user)

  // Sync active session from URL param
  useEffect(() => {
    if (urlSessionId && urlSessionId !== activeSessionId) {
      setActiveSession(urlSessionId)
    }
  }, [urlSessionId])

  // Fetch agent metadata
  const { data: agents } = useQuery({ queryKey: ['agents'], queryFn: api.agents.list })

  const { agentOverrides } = useAgentStore()

  const activeSession = getActiveSession()
  const messages = activeSession?.messages || []
  const agentName = activeSession?.agentName
  const agentInfo = agents?.find(a => a.name === agentName)

  // Resolve overrides for consistent visuals
  const agentOverride = agentName ? agentOverrides[agentName] : undefined
  const agentAvatarUrl = agentOverride?.avatar_url || agentInfo?.avatar_url
  const agentDisplayName = agentOverride?.display_name || agentInfo?.display_name || agentName || 'Agent'

  // State
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [depth, setDepth] = useState<ResearchDepth>('standard')

  // Right sidebar
  const MIN_RIGHT_SIDEBAR_WIDTH = 64
  const MAX_RIGHT_SIDEBAR_WIDTH = 800
  const DEFAULT_RIGHT_SIDEBAR_WIDTH = 340
  const [rightSidebarWidth, setRightSidebarWidth] = useState(DEFAULT_RIGHT_SIDEBAR_WIDTH)
  const [isResizingRight, setIsResizingRight] = useState(false)
  const rightSidebarCollapsed = rightSidebarWidth < 80

  // Sources panel state
  const [selectedMessageIndex, setSelectedMessageIndex] = useState<number | null>(null)
  const [expandedChunks, setExpandedChunks] = useState<Record<string, ContextChunk[]>>({})
  const [loadingContext, setLoadingContext] = useState<string | null>(null)

  // Progress panel state
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([])
  const [currentPhase, setCurrentPhase] = useState<string>('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const previousSessionIdRef = useRef<string | null>(null)

  const focusInputWithoutScroll = useCallback(() => {
    const input = inputRef.current
    if (!input) return
    try {
      input.focus({ preventScroll: true })
    } catch {
      input.focus()
    }
  }, [])

  const selectedMessage = selectedMessageIndex !== null ? messages[selectedMessageIndex] : null
  const selectedSources = selectedMessage?.sources || []
  const sourcesByFile = selectedSources.reduce<Record<string, SourceChunk[]>>((acc, src) => {
    const key = src.file_path
    if (!acc[key]) acc[key] = []
    acc[key].push(src)
    return acc
  }, {})

  // Features
  const hasSourcesPanel = agentInfo?.features?.has_sources_panel ?? false
  const hasProgressPanel = agentInfo?.features?.has_progress_panel ?? false
  const hasDepthSelector = agentInfo?.features?.has_depth_selector ?? false
  const hasRightSidebar = hasSourcesPanel || hasProgressPanel

  // Sync depth from active session
  useEffect(() => {
    if (activeSession?.depth) setDepth(activeSession.depth)
  }, [activeSession?.depth])

  // Scroll to bottom for new messages in the current session.
  // Skip when switching sessions to avoid jumping the outer viewport.
  useEffect(() => {
    const sessionChanged = previousSessionIdRef.current !== (activeSessionId ?? null)
    previousSessionIdRef.current = activeSessionId ?? null
    if (sessionChanged) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeSessionId])

  // Focus input on session switch
  useEffect(() => {
    if (activeSessionId) focusInputWithoutScroll()
  }, [activeSessionId, focusInputWithoutScroll])

  // Reset tool calls on session switch
  useEffect(() => {
    setActiveToolCalls([])
    setCurrentPhase('')
    setSelectedMessageIndex(null)
  }, [activeSessionId])

  const handleRightSidebarResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizingRight(true)
    const startX = e.clientX
    const startWidth = rightSidebarWidth

    const handleMouseMove = (e: MouseEvent) => {
      const delta = startX - e.clientX
      setRightSidebarWidth(Math.min(MAX_RIGHT_SIDEBAR_WIDTH, Math.max(MIN_RIGHT_SIDEBAR_WIDTH, startWidth + delta)))
    }

    const handleMouseUp = () => {
      setIsResizingRight(false)
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [rightSidebarWidth])

  const handleExpandContext = async (filePath: string, chunkId: string) => {
    const key = `${filePath}::${chunkId}`
    if (expandedChunks[key]) {
      setExpandedChunks(prev => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      return
    }
    setLoadingContext(key)
    try {
      const data = await api.documents.getContext(filePath, chunkId, 2)
      if (data.status === 'success') {
        setExpandedChunks(prev => ({ ...prev, [key]: data.context }))
      }
    } catch (err) {
      console.error('Failed to load context:', err)
    } finally {
      setLoadingContext(null)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading || !activeSessionId || !agentName) return

    const userMessage = input.trim()
    const sessionId = activeSessionId
    setInput('')
    addMessage(sessionId, { role: 'user', content: userMessage })
    setIsLoading(true)

    // Add placeholder for assistant response
    addMessage(sessionId, { role: 'assistant', content: '' })
    const assistantMsgIndex = messages.length + 1

    // For research agents, prepend depth
    const messageText = hasDepthSelector
      ? `[DEPTH: ${depth.toUpperCase()}]\n\n${userMessage}`
      : userMessage

    if (hasDepthSelector) {
      setSessionDepth(sessionId, depth)
      setActiveToolCalls([])
      setCurrentPhase('Initializing research...')
    }

    try {
      let assistantContent = ''
      const collectedSources: SourceChunk[] = []

      const response = await fetch(`${AGENT_BASE}/run_sse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          appName: agentName,
          userId: authUser?.username || 'local_user',
          sessionId: sessionId,
          newMessage: {
            role: 'user',
            parts: [{ text: messageText }],
          },
          streaming: true,
        }),
      })

      if (!response.ok) throw new Error(`Request failed: ${response.status}`)

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
            if (data === '[DONE]') continue
            try {
              const event = JSON.parse(data)

              // Helper to add a tool call (for progress panel)
              const addToolCall = (name: string, args?: Record<string, unknown>) => {
                const toolCall: ToolCall = { name, args, status: 'running', startTime: Date.now() }
                setActiveToolCalls(prev => [...prev, toolCall])
                setCurrentPhase(`Running ${name}...`)
              }

              if (event.content?.parts) {
                for (const part of event.content.parts) {
                  // Text content
                  if (part.text) {
                    if (event.partial === false) {
                      assistantContent = part.text
                    } else {
                      assistantContent += part.text
                    }
                    updateLastMessage(sessionId, assistantContent)

                    if (hasProgressPanel) {
                      if (assistantContent.length < 100) setCurrentPhase('Synthesizing findings...')
                      else if (assistantContent.length > 500) setCurrentPhase('Compiling report...')
                    }
                  }

                  // Tool calls (for progress panel)
                  if (hasProgressPanel) {
                    if (part.functionCall) addToolCall(part.functionCall.name, part.functionCall.args)
                    if (part.function_call) addToolCall(part.function_call.name, part.function_call.args)
                    if (part.functionResponse || part.function_response) {
                      const resp = part.functionResponse || part.function_response
                      setActiveToolCalls(prev => prev.map(tc =>
                        tc.name === resp.name && tc.status === 'running'
                          ? { ...tc, status: 'completed' }
                          : tc
                      ))
                    }
                  }

                  // Source collection (for sources panel)
                  if (hasSourcesPanel) {
                    const funcResp = part.functionResponse || part.function_response
                    if (funcResp) {
                      const toolName = funcResp.name || ''
                      const respData = funcResp.response || {}
                      if ((toolName === 'search_chunks' || toolName === 'keyword_search') && respData.status === 'success') {
                        const results = respData.results || []
                        for (const r of results) {
                          if (r.chunk_id && !collectedSources.some((s: SourceChunk) => s.chunk_id === r.chunk_id)) {
                            collectedSources.push({
                              file_path: r.file_path || '',
                              chunk_id: r.chunk_id,
                              content: r.content || '',
                              score: r.score || r.best_score || 0,
                            })
                          }
                        }
                      }
                    }
                  }
                }
              }

              // Additional tool call formats (for progress panel)
              if (hasProgressPanel) {
                if (event.tool_calls) {
                  for (const tc of event.tool_calls) {
                    addToolCall(tc.function?.name || tc.name, tc.function?.arguments || tc.args)
                  }
                }
                if (event.function_calls) {
                  for (const fc of event.function_calls) {
                    addToolCall(fc.name, fc.args)
                  }
                }
                if (event.tool_call) {
                  addToolCall(event.tool_call.function?.name || event.tool_call.name, event.tool_call.function?.arguments)
                }
              }

              if (typeof event.content === 'string') {
                assistantContent += event.content
                updateLastMessage(sessionId, assistantContent)
              }
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }

      if (!assistantContent) {
        updateLastMessage(sessionId, 'No response received.')
      }

      if (collectedSources.length > 0) {
        updateMessageSources(sessionId, assistantMsgIndex, collectedSources)
        setSelectedMessageIndex(assistantMsgIndex)
      }
    } catch (error) {
      console.error('Conversation error:', error)
      updateLastMessage(sessionId, `Error: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsLoading(false)
      if (hasProgressPanel) {
        setCurrentPhase('Complete')
        setActiveToolCalls(prev => prev.map(tc => ({ ...tc, status: 'completed' as const })))
      }
      setTimeout(() => focusInputWithoutScroll(), 0)
    }
  }

  // No active session → show launcher
  if (!activeSessionId || !activeSession) {
    return <AgentLauncher />
  }

  const agentGradient = agentBgColor(agentInfo)

  return (
    <div className={`flex h-full ${isResizingRight ? 'select-none' : ''}`}>
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-surface-900 min-w-0">
        {/* Header */}
        <div className="border-b border-surface-700/50 bg-surface-800/30 backdrop-blur-sm px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <AgentAvatar agent={agentInfo} avatarUrl={agentAvatarUrl} size="sm" />
              <div>
                <h1 className="text-lg font-semibold text-surface-100">{agentDisplayName}</h1>
                <p className="text-xs text-surface-500">{agentInfo?.description?.slice(0, 80) || 'Conversation'}</p>
              </div>
            </div>
            {hasDepthSelector && (
              <div className="flex items-center gap-3">
                <label className="text-sm text-surface-500">Depth:</label>
                <select
                  value={depth}
                  onChange={(e) => setDepth(e.target.value as ResearchDepth)}
                  disabled={isLoading}
                  className="px-3 py-2 bg-surface-800 border border-surface-600 rounded-xl text-sm text-surface-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-50"
                >
                  {depthOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <AgentAvatar agent={agentInfo} avatarUrl={agentAvatarUrl} size="xl" className="mb-6 shadow-glow" />
              <h2 className="text-xl font-medium text-surface-200">{agentDisplayName}</h2>
              <p className="text-surface-500 mt-2 max-w-md">
                {agentInfo?.description || 'Start a conversation.'}
              </p>
            </div>
          )}

          {messages.map((message, i) => (
            <div key={i}>
              <div className={`flex gap-4 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {message.role === 'assistant' && (
                  <AgentAvatar agent={agentInfo} avatarUrl={agentAvatarUrl} size="md" className="shadow-glow" />
                )}
                <div className={`max-w-[70%] rounded-2xl px-5 py-3 ${
                  message.role === 'user'
                    ? 'bg-primary-600 text-white'
                    : 'bg-surface-800 border border-surface-700'
                }`}>
                  {message.role === 'user' ? (
                    <p className="text-sm whitespace-pre-wrap leading-relaxed selection:bg-white/30 selection:text-white">{message.content}</p>
                  ) : (
                    <div className="prose prose-sm prose-invert max-w-none text-surface-200">
                      <ReactMarkdown>{message.content || '...'}</ReactMarkdown>
                    </div>
                  )}
                </div>
                {message.role === 'user' && (
                  <div className="w-9 h-9 rounded-xl bg-surface-700 flex items-center justify-center flex-shrink-0 overflow-hidden">
                    {authUser?.avatar_url ? (
                      <img src={authUser.avatar_url} alt={authUser.display_name} className="w-full h-full object-cover" />
                    ) : (
                      <User className="w-5 h-5 text-surface-300" />
                    )}
                  </div>
                )}
              </div>
              {/* Source badge */}
              {hasSourcesPanel && message.role === 'assistant' && message.sources && message.sources.length > 0 && (
                <div className="ml-13 mt-1.5 pl-13">
                  <button
                    onClick={() => setSelectedMessageIndex(selectedMessageIndex === i ? null : i)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                      selectedMessageIndex === i
                        ? 'bg-primary-600/20 text-primary-400 border border-primary-500/30'
                        : 'bg-surface-800/50 text-surface-400 hover:bg-surface-700/50 hover:text-surface-300 border border-transparent'
                    }`}
                  >
                    <FileText className="w-3.5 h-3.5" />
                    {message.sources.length} source{message.sources.length !== 1 ? 's' : ''}
                  </button>
                </div>
              )}
            </div>
          ))}

          {isLoading && messages[messages.length - 1]?.content === '' && (
            <div className="flex gap-4">
              {agentAvatarUrl ? (
                <div className="w-9 h-9 rounded-xl flex-shrink-0 relative shadow-glow">
                  <img src={agentAvatarUrl} alt="" className="w-9 h-9 rounded-xl object-cover opacity-60" />
                  <Loader2 className="w-5 h-5 text-white animate-spin absolute inset-0 m-auto" />
                </div>
              ) : (
                <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${agentGradient} flex items-center justify-center shadow-glow`}>
                  <Loader2 className="w-5 h-5 text-white animate-spin" />
                </div>
              )}
              <div className="bg-surface-800 border border-surface-700 rounded-2xl px-5 py-3">
                <p className="text-sm text-surface-500">Thinking...</p>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-surface-700/50 bg-surface-800/30 backdrop-blur-sm p-4">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={agentInfo?.features?.has_depth_selector ? 'Ask a research question...' : 'Type a message...'}
              disabled={isLoading || !activeSessionId}
              className="flex-1 px-5 py-3 bg-surface-800 border border-surface-600 rounded-xl text-surface-200 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading || !activeSessionId}
              className="px-5 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl hover:from-primary-500 hover:to-primary-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-glow"
            >
              <Send className="w-5 h-5" />
            </button>
          </form>
        </div>
      </div>

      {/* Right sidebar (only if agent has one) */}
      {hasRightSidebar && (
        <>
          {/* Resize handle */}
          <div
            onMouseDown={handleRightSidebarResize}
            className={`w-1 cursor-col-resize hover:bg-primary-500/50 transition-colors ${isResizingRight ? 'bg-primary-500' : 'bg-transparent'}`}
          />

          <div
            style={{ width: rightSidebarWidth }}
            className="border-l border-surface-700/30 bg-surface-950/40 backdrop-blur-sm flex flex-col flex-shrink-0"
          >
            <div className={`${rightSidebarCollapsed ? 'p-2' : 'px-4 py-3'} border-b border-surface-700/30 flex items-center justify-between`}>
              {!rightSidebarCollapsed && (
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-surface-100">
                    {hasSourcesPanel ? 'Sources' : 'Progress'}
                  </h3>
                  {hasSourcesPanel && selectedSources.length > 0 && (
                    <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-md bg-primary-500/20 text-primary-300">
                      {selectedSources.length}
                    </span>
                  )}
                </div>
              )}
              <button
                onClick={() => setRightSidebarWidth(rightSidebarCollapsed ? DEFAULT_RIGHT_SIDEBAR_WIDTH : MIN_RIGHT_SIDEBAR_WIDTH)}
                className="p-1.5 rounded-lg text-surface-400 hover:bg-white/[0.06] hover:text-surface-200 transition-all"
                title={rightSidebarCollapsed ? 'Expand' : 'Collapse'}
              >
                {rightSidebarCollapsed ? <PanelRight className="w-4 h-4" /> : <PanelRightClose className="w-4 h-4" />}
              </button>
            </div>

            {/* Sources panel content */}
            {hasSourcesPanel && !rightSidebarCollapsed && (
              <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {selectedSources.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                    <div className="w-14 h-14 rounded-2xl bg-surface-800/80 border border-surface-700/30 flex items-center justify-center mb-4">
                      <FileText className="w-6 h-6 text-surface-500" />
                    </div>
                    <p className="text-sm font-medium text-surface-300">No sources selected</p>
                    <p className="text-xs text-surface-500 mt-1.5 leading-relaxed">Click a source badge on any response to view referenced documents</p>
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-surface-500 px-1">
                      {selectedSources.length} chunk{selectedSources.length !== 1 ? 's' : ''} from {Object.keys(sourcesByFile).length} file{Object.keys(sourcesByFile).length !== 1 ? 's' : ''}
                    </p>
                    {(() => { let firstPdfSeen = false; return Object.entries(sourcesByFile).map(([filePath, chunks]) => {
                      const basename = filePath.split('/').pop() || filePath
                      const isPdf = filePath.toLowerCase().endsWith('.pdf')
                      const isFirstPdf = isPdf && !firstPdfSeen
                      if (isPdf) firstPdfSeen = true
                      return (
                        <div key={filePath} className="space-y-2">
                          {/* File header */}
                          <div className="flex items-center gap-2 px-1">
                            <div className="w-5 h-5 rounded-md bg-primary-500/15 flex items-center justify-center flex-shrink-0">
                              <FileText className="w-3 h-3 text-primary-400" />
                            </div>
                            <a
                              href={`/knowledge?path=${encodeURIComponent(filePath)}`}
                              className="text-sm font-medium text-primary-400 hover:text-primary-300 truncate transition-colors flex items-center gap-1.5"
                              title={filePath}
                            >
                              {basename}
                              <ExternalLink className="w-3 h-3 flex-shrink-0 opacity-60" />
                            </a>
                            <span className="text-[10px] text-surface-500 flex-shrink-0 ml-auto">{chunks.length} chunk{chunks.length !== 1 ? 's' : ''}</span>
                          </div>
                          {/* PDF: one viewer per file with chunk page links */}
                          {isPdf ? (
                            <PdfSourceViewer filePath={filePath} chunks={chunks} defaultExpanded={isFirstPdf} />
                          ) : (
                            /* Non-PDF: per-chunk text cards */
                            chunks.map((chunk) => {
                              const contextKey = `${filePath}::${chunk.chunk_id}`
                              const contextData = expandedChunks[contextKey]
                              const isExpanding = loadingContext === contextKey

                              return (
                                <div key={chunk.chunk_id} className="bg-surface-800/60 border border-surface-700/30 rounded-xl overflow-hidden">
                                  {!contextData ? (
                                    <>
                                      <div className="px-3.5 py-3 text-[13px] text-surface-300 leading-relaxed max-h-36 overflow-y-auto prose prose-sm prose-invert max-w-none">
                                        <ReactMarkdown>{chunk.content}</ReactMarkdown>
                                      </div>
                                      <button
                                        onClick={() => handleExpandContext(filePath, chunk.chunk_id)}
                                        disabled={isExpanding}
                                        className="w-full px-3.5 py-2 text-xs font-medium text-surface-500 hover:text-primary-400 hover:bg-white/[0.03] transition-colors flex items-center justify-center gap-1.5 border-t border-surface-700/20"
                                      >
                                        {isExpanding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                        Show context
                                      </button>
                                    </>
                                  ) : (
                                    <>
                                      <div className="px-3.5 py-3 space-y-2 max-h-72 overflow-y-auto">
                                        {contextData.map((ctx) => (
                                          <div
                                            key={ctx.chunk_id}
                                            className={`text-[13px] leading-relaxed rounded-lg px-3 py-2 prose prose-sm prose-invert max-w-none ${
                                              ctx.is_target
                                                ? 'bg-primary-500/10 border border-primary-500/20 text-surface-200'
                                                : 'text-surface-400/80'
                                            }`}
                                          >
                                            <ReactMarkdown>{ctx.content}</ReactMarkdown>
                                          </div>
                                        ))}
                                      </div>
                                      <button
                                        onClick={() => handleExpandContext(filePath, chunk.chunk_id)}
                                        className="w-full px-3.5 py-2 text-xs font-medium text-surface-500 hover:text-primary-400 hover:bg-white/[0.03] transition-colors flex items-center justify-center gap-1.5 border-t border-surface-700/20"
                                      >
                                        <ChevronRight className="w-3.5 h-3.5" />
                                        Collapse
                                      </button>
                                    </>
                                  )}
                                </div>
                              )
                            })
                          )}
                        </div>
                      )
                    }) })()}
                  </>
                )}
              </div>
            )}

            {/* Progress panel content */}
            {hasProgressPanel && !rightSidebarCollapsed && (
              <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {isLoading && (
                  <div className="bg-surface-800 border border-surface-700 rounded-xl p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <div className="w-8 h-8 rounded-lg bg-primary-600/20 flex items-center justify-center">
                        <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-surface-200">In Progress</p>
                        <p className="text-xs text-surface-500">{currentPhase}</p>
                      </div>
                    </div>
                  </div>
                )}
                {activeToolCalls.length > 0 ? (
                  <div>
                    <h4 className="text-xs font-medium text-surface-400 uppercase tracking-wide mb-3">
                      Progress ({activeToolCalls.filter(t => t.status === 'completed').length}/{activeToolCalls.length})
                    </h4>
                    <div className="space-y-2">
                      {activeToolCalls.map((tool, i) => {
                        const displayInfo = getToolDisplayInfo(tool.name, tool.args)
                        return (
                          <div
                            key={`${tool.name}-${tool.startTime}-${i}`}
                            className={`p-3 rounded-xl border ${
                              tool.status === 'running'
                                ? 'bg-violet-500/10 border-violet-500/30'
                                : 'bg-surface-800/50 border-surface-700/50'
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              {tool.status === 'running' ? (
                                <Loader2 className="w-4 h-4 text-violet-400 animate-spin flex-shrink-0" />
                              ) : (
                                <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0" />
                              )}
                              <div className="flex-1 min-w-0">
                                <span className={`text-sm font-medium ${tool.status === 'running' ? 'text-violet-200' : 'text-surface-300'}`}>
                                  {displayInfo.label}
                                </span>
                                {displayInfo.detail && (
                                  <p className="text-xs text-surface-500 truncate mt-0.5">
                                    {displayInfo.detail.length > 50 ? displayInfo.detail.slice(0, 50) + '...' : displayInfo.detail}
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ) : isLoading && (
                  <div>
                    <h4 className="text-xs font-medium text-surface-400 uppercase tracking-wide mb-3">Activity</h4>
                    <div className="flex items-center gap-3 p-3 bg-surface-800 rounded-xl border border-surface-700">
                      <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                      <p className="text-xs text-surface-400">Processing query...</p>
                    </div>
                  </div>
                )}
                {!isLoading && activeToolCalls.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-48 text-center">
                    <div className="w-12 h-12 rounded-xl bg-surface-800 flex items-center justify-center mb-3">
                      <Brain className="w-6 h-6 text-surface-500" />
                    </div>
                    <p className="text-sm text-surface-400">No active task</p>
                    <p className="text-xs text-surface-500 mt-1">Start a query to see progress</p>
                  </div>
                )}
                {!isLoading && activeToolCalls.length > 0 && activeToolCalls.every(t => t.status === 'completed') && (
                  <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
                    <div className="flex items-center gap-3">
                      <CheckCircle2 className="w-5 h-5 text-green-400" />
                      <div>
                        <p className="text-sm font-medium text-green-300">Complete</p>
                        <p className="text-xs text-green-400/70">{activeToolCalls.length} tools executed</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Collapsed right sidebar */}
            {rightSidebarCollapsed && (
              <div className="flex-1 flex flex-col items-center py-4 gap-4">
                {hasSourcesPanel && selectedSources.length > 0 ? (
                  <div
                    className="w-10 h-10 rounded-xl bg-primary-600/20 flex items-center justify-center cursor-pointer"
                    title={`${selectedSources.length} sources`}
                    onClick={() => setRightSidebarWidth(DEFAULT_RIGHT_SIDEBAR_WIDTH)}
                  >
                    <FileText className="w-5 h-5 text-primary-400" />
                  </div>
                ) : hasProgressPanel && isLoading ? (
                  <div className="w-10 h-10 rounded-xl bg-primary-600/20 flex items-center justify-center" title={currentPhase}>
                    <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
                  </div>
                ) : hasProgressPanel && activeToolCalls.length > 0 && activeToolCalls.every(t => t.status === 'completed') ? (
                  <div className="w-10 h-10 rounded-xl bg-green-500/20 flex items-center justify-center" title="Complete">
                    <CheckCircle2 className="w-5 h-5 text-green-400" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-xl bg-surface-800 flex items-center justify-center">
                    {hasSourcesPanel ? <FileText className="w-5 h-5 text-surface-500" /> : <Brain className="w-5 h-5 text-surface-500" />}
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}

    </div>
  )
}
