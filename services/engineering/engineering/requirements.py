import re

from pydantic import BaseModel, Field

from .cad import required_parameters
from .schemas import ComponentKind, DesignRequirements

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "eight": 8,
}
UNIT_FACTORS = {"mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "cm": 10.0, "in": 25.4, "inch": 25.4, "inches": 25.4}


class ExtractionResult(BaseModel):
    requirements: DesignRequirements | None = None
    component_kind: ComponentKind
    extracted: dict
    missing_critical: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    complete: bool = False


def _dimension(prompt: str, labels: list[str]) -> float | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    patterns = [
        rf"(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|inches?|in)\s*(?:{alternatives})\b",
        rf"(?:{alternatives})\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|inches?|in)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt, re.I)
        if match:
            return round(float(match.group(1)) * UNIT_FACTORS[match.group(2).lower()], 6)
    return None


def _component_kind(prompt: str) -> ComponentKind:
    low = prompt.lower()
    if re.search(r"\b(l[- ]?shaped?|angle)\s+(?:mounting\s+)?bracket\b", low):
        return ComponentKind.L_BRACKET
    if re.search(r"\b(spacer|bushing|sleeve)\b", low):
        return ComponentKind.SPACER
    if re.search(r"\b(enclosure|housing|case)\b", low):
        return ComponentKind.ENCLOSURE
    return ComponentKind.PLATE


def extract_requirements(prompt: str) -> ExtractionResult:
    if len(prompt) < 3 or len(prompt) > 20_000:
        raise ValueError("Engineering prompt must be 3–20,000 characters")
    kind = _component_kind(prompt)
    low = prompt.lower()
    assumptions: list[str] = []
    material_match = re.search(
        r"\b(steel|stainless steel|aluminum|aluminium|brass|copper|abs|polycarbonate|nylon)\b",
        low,
    )
    material = material_match.group(1).title() if material_match else None
    parameters: dict[str, float] = {}

    length = _dimension(prompt, ["long", "length"])
    width = _dimension(prompt, ["wide", "width"])
    height = _dimension(prompt, ["high", "height", "tall"])
    thickness = _dimension(prompt, ["thick", "thickness"])
    wall = _dimension(prompt, ["wall", "wall thickness"])
    outer = _dimension(prompt, ["outer diameter", "outside diameter", "od"])
    inner = _dimension(prompt, ["inner diameter", "inside diameter", "id", "bore"])

    if kind in {ComponentKind.PLATE, ComponentKind.L_BRACKET, ComponentKind.ENCLOSURE}:
        for key, value in (
            ("length_mm", length),
            ("width_mm", width),
            ("height_mm", height),
            ("thickness_mm", thickness),
            ("wall_thickness_mm", wall or thickness),
        ):
            if value is not None:
                parameters[key] = value
    if kind == ComponentKind.L_BRACKET and height is None and width is not None:
        parameters["height_mm"] = width
        assumptions.append(
            "Equal-leg L bracket assumed: vertical height equals the stated bracket width."
        )
    if kind == ComponentKind.SPACER:
        if outer is not None:
            parameters["outer_diameter_mm"] = outer
        if inner is not None:
            parameters["inner_diameter_mm"] = inner
        if length is not None:
            parameters["length_mm"] = length

    hole_match = re.search(
        r"\b(one|two|three|four|five|six|eight|\d+)\s+"
        r"(?:(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|inches?|in)\s+)?"
        r"(?:mounting\s+)?holes?\b",
        low,
    )
    hole_count = 0
    hole_diameter = None
    if hole_match:
        hole_count = (
            NUMBER_WORDS.get(hole_match.group(1), 0)
            if not hole_match.group(1).isdigit()
            else int(hole_match.group(1))
        )
        if hole_match.group(2):
            hole_diameter = round(
                float(hole_match.group(2)) * UNIT_FACTORS[hole_match.group(3).lower()], 6
            )
    if hole_count and hole_diameter is None:
        hole_diameter = _dimension(prompt, ["hole diameter", "diameter holes"])

    fillet = _dimension(prompt, ["fillet", "fillet radius"])
    if fillet is not None:
        parameters["fillet_radius_mm"] = fillet

    missing = sorted(required_parameters(kind) - parameters.keys())
    if material is None:
        missing.append("material")
    if hole_count and hole_diameter is None:
        missing.append("hole_diameter_mm")
    questions = [f"Provide {name.replace('_mm', '').replace('_', ' ')}." for name in missing]
    extracted = {
        "component_name": {
            ComponentKind.PLATE: "Mounting plate",
            ComponentKind.L_BRACKET: "L-shaped mounting bracket",
            ComponentKind.SPACER: "Cylindrical spacer",
            ComponentKind.ENCLOSURE: "Enclosure",
        }[kind],
        "component_kind": kind.value,
        "units": "mm",
        "material": material,
        "parameters": parameters,
        "hole_count": hole_count,
        "hole_diameter_mm": hole_diameter,
        "requested_outputs": ["step", "stl", "pdf", "dxf", "source"],
        "assumptions": assumptions,
    }
    requirements = DesignRequirements(**extracted) if not missing else None
    return ExtractionResult(
        requirements=requirements,
        component_kind=kind,
        extracted=extracted,
        missing_critical=missing,
        questions=questions,
        assumptions=assumptions,
        complete=not missing,
    )
