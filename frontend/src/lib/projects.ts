import { createSpec, type SiteSpec } from './site-generator'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  changes?: string[]
  at: number
}

export interface Project {
  id: string
  name: string
  prompt: string
  versions: SiteSpec[]
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  generated: boolean
}

const KEY = 'omniweb.builder.projects.v1'

function uid(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 12)
    : Math.random().toString(36).slice(2, 14)
}

export function newMessage(role: ChatMessage['role'], text: string, changes?: string[]): ChatMessage {
  return { id: uid(), role, text, changes, at: Date.now() }
}

export function loadProjects(): Project[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as Project[]) : []
    return Array.isArray(parsed) ? parsed.sort((a, b) => b.updatedAt - a.updatedAt) : []
  } catch {
    return []
  }
}

function persist(projects: Project[]) {
  window.localStorage.setItem(KEY, JSON.stringify(projects.slice(0, 40)))
}

export function getProject(id: string): Project | undefined {
  return loadProjects().find((project) => project.id === id)
}

export function saveProject(project: Project) {
  const others = loadProjects().filter((item) => item.id !== project.id)
  persist([{ ...project, updatedAt: Date.now() }, ...others])
}

export function deleteProject(id: string) {
  persist(loadProjects().filter((project) => project.id !== id))
}

export function createProject(prompt: string): Project {
  const spec = createSpec(prompt)
  const project: Project = {
    id: uid(),
    name: spec.name,
    prompt,
    versions: [spec],
    messages: [newMessage('user', prompt)],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    generated: false,
  }
  saveProject(project)
  return project
}
