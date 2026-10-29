import { accessToken, type Me } from './auth'

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
  (import.meta.env.DEV && typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8010`
    : '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly conflicts: string[] = [],
  ) {
    super(message)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await accessToken()
  let response: Response
  try {
    response = await fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError('The Omniweb API is not reachable. Start it with `uvicorn app.main:app --port 8010`.', 0)
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    const detail = typeof error.detail === 'string' ? error.detail : (error.detail?.message ?? 'Request failed')
    const conflicts = Array.isArray(error.detail?.conflicts) ? (error.detail.conflicts as string[]) : []
    throw new ApiError(response.status === 401 ? `401: ${detail}` : detail, response.status, conflicts)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export type GenerationStatus = 'draft' | 'planning' | 'building' | 'ready' | 'needs_attention' | 'failed'
export type Tier = 'economy' | 'standard' | 'advanced' | 'self_hosted'

export interface Project {
  id: string
  name: string
  description: string
  prompt: string
  template: string
  template_label: string
  stack: string[]
  generation_status: GenerationStatus
  deployment_status: string
  github_repo: string | null
  app_config: Record<string, unknown>
  has_code: boolean
  head_sha: string | null
  estimated_usage_usd: number
  message_count: number
  your_role: 'owner' | 'editor' | 'viewer'
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  agent: string | null
  model: string | null
  tier: string | null
  input_tokens: number
  output_tokens: number
  cost_usd: number
  development_model: boolean
  created_at: string
}

export interface Execution {
  id: string
  agent: string
  stage: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  model: string | null
  cost_usd: number
  detail: string | null
  attempts: { model: string; tier: string; status: string; error?: string }[]
  started_at: string
  finished_at: string | null
}

export interface UsageBucket {
  key: string
  requests: number
  failed: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  cost_usd: number
}

export interface Usage {
  totals: UsageBucket
  failed_cost_usd: number
  by_model: UsageBucket[]
  by_agent: UsageBucket[]
  by_project: UsageBucket[]
  by_billing_model: UsageBucket[]
  budgets: { scope: string; limit_usd: number; spent_usd: number; remaining_usd: number; hard_limit: boolean; alert_threshold: number }[]
  alerts: { message: string; kind: string; created_at: string }[]
  recent: { request_id: string; agent: string; model: string; tier: string; status: string; input_tokens: number; output_tokens: number; cost_usd: number; latency_ms: number; created_at: string }[]
}

export interface ProviderStatus {
  provider: string
  label: string
  kind: 'hosted' | 'self_hosted' | 'development'
  needs_key: boolean
  needs_base_url: boolean
  configured: 'platform' | 'customer' | null
  key_fingerprint: string | null
  base_url: string
  models: number
}

export interface ModelInfo {
  provider: string
  model_id: string
  display_name: string
  capabilities: string[]
  context_window: number | null
  input_usd_per_mtok: number | null
  output_usd_per_mtok: number | null
  supports_tools: boolean
  supports_structured_output: boolean
  available: boolean
  routable: boolean
  deprecated: boolean
  pricing_source: string
  last_verified_at: string
}

export interface Preferences {
  default_tier: Tier
  allowed_providers: string[]
  pinned_models: Record<string, string>
  max_escalations: number
  max_attempts?: number
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: string
}

export type IntelligenceMode = 'AUTO' | 'BUILD' | 'BUSINESS' | 'MARKETING' | 'CONTENT' | 'IMAGE' | 'VIDEO' | 'ENGINEERING'

export interface IntelligenceTask {
  id: string
  key: string
  kind: string
  title: string
  status: string
  depends_on: string[]
  output: Record<string, unknown>
  error: string | null
}

export interface IntelligenceWorkflow {
  id: string
  project_id: string | null
  mode: IntelligenceMode
  prompt: string
  status: string
  total_cost_usd: number
  result: Record<string, unknown>
  created_at: string
  finished_at: string | null
  tasks: IntelligenceTask[]
}

export interface Asset {
  id: string
  project_id: string | null
  campaign_id: string | null
  content_type: string
  title: string
  status: string
  current_version: number
  provider: string | null
  model: string | null
  cost_usd: number
  content?: string | null
  created_at: string
  updated_at: string
}

export interface BusinessPlan {
  id: string
  title: string
  status: string
  version: number
  assumptions: unknown[]
  scenarios: unknown[]
  updated_at: string
}

export interface Campaign {
  id: string
  name: string
  objective: string
  status: string
  audience: Record<string, unknown>
  calendar: unknown[]
  budget_limit_usd: number
  spend_usd: number
}

export interface Funnel {
  id: string
  name: string
  funnel_type: string
  status: string
  current_version: number
  preview_url: string | null
  definition: { steps?: Array<{ key: string; type: string; title?: string }> }
}

export interface CrmContact {
  id: string
  email: string
  first_name: string
  last_name: string
  company: string
  source: string
  stage: string
  score: number
  tags: string[]
  marketing_consent: boolean
  unsubscribed: boolean
}

export interface EvolutionCase {
  id: string
  direction: string
  state: string
  title: string
  objective: string
  hypothesis: Record<string, unknown>
  alternatives: Array<Record<string, unknown>>
  updated_at: string
}

export interface EngineeringRequirements {
  component_name: string
  component_kind: 'plate' | 'l_bracket' | 'spacer' | 'enclosure'
  units: 'mm'
  material: string
  manufacturing_process: string | null
  parameters: Record<string, number>
  hole_count: number
  hole_diameter_mm: number | null
  tolerances: Record<string, number>
  requested_outputs: Array<'step' | 'stl' | 'pdf' | 'dxf' | 'source'>
  standards: string[]
  assumptions: string[]
}

export interface EngineeringArtifact {
  id: string
  kind: string
  format: 'step' | 'stl' | 'pdf' | 'dxf' | 'json'
  filename: string
  media_type: string
  sha256: string
  size: number
}

export interface EngineeringRevision {
  id: string
  revision: number
  status: string
  approval_status: string
  change_note: string
  requirements: EngineeringRequirements
  missing_critical: string[]
  assumptions: string[]
  operations: Array<{ operation: string; parameters: Record<string, unknown> }>
  geometry: Record<string, number | string | Array<number>>
  preview: { vertices?: number[][]; triangles?: number[][] }
  validation_level: string
  validation_checks: Array<{ key: string; status: string; message: string; measured?: unknown }>
  safety_notice: string
  job: { id: string; status: string; attempts: number; error: string | null; duration_seconds: number | null } | null
  artifacts: EngineeringArtifact[]
  created_at: string
}

export interface EngineeringDesign {
  id: string
  project_id: string
  name: string
  component_kind: string
  status: string
  current_revision: number
  created_at: string
  updated_at: string
  revisions?: EngineeringRevision[]
}

export async function engineeringArtifact(artifactId: string): Promise<Blob> {
  const token = await accessToken()
  const response = await fetch(`${API_URL}/api/v1/engineering/artifacts/${artifactId}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new ApiError('Engineering artifact download failed', response.status)
  return response.blob()
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export const platform = {
  me: () => request<Me>('/me'),
  projects: () => request<Project[]>('/projects'),
  createProject: (prompt: string, template?: string) => request<Project>('/projects', json('POST', { prompt, template })),
  project: (id: string) => request<Project>(`/projects/${id}`),
  updateProject: (id: string, input: Partial<Pick<Project, 'name' | 'description' | 'template' | 'app_config'>>) =>
    request<Project>(`/projects/${id}`, json('PATCH', input)),
  deleteProject: (id: string, confirmName: string) =>
    request<void>(`/projects/${id}?confirm_name=${encodeURIComponent(confirmName)}`, { method: 'DELETE' }),
  messages: (id: string) => request<ChatMessage[]>(`/projects/${id}/messages`),
  send: (id: string, content: string, requestId: string, tier?: Tier) =>
    request<{ user_message: ChatMessage; assistant_message: ChatMessage; alerts: string[] }>(
      `/projects/${id}/messages`,
      json('POST', { content, request_id: requestId, ...(tier ? { tier } : {}) }),
    ),
  cancel: (id: string, requestId: string) => request<unknown>(`/projects/${id}/requests/${requestId}/cancel`, { method: 'POST' }),
  executions: (id: string) => request<Execution[]>(`/projects/${id}/executions`),
  projectUsage: (id: string) => request<Usage>(`/projects/${id}/usage`),
  projectBudget: (id: string, limit_usd: number, hard_limit: boolean) =>
    request<unknown>(`/projects/${id}/budget`, json('PUT', { limit_usd, hard_limit })),
  projectPreferences: (id: string) => request<Preferences>(`/projects/${id}/model-preferences`),
  setProjectPreferences: (id: string, prefs: Omit<Preferences, 'max_attempts'>) =>
    request<Preferences>(`/projects/${id}/model-preferences`, json('PUT', prefs)),
  members: (id: string) => request<Member[]>(`/projects/${id}/members`),
  addMember: (id: string, email: string, role: 'editor' | 'viewer') => request<Member>(`/projects/${id}/members`, json('POST', { email, role })),
  removeMember: (id: string, userId: string) => request<void>(`/projects/${id}/members/${userId}`, { method: 'DELETE' }),
  env: (id: string) => request<{ key: string; environment: string; updated_at: string }[]>(`/projects/${id}/env`),
  setEnv: (id: string, key: string, value: string, environment: string) =>
    request<unknown>(`/projects/${id}/env`, json('PUT', { key, value, environment })),
  deleteEnv: (id: string, environment: string, key: string) =>
    request<void>(`/projects/${id}/env/${environment}/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  providers: () => request<ProviderStatus[]>('/ai/providers'),
  setCredential: (provider: string, apiKey: string, baseUrl: string) =>
    request<unknown>(`/ai/credentials/${provider}`, json('PUT', { api_key: apiKey || null, base_url: baseUrl })),
  deleteCredential: (provider: string) => request<void>(`/ai/credentials/${provider}`, { method: 'DELETE' }),
  refreshRegistry: () => request<Record<string, { status: string; models?: number }>>('/ai/registry/refresh', { method: 'POST' }),
  models: (provider?: string) => request<ModelInfo[]>(`/ai/models${provider ? `?provider=${provider}` : ''}`),
  tiers: () => request<{ tier: Tier; candidates: ModelInfo[]; count: number }[]>('/ai/tiers'),
  usage: () => request<Usage>('/ai/usage'),
  orgBudget: (limit_usd: number, hard_limit: boolean) => request<unknown>('/ai/budget', json('PUT', { limit_usd, hard_limit })),
  orgPreferences: () => request<Preferences>('/ai/preferences'),
  setOrgPreferences: (prefs: Omit<Preferences, 'max_attempts'>) => request<Preferences>('/ai/preferences', json('PUT', prefs)),
  intelligenceCreate: (input: { prompt: string; mode: IntelligenceMode; project_id?: string; idempotency_key: string }) =>
    request<IntelligenceWorkflow>('/intelligence/requests', json('POST', input)),
  intelligenceWorkflow: (id: string) => request<IntelligenceWorkflow>(`/intelligence/requests/${id}`),
  intelligenceWorkflows: (projectId?: string) =>
    request<IntelligenceWorkflow[]>(`/intelligence/requests${projectId ? `?project_id=${projectId}` : ''}`),
  assets: (projectId: string) => request<Asset[]>(`/assets?project_id=${projectId}`),
  businessPlans: (projectId: string) => request<BusinessPlan[]>(`/business-plans?project_id=${projectId}`),
  campaigns: (projectId: string) => request<Campaign[]>(`/campaigns?project_id=${projectId}`),
  funnels: (projectId: string) => request<Funnel[]>(`/funnels?project_id=${projectId}`),
  contacts: (projectId: string) => request<CrmContact[]>(`/crm/contacts?project_id=${projectId}`),
  analytics: (projectId: string) => request<{ events: Record<string, number>; visitors: number; leads: number; funnel_conversion_rate: number | null; note: string }>(`/marketing/analytics?project_id=${projectId}`),
  evolutionCases: (projectId: string) => request<EvolutionCase[]>(`/evolution/cases?project_id=${projectId}`),
  engineeringDesigns: (projectId: string) =>
    request<EngineeringDesign[]>(`/engineering/designs?project_id=${projectId}`),
  engineeringDesign: (designId: string) =>
    request<EngineeringDesign>(`/engineering/designs/${designId}`),
  createEngineeringDesign: (input: { project_id: string; prompt: string; idempotency_key: string }) =>
    request<EngineeringDesign>('/engineering/designs', json('POST', input)),
  reviseEngineeringDesign: (
    designId: string,
    input: {
      requirements: EngineeringRequirements
      change_note: string
      source_prompt: string
      idempotency_key: string
    },
  ) => request<EngineeringRevision>(`/engineering/designs/${designId}/revisions`, json('POST', input)),
  requestEngineeringApproval: (designId: string) =>
    request<{ approval_id: string; status: string }>(
      `/engineering/designs/${designId}/approval-request`,
      { method: 'POST' },
    ),
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
