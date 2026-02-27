import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useAuthStore, type AgentOverride } from './authStore'

function syncAgentsToServer(agents: string[]) {
  useAuthStore.getState().updateProfile({ picked_agents: agents }).catch(() => {})
}

function syncOverridesToServer(overrides: Record<string, AgentOverride>) {
  useAuthStore.getState().updateProfile({ agent_overrides: overrides }).catch(() => {})
}

interface AgentStore {
  pickedAgents: string[]
  agentOverrides: Record<string, AgentOverride>
  addAgent: (name: string) => void
  removeAgent: (name: string) => void
  isAgentPicked: (name: string) => boolean
  setAgentOverride: (name: string, override: AgentOverride) => void
  initFromAuth: (agents: string[]) => void
  initOverridesFromAuth: (overrides: Record<string, AgentOverride>) => void
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      pickedAgents: ['doc_qa_agent', 'deep_research_agent'],
      agentOverrides: {},
      addAgent: (name) => {
        const current = get().pickedAgents
        if (current.includes(name)) return
        const updated = [...current, name]
        set({ pickedAgents: updated })
        syncAgentsToServer(updated)
      },
      removeAgent: (name) => {
        const updated = get().pickedAgents.filter((a) => a !== name)
        set({ pickedAgents: updated })
        syncAgentsToServer(updated)
      },
      isAgentPicked: (name) => get().pickedAgents.includes(name),
      setAgentOverride: (name, override) => {
        const current = get().agentOverrides
        const updated = { ...current, [name]: { ...current[name], ...override } }
        set({ agentOverrides: updated })
        syncOverridesToServer(updated)
      },
      initFromAuth: (agents) => set({ pickedAgents: agents }),
      initOverridesFromAuth: (overrides) => set({ agentOverrides: overrides }),
    }),
    {
      name: 'sosie-agent-selection',
    }
  )
)
