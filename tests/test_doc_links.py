"""Link-Check der Doku (P5.6): Jeder relative Link in den Markdown-Dateien des Repos fuehrt zu
einer vorhandenen Datei, ein Anker zu einer Ueberschrift dort.

Externe Links (http, mailto) prueft der Test nicht, er laeuft ohne Netz. Codebloecke und
Inline-Code zaehlen nicht als Link. Anker folgen den Regeln von GitHub: klein geschrieben,
Satzzeichen entfernt, Leerzeichen zu Bindestrichen, doppelte Ueberschriften mit ``-1``, ``-2``.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Was nicht zum Repo gehoert oder nur Werkzeug-Stand ist
SKIP_DIRS = {
    ".git",
    ".venv",
    ".local",
    ".claude",
    "node_modules",
    "pgdata",
    "natsdata",
    "logs",
    "backups",
    "dist",
    ".angular",
    ".pytest_cache",
    ".ruff_cache",
}

FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in parts[:-1]):
            continue
        files.append(path)
    return sorted(files)


def _prose(text: str) -> str:
    return INLINE_CODE.sub("", FENCE.sub("", text))


def _slug(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # Link in der Ueberschrift
    text = INLINE_CODE.sub(lambda m: m.group(0).strip("`"), text)
    text = text.strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    anchors: set[str] = set(HTML_ANCHOR.findall(text))
    seen: dict[str, int] = {}
    for heading in HEADING.findall(text):
        slug = _slug(heading)
        count = seen.get(slug, 0)
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return anchors


def _broken(path: Path) -> list[str]:
    broken: list[str] = []
    for target in LINK.findall(_prose(path.read_text(encoding="utf-8"))):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
            continue
        file_part, _, anchor = target.partition("#")
        resolved = (path.parent / unquote(file_part)).resolve() if file_part else path
        if not resolved.exists():
            broken.append(f"{target}: Datei fehlt")
            continue
        if anchor and resolved.suffix == ".md" and unquote(anchor) not in _anchors(resolved):
            broken.append(f"{target}: Anker fehlt")
    return broken


FILES = _markdown_files()


def test_the_check_sees_the_docs():
    names = {path.relative_to(ROOT).as_posix() for path in FILES}
    assert {"README.md", "CLAUDE.md", "docs/README.md"} <= names
    assert any(name.startswith("docs/adr/") for name in names)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(path: Path):
    assert _broken(path) == []


def test_slugs_follow_github():
    # Der Gedankenstrich faellt weg, die beiden Leerzeichen um ihn werden zu "--"
    dash = chr(0x2013)  # Halbgeviertstrich wie in den Ueberschriften des Plans
    assert _slug(f"Phase 5 {dash} Aufteilen in Services") == "phase-5--aufteilen-in-services"
    assert _slug("Sicherheitsregeln (LAN, ohne Login)") == "sicherheitsregeln-lan-ohne-login"
    assert _slug("P5.4 Scheduler im web-api") == "p54-scheduler-im-web-api"
    assert _slug("`make check` läuft") == "make-check-läuft"
