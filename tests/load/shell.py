"""The static files Streamlit's page shell names; kept free of Locust so tests can import it."""

import re

_ASSET = re.compile(r'(?:src|href)="\./(static/[^"]+)"')


def static_paths(html: str) -> list[str]:
    """Every ./static/... path named by a src= or href= attribute, as /static/..., without
    duplicates, in page order."""
    return list(dict.fromkeys(f"/{path}" for path in _ASSET.findall(html)))
