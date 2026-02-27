import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useAuthStore } from './authStore'

// Use relative URLs so the proxy (Vite in dev, indexer in production) routes to agent server
const AGENT_BASE = '/api'

function getAdkUserId(): string {
  return useAuthStore.getState().user?.username || 'local_user'
}

export type ResearchDepth = 'quick' | 'standard' | 'deep'

export interface SourceChunk {
  file_path: string
  chunk_id: string
  content: string
  score: number
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceChunk[]
}

export interface ConversationSession {
  id: string
  title: string
  agentName: string
  messages: Message[]
  depth?: ResearchDepth
  createdAt: number
  updatedAt: number
}

interface ConversationStore {
  sessions: ConversationSession[]
  activeSessionId: string | null
  isLoading: boolean

  // Actions
  fetchSessions: (agentName: string) => Promise<void>
  fetchAllSessions: (agentNames: string[]) => Promise<void>
  createSession: (agentName: string, depth?: ResearchDepth) => Promise<string>
  deleteSession: (id: string) => Promise<void>
  setActiveSession: (id: string | null) => void
  getActiveSession: () => ConversationSession | undefined
  getSessionsByAgent: (agentName: string) => ConversationSession[]
  addMessage: (sessionId: string, message: Message) => void
  updateLastMessage: (sessionId: string, content: string) => void
  updateMessageSources: (sessionId: string, messageIndex: number, sources: SourceChunk[]) => void
  setSessionDepth: (sessionId: string, depth: ResearchDepth) => void
  setSessionTitle: (sessionId: string, title: string) => void
  clearSessions: () => void
}

const generateTitle = (messages: Message[]) => {
  const firstUserMsg = messages.find(m => m.role === 'user')
  if (firstUserMsg) {
    let content = firstUserMsg.content
    content = content.replace(/^\[DEPTH: (QUICK|STANDARD|DEEP)\]\s*/i, '')
    return content.slice(0, 50) + (content.length > 50 ? '...' : '')
  }
  return 'New Conversation'
}

// Parse ADK events into messages
interface AdkFunctionResponse {
  name?: string
  response?: { status?: string; results?: Array<{ file_path?: string; chunk_id?: string; content?: string; score?: number; best_score?: number }> }
}

interface AdkEvent {
  author?: string
  content?: {
    role?: string
    parts?: Array<{ text?: string; functionCall?: unknown; functionResponse?: AdkFunctionResponse; function_response?: AdkFunctionResponse }>
  }
}

const parseEventsToMessages = (events: AdkEvent[]): Message[] => {
  const messages: Message[] = []
  let pendingSources: SourceChunk[] = []

  for (const event of events) {
    const role = event.content?.role
    const parts = event.content?.parts || []

    for (const part of parts) {
      // Collect sources from tool responses
      const funcResp = part.functionResponse || part.function_response
      if (funcResp) {
        const toolName = funcResp.name || ''
        const respData = funcResp.response || {}
        if ((toolName === 'search_chunks' || toolName === 'keyword_search') && respData.status === 'success') {
          for (const r of (respData.results || [])) {
            if (r.chunk_id && !pendingSources.some(s => s.chunk_id === r.chunk_id)) {
              pendingSources.push({
                file_path: r.file_path || '',
                chunk_id: r.chunk_id,
                content: r.content || '',
                score: r.score || r.best_score || 0,
              })
            }
          }
        }
      }

      // Build messages from text content
      if (part.text && (role === 'user' || role === 'model')) {
        const msg: Message = {
          role: role === 'user' ? 'user' : 'assistant',
          content: part.text,
        }
        // Attach collected sources to assistant messages
        if (role === 'model' && pendingSources.length > 0) {
          msg.sources = [...pendingSources]
          pendingSources = []
        }
        messages.push(msg)
      }
    }
  }

  return messages
}

export const useConversationStore = create<ConversationStore>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,
      isLoading: false,

      fetchSessions: async (agentName: string) => {
        try {
          const listResponse = await fetch(`${AGENT_BASE}/apps/${agentName}/users/${getAdkUserId()}/sessions`)
          if (!listResponse.ok) return

          const backendSessions = await listResponse.json()
          const sessionList: Array<{ id: string; last_update_time?: number }> =
            Array.isArray(backendSessions) ? backendSessions : (backendSessions.sessions || [])

          const sessionsWithEvents = await Promise.all(
            sessionList.map(async (s) => {
              try {
                const sessionResponse = await fetch(
                  `${AGENT_BASE}/apps/${agentName}/users/${getAdkUserId()}/sessions/${s.id}`
                )
                if (sessionResponse.ok) {
                  return await sessionResponse.json()
                }
              } catch (err) {
                console.error(`Failed to fetch session ${s.id}:`, err)
              }
              return { id: s.id, events: [], last_update_time: s.last_update_time }
            })
          )

          const newSessions = sessionsWithEvents.map((s: {
            id: string
            events?: AdkEvent[]
            last_update_time?: number
          }) => {
            const messagesFromEvents = parseEventsToMessages(s.events || [])
            const title = generateTitle(messagesFromEvents)

            return {
              id: s.id,
              title: title || 'New Conversation',
              agentName,
              messages: messagesFromEvents,
              createdAt: (s.last_update_time ? s.last_update_time * 1000 : Date.now()),
              updatedAt: (s.last_update_time ? s.last_update_time * 1000 : Date.now()),
            }
          })

          // Merge: replace sessions for this agent, keep others
          set((state) => {
            const otherSessions = state.sessions.filter(s => s.agentName !== agentName)
            const merged = [...otherSessions, ...newSessions]
            merged.sort((a, b) => b.updatedAt - a.updatedAt)
            return { sessions: merged }
          })
        } catch (error) {
          console.error(`Failed to fetch sessions for ${agentName}:`, error)
        }
      },

      fetchAllSessions: async (agentNames: string[]) => {
        set({ isLoading: true })
        try {
          await Promise.all(agentNames.map(name => get().fetchSessions(name)))
        } finally {
          set({ isLoading: false })
        }
      },

      createSession: async (agentName: string, depth?: ResearchDepth) => {
        const response = await fetch(`${AGENT_BASE}/apps/${agentName}/users/${getAdkUserId()}/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        })

        if (!response.ok) {
          throw new Error(`Failed to create session: ${response.status}`)
        }

        const data = await response.json()
        const id = data.id
        const session: ConversationSession = {
          id,
          title: 'New Conversation',
          agentName,
          messages: [],
          depth,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        }
        set(state => ({
          sessions: [session, ...state.sessions],
          activeSessionId: id,
        }))
        return id
      },

      deleteSession: async (id) => {
        const session = get().sessions.find(s => s.id === id)
        if (session) {
          try {
            await fetch(`${AGENT_BASE}/apps/${session.agentName}/users/${getAdkUserId()}/sessions/${id}`, { method: 'DELETE' })
          } catch (error) {
            console.error('Failed to delete session from backend:', error)
          }
        }

        set(state => ({
          sessions: state.sessions.filter(s => s.id !== id),
          activeSessionId: state.activeSessionId === id ? null : state.activeSessionId,
        }))
      },

      setActiveSession: (id) => {
        set({ activeSessionId: id })
      },

      getActiveSession: () => {
        const { sessions, activeSessionId } = get()
        return sessions.find(s => s.id === activeSessionId)
      },

      getSessionsByAgent: (agentName: string) => {
        return get().sessions
          .filter(s => s.agentName === agentName)
          .sort((a, b) => b.updatedAt - a.updatedAt)
      },

      addMessage: (sessionId, message) => {
        set(state => ({
          sessions: state.sessions.map(s => {
            if (s.id !== sessionId) return s
            const newMessages = [...s.messages, message]
            const newTitle = s.messages.length === 0 && message.role === 'user'
              ? generateTitle([message])
              : s.title
            return {
              ...s,
              messages: newMessages,
              title: newTitle,
              updatedAt: Date.now(),
            }
          }),
        }))
      },

      updateLastMessage: (sessionId, content) => {
        set(state => ({
          sessions: state.sessions.map(s => {
            if (s.id !== sessionId) return s
            const messages = [...s.messages]
            if (messages.length > 0) {
              messages[messages.length - 1] = { ...messages[messages.length - 1], content }
            }
            return { ...s, messages, updatedAt: Date.now() }
          }),
        }))
      },

      updateMessageSources: (sessionId, messageIndex, sources) => {
        set(state => ({
          sessions: state.sessions.map(s => {
            if (s.id !== sessionId) return s
            const messages = [...s.messages]
            if (messageIndex >= 0 && messageIndex < messages.length) {
              messages[messageIndex] = { ...messages[messageIndex], sources }
            }
            return { ...s, messages, updatedAt: Date.now() }
          }),
        }))
      },

      setSessionDepth: (sessionId, depth) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId ? { ...s, depth, updatedAt: Date.now() } : s
          ),
        }))
      },

      setSessionTitle: (sessionId, title) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId ? { ...s, title, updatedAt: Date.now() } : s
          ),
        }))
      },

      clearSessions: () => {
        set({ sessions: [], activeSessionId: null })
      },
    }),
    {
      name: 'sosie-conversations',
      partialize: (state) => ({
        sessions: state.sessions,
        activeSessionId: state.activeSessionId,
      }),
    }
  )
)
