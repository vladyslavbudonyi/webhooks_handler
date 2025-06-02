from typing import Tuple
from urllib.parse import urlparse


def parse_url_components(full_url: str) -> Tuple[str, str, str]:
    parsed = urlparse(full_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Expected at least tenant/instance in URL path: {full_url}")
    tenant = parts[0]
    instance = parts[1]
    return base, tenant, instance
