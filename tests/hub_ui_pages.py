"""Reading the hub screen's pages in tests: the text of one panel (an element found by its id) and the page token."""
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Panel(HTMLParser):
    """Collects the text inside the element whose id is `wanted`, and the attributes of the elements in it."""

    def __init__(self, wanted: str):
        super().__init__()
        self.wanted, self.depth, self.found = wanted, 0, False
        self.parts: list[str] = []
        self.elements: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.depth:
            self.elements.append((tag, attrs))
            if tag not in VOID:
                self.depth += 1
        elif attrs.get("id") == self.wanted:
            self.found, self.depth = True, 1
            self.elements.append((tag, attrs))

    def handle_endtag(self, tag):
        if self.depth and tag not in VOID:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def panel(html: str, element_id: str) -> str:
    """The text of the element with this id, its runs of white space made one space. AssertionError if it is missing."""
    p = _Panel(element_id)
    p.feed(html)
    assert p.found, f"no element with id {element_id!r}"
    return " ".join("".join(p.parts).split())


def panel_elements(html: str, element_id: str) -> list[tuple[str, dict]]:
    """The tags and attributes of the element with this id and of every element inside it, in page order."""
    p = _Panel(element_id)
    p.feed(html)
    assert p.found, f"no element with id {element_id!r}"
    return p.elements


def token(html: str) -> str:
    """The page token a form sends back (the meta element hub-token)."""
    return re.search(r'<meta name="hub-token" content="([^"]+)">', html).group(1)
