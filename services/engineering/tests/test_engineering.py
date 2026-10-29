import base64
import json
import tempfile
import uuid
from pathlib import Path

import cadquery as cq
import ezdxf
import pytest
from fastapi.testclient import TestClient

from engineering.cad import generate
from engineering.main import app
from engineering.requirements import extract_requirements
from engineering.schemas import DesignRequirements, GenerateRequest


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
