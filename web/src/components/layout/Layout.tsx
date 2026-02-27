import { ReactNode, useState, useRef, useCallback, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Settings,
  Sparkles,
  Server,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Bot,
  Plus,
  Trash2,
  MessageSquare,
} from 'lucide-react'
import { useAgentStore } from '../../stores/agentStore'
import { useConversationStore } from '../../stores/conversationStore'
import { useAuthStore } from '../../stores/authStore'
import { api } from '../../api/client'

interface LayoutProps {
  children: ReactNode
}

const agentNavItems = [
  { path: '/teams', label: 'Teams', icon: Bot },
  { path: '/knowledge', label: 'Knowledge', icon: BookOpen },
]

const configurationNavItems = [
  { path: '/system', label: 'System', icon: Server },
  { path: '/settings', label: 'Settings', icon: Settings },
]

const MIN_SIDEBAR_WIDTH = 72
const MAX_SIDEBAR_WIDTH = 400
const DEFAULT_SIDEBAR_WIDTH = 320

// Map agent icon string to Lucide component
function getAgentIcon(icon?: string) {
  if (icon === 'book-open') return BookOpen
  if (icon === 'message-square') return MessageSquare
  return Bot
}

function getAgentColorClasses(color?: string) {
  if (color === 'purple') return { bg: 'bg-purple-500/20', text: 'text-purple-400', gradient: 'from-violet-600 to-purple-500' }
  if (color === 'blue') return { bg: 'bg-blue-500/20', text: 'text-blue-400', gradient: 'from-blue-500 to-cyan-500' }
  return { bg: 'bg-primary-500/20', text: 'text-primary-400', gradient: 'from-primary-500 to-primary-600' }
}


export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const [collapsedAgents, setCollapsedAgents] = useState<Record<string, boolean>>({})
  const [collapsedAgentPages, setCollapsedAgentPages] = useState(false)
  const [collapsedConfiguration, setCollapsedConfiguration] = useState(true)
  const sidebarRef = useRef<HTMLElement>(null)
  const hasFetchedRef = useRef(false)

  const sidebarCollapsed = sidebarWidth < 88

  const user = useAuthStore(s => s.user)
  const { pickedAgents, agentOverrides } = useAgentStore()
  const {
    activeSessionId,
    fetchAllSessions,
    createSession,
    deleteSession,
    setActiveSession,
    getSessionsByAgent,
  } = useConversationStore()

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: api.agents.list,
    staleTime: 60000,
  })

  // Fetch sessions for all picked agents on mount
  useEffect(() => {
    if (!hasFetchedRef.current && pickedAgents.length > 0) {
      hasFetchedRef.current = true
      fetchAllSessions(pickedAgents)
    }
  }, [pickedAgents])

  // Build agent display list from pickedAgents, with local overrides on top
  const pickedAgentInfos = pickedAgents.map(name => {
    const info = agents?.find(a => a.name === name)
    const override = agentOverrides[name]
    return {
      name,
      display_name: override?.display_name || info?.display_name || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      icon: info?.icon,
      color: info?.color,
      avatar_url: override?.avatar_url || info?.avatar_url,
    }
  })

  const toggleAgentCollapse = (name: string) => {
    setCollapsedAgents(prev => ({ ...prev, [name]: !prev[name] }))
  }

  const handleNewSession = async (agentName: string) => {
    try {
      const id = await createSession(agentName)
      setActiveSession(id)
      navigate(`/chat/${id}`)
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }

  const handleSelectSession = (sessionId: string) => {
    setActiveSession(sessionId)
    navigate(`/chat/${sessionId}`)
  }

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation()
    await deleteSession(sessionId)
  }

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = e.clientX
      setSidebarWidth(Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, newWidth)))
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  return (
    <div className={`flex h-screen bg-surface-900 ${isResizing ? 'select-none' : ''}`}>
      {/* Sidebar */}
      <aside
        ref={sidebarRef}
        style={{ width: sidebarWidth }}
        className="bg-surface-950/60 backdrop-blur-xl border-r border-surface-700/30 flex flex-col flex-shrink-0"
      >
        {/* User / App identity */}
        <Link
          to="/settings"
          className={`h-14 flex items-center ${sidebarCollapsed ? 'justify-center px-2' : 'px-4'} border-b border-surface-700/30 hover:bg-white/[0.03] transition-colors group`}
          title={sidebarCollapsed ? (user?.display_name || 'Settings') : undefined}
        >
          {user?.avatar_url ? (
            <img src={user.avatar_url} alt={user.display_name || 'User'} className="w-8 h-8 rounded-xl object-cover flex-shrink-0 ring-1 ring-white/10 group-hover:ring-white/20 transition-all" />
          ) : (
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shadow-glow flex-shrink-0">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
          )}
          {!sidebarCollapsed && (
            <span className="ml-3 text-[15px] font-semibold text-surface-100 truncate group-hover:text-white transition-colors">
              {user?.display_name || 'Sosie'}
            </span>
          )}
        </Link>

        {/* Chats section */}
        <div className="flex-1 overflow-y-auto px-2 pt-3 pb-2">
          {!sidebarCollapsed && pickedAgentInfos.length > 0 && (
            <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-widest text-surface-500">Chats</p>
          )}

          {pickedAgentInfos.map((agent) => {
            const agentSessions = getSessionsByAgent(agent.name)
            const isCollapsed = collapsedAgents[agent.name] ?? false
            const colors = getAgentColorClasses(agent.color)
            const Icon = getAgentIcon(agent.icon)

            return (
              <div key={agent.name} className="mb-1">
                {/* Agent header */}
                {!sidebarCollapsed ? (
                  <div className="flex items-center gap-1 px-1 mb-0.5">
                    <button
                      onClick={() => toggleAgentCollapse(agent.name)}
                      className="flex items-center gap-2.5 flex-1 px-2 py-2 rounded-lg text-sm font-medium text-surface-300 hover:text-surface-100 hover:bg-white/[0.04] transition-all"
                    >
                      {agent.avatar_url ? (
                        <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg flex-shrink-0 object-cover ring-1 ring-white/10" />
                      ) : (
                        <div className={`w-6 h-6 rounded-lg bg-gradient-to-br ${colors.gradient} flex items-center justify-center flex-shrink-0`}>
                          <Icon className="w-3.5 h-3.5 text-white/90" />
                        </div>
                      )}
                      <span className="truncate">{agent.display_name}</span>
                      <ChevronDown className={`w-3 h-3 ml-auto flex-shrink-0 text-surface-500 transition-transform duration-200 ${isCollapsed ? '-rotate-90' : ''}`} />
                    </button>
                    <button
                      onClick={() => handleNewSession(agent.name)}
                      className="w-7 h-7 rounded-lg hover:bg-white/[0.06] transition-all flex-shrink-0 flex items-center justify-center text-surface-400 hover:text-surface-200"
                      title={`New ${agent.display_name} chat`}
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => handleNewSession(agent.name)}
                    className="w-full flex items-center justify-center p-2 rounded-xl hover:bg-white/[0.06] transition-all mb-1"
                    title={`New ${agent.display_name} session`}
                  >
                    {agent.avatar_url ? (
                      <img src={agent.avatar_url} alt="" className="w-7 h-7 rounded-lg object-cover ring-1 ring-white/10" />
                    ) : (
                      <div className={`w-7 h-7 rounded-lg bg-gradient-to-br ${colors.gradient} flex items-center justify-center`}>
                        <Icon className="w-3.5 h-3.5 text-white/90" />
                      </div>
                    )}
                  </button>
                )}

                {/* Sessions list */}
                {!sidebarCollapsed && !isCollapsed && (
                  <div className="ml-3 pl-3 border-l border-surface-700/40 space-y-px mb-1">
                    {agentSessions.map((session) => {
                      const isActive = session.id === activeSessionId
                      return (
                        <div
                          key={session.id}
                          className={`group flex items-center gap-2 px-2.5 py-1.5 rounded-lg cursor-pointer transition-all text-sm ${
                            isActive
                              ? 'bg-primary-500/15 text-primary-300 font-medium'
                              : 'text-surface-400 hover:bg-white/[0.04] hover:text-surface-200'
                          }`}
                          onClick={() => handleSelectSession(session.id)}
                        >
                          {isActive && (
                            <div className="absolute -left-3 w-[3px] h-4 rounded-full bg-primary-400" style={{ marginLeft: '-0.75rem' }} />
                          )}
                          <span className="flex-1 truncate">{session.title}</span>
                          <button
                            onClick={(e) => handleDeleteSession(e, session.id)}
                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-surface-600/50 rounded-md transition-all flex-shrink-0"
                          >
                            <Trash2 className="w-3 h-3 text-surface-500 hover:text-red-400" />
                          </button>
                        </div>
                      )
                    })}
                    {agentSessions.length === 0 && (
                      <p className="text-xs text-surface-600 px-2.5 py-1.5 italic">No conversations yet</p>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {pickedAgentInfos.length === 0 && !sidebarCollapsed && (
            <div className="text-center py-8 px-4">
              <div className="w-10 h-10 rounded-xl bg-surface-800 flex items-center justify-center mx-auto mb-3">
                <Bot className="w-5 h-5 text-surface-500" />
              </div>
              <p className="text-xs text-surface-500 mb-1">No team members yet</p>
              <Link to="/teams" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                Browse & add members →
              </Link>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="px-2 py-2 border-t border-surface-700/30 space-y-1">
          {!sidebarCollapsed && (
            <button
              onClick={() => setCollapsedAgentPages(prev => !prev)}
              className="w-full flex items-center px-3 pb-1.5 text-[11px] font-semibold tracking-wide text-surface-500 hover:text-surface-400 transition-colors"
              aria-expanded={!collapsedAgentPages}
              aria-label="Toggle agents section"
            >
              <span>Agents</span>
              <ChevronDown className={`w-3 h-3 ml-auto transition-transform duration-200 ${collapsedAgentPages ? '-rotate-90' : ''}`} />
            </button>
          )}
          {(!collapsedAgentPages || sidebarCollapsed) && (
            <div className="space-y-0.5">
              {agentNavItems.map((item) => {
                const isActive = location.pathname === item.path ||
                  (item.path !== '/' && location.pathname.startsWith(item.path))
                const Icon = item.icon

                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    title={sidebarCollapsed ? item.label : undefined}
                    className={`flex items-center ${sidebarCollapsed ? 'justify-center px-2' : 'px-3'} py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary-500/15 text-primary-300'
                        : 'text-surface-400 hover:bg-white/[0.04] hover:text-surface-200'
                    }`}
                  >
                    <Icon className={`w-[18px] h-[18px] ${sidebarCollapsed ? '' : 'mr-3'} ${isActive ? 'text-primary-400' : 'text-surface-500'}`} />
                    {!sidebarCollapsed && item.label}
                  </Link>
                )
              })}
            </div>
          )}

          {!sidebarCollapsed && (
            <button
              onClick={() => setCollapsedConfiguration(prev => !prev)}
              className="w-full flex items-center px-3 pt-1 pb-1.5 text-[11px] font-semibold tracking-wide text-surface-500 hover:text-surface-400 transition-colors"
              aria-expanded={!collapsedConfiguration}
              aria-label="Toggle configuration section"
            >
              <span>Configuration</span>
              <ChevronDown className={`w-3 h-3 ml-auto transition-transform duration-200 ${collapsedConfiguration ? '-rotate-90' : ''}`} />
            </button>
          )}
          {(!collapsedConfiguration || sidebarCollapsed) && (
            <div className="space-y-0.5">
              {configurationNavItems.map((item) => {
                const isActive = location.pathname === item.path ||
                  (item.path !== '/' && location.pathname.startsWith(item.path))
                const Icon = item.icon

                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    title={sidebarCollapsed ? item.label : undefined}
                    className={`flex items-center ${sidebarCollapsed ? 'justify-center px-2' : 'px-3'} py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary-500/15 text-primary-300'
                        : 'text-surface-400 hover:bg-white/[0.04] hover:text-surface-200'
                    }`}
                  >
                    <Icon className={`w-[18px] h-[18px] ${sidebarCollapsed ? '' : 'mr-3'} ${isActive ? 'text-primary-400' : 'text-surface-500'}`} />
                    {!sidebarCollapsed && item.label}
                  </Link>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-2 py-2 border-t border-surface-700/30">
          <button
            onClick={() => setSidebarWidth(sidebarCollapsed ? DEFAULT_SIDEBAR_WIDTH : MIN_SIDEBAR_WIDTH)}
            className={`w-full flex items-center ${sidebarCollapsed ? 'justify-center' : 'px-3'} py-2 rounded-lg text-surface-500 hover:bg-white/[0.04] hover:text-surface-300 transition-all`}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4" />
            ) : (
              <>
                <div className="flex items-center gap-2 flex-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-xs text-surface-600">v0.1.0</span>
                </div>
                <ChevronLeft className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Resize handle */}
      <div
        onMouseDown={handleMouseDown}
        className={`w-1 cursor-col-resize hover:bg-primary-500/30 transition-colors ${isResizing ? 'bg-primary-500/60' : 'bg-transparent'}`}
      />

      {/* Main content */}
      <main className="flex-1 overflow-auto bg-surface-900 relative">
        {children}
      </main>
    </div>
  )
}
