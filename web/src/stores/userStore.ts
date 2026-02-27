import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UserSettings {
  displayName: string
  avatarUrl: string | null
}

interface UserStore {
  settings: UserSettings
  setDisplayName: (name: string) => void
  setAvatarUrl: (url: string | null) => void
  clearAvatar: () => void
}

export const useUserStore = create<UserStore>()(
  persist(
    (set) => ({
      settings: {
        displayName: 'User',
        avatarUrl: null,
      },
      setDisplayName: (name) =>
        set((state) => ({
          settings: { ...state.settings, displayName: name },
        })),
      setAvatarUrl: (url) =>
        set((state) => ({
          settings: { ...state.settings, avatarUrl: url },
        })),
      clearAvatar: () =>
        set((state) => ({
          settings: { ...state.settings, avatarUrl: null },
        })),
    }),
    {
      name: 'myai-user-settings',
    }
  )
)
