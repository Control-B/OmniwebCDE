export type WorkspaceState =
  | 'REQUESTED'
  | 'VALIDATING'
  | 'PROVISIONING'
  | 'BOOTSTRAPPING'
  | 'CONNECTING'
  | 'READY'
  | 'STOPPING'
  | 'STOPPED'
  | 'STARTING'
  | 'REBUILDING'
  | 'DELETING'
  | 'DELETED'
  | 'FAILED'
  | 'RECOVERING'

export interface Workspace {
  id: string
  name: string
  region: string
  size: string
  image: string
  template: string
  state: WorkspaceState
  estimated_monthly_usd: string
  error_code: string | null
  error_detail: string | null
  created_at: string
  updated_at: string
}

export interface CloudConnection {
  id: string
  provider: string
  label: string
  token_fingerprint: string
  provider_account_id: string | null
  healthy: boolean
  last_checked_at: string | null
}

export interface Region {
  slug: string
  name: string
  available: boolean
}

export interface Size {
  slug: string
  vcpus: number
  memory_mb: number
  disk_gb: number
  monthly_usd: string
  available: boolean
}

const API_URL =
  import.meta.env.VITE_API_URL ??
  (typeof window !== 'undefined' && window.location.port === '43210'
    ? 'http://localhost:8010'
    : '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail ?? 'Request failed')
  }
  return response.json()
}

export const api = {
  dashboard: () =>
    request<{
      total: number
      running: number
      stopped: number
      failed: number
      cloud_connections: number
      estimated_monthly_usd: string
    }>('/dashboard'),
  workspaces: () => request<Workspace[]>('/workspaces'),
  connections: () => request<CloudConnection[]>('/cloud-connections'),
  regions: () => request<Region[]>('/catalog/regions'),
  sizes: (region: string) => request<Size[]>(`/catalog/sizes?region=${region}`),
  connect: (label: string, token: string) =>
    request<CloudConnection>('/cloud-connections', {
      method: 'POST',
      body: JSON.stringify({ label, token }),
    }),
  createWorkspace: (input: Record<string, string>) =>
    request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(input) }),
  lifecycle: (id: string, action: string) =>
    request<Workspace>(`/workspaces/${id}/${action}`, { method: 'POST' }),
  access: (id: string, kind: 'ide' | 'console') =>
    request<{ url: string; expires_in_seconds: number }>(`/workspaces/${id}/access/${kind}`, {
      method: 'POST',
    }),
}

export const demoData = {
  dashboard: {
    total: 4,
    running: 2,
    stopped: 1,
    failed: 1,
    cloud_connections: 1,
    estimated_monthly_usd: '78.00',
  },
  connections: [
    {
      id: '10000000-0000-4000-8000-000000000010',
      provider: 'digitalocean',
      label: 'Omniweb Production',
      token_fingerprint: 'a74cf92e10',
      provider_account_id: 'do-team-8831',
      healthy: true,
      last_checked_at: new Date().toISOString(),
    },
  ] satisfies CloudConnection[],
  regions: [
    { slug: 'nyc3', name: 'New York 3', available: true },
    { slug: 'sfo3', name: 'San Francisco 3', available: true },
    { slug: 'ams3', name: 'Amsterdam 3', available: true },
  ] satisfies Region[],
  sizes: [
    { slug: 's-1vcpu-1gb', vcpus: 1, memory_mb: 1024, disk_gb: 25, monthly_usd: '6', available: true },
    { slug: 's-2vcpu-4gb', vcpus: 2, memory_mb: 4096, disk_gb: 80, monthly_usd: '24', available: true },
    { slug: 's-4vcpu-8gb', vcpus: 4, memory_mb: 8192, disk_gb: 160, monthly_usd: '48', available: true },
  ] satisfies Size[],
  workspaces: [
    {
      id: '30000000-0000-4000-8000-000000000001',
      name: 'omniweb-core',
      region: 'nyc3',
      size: 's-4vcpu-8gb',
      image: 'ubuntu-24-04-x64',
      template: 'Full-stack TypeScript',
      state: 'READY',
      estimated_monthly_usd: '48.00',
      error_code: null,
      error_detail: null,
      created_at: new Date(Date.now() - 86400000 * 12).toISOString(),
      updated_at: new Date(Date.now() - 900000).toISOString(),
    },
    {
      id: '30000000-0000-4000-8000-000000000002',
      name: 'design-system',
      region: 'sfo3',
      size: 's-2vcpu-4gb',
      image: 'ubuntu-24-04-x64',
      template: 'React + Node',
      state: 'READY',
      estimated_monthly_usd: '24.00',
      error_code: null,
      error_detail: null,
      created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
      updated_at: new Date(Date.now() - 180000).toISOString(),
    },
    {
      id: '30000000-0000-4000-8000-000000000003',
      name: 'api-sandbox',
      region: 'ams3',
      size: 's-1vcpu-1gb',
      image: 'ubuntu-24-04-x64',
      template: 'Python',
      state: 'STOPPED',
      estimated_monthly_usd: '6.00',
      error_code: null,
      error_detail: null,
      created_at: new Date(Date.now() - 86400000 * 8).toISOString(),
      updated_at: new Date(Date.now() - 86400000).toISOString(),
    },
  ] satisfies Workspace[],
}
