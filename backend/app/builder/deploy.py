"""Deploys generated apps to DigitalOcean App Platform on the customer's own account.

A deployment is always a two-step operation: Omniweb prepares the App Platform spec and a cost
estimate, and a person approves it (typing the project name for production). Only then is the
customer's encrypted DigitalOcean token decrypted, in this process, for the API calls. With
OMNIWEB_MOCK_INFRASTRUCTURE=true (the default) nothing is created and the adapter returns fixtures.

App Platform builds from the GitHub repository, so the project must be pushed first.
"""

from ..config import Settings
from ..providers.digitalocean import DigitalOceanAdapter
from .spec import AppSpec
from .templates import app_platform_spec

# Published App Platform list prices (USD/month) used for estimates only; DigitalOcean bills the customer.
PRICES = {
    "development": {
        "service": 5.0,
        "service_size": "apps-s-1vcpu-0.5gb",
        "database": 7.0,
        "database_label": "Dev database",
        "static": 0.0,
    },
    "production": {
        "service": 12.0,
        "service_size": "apps-s-1vcpu-1gb",
        "database": 15.0,
        "database_label": "Managed PostgreSQL (1 GB)",
        "static": 3.0,
    },
}
REGIONS = {
    "nyc": "New York",
    "sfo": "San Francisco",
    "ams": "Amsterdam",
    "fra": "Frankfurt",
    "lon": "London",
    "sgp": "Singapore",
    "tor": "Toronto",
    "blr": "Bangalore",
    "syd": "Sydney",
}


def estimate(spec: AppSpec, environment: str) -> dict:
    price = PRICES[environment]
    lines = []
    if "web" in spec.targets:
        lines.append({"item": "Static site (web app)", "monthly_usd": price["static"]})
    if "api" in spec.targets:
        lines.append(
            {"item": f"API service ({price['service_size']})", "monthly_usd": price["service"]}
        )
        lines.append({"item": price["database_label"], "monthly_usd": price["database"]})
    total = round(sum(line["monthly_usd"] for line in lines), 2)
    return {
        "lines": lines,
        "monthly_usd": total,
        "note": "Estimate from App Platform list prices. Bandwidth overages and taxes are extra; DigitalOcean bills your account directly.",
    }


def prepare(spec: AppSpec, repo: str, branch: str, region: str, environment: str) -> dict:
    if "mobile" in spec.targets and spec.targets == ["mobile"]:
        raise ValueError(
            "Mobile-only apps are distributed through EAS builds and app stores, not App Platform"
        )
    app_spec = app_platform_spec(spec, repo, branch, region, environment)
    if environment == "production":
        for service in app_spec.get("services", []):
            service["instance_size_slug"] = PRICES["production"]["service_size"]
        for database in app_spec.get("databases", []):
            database["production"] = True
    return app_spec


async def execute(settings: Settings, token: str, app_spec: dict, app_id: str | None) -> dict:
    async with DigitalOceanAdapter(token, settings) as client:
        new_app_id, deployment_id = await client.upsert_app(app_spec, app_id)
        state = await client.app_deployment(new_app_id, deployment_id) if deployment_id else {}
    return {
        "app_id": new_app_id,
        "deployment_id": deployment_id,
        "phase": state.get("phase"),
        "url": state.get("live_url"),
        "mock": settings.mock_infrastructure,
    }


async def rollback(settings: Settings, token: str, app_id: str, deployment_id: str) -> dict:
    async with DigitalOceanAdapter(token, settings) as client:
        new_deployment = await client.rollback_app(app_id, deployment_id)
        state = await client.app_deployment(app_id, new_deployment)
    return {
        "deployment_id": new_deployment,
        "phase": state.get("phase"),
        "url": state.get("live_url"),
        "mock": settings.mock_infrastructure,
    }
