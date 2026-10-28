import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleAlert, Code2, ExternalLink, Hammer, Loader2, MousePointerClick, RotateCw, Smartphone, Waypoints, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { builder, type BuilderState, type SelectedElement } from '../../lib/builder'

type Device = 'desktop' | 'tablet' | 'mobile'

export function PreviewFrame({
  projectId,
  state,
  device,
  selecting,
  onSelectingChange,
  readOnly,
  onGenerate,
  onOpenFile,
}: {
  projectId: string
  state: BuilderState | undefined
  device: Device
  selecting: boolean
  onSelectingChange: (value: boolean) => void
  readOnly: boolean
  onGenerate: () => void
  onOpenFile: (path: string) => void
}) {
  const frame = useRef<HTMLIFrameElement>(null)
  const [surface, setSurface] = useState<'web' | 'mobile'>('web')
  const [selected, setSelected] = useState<SelectedElement | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const preview = state?.preview
  const hasWeb = Boolean(preview?.web)
  const hasMobile = Boolean(preview?.mobile)
  const kind = surface === 'mobile' && hasMobile ? 'mobile' : hasWeb ? 'web' : 'mobile'
  const origin = useMemo(() => (preview?.url ? new URL(preview.url).origin : null), [preview?.url])
  const src = preview?.url ? `${preview.url}${kind === 'mobile' ? 'mobile/' : ''}?v=${preview.sha?.slice(0, 8)}` : null

  useEffect(() => {
    if (!origin) return
    const listener = (event: MessageEvent) => {
      if (event.origin !== origin || event.source !== frame.current?.contentWindow) return
      const data = event.data as { source?: string; type?: string; element?: SelectedElement; message?: string }
      if (data?.source !== 'omniweb-preview') return
      if (data.type === 'selected' && data.element) {
        setSelected(data.element)
        onSelectingChange(false)
      }
      if (data.type === 'error' && data.message) setErrors((current) => [...current.slice(-4), data.message as string])
    }
    window.addEventListener('message', listener)
    return () => window.removeEventListener('message', listener)
  }, [origin, onSelectingChange])

  useEffect(() => {
    if (!origin) return
    frame.current?.contentWindow?.postMessage({ type: 'omniweb:select', enabled: selecting }, origin)
  }, [selecting, origin, src])

  useEffect(() => {
    setSelected(null)
    setErrors([])
  }, [src])

  const width = device === 'mobile' || kind === 'mobile' ? 390 : device === 'tablet' ? 820 : null
  const building = state?.active
  const runSteps = state?.run?.steps ?? []
  const currentStep = [...runSteps].reverse().find((s) => s.status === 'running')

  if (!preview?.url) {
    return (
      <div className="bd-canvas">
        <div className={`bd-frame bd-frame-${device} st-preview-empty`}>
          <div>
            {building ? <Loader2 size={22} className="bd-spin" /> : state?.last_build && !state.last_build.ok ? <CircleAlert size={22} /> : <Waypoints size={22} />}
            <h3>{building ? 'Building your app' : state?.last_build && !state.last_build.ok ? 'The first build needs attention' : 'No preview yet'}</h3>
            <p>
              {building
                ? currentStep?.detail || 'Planning the data model, writing code, and running checks in an isolated sandbox.'
                : state?.last_build && !state.last_build.ok
                  ? 'Some checks failed, so there is nothing to preview yet. The Logs tab shows what went wrong.'
                  : 'Omniweb writes the code, type-checks it, runs its tests and migrations in a sandbox, and only then shows it here.'}
            </p>
            {!building && !readOnly && (
              <button type="button" className="lv-btn lv-btn-light" onClick={onGenerate}>
                <Hammer size={14} /> {state?.spec ? 'Rebuild app' : 'Generate app'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bd-canvas pv">
      {(hasWeb && hasMobile) || building ? (
        <div className="pv-strip">
          {hasWeb && hasMobile && (
            <div className="bd-switch">
              <button type="button" aria-pressed={kind === 'web'} onClick={() => setSurface('web')}>Web</button>
              <button type="button" aria-pressed={kind === 'mobile'} onClick={() => setSurface('mobile')}><Smartphone size={12} /> Mobile</button>
            </div>
          )}
          {building && <span className="pv-building"><Loader2 size={12} className="bd-spin" /> {currentStep?.detail || 'Updating'} — showing the last working version</span>}
        </div>
      ) : null}
      <div className={`bd-frame pv-frame${kind === 'mobile' ? ' pv-phone' : ''}`} style={width ? { width, maxWidth: '100%' } : undefined} data-selecting={selecting}>
        {src && (
          <iframe
            ref={frame}
            key={src}
            src={src}
            title="App preview"
            sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups"
            referrerPolicy="no-referrer"
            onLoad={() => origin && frame.current?.contentWindow?.postMessage({ type: 'omniweb:select', enabled: selecting }, origin)}
          />
        )}
      </div>
      {errors.length > 0 && (
        <div className="pv-errors" role="status">
          <CircleAlert size={13} /> <span>Preview error: {errors[errors.length - 1]}</span>
          <button type="button" className="bd-icon" onClick={() => setErrors([])} aria-label="Dismiss"><X size={12} /></button>
        </div>
      )}
      {selected && (
        <Inspector
          key={selected.loc}
          projectId={projectId}
          element={selected}
          kind={kind}
          readOnly={readOnly || Boolean(building)}
          onClose={() => setSelected(null)}
          onOpenFile={onOpenFile}
        />
      )}
    </div>
  )
}

export function PreviewToolbarActions({ state, selecting, onSelectingChange, onReload }: { state: BuilderState | undefined; selecting: boolean; onSelectingChange: (v: boolean) => void; onReload: () => void }) {
  const url = state?.preview.url
  return (
    <>
      <button
        type="button"
        className="bd-icon"
        aria-pressed={selecting}
        disabled={!url || state?.your_role === 'viewer'}
        onClick={() => onSelectingChange(!selecting)}
        title={url ? (selecting ? 'Stop selecting' : 'Select an element to edit its text or styles') : 'Available once there is a preview'}
      >
        <MousePointerClick size={15} />
      </button>
      {url ? (
        <>
          <span className="bd-url" title={url}>{url.replace(/^https?:\/\//, '')}</span>
          <button type="button" className="bd-icon" onClick={onReload} title="Reload preview"><RotateCw size={14} /></button>
          <a className="bd-icon" href={url} target="_blank" rel="noreferrer" title="Open preview in a new tab"><ExternalLink size={14} /></a>
        </>
      ) : (
        <span className="bd-muted">{state?.active ? 'Building…' : 'No build yet'}</span>
      )}
    </>
  )
}

function Inspector({ projectId, element, kind, readOnly, onClose, onOpenFile }: { projectId: string; element: SelectedElement; kind: 'web' | 'mobile'; readOnly: boolean; onClose: () => void; onOpenFile: (path: string) => void }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState(element.text ?? '')
  const [classes, setClasses] = useState(element.className ?? '')
  const path = element.loc.split(':')[0]
  const line = element.loc.split(':')[1]
  const edit = useMutation({
    mutationFn: () => {
      const change: { text?: string; className?: string } = {}
      if (element.text !== null && text !== element.text) change.text = text
      if (kind === 'web' && element.className !== null && classes !== element.className) change.className = classes
      return builder.visualEdit(projectId, element.loc, change)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['builder', projectId] })
      onClose()
    },
  })
  const changed = (element.text !== null && text !== element.text) || (kind === 'web' && classes !== (element.className ?? ''))
  return (
    <aside className="pv-inspector" aria-label="Edit selected element">
      <header>
        <strong>&lt;{element.tag}&gt;</strong>
        <button type="button" className="cp-link" onClick={() => onOpenFile(path)} title="Open in the code editor">
          <Code2 size={12} /> {path.split('/').pop()}:{line}
        </button>
        <button type="button" className="bd-icon" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </header>
      <form
        className="st-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (changed) edit.mutate()
        }}
      >
        {element.text !== null ? (
          <label className="st-field">Text<textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} disabled={readOnly} /></label>
        ) : (
          <p className="st-fine">This element contains other elements. Select a text element inside it to change its wording.</p>
        )}
        {kind === 'web' && (
          <label className="st-field">Tailwind classes<input value={classes} onChange={(e) => setClasses(e.target.value)} disabled={readOnly} spellCheck={false} /></label>
        )}
        {edit.error && <p className="st-error">{edit.error.message}</p>}
        <div className="st-row">
          <button type="submit" className="lv-btn lv-btn-light" disabled={!changed || edit.isPending || readOnly}>
            {edit.isPending ? <Loader2 size={13} className="bd-spin" /> : null} Apply and rebuild
          </button>
          <span className="st-fine">Edits the source directly and runs checks.</span>
        </div>
      </form>
    </aside>
  )
}
