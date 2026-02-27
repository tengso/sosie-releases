import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import ConversationPage from './pages/ConversationPage'
import KnowledgePage from './pages/KnowledgePage'
import AgentsPage from './pages/AgentsPage'
import SettingsPage from './pages/SettingsPage'
import SystemPage from './pages/SystemPage'
import LoginPage from './pages/LoginPage'
import { useAuthStore } from './stores/authStore'
import { useAgentStore } from './stores/agentStore'
import { Loader2 } from 'lucide-react'

function App() {
  const { user, isLoading, isRemote, checkMode, fetchMe } = useAuthStore()
  const initFromAuth = useAgentStore(s => s.initFromAuth)
  const initOverridesFromAuth = useAgentStore(s => s.initOverridesFromAuth)

  useEffect(() => {
    const init = async () => {
      await checkMode()
      await fetchMe()
    }
    init()
  }, [checkMode, fetchMe])

  // Sync agentStore from auth user's picked_agents + agent_overrides
  useEffect(() => {
    if (user?.picked_agents && user.picked_agents.length > 0) {
      initFromAuth(user.picked_agents)
    }
    if (user?.agent_overrides) {
      initOverridesFromAuth(user.agent_overrides)
    }
  }, [user?.picked_agents, user?.agent_overrides, initFromAuth, initOverridesFromAuth])

  // Still loading auth state
  if (isLoading || isRemote === null) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    )
  }

  // Remote mode + not authenticated → show login
  if (isRemote && !user) {
    return <LoginPage />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/teams" replace />} />
        <Route path="/chat" element={<ConversationPage />} />
        <Route path="/chat/:sessionId" element={<ConversationPage />} />
        <Route path="/research" element={<Navigate to="/chat" replace />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/knowledge/*" element={<KnowledgePage />} />
        <Route path="/documents" element={<Navigate to="/knowledge" replace />} />
        <Route path="/documents/*" element={<Navigate to="/knowledge" replace />} />
        <Route path="/teams" element={<AgentsPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Layout>
  )
}

export default App
