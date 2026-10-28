import { request } from './api'

export type FieldType = 'string' | 'text' | 'number' | 'boolean' | 'date' | 'email'

export interface FieldSpec {
  name: string
  label: string
  type: FieldType
  required: boolean
}

export interface EntitySpec {
  name: string
  label: string
  description: string
  fields: FieldSpec[]
}

export interface AppSpec {
  version: number
  name: string
  tagline: string
  targets: ('web' | 'api' | 'mobile')[]
  accent: string
  auth: boolean
  roles: string[]
  entities: EntitySpec[]
}

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'no_change' | 'awaiting_approval'

export interface RunStep {
  name: string
  status: 'running' | 'done' | 'failed'
  detail: string
  at: string
}

export interface Run {
  id: string
  kind: 'generate' | 'edit' | 'restore' | 'verify'
  instruction: string
  status: RunStatus
  stage: string
  steps: RunStep[]
  changes: string[]
  preserved: string[]
  repair_attempts: number
  cost_usd: number
  error: string | null
  checkpoint_sha: string | null
  created_at: string
  finished_at: string | null
}

export interface CheckResult {
  name: string
  label: string
  target: string
  ok: boolean
  exit_code: number
  duration: number
  timed_out: boolean
  output: string
}

export interface Approval {
  id: string
  kind: 'destructive_migration' | 'deployment' | 'production_deployment' | 'rollback' | 'production_rollback'
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  summary: string
  details: Record<string, unknown>
  estimated_monthly_usd: number | null
  requested_by: string
  requires_confirmation: boolean
  created_at: string
  decided_at: string | null
}

export interface BuilderState {
  spec: AppSpec | null
  head_sha: string | null
  generation_status: string
  your_role: 'owner' | 'editor' | 'viewer'
  run: Run | null
  active: boolean
  approvals: Approval[]
  last_build: { ok: boolean; sha: string | null; steps: CheckResult[]; failed: string[]; unavailable: string | null; finished_at: string } | null
  preview: { url: string | null; sha: string | null; web: boolean; mobile: boolean; api: { running: boolean } | null }
  toolchain_ready: boolean
  sandbox: string
  github: { repo: string | null; branch: string; mode: 'github' | 'local'; last_pushed_sha: string | null }
}

export interface FileEntry {
  path: string
  size: number
  generated: boolean
  modified: boolean
}

export interface Checkpoint {
  sha: string
  parent_sha: string | null
  message: string
  author: 'agent' | 'user'
  action: 'change' | 'undo' | 'redo' | 'restore'
  verified: boolean
  restores_sha: string | null
  created_at: string
}

export interface Diff {
  sha: string
  base: string
  files: { path: string; added: number; removed: number }[]
  patch: string
  truncated: boolean
}

export interface Migration {
  revision: string
  down_revision: string | null
  message: string
  destructive: boolean
  ops: { op: string; table: string; column?: string; field?: { name: string; type: string } }[]
}

export interface GitHubStatus {
  repo: string | null
  branch: string
  mode: 'github' | 'local'
  last_pushed_sha: string | null
  last_pulled_sha: string | null
  remote_sha?: string | null
  head?: string | null
  ahead?: number
  behind?: number
  clone_url?: string
  error?: string
}

export interface Deployment {
  id: string
  environment: 'development' | 'production'
  commit_sha: string
  region: string
  status: 'awaiting_approval' | 'deploying' | 'live' | 'superseded' | 'failed' | 'rejected'
  url: string | null
  estimated_monthly_usd: number
  rollback_of: string | null
  approval_id: string | null
  log: { at: string; message: string }[]
  created_at: string
  finished_at: string | null
}

export interface Estimate {
  environment: string
  region: string
  lines: { item: string; monthly_usd: number }[]
  monthly_usd: number
  note: string
}

export interface SelectedElement {
  loc: string
  tag: string
  text: string | null
  className: string | null
  rect: { x: number; y: number; width: number; height: number }
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })
const p = (id: string) => `/projects/${id}`

export const builder = {
  state: (id: string) => request<BuilderState>(`${p(id)}/builder`),
  generate: (id: string) => request<Run>(`${p(id)}/generate`, { method: 'POST' }),
  edit: (id: string, instruction: string) => request<{ run: Run }>(`${p(id)}/edits`, json('POST', { instruction })),
  runs: (id: string) => request<Run[]>(`${p(id)}/runs`),
  run: (id: string, runId: string) => request<Run & { verify: CheckResult[] }>(`${p(id)}/runs/${runId}`),
  cancel: (id: string, runId: string) => request<Run>(`${p(id)}/runs/${runId}/cancel`, { method: 'POST' }),
  files: (id: string) => request<{ files: FileEntry[]; head: string | null }>(`${p(id)}/files`),
  file: (id: string, path: string) => request<{ path: string; content: string }>(`${p(id)}/files/content?path=${encodeURIComponent(path)}`),
  saveFile: (id: string, path: string, content: string) => request<{ sha: string; changed: boolean; run: Run | null }>(`${p(id)}/files`, json('PUT', { path, content })),
  deleteFile: (id: string, path: string) => request<{ sha: string }>(`${p(id)}/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  visualEdit: (id: string, loc: string, change: { text?: string; className?: string }) =>
    request<{ sha: string; changed: boolean; run: Run | null }>(`${p(id)}/visual-edit`, json('POST', { loc, ...change })),
  checkpoints: (id: string) => request<{ checkpoints: Checkpoint[]; can_undo: boolean; can_redo: boolean; head: string | null }>(`${p(id)}/checkpoints`),
  diff: (id: string, sha: string) => request<Diff>(`${p(id)}/checkpoints/${sha}/diff`),
  restore: (id: string, sha: string) => request<Run>(`${p(id)}/checkpoints/${sha}/restore`, { method: 'POST' }),
  undo: (id: string) => request<Run>(`${p(id)}/undo`, { method: 'POST' }),
  redo: (id: string) => request<Run>(`${p(id)}/redo`, { method: 'POST' }),
  schema: (id: string) => request<{ entities: (EntitySpec & { table: string })[]; migrations: Migration[]; auth: boolean; has_api: boolean }>(`${p(id)}/schema`),
  routes: (id: string) => request<{ routes: { method: string; path: string; summary: string; auth: boolean }[]; docs_url: string | null }>(`${p(id)}/routes`),
  resetPreviewData: (id: string) => request<{ reset: boolean }>(`${p(id)}/preview/reset-data`, { method: 'POST' }),
  approvals: (id: string) => request<Approval[]>(`${p(id)}/approvals`),
  decide: (id: string, approvalId: string, decision: 'approve' | 'reject', confirm?: string) =>
    request<{ approval: Approval; deployment?: Deployment | null }>(`${p(id)}/approvals/${approvalId}/decision`, json('POST', { decision, confirm })),
  github: (id: string) => request<GitHubStatus>(`${p(id)}/github`),
  connectGithub: (id: string, repo: string, branch: string, installation_id?: string) =>
    request<GitHubStatus>(`${p(id)}/github/connect`, json('POST', { repo, branch, installation_id: installation_id || undefined })),
  disconnectGithub: (id: string) => request<void>(`${p(id)}/github`, { method: 'DELETE' }),
  push: (id: string) => request<{ pushed: string }>(`${p(id)}/github/push`, { method: 'POST' }),
  pull: (id: string) => request<{ merged: boolean; message: string; run?: Run }>(`${p(id)}/github/pull`, { method: 'POST' }),
  deployments: (id: string) => request<Deployment[]>(`${p(id)}/deployments`),
  estimate: (id: string, environment: string, region: string) => request<Estimate>(`${p(id)}/deployments/estimate`, json('POST', { environment, region })),
  deploy: (id: string, environment: string, region: string, cloud_connection_id?: string) =>
    request<{ deployment: Deployment; approval: Approval }>(`${p(id)}/deployments`, json('POST', { environment, region, cloud_connection_id })),
  rollback: (id: string, deploymentId: string) => request<{ deployment: Deployment; approval: Approval }>(`${p(id)}/deployments/${deploymentId}/rollback`, { method: 'POST' }),
}
