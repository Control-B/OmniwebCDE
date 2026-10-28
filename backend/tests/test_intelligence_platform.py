"""Unified business, marketing, creative and bidirectional platform acceptance slices."""

import time
import uuid

from app.services.media import MockMedia


def project(client, prompt="A neighborhood service business"):
    response = client.post("/api/v1/projects", json={"prompt": prompt})
    assert response.status_code == 201, response.text
    return response.json()


def wait_workflow(client, workflow_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = client.get(f"/api/v1/intelligence/requests/{workflow_id}").json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.1)
    raise AssertionError("intelligence workflow did not finish")


def test_one_prompt_creates_project_business_campaign_funnel_content_and_media_jobs(
    client, monkeypatch
):
    from app import intelligence_api
    from app.intelligence import orchestrator

    monkeypatch.setattr(intelligence_api, "providers", lambda settings: {"openai": MockMedia()})
    monkeypatch.setattr(orchestrator, "providers", lambda settings: {"openai": MockMedia()})
    response = client.post(
        "/api/v1/intelligence/requests",
        json={
            "prompt": (
                "Build a website for my restaurant, create a business plan and marketing strategy, "
                "write social posts, generate promotional images, and propose a video campaign."
            ),
            "mode": "AUTO",
            "idempotency_key": f"unified-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 202, response.text
    workflow = wait_workflow(client, response.json()["id"])
    assert workflow["status"] == "completed"
    tasks = {task["kind"]: task for task in workflow["tasks"]}
    assert set(tasks) == {"build", "business", "marketing", "content", "image", "video"}
    assert all(task["status"] == "completed" for task in tasks.values())
    assert workflow["project_id"]
    plans = client.get(
        "/api/v1/business-plans", params={"project_id": workflow["project_id"]}
    ).json()
    assert plans and "assumptions" in plans[0]
    campaigns = client.get(
        "/api/v1/campaigns", params={"project_id": workflow["project_id"]}
    ).json()
    funnels = client.get("/api/v1/funnels", params={"project_id": workflow["project_id"]}).json()
    assets = client.get("/api/v1/assets", params={"project_id": workflow["project_id"]}).json()
    jobs = client.get("/api/v1/media/jobs", params={"project_id": workflow["project_id"]}).json()
    assert (
        campaigns
        and funnels
        and len(assets) >= 3
        and {job["kind"] for job in jobs} == {"image", "video"}
    )
    assert next(job for job in jobs if job["kind"] == "image")["status"] == "awaiting_approval"
    assert next(job for job in jobs if job["kind"] == "video")["status"] == "capability_unavailable"
    image = next(job for job in jobs if job["kind"] == "image")
    generated = client.post(f"/api/v1/media/jobs/{image['id']}/authorize")
    assert generated.status_code == 200, generated.text
    assert generated.json()["status"] == "completed" and generated.json()["asset_id"]


def test_funnel_publish_lead_capture_analytics_and_consent_aware_automation(client):
    row = project(client)
    campaign = client.post(
        "/api/v1/campaigns",
        json={
            "project_id": row["id"],
            "name": "Consultation launch",
            "objective": "Generate qualified consultation leads",
            "budget_limit_usd": 500,
        },
    ).json()
    definition = {
        "steps": [
            {
                "key": "landing",
                "type": "landing_page",
                "title": "Grow with clarity",
                "next": "form",
            },
            {
                "key": "form",
                "type": "form",
                "title": "Request a consultation",
                "fields": ["first_name", "email"],
                "consent_required": True,
                "next": "thanks",
            },
            {"key": "thanks", "type": "thank_you", "title": "Thank you"},
        ]
    }
    funnel = client.post(
        "/api/v1/funnels",
        json={
            "project_id": row["id"],
            "campaign_id": campaign["id"],
            "name": "Consultation funnel",
            "funnel_type": "consultation",
            "definition": definition,
        },
    ).json()
    assert client.get(f"/api/v1/funnels/{funnel['id']}/preview").json()["definition"] == definition
    request = client.post(f"/api/v1/funnels/{funnel['id']}/publish-request").json()
    assert request["funnel"]["status"] == "awaiting_approval"
    approved = client.post(
        f"/api/v1/marketing/approvals/{request['approval_id']}",
        json={"decision": "approve"},
    )
    assert approved.status_code == 200

    automation = client.post(
        "/api/v1/automations",
        json={
            "project_id": row["id"],
            "name": "Lead welcome",
            "trigger": {"type": "form_submitted"},
            "steps": [
                {"action": "add_tag", "tag": "consultation"},
                {"action": "send_email", "template": "welcome"},
            ],
        },
    ).json()
    assert (
        client.post(f"/api/v1/automations/{automation['id']}/activate").json()["status"] == "active"
    )
    lead = client.post(
        f"/api/v1/public/funnels/{funnel['id']}/submit",
        json={
            "email": "sam@example.com",
            "first_name": "Sam",
            "consent": True,
            "consent_text": "I agree to receive the consultation series.",
            "idempotency_key": f"lead-{uuid.uuid4().hex}",
            "utm": {"source": "newsletter"},
        },
    )
    assert lead.status_code == 201, lead.text
    contacts = client.get("/api/v1/crm/contacts", params={"project_id": row["id"]}).json()
    assert contacts[0]["email"] == "sam@example.com" and contacts[0]["marketing_consent"]
    runs = client.get(f"/api/v1/automations/{automation['id']}/runs").json()
    assert runs[0]["status"] == "completed"
    email = next(log for log in runs[0]["logs"] if log["action"] == "send_email")
    assert email["status"] == "provider_unavailable"  # never claim delivery without a provider
    analytics = client.get("/api/v1/marketing/analytics", params={"project_id": row["id"]}).json()
    assert analytics["leads"] == 1 and analytics["funnel_conversion_rate"] is None


def test_blog_editorial_approval_sitemap_and_rss(client):
    row = project(client)
    blog = client.post(
        "/api/v1/blogs",
        json={"project_id": row["id"], "name": "Field Notes"},
    ).json()
    article = client.post(
        f"/api/v1/blogs/{blog['id']}/articles",
        json={
            "title": "A practical guide",
            "content": "# A practical guide\n\nEditorially reviewed advice.",
            "seo_title": "Practical guide",
            "meta_description": "A practical guide for local teams.",
            "categories": ["Guides"],
            "tags": ["planning"],
            "claims": [
                {
                    "claim": "This recommendation is an internal planning assumption.",
                    "evidence_type": "assumption",
                }
            ],
        },
    ).json()
    request = client.post(f"/api/v1/articles/{article['id']}/publish-request").json()
    assert (
        client.post(
            f"/api/v1/marketing/approvals/{request['approval_id']}",
            json={"decision": "approve"},
        ).status_code
        == 200
    )
    public = client.get(f"/api/v1/public/blogs/{blog['id']}/articles/{article['slug']}")
    assert public.status_code == 200 and public.json()["seo"]["title"] == "Practical guide"
    assert "<urlset" in client.get(f"/api/v1/public/blogs/{blog['id']}/sitemap.xml").text
    assert "<rss" in client.get(f"/api/v1/public/blogs/{blog['id']}/rss.xml").text


def test_bidirectional_evolution_is_evidence_backed_traceable_and_blocks_unreleased_claims(client):
    row = project(client)
    observed = client.post(
        "/api/v1/evolution/observations",
        json={
            "project_id": row["id"],
            "title": "Quote funnel abandonment",
            "objective": "Visitors leave the quote request because lead capture is too complex",
            "evidence": [
                {
                    "evidence_type": "analytics",
                    "source": "first-party funnel events",
                    "payload": {"entries": 100, "submissions": 10},
                    "authorized": True,
                }
            ],
        },
    ).json()
    assert observed["state"] == "EVIDENCE_COLLECTED"
    proposed = client.post(f"/api/v1/evolution/cases/{observed['id']}/analyze").json()
    assert proposed["state"] == "CHANGE_PROPOSED"
    paths = {alternative["path"] for alternative in proposed["alternatives"]}
    assert paths == {"reuse", "adapt", "synthesize"}
    reusable = next(option for option in proposed["alternatives"] if option["path"] == "reuse")
    approved = client.post(
        f"/api/v1/evolution/cases/{observed['id']}/decision",
        json={
            "decision": "approve",
            "path": "reuse",
            "capability_id": reusable["capability_id"],
        },
    ).json()
    assert approved["state"] == "APPROVED"
    case = client.get(f"/api/v1/evolution/cases/{observed['id']}").json()
    assert [transition["to"] for transition in case["transitions"]] == [
        "OBSERVED",
        "EVIDENCE_COLLECTED",
        "HYPOTHESIS_CREATED",
        "CAPABILITY_MATCHED",
        "CHANGE_PROPOSED",
        "APPROVED",
    ]
    blocked = client.post(
        "/api/v1/evolution/releases",
        json={
            "project_id": row["id"],
            "capability_name": "Instant quotes",
            "release_version": "1",
            "released": False,
            "test_evidence": [{"name": "tests", "passed": True}],
        },
    )
    assert blocked.status_code == 409
    reverse = client.post(
        "/api/v1/evolution/releases",
        json={
            "project_id": row["id"],
            "capability_name": "Instant quotes",
            "release_version": "1",
            "released": True,
            "audience": ["existing local-service customers"],
            "test_evidence": [{"name": "integration", "passed": True}],
        },
    )
    assert reverse.status_code == 201, reverse.text
    reverse_body = reverse.json()
    assert (
        reverse_body["state"] == "RELEASED"
        and len(reverse_body["marketing_proposal_asset_ids"]) == 3
    )
    assets = client.get("/api/v1/assets", params={"project_id": row["id"]}).json()
    release_assets = [
        asset
        for asset in assets
        if asset["metadata"].get("evolution_case_id") == reverse_body["id"]
    ]
    assert len(release_assets) == 3 and all(asset["status"] == "draft" for asset in release_assets)
    graph = client.get("/api/v1/evolution/graph").json()
    assert any(edge["relation"] == "supported_by" for edge in graph)


def test_intelligence_and_evolution_block_cross_tenant_access(client):
    from app.main import app
    from app.schemas import Principal
    from app.security import get_principal

    row = project(client)
    workflow = client.post(
        "/api/v1/intelligence/requests",
        json={
            "prompt": "Write a launch email",
            "mode": "CONTENT",
            "project_id": row["id"],
            "idempotency_key": f"tenant-{uuid.uuid4().hex}",
        },
    ).json()
    outsider = Principal(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="outsider@example.com",
        role="owner",
    )
    app.dependency_overrides[get_principal] = lambda: outsider
    assert client.get(f"/api/v1/intelligence/requests/{workflow['id']}").status_code == 404
    assert client.get("/api/v1/assets", params={"project_id": row["id"]}).status_code == 404
    assert (
        client.get("/api/v1/evolution/cases", params={"project_id": row["id"]}).status_code == 404
    )
    app.dependency_overrides.clear()


def test_brand_kit_reuse_and_experiment_evaluates_only_recorded_events(client):
    row = project(client)
    logo = client.post(
        "/api/v1/assets",
        json={
            "project_id": row["id"],
            "content_type": "logo",
            "title": "Approved mark",
            "content": "<svg aria-label='Brand mark'/>",
            "usage_rights": {"status": "owned"},
        },
    ).json()
    kit_response = client.post(
        "/api/v1/brand-kits",
        json={
            "project_id": row["id"],
            "name": "Primary brand",
            "logo_asset_id": logo["id"],
            "colors": ["#10231A", "#A3FFCB"],
            "typography": {"heading": "Inter Tight"},
            "voice": "Clear, useful, and evidence-aware.",
            "messaging": ["Build and grow from one workspace."],
        },
    )
    assert kit_response.status_code == 201, kit_response.text
    kit = kit_response.json()
    campaign = client.post(
        "/api/v1/campaigns",
        json={
            "project_id": row["id"],
            "brand_kit_id": kit["id"],
            "name": "Brand-led launch",
            "objective": "Generate authorized leads",
        },
    )
    assert campaign.status_code == 201
    assert campaign.json()["brand_kit_id"] == kit["id"]

    experiment_response = client.post(
        "/api/v1/marketing/experiments",
        json={
            "project_id": row["id"],
            "campaign_id": campaign.json()["id"],
            "name": "Landing headline",
            "hypothesis": "A clearer value proposition may improve CTA interactions.",
            "metric": "cta_interaction",
            "minimum_sample_size": 20,
            "variants": [
                {"key": "control", "name": "Control", "weight": 50, "definition": {"headline": "Plan better"}},
                {"key": "clear", "name": "Clear value", "weight": 50, "definition": {"headline": "Plan, build, and grow"}},
            ],
        },
    )
    assert experiment_response.status_code == 201, experiment_response.text
    experiment = experiment_response.json()
    assert client.post(f"/api/v1/marketing/experiments/{experiment['id']}/activate").status_code == 200
    first = client.get(
        f"/api/v1/marketing/experiments/{experiment['id']}/assignment",
        params={"subject_id": "stable-visitor"},
    ).json()
    second = client.get(
        f"/api/v1/marketing/experiments/{experiment['id']}/assignment",
        params={"subject_id": "stable-visitor"},
    ).json()
    assert first["variant_key"] == second["variant_key"]

    for variant in ("control", "clear"):
        for index in range(10):
            event = client.post(
                "/api/v1/marketing/events",
                json={
                    "event_type": "page_view",
                    "idempotency_key": f"exp-view-{variant}-{index}-{uuid.uuid4().hex}",
                    "project_id": row["id"],
                    "properties": {"experiment_id": experiment["id"], "variant_key": variant},
                    "consent": {"analytics": True},
                },
            )
            assert event.status_code == 202
        conversions = 2 if variant == "control" else 5
        for index in range(conversions):
            event = client.post(
                "/api/v1/marketing/events",
                json={
                    "event_type": "cta_interaction",
                    "idempotency_key": f"exp-convert-{variant}-{index}-{uuid.uuid4().hex}",
                    "project_id": row["id"],
                    "properties": {"experiment_id": experiment["id"], "variant_key": variant},
                    "consent": {"analytics": True},
                },
            )
            assert event.status_code == 202
    evaluated = client.post(
        f"/api/v1/marketing/experiments/{experiment['id']}/evaluate"
    )
    assert evaluated.status_code == 200, evaluated.text
    result = evaluated.json()["result"]
    assert result["sample_size"] == 20
    assert result["winner"] == "clear"
    assert result["conclusion"] == "observed_leader"
