"""Starter questions for the widget, built from what each store sells."""

from shopchat.catalog.profile import CatalogProfile

_GENERAL = (
    "I'm not sure what I need. Can you help?",
    "Help me find a gift",
    "What's good for everyday use?",
    "Show me something affordable",
)
_MAX_FROM_CATALOG = 4
_MAX_SUGGESTIONS = 8


def _leaf(category: str) -> str:
    return category.rsplit(">", maxsplit=1)[-1].strip()


def suggestions_for(profile: CatalogProfile | None) -> list[str]:
    """The store's own questions first, then a spread of its categories and general ones."""
    written = profile.suggested_questions if profile else []
    kinds = sorted({_leaf(category) for category in (profile.categories if profile else [])})
    step = max(len(kinds) // _MAX_FROM_CATALOG, 1)
    from_catalog = [f"Show me {kind.lower()}" for kind in kinds[::step][:_MAX_FROM_CATALOG]]
    return list(dict.fromkeys([*written, *from_catalog, *_GENERAL]))[:_MAX_SUGGESTIONS]
