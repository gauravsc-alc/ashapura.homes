"""
content_loader.py — Reads all JSON and Markdown files from content/
and returns a single context dict for the Django view.

To add new content:
  - Portfolio project → edit content/portfolio.json
  - Service card      → edit content/services.json
  - Process step      → edit content/process.json
  - Site settings     → edit content/config.json
  - Page text         → edit content/pages/home.md
"""

import json
import markdown
from pathlib import Path
from django.conf import settings

CONTENT_DIR = Path(settings.CONTENT_DIR)
STATIC_DIR = Path(settings.BASE_DIR) / "static"


def _load_json(filename: str) -> dict | list:
    path = CONTENT_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _load_markdown(filename: str) -> str:
    path = CONTENT_DIR / "pages" / filename
    raw = path.read_text(encoding="utf-8")
    return markdown.markdown(raw, extensions=["extra", "nl2br"])


def load_service_icon(icon_path: str) -> str:
    """Return inline SVG markup for a service icon.

    The icon field holds a path such as ``icons/bungalow.svg``. Rendering that
    path directly would print the filename as visible text, so the SVG source is
    read from ``static/`` and inlined instead. The colour comes from
    ``currentColor`` in each icon, so it follows the surrounding text colour.

    Returns an empty string when the icon file is missing, which lets the
    template fall back gracefully instead of printing a broken path.
    """
    if not icon_path:
        return ""
    candidate = (STATIC_DIR / icon_path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        # Refuse paths that escape the static directory.
        return ""
    if not candidate.is_file() or candidate.suffix.lower() != ".svg":
        return ""
    markup = candidate.read_text(encoding="utf-8")
    # Strip the XML prolog if present; inline SVG must not carry it.
    if markup.lstrip().startswith("<?xml"):
        markup = markup.split("?>", 1)[-1]
    return markup.strip()


def _prepare_services(services: list[dict]) -> list[dict]:
    """Attach inline icon markup to each service card."""
    prepared = []
    for service in services:
        item = dict(service)
        item["icon_svg"] = load_service_icon(item.get("icon", ""))
        prepared.append(item)
    return prepared


def get_home_context() -> dict:
    return {
        "config":     _load_json("config.json"),
        "page_content": _load_json("page_metadata.json"),
        "portfolio":  _load_json("portfolio.json"),
        "services":   _prepare_services(_load_json("services.json")),
        "process":    _load_json("process.json"),
        "intro_html": _load_markdown("home.md"),
    }
