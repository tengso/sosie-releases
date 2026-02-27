import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bot,
  MessageSquare,
  BookOpen,
  Wrench,
  Cpu,
  Check,
  Plus,
  X,
  ArrowRight,
  Pencil,
  Camera,
  FolderOpen,
  ChevronDown,
} from 'lucide-react'
import { api, type AgentInfo, type KnowledgeRootsResponse } from '../api/client'
import { useAgentStore } from '../stores/agentStore'
import { useConversationStore } from '../stores/conversationStore'

function toolDisplayName(tool: string): string {
  return tool
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function getAgentIcon(icon?: string) {
  if (icon === 'book-open') return BookOpen
  if (icon === 'message-square') return MessageSquare
  return Bot
}

function getAgentColorClasses(color?: string) {
  if (color === 'purple') return { bg: 'bg-purple-500/20', text: 'text-purple-400' }
  if (color === 'blue') return { bg: 'bg-blue-500/20', text: 'text-blue-400' }
  return { bg: 'bg-primary-500/20', text: 'text-primary-400' }
}

interface AgentCardProps {
  agent: AgentInfo
  krData: KnowledgeRootsResponse | undefined
  krConfig: Record<string, string[] | null> | null
  onKrChange: (agentName: string, selection: string[] | null) => void
}

function AgentCard({ agent, krData, krConfig, onKrChange }: AgentCardProps) {
  const navigate = useNavigate()
  const { pickedAgents, addAgent, removeAgent, setAgentOverride, agentOverrides } = useAgentStore()
  const { createSession, setActiveSession } = useConversationStore()

  // Use local overrides for immediate display, fallback to server data
  const override = agentOverrides[agent.name]
  const displayName = override?.display_name || agent.display_name
  const avatarUrl = override?.avatar_url || agent.avatar_url

  const [isEditing, setIsEditing] = useState(false)
  const [krExpanded, setKrExpanded] = useState(false)
  const [editName, setEditName] = useState(displayName)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isPicked = pickedAgents.includes(agent.name)
  const colors = getAgentColorClasses(agent.color)
  const Icon = getAgentIcon(agent.icon)

  const handleToggleTeam = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (isPicked) {
      removeAgent(agent.name)
    } else {
      addAgent(agent.name)
    }
  }

  const handleStartChat = async () => {
    if (!isPicked) addAgent(agent.name)
    const id = await createSession(agent.name)
    setActiveSession(id)
    navigate(`/chat/${id}`)
  }

  const handleSaveEdit = () => {
    if (editName.trim() && editName.trim() !== displayName) {
      setAgentOverride(agent.name, { display_name: editName.trim() })
    }
    setIsEditing(false)
  }

  const handleAvatarUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) return
    if (file.size > 2 * 1024 * 1024) {
      alert('Image must be smaller than 2MB')
      return
    }
    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string
      setAgentOverride(agent.name, { avatar_url: dataUrl })
    }
    reader.readAsDataURL(file)
  }

  return (
    <div
      className={`bg-surface-800/50 backdrop-blur-sm rounded-2xl border p-6 transition-all hover:border-primary-500/50 ${
        isPicked
          ? 'border-primary-500/70 ring-1 ring-primary-500/30'
          : 'border-surface-700/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          {/* Avatar with upload overlay */}
          <div className="relative group/avatar">
            {avatarUrl ? (
              <img src={avatarUrl} alt="" className="w-12 h-12 rounded-xl object-cover" />
            ) : (
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${colors.bg}`}>
                <Icon className={`w-6 h-6 ${colors.text}`} />
              </div>
            )}
            <button
              onClick={() => fileInputRef.current?.click()}
              className="absolute inset-0 bg-black/60 rounded-xl flex items-center justify-center opacity-0 group-hover/avatar:opacity-100 transition-opacity"
            >
              <Camera className="w-4 h-4 text-white" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleAvatarUpload}
              className="hidden"
            />
          </div>
          <div>
            {isEditing ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSaveEdit(); if (e.key === 'Escape') setIsEditing(false) }}
                  className="px-2 py-0.5 bg-surface-700 border border-surface-600 rounded-lg text-sm text-surface-100 focus:outline-none focus:border-primary-500 w-40"
                  autoFocus
                />
                <button onClick={handleSaveEdit} className="p-1 rounded-md bg-primary-600 hover:bg-primary-500 text-white">
                  <Check className="w-3 h-3" />
                </button>
                <button onClick={() => { setIsEditing(false); setEditName(displayName) }} className="p-1 rounded-md hover:bg-surface-600 text-surface-400">
                  <X className="w-3 h-3" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 group/name">
                <h3 className="text-base font-semibold text-surface-100">{displayName}</h3>
                <button
                  onClick={() => { setEditName(displayName); setIsEditing(true) }}
                  className="p-0.5 rounded text-surface-600 hover:text-surface-300 opacity-0 group-hover/name:opacity-100 transition-opacity"
                  title="Edit name"
                >
                  <Pencil className="w-3 h-3" />
                </button>
              </div>
            )}
            <span className={`text-xs font-medium ${colors.text}`}>
              {agent.category === 'chat' ? 'Chat' : 'Research'}
            </span>
          </div>
        </div>
        {isPicked && (
          <span className="flex items-center gap-1 px-2 py-1 rounded-lg bg-primary-500/20 text-primary-400 text-xs font-medium">
            <Check className="w-3.5 h-3.5" />
            In Team
          </span>
        )}
      </div>

      {/* Description */}
      <p className="text-sm text-surface-400 mb-4 leading-relaxed">{agent.description}</p>

      {/* Model */}
      <div className="flex items-center gap-2 mb-4">
        <Cpu className="w-3.5 h-3.5 text-surface-500" />
        <span className="text-xs text-surface-500 font-mono">{agent.model}</span>
      </div>

      {/* Tools */}
      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Wrench className="w-3.5 h-3.5 text-surface-500" />
          <span className="text-xs text-surface-500 font-medium uppercase tracking-wide">Tools</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {agent.tools.map((tool) => (
            <span
              key={tool}
              className="px-2 py-0.5 rounded-md bg-surface-700/70 text-xs text-surface-300"
            >
              {toolDisplayName(tool)}
            </span>
          ))}
        </div>
      </div>

      {/* Knowledge Roots */}
      {(() => {
        const enabledRoots = krData?.available_roots.filter(r => r.enabled) || []
        if (enabledRoots.length === 0) return null
        const agentSel = krConfig?.[agent.name] ?? null
        const isAll = agentSel === null
        const badge = isAll ? 'All' : `${agentSel.length}/${enabledRoots.length}`
        return (
          <div className="mb-3">
            <button
              onClick={() => setKrExpanded(!krExpanded)}
              className="flex items-center gap-1.5 mb-2 group w-full"
            >
              <FolderOpen className="w-3.5 h-3.5 text-surface-500" />
              <span className="text-xs text-surface-500 font-medium uppercase tracking-wide">Knowledge</span>
              <span className="text-xs text-surface-500 ml-auto">{badge}</span>
              <ChevronDown className={`w-3.5 h-3.5 text-surface-500 transition-transform ${krExpanded ? 'rotate-180' : ''}`} />
            </button>
            {krExpanded && (
              <div className="space-y-1.5">
                <button
                  onClick={() => onKrChange(agent.name, null)}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg border transition-colors text-left ${
                    isAll
                      ? 'bg-primary-500/10 border-primary-500/30 text-primary-300'
                      : 'bg-surface-700/30 border-surface-600/50 text-surface-400 hover:text-surface-200 hover:bg-surface-700/50'
                  }`}
                >
                  <div className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 ${
                    isAll ? 'bg-primary-500 text-white' : 'border-2 border-surface-500'
                  }`}>
                    {isAll && <Check className="w-2.5 h-2.5" />}
                  </div>
                  <span className="text-xs font-medium">All sources</span>
                </button>
                {enabledRoots.map((root) => {
                  const isSelected = isAll || (agentSel?.includes(root.path) ?? false)
                  const folderName = root.path.split('/').filter(Boolean).pop() || root.path
                  return (
                    <button
                      key={root.path}
                      onClick={() => {
                        let newSel: string[] | null
                        if (isAll) {
                          newSel = enabledRoots.map(r => r.path).filter(p => p !== root.path)
                        } else {
                          if (agentSel!.includes(root.path)) {
                            newSel = agentSel!.filter(p => p !== root.path)
                          } else {
                            newSel = [...agentSel!, root.path]
                          }
                          if (newSel.length === enabledRoots.length) newSel = null
                        }
                        onKrChange(agent.name, newSel)
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg border transition-colors text-left ${
                        isSelected
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                          : 'bg-surface-700/30 border-surface-600/50 text-surface-400 hover:text-surface-200 hover:bg-surface-700/50'
                      }`}
                    >
                      <div className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 ${
                        isSelected ? 'bg-emerald-500 text-white' : 'border-2 border-surface-500'
                      }`}>
                        {isSelected && <Check className="w-2.5 h-2.5" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-medium block truncate">{folderName}</span>
                        <span className="text-[10px] text-surface-500 block truncate">{root.path}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })()}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-3 border-t border-surface-700/50">
        <button
          onClick={handleToggleTeam}
          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors ${
            isPicked
              ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400'
              : 'bg-surface-700 hover:bg-surface-600 text-surface-300 hover:text-surface-100'
          }`}
        >
          {isPicked ? (
            <>
              <X className="w-4 h-4" />
              Remove
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" />
              Add to Team
            </>
          )}
        </button>
        <button
          onClick={handleStartChat}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium bg-primary-600 hover:bg-primary-500 text-white transition-colors"
        >
          Chat
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

export default function AgentsPage() {
  const queryClient = useQueryClient()
  const { data: agents, isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: api.agents.list,
  })

  // Knowledge roots — shared state across all cards
  const { data: krData } = useQuery({
    queryKey: ['settings', 'knowledge-roots'],
    queryFn: api.settings.getKnowledgeRoots,
  })
  const [krConfig, setKrConfig] = useState<Record<string, string[] | null> | null>(null)
  const [krInitialized, setKrInitialized] = useState(false)

  useEffect(() => {
    if (krData && !krInitialized) {
      setKrConfig(krData.knowledge_roots)
      setKrInitialized(true)
    }
  }, [krData, krInitialized])

  const krMutation = useMutation({
    mutationFn: (kr: Record<string, string[] | null> | null) => api.settings.updateKnowledgeRoots(kr),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'knowledge-roots'] })
    },
  })

  const handleKrChange = (agentName: string, selection: string[] | null) => {
    let newConfig: Record<string, string[] | null> | null
    if (selection === null) {
      // "All sources" — remove this agent's entry
      newConfig = { ...(krConfig || {}) }
      delete newConfig[agentName]
      if (Object.keys(newConfig).length === 0) newConfig = null
    } else {
      newConfig = { ...(krConfig || {}), [agentName]: selection }
    }
    setKrConfig(newConfig)
    krMutation.mutate(newConfig)
  }

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-surface-100">Teams</h1>
        <p className="text-surface-500 mt-1">Browse available team members and build your team.</p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {agents?.map((agent) => (
            <AgentCard key={agent.name} agent={agent} krData={krData} krConfig={krConfig} onKrChange={handleKrChange} />
          ))}
          {agents?.length === 0 && (
            <div className="col-span-2 flex flex-col items-center justify-center h-64 text-center">
              <Bot className="w-12 h-12 text-surface-500 mb-3" />
              <p className="text-surface-500">No team members available</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
