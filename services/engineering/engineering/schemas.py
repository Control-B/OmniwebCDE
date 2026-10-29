from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ComponentKind(StrEnum):
    PLATE = "plate"
    L_BRACKET = "l_bracket"
    SPACER = "spacer"
    ENCLOSURE = "enclosure"


class CADOperation(BaseModel):
    operation: Literal["box", "cylinder", "union", "cut", "hole", "fillet", "chamfer"]
    parameters: dict[str, float | str | list[float]]


class DesignRequirements(BaseModel):
    component_name: str = Field(min_length=2, max_length=160)
    component_kind: ComponentKind
    units: Literal["mm"] = "mm"
    material: str = Field(min_length=2, max_length=120)
    manufacturing_process: str | None = Field(default=None, max_length=160)
    parameters: dict[str, float] = Field(default_factory=dict)
    hole_count: int = Field(default=0, ge=0, le=100)
    hole_diameter_mm: float | None = Field(default=None, gt=0, le=1_000)
    tolerances: dict[str, float] = Field(default_factory=dict)
    requested_outputs: list[Literal["step", "stl", "pdf", "dxf", "source"]] = Field(
        default_factory=lambda: ["step", "stl", "pdf", "source"]
    )
    standards: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def dimensions_are_positive(self):
        if any(value <= 0 or value > 100_000 for value in self.parameters.values()):
            raise ValueError("Dimensions must be positive and no greater than 100,000 mm")
        return self


class GenerateRequest(BaseModel):
    design_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1, le=10_000)
    requirements: DesignRequirements
    max_triangles: int = Field(default=30_000, ge=1_000, le=100_000)


class ArtifactPayload(BaseModel):
    kind: Literal[
        "cad_model",
        "mesh",
        "drawing",
        "dxf",
        "source",
        "assembly_model",
        "bill_of_materials",
    ]
    format: Literal["step", "stl", "pdf", "dxf", "json"]
    filename: str
    media_type: str
    data_base64: str
    sha256: str
    size: int


class ValidationCheck(BaseModel):
    key: str
    status: Literal["passed", "failed", "warning", "not_evaluated"]
    message: str
    measured: float | str | bool | None = None


class GenerateResponse(BaseModel):
    status: Literal["validated", "invalid"]
    validation_level: Literal["geometry"] = "geometry"
    operations: list[CADOperation]
    normalized_requirements: DesignRequirements
    geometry: dict
    preview: dict
    checks: list[ValidationCheck]
    artifacts: list[ArtifactPayload]
    safety_notice: str = (
        "Geometry validation is not structural analysis, code compliance, engineering "
        "certification, or approval for manufacturing."
    )


class AssemblyMember(BaseModel):
    member_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    name: str = Field(min_length=2, max_length=160)
    requirements: DesignRequirements
    quantity: int = Field(default=1, ge=1, le=20)
    translation_mm: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )
    rotation_deg: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )
    instance_spacing_mm: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )


class AssemblyGenerateRequest(BaseModel):
    assembly_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1, le=10_000)
    name: str = Field(min_length=2, max_length=160)
    members: list[AssemblyMember] = Field(min_length=2, max_length=50)
    max_triangles: int = Field(default=60_000, ge=1_000, le=150_000)

    @model_validator(mode="after")
    def assembly_size_is_bounded(self):
        if sum(member.quantity for member in self.members) > 50:
            raise ValueError("An assembly is limited to 50 placed component instances")
        return self


class AssemblyGenerateResponse(BaseModel):
    status: Literal["validated", "invalid"]
    validation_level: Literal["assembly_geometry"] = "assembly_geometry"
    geometry: dict
    preview: dict
    checks: list[ValidationCheck]
    bill_of_materials: list[dict]
    artifacts: list[ArtifactPayload]
    safety_notice: str = (
        "Assembly geometry validation checks placement, solids, and exports only. It does "
        "not verify joints, fasteners, fit tolerances, loads, safety, or manufacturability."
    )


class ManufacturingEstimateRequest(BaseModel):
    requirements: DesignRequirements
    geometry: dict
    process: Literal["sheet_metal", "cnc_milling", "laser_cut", "fdm_print"]
    quantity: int = Field(default=1, ge=1, le=100_000)
    material_cost_per_kg: float = Field(gt=0, le=100_000)
    machine_rate_per_hour: float = Field(gt=0, le=100_000)
    labor_rate_per_hour: float = Field(gt=0, le=100_000)
    overhead_percent: float = Field(default=15, ge=0, le=200)


class ManufacturingEstimateResponse(BaseModel):
    status: Literal["budgetary_estimate"] = "budgetary_estimate"
    process: str
    quantity: int
    currency: Literal["USD"] = "USD"
    mass_kg_each: float
    setup_minutes: float
    run_minutes_each: float
    breakdown: dict[str, float]
    unit_cost: float
    total_cost: float
    assumptions: list[str]
    confidence: Literal["low", "medium"]
    notice: str = (
        "This is an assumption-based budgetary estimate, not a supplier quote or a "
        "manufacturing feasibility determination."
    )


class SimulationRequest(BaseModel):
    requirements: DesignRequirements
    geometry: dict
    simulation_type: Literal["static_screening", "thermal_expansion", "modal_screening"]
    load_n: float | None = Field(default=None, gt=0, le=100_000_000)
    span_mm: float | None = Field(default=None, gt=0, le=100_000)
    delta_temperature_c: float | None = Field(default=None, ge=-1_000, le=10_000)
    boundary_condition: Literal["cantilever_fixed"] = "cantilever_fixed"


class SimulationResponse(BaseModel):
    status: Literal["screening_complete"] = "screening_complete"
    simulation_type: str
    method: str
    inputs: dict
    material_properties: dict
    results: dict
    checks: list[ValidationCheck]
    assumptions: list[str]
    verification_required: list[str]
    safety_notice: str = (
        "This deterministic screening calculation is not finite-element analysis, "
        "structural certification, code compliance, or approval for manufacturing."
    )
