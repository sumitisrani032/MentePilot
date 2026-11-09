"""Text clean-up shared by catalog sources."""

import re

from bs4 import BeautifulSoup

_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")
_WHITESPACE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", _WHITESPACE.sub(" ", text))
