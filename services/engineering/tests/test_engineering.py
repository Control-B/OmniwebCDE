import base64
import json
import tempfile
import uuid
from pathlib import Path

import cadquery as cq
import ezdxf
import pytest
from fastapi.testclient import TestClient

from engineering.analysis import estimate_manufacturing, run_simulation
from engineering.assembly import generate_assembly
from engineering.cad import generate
from engineering.main import app
from engineering.requirements import extract_requirements
from engineering.schemas import (
    AssemblyGenerateRequest,
    AssemblyMember,
    DesignRequirements,
    GenerateRequest,
    ManufacturingEstimateRequest,
    SimulationRequest,
)


@pytest.mark.parametrize(
    ("prompt", "kind"),
    [
        (
            "Design a steel plate 120 mm long, 80 mm wide, 6 mm thick with four 10 mm holes.",
            "plate",
        ),
        (
            "Design an L-shaped steel bracket, 200 mm long, 80 mm wide, 6 mm thick, "
            "with four 10 mm mounting holes.",
            "l_bracket",
        ),
        (
            "Design an aluminum spacer 30 mm outer diameter, 12 mm inner diameter, 20 mm long.",
            "spacer",
        ),
        (
            "Design an ABS enclosure 120 mm long, 80 mm wide, 40 mm high with a 3 mm wall.",
            "enclosure",
        ),
    ],
)
def test_extracts_supported_requirements(prompt, kind):
    result = extract_requirements(prompt)
    assert result.complete, result.questions
    assert result.requirements.component_kind.value == kind
    assert result.requirements.units == "mm"


def test_unit_conversion_and_missing_critical_fields():
    result = extract_requirements("Create a plate 4 inches long and 2 inches wide.")
    assert not result.complete
    assert result.extracted["parameters"]["length_mm"] == 101.6
    assert {"thickness_mm", "material"} <= set(result.missing_critical)


def test_preserves_stainless_steel_material_name():
    result = extract_requirements(
        "Design a stainless steel plate 100 mm long, 60 mm wide, and 4 mm thick."
    )
    assert result.requirements.material == "Stainless Steel"


def _requirements(kind: str) -> DesignRequirements:
    values = {
        "plate": dict(
            component_name="Mounting plate",
            component_kind="plate",
            material="Steel",
            parameters={"length_mm": 120, "width_mm": 80, "thickness_mm": 6},
            hole_count=4,
            hole_diameter_mm=10,
        ),
        "l_bracket": dict(
            component_name="L bracket",
            component_kind="l_bracket",
            material="Steel",
            parameters={
                "length_mm": 200,
                "width_mm": 80,
                "height_mm": 80,
                "thickness_mm": 6,
            },
            hole_count=4,
            hole_diameter_mm=10,
        ),
        "spacer": dict(
            component_name="Spacer",
            component_kind="spacer",
            material="Aluminum",
            parameters={
                "outer_diameter_mm": 30,
                "inner_diameter_mm": 12,
                "length_mm": 20,
            },
        ),
        "enclosure": dict(
            component_name="Enclosure",
            component_kind="enclosure",
            material="ABS",
            parameters={
                "length_mm": 120,
                "width_mm": 80,
                "height_mm": 40,
                "wall_thickness_mm": 3,
            },
        ),
    }[kind]
    return DesignRequirements(**values)


@pytest.mark.parametrize("kind", ["plate", "l_bracket", "spacer", "enclosure"])
def test_generates_valid_geometry_drawings_and_real_exports(kind):
    result = generate(
        GenerateRequest(
            design_id=str(uuid.uuid4()),
            revision=1,
            requirements=_requirements(kind),
        )
    )
    assert result.status == "validated"
    assert result.geometry["valid"]
    assert result.geometry["volume_mm3"] > 0
    assert result.preview["vertices"] and result.preview["triangles"]
    assert (
        next(check for check in result.checks if check.key == "structural_safety").status
        == "not_evaluated"
    )
    artifacts = {artifact.format: artifact for artifact in result.artifacts}
    assert {"step", "stl", "pdf", "json"} <= artifacts.keys()
    assert base64.b64decode(artifacts["pdf"].data_base64).startswith(b"%PDF")
    source = json.loads(base64.b64decode(artifacts["json"].data_base64))
    assert source["schema"] == "omniweb.parametric-design.v1"

    with tempfile.TemporaryDirectory() as directory:
        step_path = Path(directory) / "model.step"
        step_path.write_bytes(base64.b64decode(artifacts["step"].data_base64))
        imported = cq.importers.importStep(str(step_path))
        assert imported.val().isValid()


def test_dxf_export_is_parseable():
    requirements = _requirements("plate").model_copy(
        update={"requested_outputs": ["step", "stl", "pdf", "dxf", "source"]}
    )
    result = generate(
        GenerateRequest(design_id=str(uuid.uuid4()), revision=1, requirements=requirements)
    )
    dxf = next(item for item in result.artifacts if item.format == "dxf")
    with tempfile.NamedTemporaryFile(suffix=".dxf") as handle:
        Path(handle.name).write_bytes(base64.b64decode(dxf.data_base64))
        document = ezdxf.readfile(handle.name)
        assert len(document.modelspace()) >= 5


def test_revision_parameter_change_produces_different_immutable_source():
    first = GenerateRequest(
        design_id=str(uuid.uuid4()), revision=1, requirements=_requirements("spacer")
    )
    second = first.model_copy(
        update={
            "revision": 2,
            "requirements": first.requirements.model_copy(
                update={
                    "parameters": {
                        **first.requirements.parameters,
                        "length_mm": 30,
                    }
                }
            ),
        }
    )
    one, two = generate(first), generate(second)
    assert one.geometry["volume_mm3"] != two.geometry["volume_mm3"]
    source_one = next(item.sha256 for item in one.artifacts if item.format == "json")
    source_two = next(item.sha256 for item in two.artifacts if item.format == "json")
    assert source_one != source_two


def test_service_rejects_invalid_geometry_without_executing_input():
    client = TestClient(app)
    request = GenerateRequest(
        design_id=str(uuid.uuid4()), revision=1, requirements=_requirements("spacer")
    ).model_dump(mode="json")
    request["requirements"]["parameters"]["inner_diameter_mm"] = 40
    response = client.post("/v1/generate", json=request)
    assert response.status_code == 422
    assert "smaller" in response.json()["detail"]


def test_generates_real_step_assembly_bom_and_interference_evidence():
    request = AssemblyGenerateRequest(
        assembly_id=str(uuid.uuid4()),
        revision=1,
        name="Bracket mounting assembly",
        members=[
            AssemblyMember(
                member_id=str(uuid.uuid4()),
                name="Bracket",
                requirements=_requirements("l_bracket"),
            ),
            AssemblyMember(
                member_id=str(uuid.uuid4()),
                name="Spacer",
                requirements=_requirements("spacer"),
                quantity=2,
                translation_mm=[-50, 0, 6],
                instance_spacing_mm=[100, 0, 0],
            ),
        ],
    )
    result = generate_assembly(request)
    assert result.status == "validated"
    assert result.geometry["member_instances"] == 3
    assert len(result.bill_of_materials) == 2
    assert result.preview["triangles"]
    artifacts = {(item.kind, item.format): item for item in result.artifacts}
    step = base64.b64decode(artifacts[("assembly_model", "step")].data_base64)
    assert step.startswith(b"ISO-10303")
    bom = json.loads(
        base64.b64decode(artifacts[("bill_of_materials", "json")].data_base64)
    )
    assert bom["schema"] == "omniweb.bill-of-materials.v1"
    assert len(bom["items"]) == 2


def test_manufacturing_estimate_exposes_rates_assumptions_and_budgetary_notice():
    result = estimate_manufacturing(
        ManufacturingEstimateRequest(
            requirements=_requirements("l_bracket"),
            geometry={"volume_mm3": 182_900},
            process="sheet_metal",
            quantity=25,
            material_cost_per_kg=2.4,
            machine_rate_per_hour=95,
            labor_rate_per_hour=65,
            overhead_percent=18,
        )
    )
    assert result.status == "budgetary_estimate"
    assert result.total_cost > result.unit_cost > 0
    assert result.breakdown["material"] > 0
    assert result.confidence == "medium"
    assert "not a supplier quote" in result.notice


@pytest.mark.parametrize(
    ("simulation_type", "extra", "result_key"),
    [
        ("static_screening", {"load_n": 250}, "tip_deflection_mm"),
        (
            "thermal_expansion",
            {"delta_temperature_c": 60},
            "free_length_change_mm",
        ),
        ("modal_screening", {}, "first_natural_frequency_hz"),
    ],
)
def test_deterministic_screening_simulations_are_explicitly_not_fea(
    simulation_type, extra, result_key
):
    result = run_simulation(
        SimulationRequest(
            requirements=_requirements("l_bracket"),
            geometry={"volume_mm3": 182_900},
            simulation_type=simulation_type,
            **extra,
        )
    )
    assert result.status == "screening_complete"
    assert result.results[result_key] >= 0
    assert "not finite-element analysis" in result.safety_notice
    assert result.verification_required
    assert next(check for check in result.checks if check.key == "structural_safety").status == (
        "not_evaluated"
    )
