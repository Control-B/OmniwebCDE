# Engineering Design Agent

## Repository findings and integration decision

Omniweb already uses a TanStack Start frontend, FastAPI control plane, SQLAlchemy with Alembic
metadata, PostgreSQL, a content-addressed artifact store, LangGraph orchestration, the
Adaptive AI Execution Engine (AAEE), project-scoped authorization, approvals, audit
events, and a bidirectional capability-evolution graph. The engineering capability
extends those systems; it does not introduce separate accounts, projects, model routing,
or approval infrastructure.

CAD is isolated in `services/engineering`. The control plane owns tenant-scoped design
metadata, immutable revisions, jobs, approvals, feedback, and artifact access. The CAD
service accepts only a validated declarative model and runs deterministic
CadQuery/OpenCascade operations. It never evaluates free-form Python supplied by a user
or model.

```text
Unified Create / Engineering workspace
        │ authenticated, project-scoped
        ▼
FastAPI control plane ── LangGraph supervisor ── AAEE documentation review
        │
        ├── PostgreSQL: requirements, revisions, jobs, approvals, audit
        ├── AssetStore: content-addressed STEP/STL/PDF/DXF/JSON
        └── isolated internal network
                ▼
        Engineering CAD service
        CadQuery/OCC + ReportLab + ezdxf
```

## Supported MVP

The deterministic engine supports rectangular plates, equal-leg L brackets, cylindrical
spacers, and open-top enclosures. Its declarative operations cover boxes, cylinders,
unions, cuts, holes, fillets, and chamfers. A generation produces:

- a genuine ISO-10303 STEP solid;
- STL mesh and browser tessellation;
- dimensioned vector PDF drawing;
- DXF where requested;
- versioned native parametric JSON;
- geometry measurements and Level 1 validation evidence.

The browser workspace at `/projects/<project-id>/engineering` includes requirements,
controlled parameter editing, assumptions, orbit/pan/zoom/fit, grid and wireframe
controls, drawing preview, immutable history, validation checks, exports, and a review
request. Natural-language edits are represented as new revisions; approved revisions are
never overwritten.

The same workspace now includes three additional governed capabilities:

- **Assemblies** place validated part revisions with explicit translations, rotations,
  quantities, and instance spacing. CadQuery/OpenCascade exports a genuine multi-body
  STEP and STL, plus a versioned assembly source, bill of materials, mass estimate,
  combined preview, and volumetric interference screen.
- **Manufacturing estimates** use validated volume, material density, process throughput,
  setup time, quantity, and user-editable material/machine/labor rates. Every cost
  component and assumption remains visible. Results are budgetary estimates, never
  supplier quotes or feasibility determinations.
- **Simulations** provide deterministic static cantilever, free thermal expansion, and
  first-mode cantilever screening. Inputs, nominal material properties, method,
  assumptions, and required professional verification are stored with each result.
  These closed-form screens are deliberately not described as finite-element analysis.

## Contracts and traceability

`EngineeringDesign` belongs to an existing organization and project. Every
`DesignRevision` has one normalized `DesignRequirement`, a source prompt, assumptions,
operations, preview, validation evidence, and zero or more artifacts. `EngineeringJob`
records attempts, duration, failures, cancellation, and dead-letter state.
`EngineeringFeedback` requires explicit authorization and creates only a
`proposes_revision_to` capability edge. It cannot release a modification.

The public API is under `/api/v1/engineering`:

- `POST /designs`, `GET /designs`, `GET /designs/{id}`
- `POST /designs/{id}/revisions`
- `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel`
- `POST /designs/{id}/approval-request`, `POST /approvals/{id}`
- `POST /designs/{id}/feedback`
- `POST /assemblies`, `GET /assemblies`, `GET /assemblies/{id}`
- authenticated assembly STEP/STL/source/BOM artifact access
- `POST` and `GET /designs/{id}/manufacturing-estimates`
- `POST` and `GET /designs/{id}/simulations`
- authenticated and ten-minute signed artifact access
- tenant-scoped operational metrics

All IDs are checked against both organization and project membership. Artifact bytes are
size- and SHA-256-verified before storage and again on authenticated download.

## Validation levels and safety boundary

Level 1 is automated and required. It verifies OpenCascade BREP validity, positive
volume, finite bounds, dimensional input constraints, feature construction, export
integrity, and drawing provenance from the generated geometry.

Level 2 calculations are not presented unless a reviewed deterministic method and all
required assumptions are available. Static, thermal, and modal screens are Level 2
comparative calculations with explicit idealizations; they do not establish safety.
Level 3 structural, safety, regulatory, and code-compliance validation is not implemented.

> Geometry validation is not structural analysis, code compliance, engineering
> certification, or approval for manufacturing.

An engineering review approval records a human decision but deliberately does not change
the status to approved-for-manufacturing.

## Isolation, reliability, and operations

The Compose engineering worker runs as UID 10001 with a read-only root filesystem,
capabilities dropped, `no-new-privileges`, a no-exec temporary filesystem, PID/CPU/memory
limits, bounded concurrency, and generation timeouts. It is attached only to an internal
network shared with the control plane, so it has no external network route. The service
does not receive database, model-provider, or object-storage credentials.

Jobs are idempotent per tenant. Active jobs can be cancelled. Failed jobs can be retried
up to `OMNIWEB_ENGINEERING_MAX_JOB_ATTEMPTS` (default 3), then require operator review.
Startup resumes interrupted queued/running work. CAD generation and duration metrics are
exported by the isolated service; the control plane reports tenant-scoped status counts,
average duration, and its explicit validation limitation.

Temporary files are process-local and cleaned by the generators. Production object
storage can replace `AssetStore` behind the existing adapter; large binaries are not kept
in PostgreSQL.

## Model routing and cost

Requirement extraction and geometry math are deterministic. The Engineering Supervisor
can send documentation-completeness work to AAEE using the existing token budgets,
fallback limits, cancellation, tenant budgets, and usage ledger. An LLM may propose a
declarative plan, but it cannot execute code, certify geometry, or substitute for
engineering review.

The Onshape adapter is explicitly unavailable by default. Its capability contract is in
`engineering/integrations/onshape.py`; documented OAuth, tenant authorization, export
policy, and integration tests are required before any action can be advertised.

## Running locally

```bash
python3 -m pip install -e 'services/engineering[dev]'
python3 -m uvicorn engineering.main:app --app-dir services/engineering --port 8040
python3 -m uvicorn app.main:app --app-dir backend --port 8010
(cd frontend && npm install && npm run dev)
```

Or run the full stack with `docker compose up --build`. The backend uses
`OMNIWEB_ENGINEERING_SERVICE_URL` (default `http://127.0.0.1:8040` outside Compose).

## Verified scope and remaining limits

Automated fixtures cover all four supported component classes, normalized units, genuine
STEP round-trips through OpenCascade, STL/PDF/DXF export, immutable dimensional changes,
approval boundaries, signed downloads, tenant isolation, authorized feedback, and failed
job recovery.

FreeCAD TechDraw, GD&T rule verification, constraint-solving mates, joint/fastener
analysis, finite-element analysis, manufacturing feasibility simulation, supplier
quoting, native Onshape synchronization, and automatic approved-for-manufacturing release
are not implemented and must not be claimed.
