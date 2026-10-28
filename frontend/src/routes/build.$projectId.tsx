import { Link, createFileRoute } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowUp,
  Check,
  Code2,
  Copy,
  Download,
  ExternalLink,
  Eye,
  Loader2,
  Monitor,
  Redo2,
  RotateCw,
  Smartphone,
  Sparkles,
  Tablet,
  Undo2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { getProject, newMessage, saveProject, type Project } from '../lib/projects'
import { applyEdit, describeSpec, kindLabel, renderSite } from '../lib/site-generator'

export const Route = createFileRoute('/build/$projectId')({
  head: () => ({ meta: [{ title: 'Omniweb Builder' }] }),
  component: Builder,
})

type Device = 'desktop' | 'tablet' | 'mobile'

const GENERATION_STEPS = ['Understanding your idea', 'Choosing layout and sections', 'Pairing typography and color', 'Writing copy', 'Polishing responsive details']

const EDIT_IDEAS = [
  'Make it dark',
  'Make it light',
  'Add a pricing section',
  'Add an FAQ',
  'Add testimonials',
  'Add stats',
  'Use a green palette',
  'Use a blue palette',
  'Make the style more elegant',
  'Make it playful',
  'Make the corners sharp',
  'Make the corners round',
]

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function Builder() {
  const { projectId } = Route.useParams()
  const [project, setProject] = useState<Project | null | undefined>(undefined)
  const [cursor, setCursor] = useState(0)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(-1)
  const [device, setDevice] = useState<Device>('desktop')
  const [tab, setTab] = useState<'preview' | 'code'>('preview')
  const [mobilePane, setMobilePane] = useState<'chat' | 'preview'>('chat')
  const [copied, setCopied] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const chatEnd = useRef<HTMLDivElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const found = getProject(projectId) ?? null
    setProject(found)
    if (found) setCursor(found.versions.length - 1)
  }, [projectId])

  const commit = (next: Project) => {
    saveProject(next)
    setProject(next)
  }

  useEffect(() => {
    if (!project || project.generated || started.current) return
    started.current = true
    void (async () => {
      setBusy(true)
      for (let index = 0; index < GENERATION_STEPS.length; index++) {
        setStep(index)
        await wait(520 + Math.random() * 260)
      }
      const spec = project.versions[0]
      const reply = newMessage(
        'assistant',
        `I designed ${spec.name}, a ${kindLabel(spec.kind).replace(/^[A-Z][a-z]/, (word) => word.toLowerCase())} with ${/^[aeiou]/.test(spec.style) ? 'an' : 'a'} ${spec.style} feel. Tell me what to change and I’ll update it live.`,
        describeSpec(spec),
      )
      commit({ ...project, generated: true, messages: [...project.messages, reply] })
      setStep(-1)
      setBusy(false)
      setMobilePane('preview')
    })()
  }, [project])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [project?.messages.length, step])

  const spec = project?.versions[Math.min(cursor, (project?.versions.length ?? 1) - 1)]
  const html = useMemo(() => (spec && project?.generated ? renderSite(spec) : ''), [spec, project?.generated])
  const ideas = useMemo(() => (spec ? EDIT_IDEAS.filter((idea) => applyEdit(spec, idea).changes.length > 0).slice(0, 5) : []), [spec])

  const send = async (value: string) => {
    const text = value.trim()
    if (!text || busy || !project || !spec) return
    setInput('')
    setBusy(true)
    const withUser = { ...project, messages: [...project.messages, newMessage('user', text)] }
    commit(withUser)
    await wait(650 + Math.random() * 400)
    const result = applyEdit(spec, text)
    if (result.changes.length === 0) {
      const reply =
        result.notes.length > 0
          ? newMessage('assistant', `Nothing to change there. ${result.notes.join('. ')}.`)
          : newMessage(
              'assistant',
              'I couldn’t map that to a design change yet. Try asking for a color, dark or light mode, a style, a section to add or remove, or new copy in quotes, like: headline "Ship faster together".',
            )
      commit({ ...withUser, messages: [...withUser.messages, reply] })
    } else {
      const versions = [...project.versions.slice(0, cursor + 1), result.spec]
      commit({
        ...withUser,
        name: result.spec.name,
        versions,
        messages: [...withUser.messages, newMessage('assistant', 'Done. Here’s what I changed:', result.changes)],
      })
      setCursor(versions.length - 1)
      setMobilePane('preview')
    }
    setBusy(false)
  }

  const download = () => {
    if (!spec) return
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${spec.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'site'}.html`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const openTab = () => {
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
    window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }

  const copy = async () => {
    await navigator.clipboard.writeText(html)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  if (project === undefined) {
    return (
      <div className="bd-empty">
        <Loader2 className="bd-spin" size={22} />
      </div>
    )
  }

  if (project === null) {
    return (
      <div className="bd-empty">
        <h1>We couldn’t find that project</h1>
        <p>Projects are saved in the browser where they were created. It may have been deleted or made on another device.</p>
        <Link to="/" className="lv-btn lv-btn-light">Start a new project</Link>
      </div>
    )
  }

  const canUndo = cursor > 0 && !busy
  const canRedo = cursor < project.versions.length - 1 && !busy

  return (
    <div className="bd" data-pane={mobilePane}>
      <header className="bd-top">
        <div className="bd-top-left">
          <Link to="/" className="bd-home" aria-label="Back to home"><ArrowLeft size={16} /></Link>
          <span className="lv-mark" />
          <div className="bd-title">
            <strong>{project.name}</strong>
            <small>{project.generated ? `Version ${cursor + 1} of ${project.versions.length}` : 'Generating…'}</small>
          </div>
        </div>
        <div className="bd-switch bd-mobile-only" role="tablist">
          <button type="button" role="tab" aria-selected={mobilePane === 'chat'} onClick={() => setMobilePane('chat')}>Chat</button>
          <button type="button" role="tab" aria-selected={mobilePane === 'preview'} onClick={() => setMobilePane('preview')}>Preview</button>
        </div>
        <div className="bd-top-right">
          <button type="button" className="bd-icon" onClick={() => setCursor(cursor - 1)} disabled={!canUndo} title="Undo"><Undo2 size={16} /></button>
          <button type="button" className="bd-icon" onClick={() => setCursor(cursor + 1)} disabled={!canRedo} title="Redo"><Redo2 size={16} /></button>
          <button type="button" className="lv-btn lv-btn-light bd-export" onClick={download} disabled={!html}>
            <Download size={15} /> <span>Export</span>
          </button>
        </div>
      </header>

      <aside className="bd-chat">
        <div className="bd-messages">
          {project.messages.map((message) => (
            <div key={message.id} className={`bd-msg bd-msg-${message.role}`}>
              {message.role === 'assistant' && <span className="bd-avatar"><Sparkles size={13} /></span>}
              <div className="bd-bubble">
                <p>{message.text}</p>
                {message.changes && message.changes.length > 0 && (
                  <ul>
                    {message.changes.map((change) => (
                      <li key={change}><Check size={13} /> {change}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ))}
          {step >= 0 && (
            <div className="bd-msg bd-msg-assistant">
              <span className="bd-avatar"><Sparkles size={13} /></span>
              <div className="bd-bubble bd-steps">
                {GENERATION_STEPS.map((label, index) => (
                  <div key={label} className={index < step ? 'done' : index === step ? 'active' : ''}>
                    {index < step ? <Check size={13} /> : index === step ? <Loader2 size={13} className="bd-spin" /> : <span className="bd-dot" />}
                    {label}
                  </div>
                ))}
              </div>
            </div>
          )}
          {busy && step < 0 && (
            <div className="bd-msg bd-msg-assistant">
              <span className="bd-avatar"><Sparkles size={13} /></span>
              <div className="bd-bubble bd-typing"><span /><span /><span /></div>
            </div>
          )}
          <div ref={chatEnd} />
        </div>

        {project.generated && ideas.length > 0 && (
          <div className="bd-ideas">
            {ideas.map((idea) => (
              <button key={idea} type="button" onClick={() => void send(idea)} disabled={busy}>{idea}</button>
            ))}
          </div>
        )}

        <form
          className="bd-input"
          onSubmit={(event) => {
            event.preventDefault()
            void send(input)
          }}
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send(input)
              }
            }}
            rows={2}
            placeholder={project.generated ? 'Ask for a change, e.g. “add an FAQ and make it blue”' : 'Designing your site…'}
            disabled={!project.generated}
            aria-label="Describe a change"
          />
          <button type="submit" className="lv-send" disabled={!input.trim() || busy || !project.generated} aria-label="Send">
            <ArrowUp size={17} strokeWidth={2.5} />
          </button>
        </form>
      </aside>

      <main className="bd-stage">
        <div className="bd-toolbar">
          <div className="bd-switch" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'preview'} onClick={() => setTab('preview')}><Eye size={14} /> Preview</button>
            <button type="button" role="tab" aria-selected={tab === 'code'} onClick={() => setTab('code')}><Code2 size={14} /> Code</button>
          </div>
          {tab === 'preview' ? (
            <div className="bd-switch bd-devices">
              <button type="button" aria-pressed={device === 'desktop'} onClick={() => setDevice('desktop')} title="Desktop"><Monitor size={15} /></button>
              <button type="button" aria-pressed={device === 'tablet'} onClick={() => setDevice('tablet')} title="Tablet"><Tablet size={15} /></button>
              <button type="button" aria-pressed={device === 'mobile'} onClick={() => setDevice('mobile')} title="Mobile"><Smartphone size={15} /></button>
            </div>
          ) : (
            <span className="bd-muted">{html.split('\n').length} lines · single-file HTML</span>
          )}
          <div className="bd-toolbar-right">
            <button type="button" className="bd-icon" onClick={() => setReloadKey(reloadKey + 1)} disabled={!html} title="Reload preview"><RotateCw size={15} /></button>
            <button type="button" className="bd-icon" onClick={() => void copy()} disabled={!html} title="Copy HTML">{copied ? <Check size={15} /> : <Copy size={15} />}</button>
            <button type="button" className="bd-icon" onClick={openTab} disabled={!html} title="Open in new tab"><ExternalLink size={15} /></button>
          </div>
        </div>

        <div className="bd-canvas">
          {!html ? (
            <div className="bd-skeleton" aria-label="Generating preview">
              <div className="bd-sk-nav" />
              <div className="bd-sk-hero"><div /><div /><div /></div>
              <div className="bd-sk-grid"><div /><div /><div /></div>
            </div>
          ) : tab === 'preview' ? (
            <div className={`bd-frame bd-frame-${device}`}>
              <iframe key={reloadKey} title={`${project.name} preview`} srcDoc={html} sandbox="allow-scripts allow-forms" />
            </div>
          ) : (
            <pre className="bd-code"><code>{html}</code></pre>
          )}
        </div>
      </main>
    </div>
  )
}
