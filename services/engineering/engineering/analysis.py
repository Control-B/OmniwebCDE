import math

from .schemas import (
    ManufacturingEstimateRequest,
    ManufacturingEstimateResponse,
    SimulationRequest,
    SimulationResponse,
    ValidationCheck,
)

MATERIALS = {
    "steel": {
        "density_kg_per_mm3": 7.85e-6,
        "elastic_modulus_mpa": 200_000.0,
        "yield_strength_mpa": 250.0,
        "thermal_expansion_per_c": 12.0e-6,
    },
    "stainless steel": {
        "density_kg_per_mm3": 8.0e-6,
        "elastic_modulus_mpa": 193_000.0,
        "yield_strength_mpa": 205.0,
        "thermal_expansion_per_c": 17.3e-6,
    },
    "aluminum": {
        "density_kg_per_mm3": 2.70e-6,
        "elastic_modulus_mpa": 69_000.0,
        "yield_strength_mpa": 145.0,
        "thermal_expansion_per_c": 23.1e-6,
    },
    "aluminium": {
        "density_kg_per_mm3": 2.70e-6,
        "elastic_modulus_mpa": 69_000.0,
        "yield_strength_mpa": 145.0,
        "thermal_expansion_per_c": 23.1e-6,
    },
    "brass": {
        "density_kg_per_mm3": 8.50e-6,
        "elastic_modulus_mpa": 100_000.0,
        "yield_strength_mpa": 120.0,
        "thermal_expansion_per_c": 19.0e-6,
    },
    "copper": {
        "density_kg_per_mm3": 8.96e-6,
        "elastic_modulus_mpa": 117_000.0,
        "yield_strength_mpa": 70.0,
        "thermal_expansion_per_c": 16.5e-6,
    },
    "abs": {
        "density_kg_per_mm3": 1.04e-6,
        "elastic_modulus_mpa": 2_100.0,
        "yield_strength_mpa": 40.0,
        "thermal_expansion_per_c": 90.0e-6,
    },
    "polycarbonate": {
        "density_kg_per_mm3": 1.20e-6,
        "elastic_modulus_mpa": 2_300.0,
        "yield_strength_mpa": 62.0,
        "thermal_expansion_per_c": 65.0e-6,
    },
    "nylon": {
        "density_kg_per_mm3": 1.15e-6,
        "elastic_modulus_mpa": 2_500.0,
        "yield_strength_mpa": 45.0,
        "thermal_expansion_per_c": 80.0e-6,
    },
}

PROCESS_ASSUMPTIONS = {
    "sheet_metal": {
        "setup_minutes": 35.0,
        "throughput_mm3_per_minute": 5_000.0,
        "waste_factor": 1.18,
        "labor_fraction": 0.45,
    },
    "cnc_milling": {
        "setup_minutes": 50.0,
        "throughput_mm3_per_minute": 1_500.0,
        "waste_factor": 1.65,
        "labor_fraction": 0.35,
    },
    "laser_cut": {
        "setup_minutes": 20.0,
        "throughput_mm3_per_minute": 8_000.0,
        "waste_factor": 1.12,
        "labor_fraction": 0.25,
    },
    "fdm_print": {
        "setup_minutes": 12.0,
        "throughput_mm3_per_minute": 240.0,
        "waste_factor": 1.08,
        "labor_fraction": 0.08,
    },
}


def _material(name: str) -> dict[str, float]:
    properties = MATERIALS.get(name.lower())
    if not properties:
        raise ValueError(f"No reviewed engineering property set is available for {name}")
    return properties


def estimate_manufacturing(
    request: ManufacturingEstimateRequest,
) -> ManufacturingEstimateResponse:
    properties = _material(request.requirements.material)
    process = PROCESS_ASSUMPTIONS[request.process]
    volume = float(request.geometry.get("volume_mm3") or 0)
    if volume <= 0:
        raise ValueError("Validated positive geometry volume is required for an estimate")
    mass_each = volume * properties["density_kg_per_mm3"]
    feature_minutes = request.requirements.hole_count * 0.35
    if request.requirements.parameters.get("fillet_radius_mm"):
        feature_minutes += 2.0
    if (
        request.requirements.component_kind.value == "l_bracket"
        and request.process == "sheet_metal"
    ):
        feature_minutes += 3.0
    run_each = max(1.0, volume / process["throughput_mm3_per_minute"] + feature_minutes)

    material_total = (
        mass_each
        * request.material_cost_per_kg
        * process["waste_factor"]
        * request.quantity
    )
    machine_total = (
        (process["setup_minutes"] + run_each * request.quantity)
        / 60
        * request.machine_rate_per_hour
    )
    labor_total = (
        (
            process["setup_minutes"]
            + run_each * request.quantity * process["labor_fraction"]
        )
        / 60
        * request.labor_rate_per_hour
    )
    subtotal = material_total + machine_total + labor_total
    overhead = subtotal * request.overhead_percent / 100
    total = subtotal + overhead
    aligned = (
        request.process == "fdm_print"
        and request.requirements.material.lower() in {"abs", "polycarbonate", "nylon"}
    ) or (
        request.process in {"sheet_metal", "laser_cut"}
        and request.requirements.component_kind.value in {"plate", "l_bracket"}
    ) or request.process == "cnc_milling"
    assumptions = [
        f"Material properties use the built-in {request.requirements.material} reference set.",
        f"Material utilization factor is {process['waste_factor']:.2f}.",
        (
            f"Nominal process throughput is "
            f"{process['throughput_mm3_per_minute']:.0f} mm³/min."
        ),
        "Rates exclude shipping, taxes, inspection, tooling purchases, and supplier margin.",
        "Geometry has not been checked for machine access, bend tooling, supports, or workholding.",
    ]
    if not aligned:
        assumptions.append(
            "The selected process is not the default match for this material/geometry; "
            "confidence is low."
        )
    return ManufacturingEstimateResponse(
        process=request.process,
        quantity=request.quantity,
        mass_kg_each=round(mass_each, 6),
        setup_minutes=round(process["setup_minutes"], 2),
        run_minutes_each=round(run_each, 2),
        breakdown={
            "material": round(material_total, 2),
            "machine": round(machine_total, 2),
            "labor": round(labor_total, 2),
            "overhead": round(overhead, 2),
        },
        unit_cost=round(total / request.quantity, 2),
        total_cost=round(total, 2),
        assumptions=assumptions,
        confidence="medium" if aligned else "low",
    )


def _section(request: SimulationRequest) -> tuple[float, float, float]:
    parameters = request.requirements.parameters
    span = request.span_mm or parameters.get("length_mm")
    if not span:
        raise ValueError("A positive simulation span is required")
    kind = request.requirements.component_kind.value
    if kind in {"plate", "l_bracket"}:
        width = parameters["width_mm"]
        thickness = parameters["thickness_mm"]
    elif kind == "enclosure":
        width = parameters["width_mm"]
        thickness = parameters["wall_thickness_mm"]
    else:
        width = parameters["outer_diameter_mm"]
        thickness = (
            parameters["outer_diameter_mm"] - parameters["inner_diameter_mm"]
        ) / 2
    return float(span), float(width), float(thickness)


def run_simulation(request: SimulationRequest) -> SimulationResponse:
    properties = _material(request.requirements.material)
    span, width, thickness = _section(request)
    area = width * thickness
    inertia = width * thickness**3 / 12
    common_inputs = {
        "span_mm": span,
        "section_width_mm": width,
        "section_thickness_mm": thickness,
        "boundary_condition": request.boundary_condition,
    }
    assumptions = [
        "The component is idealized as a uniform rectangular cantilever beam.",
        "Material is homogeneous, isotropic, and represented by nominal reference properties.",
        "Connections, holes, fillets, local stress concentrations, contact, and "
        "buckling are omitted.",
        "Results are suitable only for preliminary comparative screening.",
    ]
    verification = [
        "Confirm material grade and certified properties.",
        "Define real fixtures, contacts, fasteners, and load combinations.",
        "Run a mesh-converged FEA or validated analytical method.",
        "Obtain qualified engineering review before design release.",
    ]
    checks = [
        ValidationCheck(
            key="method_scope",
            status="warning",
            message="Idealized closed-form screening method; this is not FEA.",
        ),
        ValidationCheck(
            key="structural_safety",
            status="not_evaluated",
            message="Safety, code compliance, fatigue, and failure modes are not certified.",
        ),
    ]

    if request.simulation_type == "static_screening":
        if request.load_n is None:
            raise ValueError("Static screening requires a positive load_n")
        stress = 6 * request.load_n * span / (width * thickness**2)
        deflection = request.load_n * span**3 / (
            3 * properties["elastic_modulus_mpa"] * inertia
        )
        utilization = stress / properties["yield_strength_mpa"]
        results = {
            "nominal_bending_stress_mpa": round(stress, 6),
            "tip_deflection_mm": round(deflection, 6),
            "yield_utilization_ratio": round(utilization, 6),
            "nominal_yield_ratio_inverse": (
                round(1 / utilization, 6) if utilization > 0 else None
            ),
        }
        method = "Euler–Bernoulli cantilever beam, end point load"
        inputs = {**common_inputs, "load_n": request.load_n}
    elif request.simulation_type == "thermal_expansion":
        if request.delta_temperature_c is None:
            raise ValueError("Thermal expansion screening requires delta_temperature_c")
        expansion = (
            properties["thermal_expansion_per_c"]
            * span
            * request.delta_temperature_c
        )
        results = {
            "free_length_change_mm": round(expansion, 6),
            "thermal_strain": round(
                properties["thermal_expansion_per_c"] * request.delta_temperature_c,
                9,
            ),
        }
        method = "Unconstrained one-dimensional linear thermal expansion"
        inputs = {
            **common_inputs,
            "delta_temperature_c": request.delta_temperature_c,
        }
        assumptions[0] = "The component is idealized as a freely expanding uniform member."
    else:
        length_m = span / 1_000
        modulus_pa = properties["elastic_modulus_mpa"] * 1_000_000
        inertia_m4 = inertia * 1e-12
        area_m2 = area * 1e-6
        density_kg_m3 = properties["density_kg_per_mm3"] * 1e9
        frequency = (
            1.875104**2
            / (2 * math.pi * length_m**2)
            * math.sqrt(modulus_pa * inertia_m4 / (density_kg_m3 * area_m2))
        )
        results = {"first_natural_frequency_hz": round(frequency, 6)}
        method = "Euler–Bernoulli uniform cantilever first-mode estimate"
        inputs = common_inputs

    return SimulationResponse(
        simulation_type=request.simulation_type,
        method=method,
        inputs=inputs,
        material_properties={
            key: round(value, 9) for key, value in properties.items()
        },
        results=results,
        checks=checks,
        assumptions=assumptions,
        verification_required=verification,
    )
