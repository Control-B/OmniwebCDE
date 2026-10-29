import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  AlertTriangle, ArrowLeft, Box, Boxes, Calculator, CheckCircle2, Download,
  DraftingCompass, Eye, Factory, FileText, Gauge, Grid3X3, History, LoaderCircle,
  Play, Plus, RefreshCcw, RotateCcw, Save, ShieldCheck, Trash2, XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import {
  assemblyArtifact,
  engineeringArtifact,
  platform,
  type EngineeringArtifact,
  type EngineeringAssembly,
  type EngineeringDesign,
  type EngineeringRequirements,
  type EngineeringRevision,
  type EngineeringSimulation,
  type ManufacturingEstimate,
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
  const [workspaceMode, setWorkspaceMode] = useState<
    'parts' | 'assemblies' | 'manufacturing' | 'simulations'
  >('parts')
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

      <nav className="eng-capability-nav" aria-label="Engineering capabilities">
        {([
          ['parts', 'Parts', Box],
          ['assemblies', 'Assemblies', Boxes],
          ['manufacturing', 'Manufacturing', Factory],
          ['simulations', 'Simulations', Gauge],
        ] as const).map(([id, label, Icon]) => (
          <button key={id} type="button" aria-current={workspaceMode === id ? 'page' : undefined} onClick={() => setWorkspaceMode(id)}>
            <Icon size={15} />{label}
          </button>
        ))}
      </nav>

      {workspaceMode === 'parts' && <>
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
      </>}
      {workspaceMode === 'assemblies' && (
        <AssembliesWorkspace projectId={projectId} designs={designs.data ?? []} />
      )}
      {workspaceMode === 'manufacturing' && (
        <ManufacturingWorkspace
          designs={designs.data ?? []}
          selectedId={selectedId}
          selectDesign={setSelectedId}
          design={design.data}
          revision={current}
        />
      )}
      {workspaceMode === 'simulations' && (
        <SimulationsWorkspace
          designs={designs.data ?? []}
          selectedId={selectedId}
          selectDesign={setSelectedId}
          design={design.data}
          revision={current}
        />
      )}
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

type AssemblyMemberDraft = {
  designId: string
  quantity: number
  x: number
  y: number
  z: number
  spacingX: number
}

function AssembliesWorkspace({ projectId, designs }: { projectId: string; designs: EngineeringDesign[] }) {
  const cache = useQueryClient()
  const [name, setName] = useState('Bracket mounting assembly')
  const [members, setMembers] = useState<AssemblyMemberDraft[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  useEffect(() => {
    if (!members.length && designs.length) {
      setMembers([
        { designId: designs[0].id, quantity: 1, x: 0, y: 0, z: 0, spacingX: 0 },
        {
          designId: designs[1]?.id ?? designs[0].id,
          quantity: 1,
          x: 0,
          y: 100,
          z: 20,
          spacingX: 0,
        },
      ])
    }
  }, [designs, members.length])
  const assemblies = useQuery({
    queryKey: ['engineering-assemblies', projectId],
    queryFn: () => platform.engineeringAssemblies(projectId),
  })
  useEffect(() => {
    if (!selectedId && assemblies.data?.length) setSelectedId(assemblies.data[0].id)
  }, [assemblies.data, selectedId])
  const assembly = useQuery({
    queryKey: ['engineering-assembly', selectedId],
    queryFn: () => platform.engineeringAssembly(selectedId!),
    enabled: Boolean(selectedId),
  })
  const create = useMutation({
    mutationFn: async () => {
      const detailed = await Promise.all(
        members.map((member) => platform.engineeringDesign(member.designId)),
      )
      return platform.createEngineeringAssembly({
        project_id: projectId,
        name,
        idempotency_key: `assembly-${crypto.randomUUID()}`,
        members: members.map((member, index) => {
          const revision = detailed[index].revisions?.find((item) => item.status === 'validated')
          if (!revision) throw new Error(`${detailed[index].name} needs a validated revision`)
          return {
            revision_id: revision.id,
            quantity: member.quantity,
            translation_mm: [member.x, member.y, member.z],
            rotation_deg: [0, 0, 0],
            instance_spacing_mm: [member.spacingX, 0, 0],
          }
        }),
      })
    },
    onSuccess: async (row) => {
      setSelectedId(row.id)
      await cache.invalidateQueries({ queryKey: ['engineering-assemblies', projectId] })
    },
  })
  const updateMember = (index: number, patch: Partial<AssemblyMemberDraft>) => {
    setMembers((current) => current.map((member, position) => position === index ? { ...member, ...patch } : member))
  }
  const current = assembly.data?.revisions?.[0]

  return (
    <section className="eng-expansion-shell">
      <header className="eng-expansion-head">
        <div><span>Multi-part engineering</span><h2>CAD assemblies</h2><p>Place validated parametric parts into a genuine multi-body STEP assembly with interference screening and a generated bill of materials.</p></div>
        <span className="eng-boundary"><ShieldCheck size={14} /> Geometry-level assembly checks</span>
      </header>
      <div className="eng-expansion-grid">
        <aside className="eng-config-panel">
          <div className="eng-panel-title"><Plus size={15} /><strong>New assembly</strong><span>{members.length} members</span></div>
          <label>Assembly name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <div className="eng-member-list">
            {members.map((member, index) => (
              <article key={`${index}-${member.designId}`}>
                <header><strong>Member {index + 1}</strong>{members.length > 2 && <button type="button" aria-label={`Remove member ${index + 1}`} onClick={() => setMembers((current) => current.filter((_, position) => position !== index))}><Trash2 size={13} /></button>}</header>
                <select aria-label={`Member ${index + 1} design`} value={member.designId} onChange={(event) => updateMember(index, { designId: event.target.value })}>
                  {designs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
                <div className="eng-mini-fields">
                  <label>Qty<input type="number" min="1" max="20" value={member.quantity} onChange={(event) => updateMember(index, { quantity: Number(event.target.value) })} /></label>
                  <label>X<input type="number" value={member.x} onChange={(event) => updateMember(index, { x: Number(event.target.value) })} /></label>
                  <label>Y<input type="number" value={member.y} onChange={(event) => updateMember(index, { y: Number(event.target.value) })} /></label>
                  <label>Z<input type="number" value={member.z} onChange={(event) => updateMember(index, { z: Number(event.target.value) })} /></label>
                  <label>Spacing X<input type="number" value={member.spacingX} onChange={(event) => updateMember(index, { spacingX: Number(event.target.value) })} /></label>
                </div>
              </article>
            ))}
          </div>
          <button className="eng-add-member" type="button" disabled={!designs.length || members.length >= 10} onClick={() => setMembers((current) => [...current, { designId: designs[0].id, quantity: 1, x: 0, y: current.length * 100, z: 0, spacingX: 0 }])}><Plus size={13} /> Add member</button>
          <button className="growth-primary eng-wide-action" type="button" disabled={create.isPending || members.length < 2 || name.trim().length < 2} onClick={() => create.mutate()}>
            {create.isPending ? <LoaderCircle className="eng-spin" size={15} /> : <Boxes size={15} />} Generate assembly
          </button>
          {create.error && <p className="st-error">{create.error.message}</p>}
          <div className="eng-existing-list">
            <strong>Saved assemblies</strong>
            {assemblies.data?.map((item) => <button type="button" key={item.id} className={item.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(item.id)}><span>{item.name}</span><small>R{item.current_revision} · {item.status}</small></button>)}
            {!assemblies.data?.length && <p>No assemblies yet.</p>}
          </div>
        </aside>
        <div className="eng-expansion-results">
          {!current && <div className="eng-empty expansion"><Boxes size={32} /><h2>Build the product, not just the part.</h2><p>Add at least two validated part revisions, set their placement, and generate an assembly.</p></div>}
          {assembly.isLoading && <div className="eng-loading large"><span className="st-spinner" /> Loading assembly…</div>}
          {current && <AssemblyResult assembly={assembly.data!} revision={current} />}
        </div>
      </div>
    </section>
  )
}

function AssemblyResult({ assembly, revision }: { assembly: EngineeringAssembly; revision: NonNullable<EngineeringAssembly['revisions']>[number] }) {
  return (
    <>
      <div className="eng-result-title"><div><span>Assembly revision {revision.revision}</span><h3>{assembly.name}</h3></div><span className={`eng-state ${revision.status}`}><span />{revision.status}</span></div>
      <div className="eng-assembly-view"><ModelViewer preview={revision.preview} grid wireframe={false} fitSignal={0} /></div>
      <div className="eng-result-metrics">
        <div><small>Instances</small><strong>{String(revision.geometry.member_instances ?? '—')}</strong></div>
        <div><small>Unique parts</small><strong>{String(revision.geometry.unique_parts ?? '—')}</strong></div>
        <div><small>Estimated mass</small><strong>{formatNumber(revision.geometry.estimated_mass_kg)} kg</strong></div>
        <div><small>Interferences</small><strong>{Array.isArray(revision.geometry.interferences) ? revision.geometry.interferences.length : 0}</strong></div>
      </div>
      <div className="eng-assembly-lower">
        <section className="eng-card"><div className="eng-panel-title"><Calculator size={15} /><strong>Bill of materials</strong><span>{revision.bill_of_materials.length} items</span></div><div className="eng-bom">{revision.bill_of_materials.map((item) => <div key={item.member_id}><span>{item.part_number}</span><div><strong>{item.name}</strong><small>{item.material} · {item.component_kind.replaceAll('_', ' ')}</small></div><b>×{item.quantity}</b></div>)}</div></section>
        <section className="eng-card"><div className="eng-panel-title"><CheckCircle2 size={15} /><strong>Assembly checks</strong><span>geometry</span></div>{revision.validation_checks.map((check) => <div className="eng-check" key={check.key}><span className={check.status}>{check.status === 'passed' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{check.key.replaceAll('_', ' ')}</strong><p>{check.message}</p></div></div>)}</section>
        <AssemblyArtifacts artifacts={revision.artifacts} />
      </div>
      <div className="eng-safety"><AlertTriangle size={17} /><div><strong>Assembly validation boundary</strong><p>{revision.safety_notice}</p></div></div>
    </>
  )
}

function AssemblyArtifacts({ artifacts }: { artifacts: EngineeringArtifact[] }) {
  const download = async (artifact: EngineeringArtifact) => {
    const blob = await assemblyArtifact(artifact.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.filename
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <section className="eng-card"><div className="eng-panel-title"><Download size={15} /><strong>Assembly exports</strong><span>{artifacts.length}</span></div><div className="eng-exports">{artifacts.map((artifact) => <button type="button" key={artifact.id} onClick={() => void download(artifact)}><span>{artifact.format.toUpperCase()}</span><div><strong>{artifact.filename}</strong><small>{artifact.kind.replaceAll('_', ' ')} · {formatBytes(artifact.size)}</small></div><Download size={14} /></button>)}</div></section>
}

function DesignSelector({ designs, selectedId, selectDesign }: { designs: EngineeringDesign[]; selectedId: string | null; selectDesign: (id: string) => void }) {
  return <label className="eng-design-selector">Part<select value={selectedId ?? ''} onChange={(event) => selectDesign(event.target.value)}>{designs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
}

function ManufacturingWorkspace({ designs, selectedId, selectDesign, design, revision }: {
  designs: EngineeringDesign[]
  selectedId: string | null
  selectDesign: (id: string) => void
  design?: EngineeringDesign
  revision?: EngineeringRevision
}) {
  const cache = useQueryClient()
  const [process, setProcess] = useState<'sheet_metal' | 'cnc_milling' | 'laser_cut' | 'fdm_print'>('sheet_metal')
  const [quantity, setQuantity] = useState(25)
  const [materialRate, setMaterialRate] = useState(2.4)
  const [machineRate, setMachineRate] = useState(95)
  const [laborRate, setLaborRate] = useState(65)
  const estimates = useQuery({
    queryKey: ['manufacturing-estimates', selectedId],
    queryFn: () => platform.manufacturingEstimates(selectedId!),
    enabled: Boolean(selectedId),
  })
  const create = useMutation({
    mutationFn: () => {
      if (!selectedId || !revision) throw new Error('Select a validated part revision')
      return platform.createManufacturingEstimate(selectedId, {
        revision_id: revision.id,
        process,
        quantity,
        material_cost_per_kg: materialRate,
        machine_rate_per_hour: machineRate,
        labor_rate_per_hour: laborRate,
        overhead_percent: 18,
      })
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ['manufacturing-estimates', selectedId] }),
  })
  const result = create.data ?? estimates.data?.[0]
  return (
    <section className="eng-expansion-shell">
      <header className="eng-expansion-head"><div><span>Cost and process planning</span><h2>Manufacturing estimates</h2><p>Build a transparent budgetary estimate from validated geometry, material mass, process throughput, setup time, and editable shop rates.</p></div><DesignSelector designs={designs} selectedId={selectedId} selectDesign={selectDesign} /></header>
      <div className="eng-analysis-grid">
        <aside className="eng-config-panel">
          <div className="eng-panel-title"><Factory size={15} /><strong>Estimate inputs</strong><span>USD</span></div>
          <label>Process<select value={process} onChange={(event) => setProcess(event.target.value as typeof process)}><option value="sheet_metal">Sheet metal</option><option value="cnc_milling">CNC milling</option><option value="laser_cut">Laser cutting</option><option value="fdm_print">FDM printing</option></select></label>
          <label>Quantity<input type="number" min="1" value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></label>
          <label>Material cost / kg<input type="number" min="0.01" step="0.1" value={materialRate} onChange={(event) => setMaterialRate(Number(event.target.value))} /></label>
          <label>Machine rate / hour<input type="number" min="0.01" step="1" value={machineRate} onChange={(event) => setMachineRate(Number(event.target.value))} /></label>
          <label>Labor rate / hour<input type="number" min="0.01" step="1" value={laborRate} onChange={(event) => setLaborRate(Number(event.target.value))} /></label>
          <button className="growth-primary eng-wide-action" type="button" disabled={!revision || revision.status !== 'validated' || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <LoaderCircle className="eng-spin" size={15} /> : <Calculator size={15} />} Calculate estimate</button>
          {create.error && <p className="st-error">{create.error.message}</p>}
          <p className="st-fine">Using {design?.name ?? 'selected part'} · revision {revision?.revision ?? '—'}</p>
        </aside>
        <div className="eng-expansion-results">
          {!result ? <div className="eng-empty expansion"><Factory size={32} /><h2>Know the cost drivers.</h2><p>Select a process and enter your local material, machine, and labor rates.</p></div> : <ManufacturingResult result={result} />}
        </div>
      </div>
    </section>
  )
}

function ManufacturingResult({ result }: { result: ManufacturingEstimate }) {
  return <><div className="eng-result-title"><div><span>{result.process.replaceAll('_', ' ')} · {result.confidence} confidence</span><h3>Budgetary manufacturing estimate</h3></div><span className="eng-estimate-total">${result.total_cost.toFixed(2)}</span></div><div className="eng-result-metrics"><div><small>Unit cost</small><strong>${result.unit_cost.toFixed(2)}</strong></div><div><small>Quantity</small><strong>{result.quantity}</strong></div><div><small>Mass each</small><strong>{result.mass_kg_each.toFixed(3)} kg</strong></div><div><small>Run time each</small><strong>{result.run_minutes_each.toFixed(1)} min</strong></div></div><div className="eng-cost-layout"><section className="eng-card"><div className="eng-panel-title"><Calculator size={15} /><strong>Cost breakdown</strong><span>order</span></div>{Object.entries(result.breakdown).map(([key, value]) => <div className="eng-cost-row" key={key}><span>{key}</span><strong>${value.toFixed(2)}</strong></div>)}</section><section className="eng-card"><div className="eng-panel-title"><AlertTriangle size={15} /><strong>Assumptions</strong><span>{result.assumptions.length}</span></div><ul className="eng-assumption-list">{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></section></div><div className="eng-safety"><AlertTriangle size={17} /><div><strong>Estimate boundary</strong><p>{result.notice}</p></div></div></>
}

function SimulationsWorkspace({ designs, selectedId, selectDesign, design, revision }: {
  designs: EngineeringDesign[]
  selectedId: string | null
  selectDesign: (id: string) => void
  design?: EngineeringDesign
  revision?: EngineeringRevision
}) {
  const cache = useQueryClient()
  const [type, setType] = useState<'static_screening' | 'thermal_expansion' | 'modal_screening'>('static_screening')
  const [load, setLoad] = useState(250)
  const [span, setSpan] = useState(200)
  const [temperature, setTemperature] = useState(60)
  const simulations = useQuery({
    queryKey: ['engineering-simulations', selectedId],
    queryFn: () => platform.engineeringSimulations(selectedId!),
    enabled: Boolean(selectedId),
  })
  const create = useMutation({
    mutationFn: () => {
      if (!selectedId || !revision) throw new Error('Select a validated part revision')
      return platform.createEngineeringSimulation(selectedId, {
        revision_id: revision.id,
        simulation_type: type,
        boundary_condition: 'cantilever_fixed',
        span_mm: span,
        ...(type === 'static_screening' ? { load_n: load } : {}),
        ...(type === 'thermal_expansion' ? { delta_temperature_c: temperature } : {}),
      })
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ['engineering-simulations', selectedId] }),
  })
  const result = create.data ?? simulations.data?.[0]
  return (
    <section className="eng-expansion-shell">
      <header className="eng-expansion-head"><div><span>Deterministic engineering screening</span><h2>Simulations</h2><p>Compare static deflection, thermal expansion, and first-mode response using explicit idealized methods and visible assumptions.</p></div><DesignSelector designs={designs} selectedId={selectedId} selectDesign={selectDesign} /></header>
      <div className="eng-analysis-grid">
        <aside className="eng-config-panel">
          <div className="eng-panel-title"><Gauge size={15} /><strong>Load case</strong><span>cantilever</span></div>
          <label>Simulation<select value={type} onChange={(event) => setType(event.target.value as typeof type)}><option value="static_screening">Static deflection</option><option value="thermal_expansion">Thermal expansion</option><option value="modal_screening">First natural frequency</option></select></label>
          <label>Effective span (mm)<input type="number" min="0.1" value={span} onChange={(event) => setSpan(Number(event.target.value))} /></label>
          {type === 'static_screening' && <label>End load (N)<input type="number" min="0.1" value={load} onChange={(event) => setLoad(Number(event.target.value))} /></label>}
          {type === 'thermal_expansion' && <label>Temperature change (°C)<input type="number" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label>}
          <div className="eng-boundary-box"><strong>Fixed boundary</strong><p>Uniform rectangular cantilever idealization. Real joints, contacts, holes, and local effects are omitted.</p></div>
          <button className="growth-primary eng-wide-action" type="button" disabled={!revision || revision.status !== 'validated' || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <LoaderCircle className="eng-spin" size={15} /> : <Gauge size={15} />} Run screening</button>
          {create.error && <p className="st-error">{create.error.message}</p>}
          <p className="st-fine">Using {design?.name ?? 'selected part'} · revision {revision?.revision ?? '—'}</p>
        </aside>
        <div className="eng-expansion-results">
          {!result ? <div className="eng-empty expansion"><Gauge size={32} /><h2>Test an explicit load case.</h2><p>Choose a screening method and enter the known load, span, or temperature change.</p></div> : <SimulationResult result={result} />}
        </div>
      </div>
    </section>
  )
}

function SimulationResult({ result }: { result: EngineeringSimulation }) {
  return <><div className="eng-result-title"><div><span>{result.simulation_type.replaceAll('_', ' ')}</span><h3>Screening results</h3><p>{result.method}</p></div><span className="eng-screening-badge">Screening only</span></div><div className="eng-simulation-results">{Object.entries(result.results).map(([key, value]) => <article key={key}><small>{key.replaceAll('_', ' ')}</small><strong>{value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 5 })}</strong></article>)}</div><div className="eng-cost-layout"><section className="eng-card"><div className="eng-panel-title"><Calculator size={15} /><strong>Model inputs</strong><span>explicit</span></div>{Object.entries(result.inputs).map(([key, value]) => <div className="eng-cost-row" key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{String(value)}</strong></div>)}</section><section className="eng-card"><div className="eng-panel-title"><CheckCircle2 size={15} /><strong>Verification required</strong><span>{result.verification_required.length}</span></div><ol className="eng-assumption-list">{result.verification_required.map((item) => <li key={item}>{item}</li>)}</ol></section></div><section className="eng-card eng-model-assumptions"><div className="eng-panel-title"><AlertTriangle size={15} /><strong>Model assumptions</strong><span>{result.assumptions.length}</span></div><ul className="eng-assumption-list">{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></section><div className="eng-safety"><AlertTriangle size={17} /><div><strong>Simulation boundary</strong><p>{result.safety_notice}</p></div></div></>
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
