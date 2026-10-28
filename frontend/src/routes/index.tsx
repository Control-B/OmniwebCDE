import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import {
  ArrowRight,
  ArrowUp,
  AppWindow,
  Blocks,
  Code2,
  Cloud,
  Layers,
  MessageSquareText,
  MonitorSmartphone,
  Palette,
  Paperclip,
  Sparkles,
  Trash2,
  Wand2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { platform } from '../lib/api'
import { createProject, deleteProject, loadProjects, type Project } from '../lib/projects'
import { TEMPLATE_PROMPTS, createSpec, kindLabel, renderSite } from '../lib/site-generator'

export const Route = createFileRoute('/')({
  head: () => ({ meta: [{ title: 'Omniweb — Build websites by chatting with AI' }] }),
  component: Landing,
})

const SUGGESTIONS = [
  { label: 'SaaS landing page', prompt: 'A modern SaaS landing page for an AI note-taking app called "Quill" with pricing and FAQ' },
  { label: 'Restaurant', prompt: 'An elegant restaurant website called "Ember & Oak" with a menu and reservations' },
  { label: 'Portfolio', prompt: 'A minimal portfolio for a product designer named "Mira Chen"' },
  { label: 'Online store', prompt: 'A calm online store for handmade ceramics called "Kiln & Co"' },
  { label: 'Fitness studio', prompt: 'A bold dark gym website called "Forge Athletics" with class pricing' },
]

const APP_SUGGESTIONS = [
  { label: 'Client portal', prompt: 'A client portal for an accounting firm where clients upload documents, track requests, and message their accountant' },
  { label: 'Booking app', prompt: 'A booking app for a hair salon with stylists, services, appointments, and reminders' },
  { label: 'Inventory tracker', prompt: 'An inventory tracker for a small warehouse with products, stock levels, suppliers, and purchase orders' },
  { label: 'Habit tracker (mobile)', prompt: 'A mobile habit tracker with daily check-ins, streaks, and reminders' },
]

const TYPED = [
  'a landing page for my coffee roastery…',
  'a portfolio for my photography…',
  'a SaaS site with pricing and FAQ…',
  'a website for my yoga studio…',
]

function useTypewriter(lines: string[]) {
  const [text, setText] = useState('')
  useEffect(() => {
    let line = 0
    let char = 0
    let deleting = false
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      const current = lines[line]
      char += deleting ? -1 : 1
      setText(current.slice(0, char))
      let delay = deleting ? 22 : 48
      if (!deleting && char === current.length) {
        deleting = true
        delay = 1600
      } else if (deleting && char === 0) {
        deleting = false
        line = (line + 1) % lines.length
        delay = 300
      }
      timer = setTimeout(tick, delay)
    }
    timer = setTimeout(tick, 400)
    return () => clearTimeout(timer)
  }, [lines])
  return text
}

function timeAgo(at: number) {
  const minutes = Math.round((Date.now() - at) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function SitePreview({ html, title }: { html: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.3)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / 1280))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return (
    <div ref={ref} className="lv-thumb" aria-hidden>
      <iframe title={title} srcDoc={html.replace(/ onsubmit="[^"]*"/g, '')} sandbox="" loading="lazy" tabIndex={-1} style={{ transform: `scale(${scale})` }} />
    </div>
  )
}

function Landing() {
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [mode, setMode] = useState<'site' | 'app'>('site')
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const typed = useTypewriter(TYPED)

  useEffect(() => setProjects(loadProjects()), [])

  const templates = useMemo(
    () => TEMPLATE_PROMPTS.map((template) => ({ ...template, html: renderSite(createSpec(template.prompt)) })),
    [],
  )

  const start = (value: string) => {
    const text = value.trim()
    if (!text || submitting) return
    setSubmitting(true)
    setError('')
    if (mode === 'app') {
      platform
        .createProject(text)
        .then((project) => navigate({ to: '/projects/$projectId', params: { projectId: project.id }, search: { start: true } }))
        .catch((reason: Error) => {
          setError(reason.message)
          setSubmitting(false)
        })
      return
    }
    const project = createProject(text)
    void navigate({ to: '/build/$projectId', params: { projectId: project.id } })
  }

  const remove = (id: string) => {
    deleteProject(id)
    setProjects(loadProjects())
  }

  return (
    <div className="lv">
      <header className="lv-nav">
        <div className="lv-wrap lv-nav-inner">
          <Link to="/" className="lv-brand">
            <span className="lv-mark" />
            Omniweb
          </Link>
          <nav className="lv-links" aria-label="Primary">
            <a href="#templates">Templates</a>
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <Link to="/usage" hash="pricing">Pricing</Link>
            <Link to="/app">Cloud workspaces</Link>
          </nav>
          <div className="lv-nav-actions">
            <Link to="/signin" className="lv-btn lv-btn-ghost">Sign in</Link>
            <Link to="/projects" className="lv-btn lv-btn-ghost">Projects</Link>
            <button type="button" className="lv-btn lv-btn-light" onClick={() => inputRef.current?.focus()}>
              Start building
            </button>
          </div>
        </div>
      </header>

      <section className="lv-hero">
        <div className="lv-glow" aria-hidden />
        <div className="lv-wrap lv-hero-inner">
          <Link to="/app" className="lv-pill">
            <span className="lv-pill-tag">New</span>
            Cloud dev environments are live
            <ArrowRight size={14} />
          </Link>
          <h1>
            Build something <span className="lv-grad">remarkable</span>
          </h1>
          <p className="lv-sub">Describe the website you want. Omniweb designs it, builds it, and lets you refine every detail by chatting.</p>

          <form
            className="lv-prompt"
            onSubmit={(event) => {
              event.preventDefault()
              start(prompt)
            }}
          >
            <textarea
              ref={inputRef}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  start(prompt)
                }
              }}
              placeholder={mode === 'site' ? `Ask Omniweb to create ${typed}` : 'Describe the application: who uses it, what they do, and the data it keeps…'}
              rows={3}
              aria-label={mode === 'site' ? 'Describe the website you want to build' : 'Describe the application you want to build'}
            />
            <div className="lv-prompt-bar">
              <div className="lv-prompt-tools">
                <button type="button" className="lv-icon-btn" title="Attachments are coming soon" disabled>
                  <Paperclip size={16} />
                </button>
                <div className="bd-switch lv-mode" role="tablist" aria-label="What to build">
                  <button type="button" role="tab" aria-selected={mode === 'site'} onClick={() => setMode('site')}><Sparkles size={13} /> Website</button>
                  <button type="button" role="tab" aria-selected={mode === 'app'} onClick={() => setMode('app')}><AppWindow size={13} /> Full-stack app</button>
                </div>
              </div>
              <button type="submit" className="lv-send" disabled={!prompt.trim() || submitting} aria-label={mode === 'site' ? 'Generate website' : 'Create application'}>
                <ArrowUp size={18} strokeWidth={2.5} />
              </button>
            </div>
            {error && <p className="lv-prompt-error" role="alert">{error}</p>}
          </form>

          <div className="lv-chips">
            {(mode === 'site' ? SUGGESTIONS : APP_SUGGESTIONS).map((item) => (
              <button key={item.label} type="button" onClick={() => start(item.prompt)}>
                {item.label}
                <ArrowUp size={12} className="lv-chip-arrow" />
              </button>
            ))}
          </div>
        </div>
      </section>

      {projects.length > 0 && (
        <section className="lv-section lv-section-tight">
          <div className="lv-wrap">
            <div className="lv-section-head">
              <h2>Your projects</h2>
              <span className="lv-muted">Saved in this browser</span>
            </div>
            <div className="lv-grid">
              {projects.slice(0, 6).map((project) => (
                <article key={project.id} className="lv-card">
                  <Link to="/build/$projectId" params={{ projectId: project.id }} className="lv-card-link">
                    <SitePreview html={renderSite(project.versions[project.versions.length - 1])} title={project.name} />
                    <div className="lv-card-meta">
                      <div>
                        <h3>{project.name}</h3>
                        <p>Edited {timeAgo(project.updatedAt)} · {project.versions.length} version{project.versions.length === 1 ? '' : 's'}</p>
                      </div>
                    </div>
                  </Link>
                  <button type="button" className="lv-card-delete" onClick={() => remove(project.id)} aria-label={`Delete ${project.name}`}>
                    <Trash2 size={14} />
                  </button>
                </article>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="lv-section" id="templates">
        <div className="lv-wrap">
          <div className="lv-section-head">
            <div>
              <p className="lv-kicker">From the community</p>
              <h2>Start from something beautiful</h2>
            </div>
            <span className="lv-muted">Every template was generated from a single sentence.</span>
          </div>
          <div className="lv-grid">
            {templates.map((template) => (
              <article key={template.title} className="lv-card">
                <button type="button" className="lv-card-link" onClick={() => start(template.prompt)}>
                  <SitePreview html={template.html} title={template.title} />
                  <div className="lv-card-meta">
                    <div>
                      <h3>{template.title}</h3>
                      <p>{kindLabel(template.kind)}</p>
                    </div>
                    <span className="lv-remix">Remix <ArrowRight size={13} /></span>
                  </div>
                </button>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lv-section" id="how">
        <div className="lv-wrap">
          <p className="lv-kicker lv-center">How it works</p>
          <h2 className="lv-center">From idea to website in three messages</h2>
          <div className="lv-steps">
            {[
              { icon: MessageSquareText, title: 'Describe it', text: 'Tell Omniweb what you are building, who it is for, and the feeling you want. Plain language is enough.' },
              { icon: Wand2, title: 'Watch it design', text: 'Layout, typography, palette, and copy are composed in seconds, and you see the result live.' },
              { icon: Layers, title: 'Refine by chatting', text: '“Make it dark”, “add pricing”, “rename it to Atlas”. Each change is saved as a version you can undo.' },
            ].map((step, index) => (
              <div key={step.title} className="lv-step">
                <span className="lv-step-num">0{index + 1}</span>
                <step.icon size={22} />
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lv-section" id="features">
        <div className="lv-wrap">
          <p className="lv-kicker lv-center">Designer-grade by default</p>
          <h2 className="lv-center">Taste built in, not bolted on</h2>
          <div className="lv-bento">
            <div className="lv-bento-item lv-bento-wide">
              <Palette size={20} />
              <h3>Considered visual systems</h3>
              <p>Paired typefaces, tuned palettes, and spacing scales. Switch between modern, elegant, playful, minimal, and bold styles with one sentence.</p>
              <div className="lv-swatches" aria-hidden>
                {['#7c3aed', '#2563eb', '#059669', '#ea580c', '#db2777', '#0d9488', '#18181b', '#b45309'].map((color) => (
                  <span key={color} style={{ background: color }} />
                ))}
              </div>
            </div>
            <div className="lv-bento-item">
              <MonitorSmartphone size={20} />
              <h3>Responsive everywhere</h3>
              <p>Preview on desktop, tablet, and phone as you go.</p>
            </div>
            <div className="lv-bento-item">
              <Code2 size={20} />
              <h3>Real, portable code</h3>
              <p>Inspect the HTML at any time and export a single file you can host anywhere.</p>
            </div>
            <div className="lv-bento-item">
              <Blocks size={20} />
              <h3>Sections on demand</h3>
              <p>Pricing, FAQ, testimonials, stats, and contact forms appear when you ask.</p>
            </div>
            <div className="lv-bento-item lv-bento-accent">
              <Cloud size={20} />
              <h3>Grow into the cloud</h3>
              <p>When you are ready to write code, launch a full cloud development environment on your own DigitalOcean account.</p>
              <Link to="/app" className="lv-inline-link">Open cloud workspaces <ArrowRight size={14} /></Link>
            </div>
          </div>
        </div>
      </section>

      <section className="lv-section">
        <div className="lv-wrap">
          <div className="lv-final">
            <div className="lv-glow lv-glow-small" aria-hidden />
            <h2>Your next website is one sentence away</h2>
            <p>No templates to wrestle with. No design skills required.</p>
            <button
              type="button"
              className="lv-btn lv-btn-light lv-btn-lg"
              onClick={() => {
                window.scrollTo({ top: 0, behavior: 'smooth' })
                setTimeout(() => inputRef.current?.focus(), 400)
              }}
            >
              Start building <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </section>

      <footer className="lv-footer">
        <div className="lv-wrap lv-footer-inner">
          <span className="lv-brand"><span className="lv-mark" />Omniweb</span>
          <nav aria-label="Footer">
            <a href="#templates">Templates</a>
            <a href="#features">Features</a>
            <Link to="/app">Cloud workspaces</Link>
            <Link to="/about">About</Link>
          </nav>
          <span className="lv-muted">© {new Date().getFullYear()} Omniweb</span>
        </div>
      </footer>
    </div>
  )
}
