import { useState, useRef, useEffect } from 'react'
import { Settings, Database, Brain, Bell, User, Camera, X, Loader2, Check, AlertTriangle, LogOut } from 'lucide-react'
import { useAuthStore } from '../stores/authStore'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type RootStatus } from '../api/client'

const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8001'

interface StorageInfo {
  watcher_db: string
  watcher_db_size: number
  vector_db: string
  vector_db_size: number
  data_dir: string
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const { user, isRemote, updateProfile, logout } = useAuthStore()
  const [nameInput, setNameInput] = useState(user?.display_name || 'User')
  const [emailInput, setEmailInput] = useState(user?.email || '')
  const [emailError, setEmailError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [storage, setStorage] = useState<StorageInfo | null>(null)

  useEffect(() => {
    setNameInput(user?.display_name || 'User')
    setEmailInput(user?.email || '')
  }, [user?.display_name, user?.email])
  
  // Model settings
  const { data: modelSettings } = useQuery({
    queryKey: ['settings', 'models'],
    queryFn: api.settings.getModels,
  })
  
  const [selectedAgentModel, setSelectedAgentModel] = useState('')
  const [selectedEmbeddingModel, setSelectedEmbeddingModel] = useState('')
  const [modelSaving, setModelSaving] = useState(false)
  const [modelSaved, setModelSaved] = useState(false)
  const [modelError, setModelError] = useState<string | null>(null)
  const [showReindexConfirm, setShowReindexConfirm] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  
  // Roots status for indexing progress
  const { data: rootsStatus = [] } = useQuery({
    queryKey: ['settings', 'roots', 'status'],
    queryFn: api.settings.getRootsStatus,
    refetchInterval: reindexing ? 2000 : false,
  })
  
  // Sync local state when model settings load
  useEffect(() => {
    if (modelSettings) {
      setSelectedAgentModel(modelSettings.agent_model)
      setSelectedEmbeddingModel(modelSettings.embedding_model)
    }
  }, [modelSettings])
  
  // Track re-indexing completion
  useEffect(() => {
    if (reindexing && rootsStatus.length > 0) {
      const allReady = rootsStatus.every((r: RootStatus) => r.status === 'ready')
      if (allReady) {
        setReindexing(false)
      }
    }
  }, [reindexing, rootsStatus])
  
  useEffect(() => {
    fetch(`${API_BASE}/api/settings/storage`)
      .then(res => res.json())
      .then(data => setStorage(data))
      .catch(err => console.error('Failed to load storage info:', err))
  }, [])
  
  const handleAvatarUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }
    
    if (file.size > 2 * 1024 * 1024) {
      alert('Image must be smaller than 2MB')
      return
    }
    
    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string
      updateProfile({ avatar_url: dataUrl })
    }
    reader.readAsDataURL(file)
  }
  
  const handleNameSave = () => {
    if (nameInput.trim()) {
      updateProfile({ display_name: nameInput.trim() })
    }
  }

  const handleEmailSave = async () => {
    const normalized = emailInput.trim()
    if (normalized && !EMAIL_PATTERN.test(normalized)) {
      setEmailError('Please enter a valid email address (example: name@company.com).')
      return
    }
    setEmailError(null)
    try {
      await updateProfile({ email: normalized || null })
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : 'Failed to update email address')
    }
  }
  
  const handleClearAvatar = () => {
    updateProfile({ avatar_url: null })
  }
  
  const hasModelChanges = modelSettings && (
    selectedAgentModel !== modelSettings.agent_model ||
    selectedEmbeddingModel !== modelSettings.embedding_model
  )
  
  const embeddingChanged = modelSettings && selectedEmbeddingModel !== modelSettings.embedding_model
  const needsReindex = embeddingChanged && modelSettings?.has_indexed_docs
  
  const handleModelSave = async () => {
    if (!hasModelChanges) return
    
    // If embedding model changed AND there are indexed docs, show confirmation dialog
    if (needsReindex) {
      setShowReindexConfirm(true)
      return
    }
    
    // No re-index needed — save directly
    await doModelSave()
  }
  
  const doModelSave = async () => {
    setModelSaving(true)
    setModelError(null)
    setModelSaved(false)
    
    try {
      const payload: { agent_model?: string; embedding_model?: string } = {}
      if (modelSettings && selectedAgentModel !== modelSettings.agent_model) {
        payload.agent_model = selectedAgentModel
      }
      if (modelSettings && selectedEmbeddingModel !== modelSettings.embedding_model) {
        payload.embedding_model = selectedEmbeddingModel
      }
      
      const result = await api.settings.updateModels(payload)
      
      if (result.reindexing) {
        setReindexing(true)
      }
      
      queryClient.invalidateQueries({ queryKey: ['settings', 'models'] })
      queryClient.invalidateQueries({ queryKey: ['settings', 'roots', 'status'] })
      setModelSaved(true)
      setTimeout(() => setModelSaved(false), 3000)
    } catch (err: unknown) {
      setModelError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setModelSaving(false)
      setShowReindexConfirm(false)
    }
  }
  
  const indexingTotal = rootsStatus.reduce((sum: number, r: RootStatus) => sum + r.indexed_count + r.pending_count, 0)
  const indexingDone = rootsStatus.reduce((sum: number, r: RootStatus) => sum + r.indexed_count, 0)
  
  
  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-surface-100">Settings</h1>
        <p className="text-surface-500 mt-1">Configure Sosie preferences</p>
      </div>
      
      <div className="space-y-6">
        {/* Profile Settings */}
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
          <div className="flex items-center gap-3 mb-6">
            <User className="w-5 h-5 text-surface-400" />
            <h2 className="text-lg font-semibold text-surface-100">Profile</h2>
          </div>
          
          <div className="flex items-start gap-6">
            {/* Avatar */}
            <div className="relative group">
              <div className="w-24 h-24 rounded-2xl overflow-hidden bg-surface-700 flex items-center justify-center">
                {user?.avatar_url ? (
                  <img 
                    src={user.avatar_url} 
                    alt="User avatar" 
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <User className="w-10 h-10 text-surface-500" />
                )}
              </div>
              
              <button
                onClick={() => fileInputRef.current?.click()}
                className="absolute inset-0 bg-black/60 rounded-2xl flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Camera className="w-6 h-6 text-white" />
              </button>
              
              {user?.avatar_url && (
                <button
                  onClick={handleClearAvatar}
                  className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                >
                  <X className="w-4 h-4 text-white" />
                </button>
              )}
              
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarUpload}
                className="hidden"
              />
            </div>
            
            <div className="flex-1 space-y-4">
              <div>
                <label className="block text-sm font-medium text-surface-300 mb-2">
                  Display Name
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    placeholder="Enter your name"
                    className="flex-1 px-4 py-2.5 bg-surface-700 border border-surface-600 rounded-xl text-surface-200 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                  <button
                    onClick={handleNameSave}
                    className="px-4 py-2.5 bg-primary-600 hover:bg-primary-500 text-white rounded-xl text-sm font-medium transition-colors"
                  >
                    Save
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-surface-300 mb-2">
                  Email Address
                </label>
                <div className="flex gap-2">
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => {
                      setEmailInput(e.target.value)
                      if (emailError) {
                        setEmailError(null)
                      }
                    }}
                    placeholder="Enter your email"
                    className="flex-1 px-4 py-2.5 bg-surface-700 border border-surface-600 rounded-xl text-surface-200 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                  <button
                    onClick={handleEmailSave}
                    className="px-4 py-2.5 bg-primary-600 hover:bg-primary-500 text-white rounded-xl text-sm font-medium transition-colors"
                  >
                    Save
                  </button>
                </div>
                {emailError && (
                  <div className="mt-2 text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                    {emailError}
                  </div>
                )}
              </div>
              <p className="text-xs text-surface-500">
                Upload an avatar image (max 2MB). Supported formats: JPG, PNG, GIF, WebP.
              </p>
            </div>
          </div>
        </div>
        
        {/* General Settings */}
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
          <div className="flex items-center gap-3 mb-4">
            <Settings className="w-5 h-5 text-surface-400" />
            <h2 className="text-lg font-semibold text-surface-100">General</h2>
          </div>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-surface-300">Dark Mode</p>
                <p className="text-xs text-surface-500">Use dark theme for the interface</p>
              </div>
              <button className="relative w-11 h-6 bg-primary-600 rounded-full transition-colors">
                <span className="absolute right-1 top-1 w-4 h-4 bg-white rounded-full transition-transform" />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-surface-300">Notifications</p>
                <p className="text-xs text-surface-500">Show desktop notifications for events</p>
              </div>
              <button className="relative w-11 h-6 bg-surface-600 rounded-full transition-colors">
                <span className="absolute left-1 top-1 w-4 h-4 bg-white rounded-full transition-transform" />
              </button>
            </div>
          </div>
        </div>
        
        {/* Storage Settings */}
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
          <div className="flex items-center gap-3 mb-4">
            <Database className="w-5 h-5 text-surface-400" />
            <h2 className="text-lg font-semibold text-surface-100">Storage</h2>
          </div>
          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-surface-300 mb-1">Data Directory</p>
              <p className="text-sm text-surface-400 font-mono bg-surface-700 px-3 py-2 rounded-lg">
                {storage?.data_dir || 'Loading...'}
              </p>
            </div>
            <div>
              <p className="text-sm font-medium text-surface-300 mb-1">Watcher Database</p>
              <p className="text-sm text-surface-400 font-mono bg-surface-700 px-3 py-2 rounded-lg flex justify-between">
                <span>{storage?.watcher_db ? storage.watcher_db.split('/').pop() : 'Loading...'}</span>
                <span className="text-surface-500">{storage ? formatBytes(storage.watcher_db_size) : ''}</span>
              </p>
            </div>
            <div>
              <p className="text-sm font-medium text-surface-300 mb-1">Vector Database</p>
              <p className="text-sm text-surface-400 font-mono bg-surface-700 px-3 py-2 rounded-lg flex justify-between">
                <span>{storage?.vector_db ? storage.vector_db.split('/').pop() : 'Loading...'}</span>
                <span className="text-surface-500">{storage ? formatBytes(storage.vector_db_size) : ''}</span>
              </p>
            </div>
          </div>
        </div>
        
        {/* AI Settings */}
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
          <div className="flex items-center gap-3 mb-4">
            <Brain className="w-5 h-5 text-surface-400" />
            <h2 className="text-lg font-semibold text-surface-100">AI Configuration</h2>
          </div>
          <div className="space-y-4">
            {/* Agent Model */}
            <div>
              <label className="block text-sm font-medium text-surface-300 mb-1.5">Agent Model</label>
              <select
                value={selectedAgentModel}
                onChange={(e) => setSelectedAgentModel(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-700 border border-surface-600 rounded-xl text-surface-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm"
              >
                {modelSettings?.agent_model_presets.map((p) => (
                  <option key={p.model_id} value={p.model_id}>
                    {p.display_name} ({p.model_id})
                  </option>
                ))}
              </select>
            </div>
            
            {/* Embedding Model */}
            <div>
              <label className="block text-sm font-medium text-surface-300 mb-1.5">Embedding Model</label>
              <select
                value={selectedEmbeddingModel}
                onChange={(e) => setSelectedEmbeddingModel(e.target.value)}
                className="w-full px-3 py-2.5 bg-surface-700 border border-surface-600 rounded-xl text-surface-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm"
              >
                {modelSettings?.embedding_presets.map((p) => (
                  <option key={p.model_id} value={p.model_id}>
                    {p.model_id} ({p.dimensions}d)
                  </option>
                ))}
              </select>
              {needsReindex && (
                <p className="mt-1.5 text-xs text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  Changing embedding model will re-index all documents
                </p>
              )}
            </div>
            
            {/* Re-indexing progress */}
            {reindexing && (
              <div className="bg-surface-700/50 rounded-xl p-3 border border-surface-600/50">
                <div className="flex items-center gap-2 mb-2">
                  <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                  <span className="text-sm text-primary-400 font-medium">Re-indexing documents...</span>
                </div>
                <div className="w-full bg-surface-600 rounded-full h-1.5">
                  <div
                    className="bg-primary-500 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${indexingTotal > 0 ? (indexingDone / indexingTotal) * 100 : 0}%` }}
                  />
                </div>
                <p className="text-xs text-surface-400 mt-1.5">
                  {indexingDone} / {indexingTotal} documents indexed
                </p>
              </div>
            )}
            
            {/* Save button */}
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={handleModelSave}
                disabled={!hasModelChanges || modelSaving}
                className="px-4 py-2.5 bg-primary-600 hover:bg-primary-500 disabled:bg-surface-600 disabled:text-surface-400 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2"
              >
                {modelSaving ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                ) : (
                  'Save Models'
                )}
              </button>
              {modelSaved && (
                <span className="text-sm text-emerald-400 flex items-center gap-1">
                  <Check className="w-4 h-4" /> Saved
                </span>
              )}
              {modelError && (
                <span className="text-sm text-red-400">{modelError}</span>
              )}
            </div>
          </div>
        </div>
        
        {/* API Key Status */}
        <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
          <div className="flex items-center gap-3 mb-4">
            <Bell className="w-5 h-5 text-surface-400" />
            <h2 className="text-lg font-semibold text-surface-100">API Status</h2>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-surface-400">OPENAI_API_KEY</span>
              <span className="text-xs px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded-lg">Configured</span>
            </div>
          </div>
        </div>
        
        {/* Account / Logout (remote mode only) */}
        {isRemote && (
          <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
            <div className="flex items-center gap-3 mb-4">
              <LogOut className="w-5 h-5 text-surface-400" />
              <h2 className="text-lg font-semibold text-surface-100">Account</h2>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-surface-300">Signed in as <span className="text-surface-100">{user?.username}</span></p>
                <p className="text-xs text-surface-500 mt-0.5">{user?.is_admin ? 'Administrator' : 'User'}</p>
              </div>
              <button
                onClick={logout}
                className="px-4 py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/30 rounded-xl text-sm font-medium transition-colors flex items-center gap-2"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          </div>
        )}
      </div>
      
      {/* Re-index Confirmation Dialog */}
      {showReindexConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl p-6 max-w-md mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-surface-100">Re-index Required</h3>
            </div>
            <p className="text-sm text-surface-300 mb-6">
              Changing the embedding model requires re-indexing all documents. This will clear the existing vector store and re-process every document. This may take a while depending on the number of documents.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowReindexConfirm(false)}
                className="px-4 py-2 text-sm text-surface-300 hover:text-surface-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={doModelSave}
                disabled={modelSaving}
                className="px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2"
              >
                {modelSaving ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                ) : (
                  'Confirm & Re-index'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
