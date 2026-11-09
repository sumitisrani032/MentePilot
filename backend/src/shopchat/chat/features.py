"""Which features are live for a store: merchant choices over sensible defaults."""

from collections.abc import Mapping

from shopchat.catalog.profile import CatalogProfile
from shopchat.config import Settings


def effective_features(
    settings: Settings,
    merchant_choices: Mapping[str, bool],
    profile: CatalogProfile | None,
) -> dict[str, bool]:
    skin_default = profile is not None and profile.has_skincare
    return {
        "image": merchant_choices.get("image", True),
        "skin_analysis": merchant_choices.get("skin_analysis", skin_default),
        "voice": settings.voice_enabled and merchant_choices.get("voice", False),
    }
