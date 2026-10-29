import sys
import time
import uuid
from pathlib import Path

import pytest

ENGINEERING_DIR = Path(__file__).resolve().parents[2] / "services" / "engineering"
sys.path.insert(0, str(ENGINEERING_DIR))
from engineering.cad import generate as cad_generate  # noqa: E402
from engineering.requirements import extract_requirements  # noqa: E402
from engineering.schemas import GenerateRequest  # noqa: E402

from app.engineering import service  # noqa: E402


@pytest.fixture
def local_engineering(monkeypatch):
    async def extract(_settings, prompt):
        return extract_requirements(prompt).model_dump(mode="json")

    async def generate(_settings, body):
        return cad_generate(GenerateRequest(**body)).model_dump(mode="json")

    monkeypatch.setattr(service, "extract", extract)
    monkeypatch.setattr(service, "generate", generate)


def project(client):
    response = client.post(
        "/api/v1/projects",
        json={"prompt": f"Engineering workspace {uuid.uuid4().hex}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def wait_design(client, design_id, revision=1, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/engineering/designs/{design_id}")
        assert response.status_code == 200, response.text
        design = response.json()
        row = next(item for item in design["revisions"] if item["revision"] == revision)
        if row["status"] not in {"queued", "generating"}:
            return design, row
        time.sleep(0.05)
    raise AssertionError("engineering job did not finish")


def test_generates_revises_validates_and_exports_real_engineering_design(
    client, local_engineering
):
    row = project(client)
    response = client.post(
        "/api/v1/engineering/designs",
        json={
            "project_id": row["id"],
            "prompt": (
                "Design an L-shaped steel mounting bracket, 200 mm long, 80 mm wide, "
                "6 mm thick, with four 10 mm mounting holes."
            ),
            "idempotency_key": f"engineering-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 202, response.text
    design_id = response.json()["id"]
    design, first = wait_design(client, design_id)
    assert design["status"] == "geometrically_validated"
    assert first["status"] == "validated"
    assert first["validation_level"] == "geometry"
    assert "not structural analysis" in first["safety_notice"]
    assert first["requirements"]["parameters"]["height_mm"] == 80
    assert "Equal-leg" in first["assumptions"][0]
    artifacts = {item["format"]: item for item in first["artifacts"]}
    assert {"step", "stl", "pdf", "dxf", "json"} <= artifacts.keys()
    assert client.get(
        f"/api/v1/engineering/artifacts/{artifacts['step']['id']}"
    ).content.startswith(b"ISO-10303")
    assert client.get(
        f"/api/v1/engineering/artifacts/{artifacts['pdf']['id']}"
    ).content.startswith(b"%PDF")

    requirements = first["requirements"]
    requirements["parameters"]["thickness_mm"] = 8
    revised = client.post(
        f"/api/v1/engineering/designs/{design_id}/revisions",
        json={
            "requirements": requirements,
            "change_note": "Increase plate thickness to 8 mm",
            "source_prompt": "Increase the plate thickness to 8 mm.",
            "idempotency_key": f"engineering-revision-{uuid.uuid4().hex}",
        },
    )
    assert revised.status_code == 202, revised.text
    design, second = wait_design(client, design_id, revision=2)
    assert second["status"] == "validated"
    assert second["geometry"]["volume_mm3"] != first["geometry"]["volume_mm3"]
    preserved = next(item for item in design["revisions"] if item["revision"] == 1)
    assert preserved["requirements"]["parameters"]["thickness_mm"] == 6

    approval = client.post(
        f"/api/v1/engineering/designs/{design_id}/approval-request"
    )
    assert approval.status_code == 201, approval.text
    decision = client.post(
        f"/api/v1/engineering/approvals/{approval.json()['approval_id']}",
        json={"decision": "approve", "note": "Geometry reviewed."},
    )
    assert decision.status_code == 200
    assert decision.json()["design_status"] == "engineering_reviewed"
    assert "not by itself" in decision.json()["notice"]

    signed = client.post(
        f"/api/v1/engineering/artifacts/{second['artifacts'][0]['id']}/signed-url"
    )
    assert signed.status_code == 200
    assert client.get(signed.json()["url"]).status_code == 200


def test_missing_requirements_require_review_instead_of_invention(client, local_engineering):
    row = project(client)
    response = client.post(
        "/api/v1/engineering/designs",
        json={
            "project_id": row["id"],
            "prompt": "Design a mounting plate that is 100 mm long.",
            "idempotency_key": f"engineering-missing-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 202
    revision = response.json()["revisions"][0]
    assert revision["status"] == "requirements_review"
    assert {"width_mm", "thickness_mm", "material"} <= set(revision["missing_critical"])
    assert revision["job"] is None


def test_failed_engineering_job_can_be_retried_without_new_revision(
    client, local_engineering, monkeypatch
):
    async def fail_generate(_settings, _body):
        raise service.EngineeringUnavailable("CAD worker timeout")

    monkeypatch.setattr(service, "generate", fail_generate)
    row = project(client)
    created = client.post(
        "/api/v1/engineering/designs",
        json={
            "project_id": row["id"],
            "prompt": "Design a steel plate 120 mm long, 80 mm wide, 6 mm thick.",
            "idempotency_key": f"engineering-retry-{uuid.uuid4().hex}",
        },
    ).json()
    _, failed = wait_design(client, created["id"])
    assert failed["status"] == "failed"
    assert failed["job"]["attempts"] == 1

    async def generate(_settings, body):
        return cad_generate(GenerateRequest(**body)).model_dump(mode="json")

    monkeypatch.setattr(service, "generate", generate)
    retry = client.post(f"/api/v1/engineering/jobs/{failed['job']['id']}/retry")
    assert retry.status_code == 202, retry.text
    design, recovered = wait_design(client, created["id"])
    assert recovered["status"] == "validated"
    assert recovered["job"]["attempts"] == 2
    assert design["current_revision"] == 1


def test_engineering_feedback_requires_authorized_evidence(client, local_engineering):
    row = project(client)
    created = client.post(
        "/api/v1/engineering/designs",
        json={
            "project_id": row["id"],
            "prompt": (
                "Design an aluminum spacer 30 mm outer diameter, "
                "12 mm inner diameter, 20 mm long."
            ),
            "idempotency_key": f"engineering-feedback-{uuid.uuid4().hex}",
        },
    ).json()
    _, revision = wait_design(client, created["id"])
    blocked = client.post(
        f"/api/v1/engineering/designs/{created['id']}/feedback",
        json={
            "revision_id": revision["id"],
            "source": "Manufacturing review",
            "evidence": {"finding": "Difficult to fixture"},
            "authorized": False,
        },
    )
    assert blocked.status_code == 422
    accepted = client.post(
        f"/api/v1/engineering/designs/{created['id']}/feedback",
        json={
            "revision_id": revision["id"],
            "source": "Manufacturing review",
            "evidence": {"finding": "Difficult to fixture"},
            "authorized": True,
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["recommendation"]["status"] == "proposal_only"


def test_engineering_design_is_tenant_isolated(client, local_engineering):
    from app.main import app
    from app.schemas import Principal
    from app.security import get_principal

    row = project(client)
    created = client.post(
        "/api/v1/engineering/designs",
        json={
            "project_id": row["id"],
            "prompt": (
                "Design a steel plate 120 mm long, 80 mm wide, 6 mm thick "
                "with four 10 mm holes."
            ),
            "idempotency_key": f"engineering-tenant-{uuid.uuid4().hex}",
        },
    ).json()
    wait_design(client, created["id"])
    outsider = Principal(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="outsider@example.com",
        role="owner",
    )
    app.dependency_overrides[get_principal] = lambda: outsider
    assert client.get(f"/api/v1/engineering/designs/{created['id']}").status_code == 404
    app.dependency_overrides.clear()
