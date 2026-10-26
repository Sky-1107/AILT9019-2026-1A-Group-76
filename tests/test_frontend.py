"""Static consistency checks for the frontend (no browser needed).

Guards against the regression where main.js references a DOM id/class that does
not exist in index.html (a null reference that silently breaks result rendering).
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

JS = (STATIC / "main.js").read_text(encoding="utf-8")
HTML = (TEMPLATES / "index.html").read_text(encoding="utf-8")


def test_every_get_element_by_id_exists_in_html():
    ids = re.findall(r'getElementById\("([^"]+)"\)', JS)
    assert ids, "expected main.js to reference DOM ids"
    missing = [i for i in ids if f'id="{i}"' not in HTML]
    assert not missing, f"main.js references missing ids: {missing}"


def test_every_class_query_selector_exists_in_html():
    classes = re.findall(r'querySelector\("\.([A-Za-z0-9_-]+)"\)', JS)
    assert classes, "expected main.js to reference DOM classes"
    html_classes = set(
        token
        for attr in re.findall(r'class="([^"]+)"', HTML)
        for token in attr.split()
    )
    missing = [c for c in classes if c not in html_classes]
    assert not missing, f"main.js references missing classes: {missing}"


def test_no_inner_html_assignment():
    # Model output must be inserted via textContent only.
    assert not re.search(r"\.innerHTML\s*=", JS)
    assert not re.search(r"\.outerHTML\s*=", JS)
    assert "document.write" not in JS


def test_no_cdn_references():
    assert not re.search(r"https?://", JS), "main.js must not reference remote URLs"
    assert not re.search(r"(src|href)=\"https?://", HTML), "index.html must not use CDNs"
