import { create } from 'zustand'

const API_BASE = '/api'

export interface AgentOverride {
  display_name?: string
  avatar_url?: string
}

export interface AuthUser {
  id: number
  username: string
  display_name: string
  avatar_url: string | null
  email: string | null
  picked_agents: string[]
  agent_overrides: Record<string, AgentOverride>
  is_admin: boolean
}

interface AuthStore {
  user: AuthUser | null
  isLoading: boolean
  isRemote: boolean | null  // null = not yet checked
  error: string | null

  // Actions
  checkMode: () => Promise<void>
  fetchMe: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName?: string) => Promise<void>
  logout: () => Promise<void>
  updateProfile: (updates: Partial<Pick<AuthUser, 'display_name' | 'avatar_url' | 'email' | 'picked_agents' | 'agent_overrides'>>) => Promise<AuthUser>
}

export const useAuthStore = create<AuthStore>()((set) => ({
  user: null,
  isLoading: true,
  isRemote: null,
  error: null,

  checkMode: async () => {
    try {
      const resp = await fetch(`${API_BASE}/settings/mode`)
      if (resp.ok) {
        const data = await resp.json()
        set({ isRemote: data.mode === 'remote' })
      }
    } catch {
      set({ isRemote: false })
    }
  },

  fetchMe: async () => {
    set({ isLoading: true, error: null })
    try {
      const resp = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' })
      if (resp.ok) {
        const user = await resp.json()
        set({ user, isLoading: false })
      } else if (resp.status === 401) {
        set({ user: null, isLoading: false })
      } else {
        set({ user: null, isLoading: false })
      }
    } catch {
      set({ user: null, isLoading: false })
    }
  },

  login: async (username: string, password: string) => {
    set({ error: null })
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'include',
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({ error: 'Login failed' }))
      throw new Error(data.error || 'Login failed')
    }
    const user = await resp.json()
    set({ user, error: null })
  },

  register: async (username: string, password: string, displayName?: string) => {
    set({ error: null })
    const resp = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name: displayName || username }),
      credentials: 'include',
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({ error: 'Registration failed' }))
      throw new Error(data.error || 'Registration failed')
    }
    const user = await resp.json()
    set({ user, error: null })
  },

  logout: async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      // Ignore errors
    }
    set({ user: null })
  },

  updateProfile: async (updates) => {
    const resp = await fetch(`${API_BASE}/auth/me`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
      credentials: 'include',
    })
    if (!resp.ok) {
      throw new Error('Failed to update profile')
    }
    const user = await resp.json()
    set({ user })
    return user
  },
}))
