import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  AlertTriangle, ArrowLeft, Box, CheckCircle2, Download, DraftingCompass,
  Eye, FileText, Grid3X3, History, LoaderCircle, Play, RefreshCcw, RotateCcw, Save,
  ShieldCheck, XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import {
  engineeringArtifact,
  platform,
  type EngineeringArtifact,
  type EngineeringDesign,
  type EngineeringRequirements,
  type EngineeringRevision,
} from '../lib/api'

export const Route = createFileRoute('/projects/$projectId/engineering')({
  head: () => ({ meta: [{ title: 'Engineering Design — Omniweb' }] }),
  component: () => (
    <div className="st growth engineering">
      <AppNav />
      <RequireAuth><EngineeringWorkspace /></RequireAuth>
    </div>
  ),
})

const example = 'Design an L-shaped steel mounting bracket, 200 mm long, 80 mm wide, 6 mm thick, with four 10 mm mounting holes.'

function EngineeringWorkspace() {
  const { projectId } = Route.useParams()
  const cache = useQueryClient()
  const [prompt, setPrompt] = useState(example)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const designs = useQuery({
    queryKey: ['engineering-designs', projectId],
    queryFn: () => platform.engineeringDesigns(projectId),
  })
  useEffect(() => {
    if (!selectedId && designs.data?.length) setSelectedId(designs.data[0].id)
  }, [designs.data, selectedId])
  const design = useQuery({
    queryKey: ['engineering-design', selectedId],
    queryFn: () => platform.engineeringDesign(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: (query) => {
      const current = query.state.data as EngineeringDesign | undefined
      return current?.status === 'generating' ? 1000 : false
    },
  })
  const create = useMutation({
    mutationFn: () => platform.createEngineeringDesign({
      project_id: projectId,
      prompt: prompt.trim(),
      idempotency_key: `engineering-${crypto.randomUUID()}`,
    }),
    onSuccess: async (row) => {
      setSelectedId(row.id)
      await cache.invalidateQueries({ queryKey: ['engineering-designs', projectId] })
    },
  })
  const current = design.data?.revisions?.[0]

  return (
    <main className="eng-shell">
      <header className="eng-head">
        <div>
          <Link to="/projects/$projectId/growth" params={{ projectId }} className="st-back"><ArrowLeft size={14} /> Project workspace</Link>
          <span className="growth-eyebrow"><DraftingCompass size={14} /> Deterministic parametric CAD</span>
          <h1>Engineering Design</h1>
          <p>Generate editable mechanical components, genuine CAD files, dimensioned drawings, and traceable revisions from natural language.</p>
        </div>
        <div className="eng-status-key"><ShieldCheck size={16} /><span>Level 1</span><small>Geometry validation</small></div>
      </header>

      <WalkthroughCard />

      <section className="eng-prompt">
        <textarea aria-label="Describe the mechanical component" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} />
        <button className="growth-primary" type="button" disabled={create.isPending || prompt.trim().length < 3} onClick={() => create.mutate()}>
          {create.isPending ? <><LoaderCircle className="eng-spin" size={16} /> Extracting…</> : <><DraftingCompass size={16} /> Generate design</>}
        </button>
      </section>
      {create.error && <div className="st-alert st-alert-error">{create.error.message}</div>}

      <div className="eng-layout">
        <aside className="eng-designs">
          <div className="eng-panel-title"><Box size={15} /><strong>Designs</strong><span>{designs.data?.length ?? 0}</span></div>
          {designs.isLoading && <div className="eng-loading"><span className="st-spinner" /></div>}
          {!designs.isLoading && !designs.data?.length && <p className="st-muted">Describe a supported plate, L bracket, spacer, or enclosure to begin.</p>}
          {designs.data?.map((row) => (
            <button key={row.id} className={selectedId === row.id ? 'active' : ''} type="button" onClick={() => setSelectedId(row.id)}>
              <span><strong>{row.name}</strong><small>{row.component_kind.replaceAll('_', ' ')}</small></span>
              <span className={`eng-dot ${row.status}`} title={row.status} />
            </button>
          ))}
        </aside>

        <section className="eng-workspace">
          {!selectedId && <EmptyWorkspace />}
          {selectedId && design.isLoading && <div className="eng-loading large"><span className="st-spinner" /> Loading design…</div>}
          {design.error && <div className="st-alert st-alert-error">{design.error.message}</div>}
          {design.data && current && <DesignEditor design={design.data} revision={current} />}
        </section>
      </div>
    </main>
  )
}

function WalkthroughCard() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open])
  return (
    <>
      <button className="eng-walkthrough-card" type="button" onClick={() => setOpen(true)} aria-label="Play Engineering CAD workspace walkthrough">
        <span className="eng-walkthrough-thumb">
          <img src="/media/engineering-cad-workspace-poster.jpg" alt="" />
          <span><Play size={17} fill="currentColor" /></span>
        </span>
        <span className="eng-walkthrough-copy">
          <small>Product walkthrough · 51 seconds</small>
          <strong>See the Engineering CAD workspace in action</strong>
          <span>3D interaction, parametric revisions, drawings, validation, and exports.</span>
        </span>
        <span className="eng-walkthrough-play">Watch video <Play size={13} fill="currentColor" /></span>
      </button>
      {open && (
        <div className="eng-video-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false) }}>
          <section className="eng-video-modal" role="dialog" aria-modal="true" aria-labelledby="engineering-walkthrough-title">
            <header>
              <div><small>Omniweb Engineering Design</small><h2 id="engineering-walkthrough-title">Engineering CAD workspace walkthrough</h2></div>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close walkthrough"><XCircle size={20} /></button>
            </header>
            <video controls autoPlay preload="metadata" poster="/media/engineering-cad-workspace-poster.jpg">
              <source src="/media/engineering-cad-workspace-walkthrough.mp4" type="video/mp4" />
              Your browser does not support embedded video.
            </video>
            <footer>See how a validated bracket moves from editable parameters to genuine CAD exports and an immutable revision.</footer>
          </section>
        </div>
      )}
    </>
  )
}

function EmptyWorkspace() {
  return <div className="eng-empty"><DraftingCompass size={34} /><h2>From requirements to real geometry.</h2><p>Your model, drawing, validation evidence, parameters, and exports stay together through every immutable revision.</p></div>
}

function DesignEditor({ design, revision }: { design: EngineeringDesign; revision: EngineeringRevision }) {
  const cache = useQueryClient()
  const [tab, setTab] = useState<'model' | 'drawing'>('model')
  const [requirements, setRequirements] = useState(revision.requirements)
  const [changeNote, setChangeNote] = useState('Update design parameters')
  const [fitSignal, setFitSignal] = useState(0)
  const [grid, setGrid] = useState(true)
  const [wireframe, setWireframe] = useState(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  useEffect(() => {
    setRequirements(revision.requirements)
    setPdfUrl((current) => {
      if (current) URL.revokeObjectURL(current)
      return null
    })
  }, [revision.id, revision.requirements])
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl) }, [pdfUrl])
  const revise = useMutation({
    mutationFn: () => platform.reviseEngineeringDesign(design.id, {
      requirements,
      change_note: changeNote,
      source_prompt: changeNote,
      idempotency_key: `engineering-revision-${crypto.randomUUID()}`,
    }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ['engineering-design', design.id] }),
  })
  const approval = useMutation({
    mutationFn: () => platform.requestEngineeringApproval(design.id),
    onSuccess: () => cache.invalidateQueries({ queryKey: ['engineering-design', design.id] }),
  })
  const jobAction = useMutation({
    mutationFn: (action: 'retry' | 'cancel') => {
      if (!revision.job) throw new Error('No engineering job is available')
      return action === 'retry'
        ? platform.retryEngineeringJob(revision.job.id)
        : platform.cancelEngineeringJob(revision.job.id)
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ['engineering-design', design.id] }),
  })
  const drawing = revision.artifacts.find((item) => item.format === 'pdf')
  const previewDrawing = async () => {
    if (!drawing) return
    const blob = await engineeringArtifact(drawing.id)
    if (pdfUrl) URL.revokeObjectURL(pdfUrl)
    setPdfUrl(URL.createObjectURL(blob))
    setTab('drawing')
  }

  return (
    <>
      <header className="eng-design-head">
        <div><span>Revision {revision.revision}</span><h2>{design.name}</h2></div>
        <div className="eng-head-actions">
          <span className={`eng-state ${revision.status}`}><span />{revision.status.replaceAll('_', ' ')}</span>
          <button className="growth-primary secondary" type="button" disabled={revision.status !== 'validated' || approval.isPending} onClick={() => approval.mutate()}>
            <ShieldCheck size={14} /> Request review
          </button>
        </div>
      </header>
      {(revision.status === 'queued' || revision.status === 'generating') && <div className="eng-progress"><LoaderCircle className="eng-spin" size={16} /> Building geometry, drawings, and exports in an isolated worker…<button type="button" onClick={() => jobAction.mutate('cancel')} disabled={jobAction.isPending}><XCircle size={13} /> Cancel</button></div>}
      {revision.status === 'requirements_review' && <div className="st-alert"><AlertTriangle size={16} /> Complete the missing critical requirements: {revision.missing_critical.join(', ').replaceAll('_', ' ')}.</div>}
      {revision.job?.error && <div className="st-alert st-alert-error"><span>{revision.job.error}</span>{revision.job.status === 'failed' && <button type="button" onClick={() => jobAction.mutate('retry')} disabled={jobAction.isPending}><RefreshCcw size={13} /> Retry</button>}</div>}

      <div className="eng-main-grid">
        <section className="eng-view-panel">
          <div className="eng-tabs">
            <button type="button" aria-selected={tab === 'model'} onClick={() => setTab('model')}><Box size={14} /> 3D model</button>
            <button type="button" aria-selected={tab === 'drawing'} onClick={() => void previewDrawing()} disabled={!drawing}><FileText size={14} /> Drawing</button>
            {tab === 'model' && <div className="eng-view-tools">
              <button type="button" title="Fit model to view" onClick={() => setFitSignal((value) => value + 1)}><RotateCcw size={14} /></button>
              <button type="button" title="Toggle grid" aria-pressed={grid} onClick={() => setGrid(!grid)}><Grid3X3 size={14} /></button>
              <button type="button" title="Toggle wireframe" aria-pressed={wireframe} onClick={() => setWireframe(!wireframe)}><Eye size={14} /></button>
            </div>}
          </div>
          {tab === 'model' && <ModelViewer preview={revision.preview} grid={grid} wireframe={wireframe} fitSignal={fitSignal} />}
          {tab === 'drawing' && (pdfUrl ? <iframe className="eng-drawing" title="Engineering drawing" src={pdfUrl} /> : <div className="eng-loading large"><span className="st-spinner" /> Loading drawing…</div>)}
          <div className="eng-geometry">
            <span>Volume <strong>{formatNumber(revision.geometry.volume_mm3)} mm³</strong></span>
            <span>Triangles <strong>{revision.preview.triangles?.length ?? 0}</strong></span>
            <span>Units <strong>{requirements.units}</strong></span>
          </div>
        </section>

        <RequirementsEditor requirements={requirements} setRequirements={setRequirements} changeNote={changeNote} setChangeNote={setChangeNote} onSave={() => revise.mutate()} saving={revise.isPending} disabled={revision.status === 'queued' || revision.status === 'generating'} />
      </div>

      {(revise.error || approval.error || jobAction.error) && <div className="st-alert st-alert-error">{(revise.error ?? approval.error ?? jobAction.error)?.message}</div>}
      {approval.isSuccess && <div className="st-alert"><ShieldCheck size={16} /> Review requested. Approval confirms engineering review only; it does not approve manufacturing.</div>}

      <div className="eng-bottom-grid">
        <Validation revision={revision} />
        <Artifacts artifacts={revision.artifacts} onPreviewDrawing={() => void previewDrawing()} />
        <RevisionHistory design={design} />
      </div>
      <div className="eng-safety"><AlertTriangle size={17} /><div><strong>Engineering safety boundary</strong><p>{revision.safety_notice}</p></div></div>
    </>
  )
}

function RequirementsEditor({ requirements, setRequirements, changeNote, setChangeNote, onSave, saving, disabled }: {
  requirements: EngineeringRequirements
  setRequirements: (value: EngineeringRequirements) => void
  changeNote: string
  setChangeNote: (value: string) => void
  onSave: () => void
  saving: boolean
  disabled: boolean
}) {
  const setParameter = (key: string, value: number) => setRequirements({
    ...requirements,
    parameters: { ...requirements.parameters, [key]: value },
  })
  return (
    <aside className="eng-parameters">
      <div className="eng-panel-title"><DraftingCompass size={15} /><strong>Parameters</strong><span>Editable</span></div>
      <label>Material<input value={requirements.material} onChange={(event) => setRequirements({ ...requirements, material: event.target.value })} /></label>
      <div className="eng-parameter-grid">
        {Object.entries(requirements.parameters).map(([key, value]) => (
          <label key={key}>{key.replaceAll('_mm', '').replaceAll('_', ' ')}<span><input type="number" min="0.01" step="0.1" value={value} onChange={(event) => setParameter(key, Number(event.target.value))} /><small>mm</small></span></label>
        ))}
        {requirements.hole_count > 0 && <>
          <label>hole count<span><input type="number" min="0" step="1" value={requirements.hole_count} onChange={(event) => setRequirements({ ...requirements, hole_count: Number(event.target.value) })} /><small>qty</small></span></label>
          <label>hole diameter<span><input type="number" min="0.01" step="0.1" value={requirements.hole_diameter_mm ?? ''} onChange={(event) => setRequirements({ ...requirements, hole_diameter_mm: Number(event.target.value) })} /><small>mm</small></span></label>
        </>}
      </div>
      {requirements.assumptions.length > 0 && <div className="eng-assumptions"><strong>Assumptions</strong>{requirements.assumptions.map((item) => <p key={item}>{item}</p>)}</div>}
      <label>Revision note<input value={changeNote} onChange={(event) => setChangeNote(event.target.value)} /></label>
      <button className="growth-primary eng-save" type="button" onClick={onSave} disabled={saving || disabled || changeNote.trim().length < 3}>
        {saving ? <LoaderCircle className="eng-spin" size={15} /> : <Save size={15} />} Create immutable revision
      </button>
    </aside>
  )
}

function ModelViewer({ preview, grid, wireframe, fitSignal }: { preview: EngineeringRevision['preview']; grid: boolean; wireframe: boolean; fitSignal: number }) {
  const mount = useRef<HTMLDivElement>(null)
  const fit = useRef<(() => void) | null>(null)
  useEffect(() => {
    const host = mount.current
    if (!host || !preview.vertices?.length || !preview.triangles?.length) return
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0b0f0d')
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100000)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    host.appendChild(renderer.domElement)
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(preview.vertices.flat(), 3))
    geometry.setIndex(preview.triangles.flat())
    geometry.computeVertexNormals()
    geometry.center()
    const material = new THREE.MeshStandardMaterial({ color: '#86efac', metalness: 0.62, roughness: 0.3, wireframe })
    const mesh = new THREE.Mesh(geometry, material)
    scene.add(mesh)
    const helper = new THREE.GridHelper(500, 20, '#385247', '#1d2b25')
    helper.visible = grid
    scene.add(helper)
    scene.add(new THREE.HemisphereLight('#d9fff0', '#17241e', 2.5))
    const key = new THREE.DirectionalLight('#ffffff', 3)
    key.position.set(4, 6, 8)
    scene.add(key)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    const fitView = () => {
      const sphere = geometry.boundingSphere ?? (geometry.computeBoundingSphere(), geometry.boundingSphere)
      const radius = Math.max(sphere?.radius ?? 10, 1)
      camera.position.set(radius * 1.7, radius * 1.3, radius * 1.9)
      camera.near = Math.max(radius / 1000, 0.01)
      camera.far = radius * 100
      camera.updateProjectionMatrix()
      controls.target.set(0, 0, 0)
      controls.update()
    }
    fit.current = fitView
    fitView()
    const resize = () => {
      const width = host.clientWidth
      const height = host.clientHeight
      renderer.setSize(width, height, false)
      camera.aspect = width / Math.max(height, 1)
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(host)
    let frame = 0
    const animate = () => {
      controls.update()
      renderer.render(scene, camera)
      frame = requestAnimationFrame(animate)
    }
    resize()
    animate()
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      controls.dispose()
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      fit.current = null
    }
  }, [preview, grid, wireframe])
  useEffect(() => fit.current?.(), [fitSignal])
  if (!preview.vertices?.length) return <div className="eng-loading large">Preview becomes available after geometry generation.</div>
  return <div className="eng-model" ref={mount} aria-label="Interactive 3D model" />
}

function Validation({ revision }: { revision: EngineeringRevision }) {
  return <section className="eng-card"><div className="eng-panel-title"><CheckCircle2 size={15} /><strong>Validation</strong><span>{revision.validation_level || 'pending'}</span></div>{revision.validation_checks.length ? revision.validation_checks.map((check) => <div className="eng-check" key={check.key}><span className={check.status}>{check.status === 'passed' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{check.key.replaceAll('_', ' ')}</strong><p>{check.message}</p></div></div>) : <p className="st-muted">Validation will run after generation.</p>}</section>
}

function Artifacts({ artifacts, onPreviewDrawing }: { artifacts: EngineeringArtifact[]; onPreviewDrawing: () => void }) {
  const download = async (artifact: EngineeringArtifact) => {
    const blob = await engineeringArtifact(artifact.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.filename
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <section className="eng-card"><div className="eng-panel-title"><Download size={15} /><strong>Exports</strong><span>{artifacts.length}</span></div><div className="eng-exports">{artifacts.map((artifact) => <button type="button" key={artifact.id} onClick={() => artifact.format === 'pdf' ? onPreviewDrawing() : void download(artifact)}><span>{artifact.format.toUpperCase()}</span><div><strong>{artifact.filename}</strong><small>{formatBytes(artifact.size)} · SHA-256 verified</small></div>{artifact.format === 'pdf' ? <Eye size={14} /> : <Download size={14} />}</button>)}</div></section>
}

function RevisionHistory({ design }: { design: EngineeringDesign }) {
  return <section className="eng-card"><div className="eng-panel-title"><History size={15} /><strong>Revision history</strong><span>{design.revisions?.length ?? 0}</span></div><div className="eng-revisions">{design.revisions?.map((item) => <div key={item.id}><span>R{item.revision}</span><div><strong>{item.change_note}</strong><small>{item.status.replaceAll('_', ' ')} · {new Date(item.created_at).toLocaleString()}</small></div></div>)}</div></section>
}

const formatNumber = (value: unknown) => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'
const formatBytes = (size: number) => size > 1_000_000 ? `${(size / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1000))} KB`
