import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  ArrowRight, BriefcaseBusiness, Check, Circle, Code2, DraftingCompass, Image, Megaphone,
  PenLine, Play, Sparkles, Video,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import { platform, type IntelligenceMode, type IntelligenceWorkflow } from '../lib/api'

export const Route = createFileRoute('/create')({
  head: () => ({ meta: [{ title: 'Unified Create — Omniweb' }] }),
  component: () => (
    <div className="st growth">
      <AppNav />
      <RequireAuth><UnifiedCreate /></RequireAuth>
    </div>
  ),
})

const modes: Array<{ mode: IntelligenceMode; label: string; icon: typeof Sparkles }> = [
  { mode: 'AUTO', label: 'Auto', icon: Sparkles },
  { mode: 'BUILD', label: 'Build', icon: Code2 },
  { mode: 'BUSINESS', label: 'Business', icon: BriefcaseBusiness },
  { mode: 'MARKETING', label: 'Marketing', icon: Megaphone },
  { mode: 'CONTENT', label: 'Content', icon: PenLine },
  { mode: 'IMAGE', label: 'Image', icon: Image },
  { mode: 'VIDEO', label: 'Video', icon: Video },
  { mode: 'ENGINEERING', label: 'Engineering', icon: DraftingCompass },
]

const starters = [
  { mode: 'BUILD' as const, label: 'Build an app', icon: Code2, prompt: 'Build a full-stack customer portal with secure sign-in, onboarding, analytics, and a responsive mobile experience.' },
  { mode: 'BUSINESS' as const, label: 'Plan a business', icon: BriefcaseBusiness, prompt: 'Create an evidence-aware business plan, customer segments, pricing assumptions, risks, and a go-to-market roadmap for my idea.' },
  { mode: 'MARKETING' as const, label: 'Launch a campaign', icon: Megaphone, prompt: 'Create a complete lead-generation campaign with audience, funnel, landing page, email sequence, content calendar, and measurable objectives.' },
  { mode: 'CONTENT' as const, label: 'Create content', icon: PenLine, prompt: 'Create a month of on-brand blog, email, social, landing-page, and advertising content. Mark unsupported factual claims for review.' },
  { mode: 'IMAGE' as const, label: 'Generate images', icon: Image, prompt: 'Prepare promotional image concepts and generation jobs for web, email, and social media, with variants and usage metadata.' },
  { mode: 'VIDEO' as const, label: 'Create a video brief', icon: Video, prompt: 'Create a campaign video brief, storyboard, shot list, aspect ratios, and an asynchronous generation job where a provider is available.' },
  { mode: 'ENGINEERING' as const, label: 'Design a component', icon: DraftingCompass, prompt: 'Design an L-shaped steel mounting bracket, 200 mm long, 80 mm wide, 6 mm thick, with four 10 mm mounting holes. Generate a 3D model, a dimensioned drawing, and manufacturing notes.' },
]

function UnifiedCreate() {
  const [mode, setMode] = useState<IntelligenceMode>('AUTO')
  const [prompt, setPrompt] = useState('')
  const [workflow, setWorkflow] = useState<IntelligenceWorkflow | null>(null)
  const create = useMutation({
    mutationFn: (input: { prompt: string; mode: IntelligenceMode }) =>
      platform.intelligenceCreate({ ...input, idempotency_key: crypto.randomUUID() }),
    onSuccess: setWorkflow,
  })
  const current = useQuery({
    queryKey: ['intelligence-workflow', workflow?.id],
    queryFn: () => platform.intelligenceWorkflow(workflow!.id),
    enabled: Boolean(workflow?.id),
    refetchInterval: (query) => ['completed', 'failed'].includes(query.state.data?.status ?? '') ? false : 1200,
  })
  useEffect(() => { if (current.data) setWorkflow(current.data) }, [current.data])

  const submit = (value = prompt, selected = mode) => {
    const clean = value.trim()
    if (clean.length < 3) return
    setMode(selected)
    setPrompt(clean)
    create.mutate({ prompt: clean, mode: selected })
  }

  return (
    <main className="st-page growth-page">
      <section className="growth-hero">
        <span className="growth-eyebrow"><Sparkles size={14} /> One prompt. One connected workspace.</span>
        <h1>Turn an idea into a business, product, and campaign.</h1>
        <p>Omniweb detects every intent, builds a dependency-aware plan, and uses the shared cost-aware execution engine. Nothing publishes or spends without approval.</p>
      </section>

      <form className="growth-prompt" onSubmit={(event) => { event.preventDefault(); submit() }}>
        <div className="growth-modes" role="tablist" aria-label="Creation mode">
          {modes.map((item) => <button key={item.mode} type="button" role="tab" aria-selected={mode === item.mode} onClick={() => setMode(item.mode)}><item.icon size={14} />{item.label}</button>)}
        </div>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} placeholder="Build a website for my restaurant, create the business plan and marketing strategy, write ten social posts, generate promotional images, and prepare a video campaign…" />
        <div className="growth-submit">
          <span>Multiple goals become linked tasks with budgets, evidence, and approval gates.</span>
          <button className="growth-primary" type="submit" disabled={create.isPending || prompt.trim().length < 3}>{create.isPending ? 'Planning…' : <>Create plan <ArrowRight size={16} /></>}</button>
        </div>
      </form>
      {create.error && <div className="st-alert st-alert-error">{create.error.message}</div>}

      {!workflow && (
        <section className="growth-actions" aria-label="Quick starts">
          {starters.map((item) => (
            <button key={item.label} type="button" onClick={() => submit(item.prompt, item.mode)}>
              <span className="growth-action-icon"><item.icon size={19} /></span>
              <strong>{item.label}</strong>
              <small>{item.prompt.split(',')[0]}</small>
              <ArrowRight size={15} />
            </button>
          ))}
        </section>
      )}

      {workflow && <WorkflowView workflow={workflow} />}
    </main>
  )
}

function WorkflowView({ workflow }: { workflow: IntelligenceWorkflow }) {
  const running = !['completed', 'failed'].includes(workflow.status)
  return (
    <section className="growth-workflow">
      <header>
        <div><span className={`growth-live ${running ? 'running' : ''}`}>{running ? 'Executing' : workflow.status}</span><h2>Your connected execution plan</h2></div>
        {workflow.project_id && <Link className="growth-primary secondary" to="/projects/$projectId/growth" params={{ projectId: workflow.project_id }}>Open workspace <ArrowRight size={15} /></Link>}
      </header>
      <div className="growth-task-list">
        {workflow.tasks.map((task, index) => (
          <article key={task.id} className={`growth-task ${task.status}`}>
            <span className="growth-task-node">{task.status === 'completed' ? <Check size={15} /> : task.status === 'running' ? <Play size={13} /> : <Circle size={12} />}</span>
            <div><small>0{index + 1} · {task.kind.replaceAll('_', ' ')}</small><strong>{task.title}</strong>{task.depends_on.length > 0 && <p>After {task.depends_on.join(', ')}</p>}{task.error && <p className="st-error">{task.error}</p>}</div>
            <span className="st-pill">{task.status}</span>
          </article>
        ))}
      </div>
      <footer><span>Recorded AI cost</span><strong>${workflow.total_cost_usd.toFixed(4)}</strong><small>Provider-reported usage only</small></footer>
    </section>
  )
}
