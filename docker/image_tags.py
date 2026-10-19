"""Tags fuer das Image in GHCR (P0.6b). Laeuft in der CI vor dem Push, nur Standardbibliothek.

- ``sha-<commit>`` fuer jeden Push auf ``main`` und jeden Versions-Tag
- ``latest`` nur, wenn der Commit noch der Kopf von ``main`` ist: Ein nachgeholter alter
  Lauf setzt ``latest`` sonst auf einen alten Stand zurueck
- ``<version>`` bei einem Git-Tag ``vX.Y.Z``, der zur Version in pyproject.toml passt

Aufruf in der CI: ``python3 docker/image_tags.py`` gibt einen Tag je Zeile aus und endet
mit Exit 1, wenn ein Versions-Tag nicht passt - dann wird nichts gepusht.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
MAIN = "refs/heads/main"
TAG_PREFIX = "refs/tags/"


def image_tags(ref: str, sha: str, *, version: str, main_head: str | None) -> list[str]:
    """Tags fuer ``ref``/``sha``; leer, wenn fuer diesen Ref kein Image entsteht."""
    if ref == MAIN:
        return [f"sha-{sha[:7]}"] + (["latest"] if main_head == sha else [])
    if ref.startswith(TAG_PREFIX):
        name = ref.removeprefix(TAG_PREFIX)
        match = VERSION_TAG.match(name)
        if match is None:
            msg = f"Tag {name!r} ist keine Version der Form vX.Y.Z"
            raise ValueError(msg)
        if match.group(1) != version:
            msg = f"Tag {name!r} passt nicht zur Version {version!r} in pyproject.toml"
            raise ValueError(msg)
        return [f"sha-{sha[:7]}", version]
    return []


def _project_version() -> str:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def _main_head() -> str:
    out = subprocess.run(
        ["git", "ls-remote", "origin", MAIN],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return out.split()[0] if out else ""


def main() -> int:
    ref, sha = os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"]
    try:
        tags = image_tags(
            ref,
            sha,
            version=_project_version(),
            main_head=_main_head() if ref == MAIN else None,
        )
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    print("\n".join(tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
