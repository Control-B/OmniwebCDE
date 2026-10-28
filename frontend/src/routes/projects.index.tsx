import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { ArrowUp, FolderGit2, GitBranch, Rocket, Search, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import { platform, type Project } from '../lib/api'

export const Route = createFileRoute('/projects/')({
  head: () => ({ meta: [{ title: 'Projects — Omniweb' }] }),
  component: () => (
    <div className="st">
      <AppNav />
      <RequireAuth>
        <Projects />
      </RequireAuth>
    </div>
  ),
})

export const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  planning: 'Planning',
  generating: 'Generating',
  building: 'Building',
  ready: 'Ready',
  needs_attention: 'Needs attention',
  failed: 'Failed',
  not_deployed: 'Not deployed',
  deploying: 'Deploying',
  development_live: 'Live (development)',
  production_live: 'Live (production)',
}

export function relativeTime(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function usd(value: number) {
  if (value === 0) return '$0.00'
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

function Projects() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [prompt, setPrompt] = useState('')
  const [filter, setFilter] = useState('')
  const projects = useQuery({ queryKey: ['projects'], queryFn: platform.projects })
  const create = useMutation({
    mutationFn: (value: string) => platform.createProject(value),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      void navigate({ to: '/projects/$projectId', params: { projectId: project.id }, search: { start: true } })
    },
  })
  const visible = useMemo(
    () => (projects.data ?? []).filter((p) => `${p.name} ${p.description}`.toLowerCase().includes(filter.toLowerCase())),
    [projects.data, filter],
  )

  return (
    <main className="st-page">
      <section className="st-hero-row">
        <div>
          <h1>Projects</h1>
          <p className="st-muted">Describe an application and Omniweb plans it with you, then builds it.</p>
        </div>
      </section>

      <form
        className="lv-prompt st-new"
        onSubmit={(event) => {
          event.preventDefault()
          if (prompt.trim().length >= 3) create.mutate(prompt.trim())
        }}
      >
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              if (prompt.trim().length >= 3) create.mutate(prompt.trim())
            }
          }}
          rows={2}
          placeholder="Build a property management app with landlords, tenants, rent collection, and maintenance requests…"
          aria-label="Describe a new application"
        />
        <div className="lv-prompt-bar">
          <span className="lv-model"><Sparkles size={13} /> New application</span>
          <button type="submit" className="lv-send" disabled={prompt.trim().length < 3 || create.isPending} aria-label="Create project">
            <ArrowUp size={18} strokeWidth={2.5} />
          </button>
        </div>
        {create.error && <p className="st-error">{create.error.message}</p>}
      </form>

      <div className="st-toolbar">
        <h2>All projects</h2>
        <label className="st-search">
          <Search size={14} />
          <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search projects" aria-label="Search projects" />
        </label>
      </div>

      {projects.isLoading ? (
        <div className="st-grid">
          {[0, 1, 2].map((i) => <div key={i} className="st-card st-skeleton" />)}
        </div>
      ) : projects.error ? (
        <div className="st-empty">
          <h3>Projects couldn’t be loaded</h3>
          <p className="st-muted">{projects.error.message}</p>
          <button type="button" className="lv-btn lv-btn-light" onClick={() => void projects.refetch()}>Retry</button>
        </div>
      ) : visible.length === 0 ? (
        <div className="st-empty">
          <FolderGit2 size={22} />
          <h3>{filter ? 'No projects match your search' : 'No projects yet'}</h3>
          <p className="st-muted">{filter ? 'Try a different name.' : 'Describe your first application above to get started.'}</p>
        </div>
      ) : (
        <div className="st-grid">
          {visible.map((project) => <ProjectCard key={project.id} project={project} />)}
        </div>
      )}
    </main>
  )
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link to="/projects/$projectId" params={{ projectId: project.id }} search={{ start: false }} className="st-card st-project">
      <div className="st-project-head">
        <h3>{project.name}</h3>
        <span className={`st-status st-status-${project.generation_status}`}>{STATUS_LABEL[project.generation_status]}</span>
      </div>
      <p className="st-project-desc">{project.description}</p>
      <div className="st-chips">
        {project.stack.slice(0, 4).map((item) => <span key={item}>{item}</span>)}
        {project.stack.length > 4 && <span>+{project.stack.length - 4}</span>}
      </div>
      <dl className="st-meta">
        <div><dt>Modified</dt><dd>{relativeTime(project.updated_at)}</dd></div>
        <div><dt><Rocket size={12} /> Deploy</dt><dd>{STATUS_LABEL[project.deployment_status] ?? project.deployment_status}</dd></div>
        <div><dt><GitBranch size={12} /> GitHub</dt><dd>{project.github_repo ?? 'Not connected'}</dd></div>
        <div><dt>AI usage</dt><dd>{usd(project.estimated_usage_usd)}</dd></div>
      </dl>
    </Link>
  )
}
