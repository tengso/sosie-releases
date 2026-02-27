import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { 
  Database, 
  CheckCircle,
  RefreshCw,
  Activity,
  Trash2,
  ArrowRight,
  Clock,
  Server,
  FolderOpen,
  FileText
} from 'lucide-react'
import { api, formatBytes, type ActivityItem } from '../api/client'

function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function ActivityFeed({ activities }: { activities: ActivityItem[] }) {
  if (activities.length === 0) {
    return <p className="text-sm text-surface-500 text-center py-8">No recent activity</p>
  }
  
  const getActivityConfig = (type: string) => {
    switch (type) {
      // Document activities
      case 'indexed':
        return { icon: CheckCircle, bg: 'bg-emerald-500/20', iconColor: 'text-emerald-400' }
      case 'deleted':
        return { icon: Trash2, bg: 'bg-red-500/20', iconColor: 'text-red-400' }
      case 'moved':
        return { icon: ArrowRight, bg: 'bg-primary-500/20', iconColor: 'text-primary-400' }
      case 'queued':
        return { icon: Clock, bg: 'bg-amber-500/20', iconColor: 'text-amber-400' }
      case 'root_added':
        return { icon: FolderOpen, bg: 'bg-emerald-500/20', iconColor: 'text-emerald-400' }
      case 'root_removed':
        return { icon: FolderOpen, bg: 'bg-red-500/20', iconColor: 'text-red-400' }
      // System log levels
      case 'info':
        return { icon: Activity, bg: 'bg-blue-500/20', iconColor: 'text-blue-400' }
      case 'warning':
        return { icon: Activity, bg: 'bg-amber-500/20', iconColor: 'text-amber-400' }
      case 'error':
      case 'critical':
        return { icon: Activity, bg: 'bg-red-500/20', iconColor: 'text-red-400' }
      case 'debug':
        return { icon: Activity, bg: 'bg-surface-600', iconColor: 'text-surface-400' }
      default:
        return { icon: Activity, bg: 'bg-surface-600', iconColor: 'text-surface-400' }
    }
  }
  
  return (
    <div className="space-y-2 max-h-[400px] overflow-y-auto">
      {activities.map((item, i) => {
        const config = getActivityConfig(item.type)
        const Icon = config.icon
        return (
          <div key={i} className="flex items-start gap-3 p-3 rounded-xl hover:bg-surface-700/30 transition-colors">
            <div className={`p-2 rounded-lg ${config.bg}`}>
              <Icon className={`w-4 h-4 ${config.iconColor}`} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-surface-200">{item.message}</p>
              {item.filename && (
                <p className="text-xs text-surface-500 truncate" title={item.filename}>
                  {item.filename}
                </p>
              )}
              <p className="text-xs text-surface-600 mt-1">{formatTimestamp(item.timestamp)}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function SystemPage() {
  const queryClient = useQueryClient()
  
  const { data: stats } = useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: api.dashboard.getStats,
    refetchInterval: 10000,
  })
  
  const { data: health } = useQuery({
    queryKey: ['dashboard', 'health'],
    queryFn: api.dashboard.getHealth,
    refetchInterval: 30000,
  })
  
  const { data: activity } = useQuery({
    queryKey: ['dashboard', 'activity'],
    queryFn: () => api.dashboard.getActivity(100),
    refetchInterval: 5000,
  })
  
  const { data: indexOverview } = useQuery({
    queryKey: ['dashboard', 'index-overview'],
    queryFn: api.dashboard.getIndexOverview,
    refetchInterval: 10000,
  })
  
  const reconcileMutation = useMutation({
    mutationFn: api.dashboard.reconcile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })
  
  return (
    <div className="p-8">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 rounded-xl bg-surface-800">
            <Server className="w-6 h-6 text-primary-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-surface-100">System</h1>
            <p className="text-surface-500">Index overview and maintenance tools</p>
          </div>
        </div>
      </div>
      
      {/* Maintenance Actions */}
      <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6 mb-8">
        <h2 className="text-lg font-semibold text-surface-100 mb-4">Maintenance Actions</h2>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => reconcileMutation.mutate()}
            disabled={reconcileMutation.isPending}
            className="inline-flex items-center px-4 py-2.5 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-xl text-sm font-medium transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${reconcileMutation.isPending ? 'animate-spin' : ''}`} />
            Reconcile Files
          </button>
        </div>
        <p className="text-xs text-surface-500 mt-3">Reconcile scans all document roots and re-syncs with the file system.</p>
      </div>
      
      {/* Index Database Overview */}
      <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6 mb-8">
        <div className="flex items-center gap-3 mb-4">
          <Database className="w-5 h-5 text-primary-400" />
          <h2 className="text-lg font-semibold text-surface-100">Index Database (index.db)</h2>
        </div>
        
        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-surface-700/30 rounded-xl p-4 text-center">
            <p className="text-2xl font-bold text-primary-400">{indexOverview?.total_documents ?? stats?.documents ?? '-'}</p>
            <p className="text-xs text-surface-500">Documents</p>
          </div>
          <div className="bg-surface-700/30 rounded-xl p-4 text-center">
            <p className="text-2xl font-bold text-emerald-400">{indexOverview?.total_chunks ?? stats?.chunks ?? '-'}</p>
            <p className="text-xs text-surface-500">Chunks</p>
          </div>
          <div className="bg-surface-700/30 rounded-xl p-4 text-center">
            <p className="text-2xl font-bold text-purple-400">{indexOverview?.total_vectors ?? stats?.embeddings ?? '-'}</p>
            <p className="text-xs text-surface-500">Vectors (VSS)</p>
          </div>
          <div className="bg-surface-700/30 rounded-xl p-4 text-center">
            <p className="text-2xl font-bold text-amber-400">{health ? formatBytes(health.db_size_bytes) : '-'}</p>
            <p className="text-xs text-surface-500">DB Size</p>
          </div>
        </div>
        
        {/* Document Roots */}
        <div className="mb-6">
          <h3 className="text-sm font-medium text-surface-300 mb-3 flex items-center gap-2">
            <FolderOpen className="w-4 h-4" />
            Document Roots ({indexOverview?.roots?.length ?? 0})
          </h3>
          {indexOverview?.roots && indexOverview.roots.length > 0 ? (
            <div className="space-y-2">
              {indexOverview.roots.map((root) => (
                <div key={root.root_id} className="bg-surface-700/30 rounded-lg p-3 flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <FolderOpen className="w-4 h-4 text-amber-400 flex-shrink-0" />
                    <span className="text-sm text-surface-200 truncate" title={root.path}>{root.path}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-surface-500 flex-shrink-0">
                    <span>{root.doc_count} docs</span>
                    <span>{root.chunk_count} chunks</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-surface-500">No document roots configured</p>
          )}
        </div>
        
        {/* Recent Documents */}
        <div>
          <h3 className="text-sm font-medium text-surface-300 mb-3 flex items-center gap-2">
            <FileText className="w-4 h-4" />
            Recent Documents
          </h3>
          {indexOverview?.recent_documents && indexOverview.recent_documents.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="text-left py-2 px-3 font-medium text-surface-400">Filename</th>
                    <th className="text-left py-2 px-3 font-medium text-surface-400">Chunks</th>
                    <th className="text-left py-2 px-3 font-medium text-surface-400">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {indexOverview.recent_documents.map((doc) => (
                    <tr key={doc.doc_id} className="border-b border-surface-700/50 hover:bg-surface-700/30">
                      <td className="py-2 px-3 text-surface-200 truncate max-w-[300px]" title={doc.path}>
                        {doc.filename}
                      </td>
                      <td className="py-2 px-3 text-surface-400">{doc.chunk_count}</td>
                      <td className="py-2 px-3 text-surface-500 text-xs">{formatTimestamp(doc.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-surface-500">No documents indexed yet</p>
          )}
        </div>
      </div>
      
      {/* Activity Log */}
      <div className="bg-surface-800/50 backdrop-blur-sm rounded-2xl border border-surface-700/50 p-6">
        <h2 className="text-lg font-semibold text-surface-100 mb-4">Activity Log</h2>
        <ActivityFeed activities={activity ?? []} />
      </div>
      
    </div>
  )
}
