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
    kind: Literal["cad_model", "mesh", "drawing", "dxf", "source"]
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
