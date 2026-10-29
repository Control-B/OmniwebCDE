from dataclasses import dataclass


@dataclass(frozen=True)
class OnshapeCapability:
    available: bool = False
    reason: str = (
        "Onshape integration is disabled. Configure documented OAuth credentials, "
        "tenant authorization, and an approved export policy before enabling it."
    )
    supported_actions: tuple[str, ...] = ()


def capability() -> OnshapeCapability:
    """Return an explicit capability status without making a network request."""
    return OnshapeCapability()
