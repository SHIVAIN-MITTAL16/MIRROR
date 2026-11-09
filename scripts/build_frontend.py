"""Copy the static frontend and inject a validated public API origin for deployment."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontened"
DESTINATION = ROOT / "build" / "frontend"


def main() -> None:
    api_base = os.getenv("MIRROR_API_BASE_URL", "http://127.0.0.1:8002").strip().rstrip("/")
    parsed = urlparse(api_base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise SystemExit("MIRROR_API_BASE_URL must be an absolute HTTP(S) origin without credentials or query data")
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    shutil.copytree(SOURCE, DESTINATION)
    index = DESTINATION / "index.html"
    content = index.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(<meta\s+name="mirror-api-base-url"\s+content=")[^"]*("\s*/?>)',
        lambda match: match.group(1) + api_base.replace("&", "&amp;").replace('"', "&quot;") + match.group(2),
        content,
        count=1,
        flags=re.IGNORECASE,
    )
    if count != 1:
        raise SystemExit("Frontend index is missing its MIRROR API base URL meta tag")
    index.write_text(updated, encoding="utf-8")
    print(f"Built static frontend with API origin {api_base}")


if __name__ == "__main__":
    main()
