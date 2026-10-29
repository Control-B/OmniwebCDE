import asyncio
import time

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from .analysis import estimate_manufacturing, run_simulation
from .assembly import generate_assembly
from .cad import generate
from .requirements import ExtractionResult, extract_requirements
from .schemas import (
    AssemblyGenerateRequest,
    AssemblyGenerateResponse,
    GenerateRequest,
    GenerateResponse,
    ManufacturingEstimateRequest,
    ManufacturingEstimateResponse,
    SimulationRequest,
    SimulationResponse,
)

app = FastAPI(
    title="Omniweb Engineering Design Service",
    version="0.1.0",
    description="Deterministic, isolated parametric CAD generation and geometry validation.",
)
CONCURRENCY = asyncio.Semaphore(2)
GENERATIONS = Counter(
    "omniweb_engineering_generations_total",
    "CAD generation outcomes",
    ["component", "status"],
)
DURATION = Histogram(
    "omniweb_engineering_generation_duration_seconds",
    "CAD generation duration",
    ["component"],
)


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/requirements/extract", response_model=ExtractionResult)
async def requirements(prompt: str) -> ExtractionResult:
    try:
        return extract_requirements(prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/generate", response_model=GenerateResponse)
async def generate_design(request: GenerateRequest) -> GenerateResponse:
    started = time.monotonic()
    component = request.requirements.component_kind.value
    try:
        async with asyncio.timeout(90):
            async with CONCURRENCY:
                result = await asyncio.to_thread(generate, request)
        GENERATIONS.labels(component, result.status).inc()
        return result
    except TimeoutError as exc:
        GENERATIONS.labels(component, "timeout").inc()
        raise HTTPException(
            status_code=504, detail="CAD generation exceeded its time limit"
        ) from exc
    except ValueError as exc:
        GENERATIONS.labels(component, "invalid").inc()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        GENERATIONS.labels(component, "failed").inc()
        raise HTTPException(status_code=500, detail="CAD generation failed safely") from exc
    finally:
        DURATION.labels(component).observe(time.monotonic() - started)


@app.post("/v1/assemblies/generate", response_model=AssemblyGenerateResponse)
async def generate_assembly_design(
    request: AssemblyGenerateRequest,
) -> AssemblyGenerateResponse:
    try:
        async with asyncio.timeout(90):
            async with CONCURRENCY:
                return await asyncio.to_thread(generate_assembly, request)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504, detail="Assembly generation exceeded its time limit"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Assembly generation failed safely") from exc


@app.post("/v1/manufacturing/estimate", response_model=ManufacturingEstimateResponse)
async def manufacturing_estimate(
    request: ManufacturingEstimateRequest,
) -> ManufacturingEstimateResponse:
    try:
        return estimate_manufacturing(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/simulations/run", response_model=SimulationResponse)
async def simulation(request: SimulationRequest) -> SimulationResponse:
    try:
        return run_simulation(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
