"""Decide which requirements this store's data can actually enforce."""

import re

from shopchat.catalog.profile import CatalogProfile, FacetSummary
from shopchat.search.types import Requirements

# Free text rarely matches exactly, so a text "requirement" would just hide good products.
_ENFORCEABLE_TYPES = frozenset({"bool", "number"})
_TRUE_WORDS = frozenset({"true", "yes"})
_FALSE_WORDS = frozenset({"false", "no"})
_YES_NO_VALUES = frozenset({"true", "false"})
_DECLINED_BEFORE = re.compile(
    r"(?:\b(?:not|no|non|never|without|dont|doesnt|isnt)|n['\u2019]t)\b(?:[\s-]+[\w']+){0,3}?[\s-]*$",
    re.IGNORECASE,
)


def _coerce(value: bool | float | str, value_type: str) -> bool | float | str | None:
    """Convert a planned value to the type stored for this facet, or None if it cannot be."""
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        word = str(value).strip().lower()
        return True if word in _TRUE_WORDS else False if word in _FALSE_WORDS else None
    if value_type == "number":
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return str(value)


def effective_requirements(
    requirements: Requirements, profile: CatalogProfile
) -> tuple[Requirements, list[str]]:
    """Split facts into enforceable ones and those downgraded to soft preferences."""
    firm: dict[str, bool | float | str] = {}
    soft: list[str] = []
    for key, value in requirements.facts.items():
        facet = profile.facets.get(key)
        coerced = _coerce(value, facet.value_type) if facet is not None else None
        if (
            facet is not None
            and facet.value_type in _ENFORCEABLE_TYPES
            and facet.stated_count > 0
            and coerced is not None
            # Nobody shops for the absence of a feature, so "false" must never exclude products.
            and coerced is not False
        ):
            firm[key] = coerced
        else:
            soft.append(f"{key.replace('_', ' ')}: {value}")
    return requirements.model_copy(update={"facts": firm}), soft


def _is_true_yes_no(facet: FacetSummary) -> bool:
    """A real yes/no facet that some products state as yes, not free text typed as one."""
    values = {value.strip().lower() for value in facet.top_values}
    return (
        facet.value_type == "bool"
        and facet.stated_count > 0
        and "true" in values
        and values <= _YES_NO_VALUES
    )


def _mentions(message: str, key: str) -> bool:
    """Whether the customer asks for this feature, in any spacing, and does not decline it."""
    letters = key.replace("_", "").replace("-", "")
    pattern = r"(?<![a-z])" + r"[\s_-]?".join(map(re.escape, letters)) + r"(?![a-z])"
    match = re.search(pattern, message, re.IGNORECASE)
    return match is not None and not _DECLINED_BEFORE.search(message[: match.start()])


def named_features(message: str, profile: CatalogProfile) -> dict[str, bool]:
    """Yes/no features the customer named outright, which must not depend on the model."""
    return {
        key: True
        for key, facet in profile.facets.items()
        if _is_true_yes_no(facet) and _mentions(message, key)
    }
