"""Nur Tokens, nur Grau: Farbwerte stehen im UI an genau einer Stelle (Track G, Test 6).

Die Papier-Palette in ``frontend/src/styles/_paper.scss`` ist die einzige Quelle für Farben
(docs/architecture/ui-neugestaltung.md, Palette). Alle anderen Styles nehmen ``--mat-sys-*``.
Statisch geprüft, ohne Build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
SRC = FRONTEND / "src"
PAPER = SRC / "styles" / "_paper.scss"

# Einzige Ausnahme außerhalb der Palette: Die Mail bringt ihr eigenes helles Layout mit
ALLOWED = {("app/runs/run-detail-page.scss", "background-color: white;")}

HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
FUNCTION = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(")
NAMED = re.compile(
    r":[^;{}]*?(?<![-$\w.])"
    r"(white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy|teal)"
    r"(?![-\w])"
)

# Rollen der Palette, die hell und dunkel einen eigenen Wert brauchen (Spec, Tabelle Palette)
ROLES = [
    "surface",
    "surface-container-lowest",
    "surface-container-low",
    "surface-container",
    "surface-container-high",
    "surface-container-highest",
    "outline-variant",
    "outline",
    "on-surface-variant",
    "on-surface",
    "primary",
    "on-primary",
    "error",
    "on-error",
    "error-container",
    "on-error-container",
    "inverse-surface",
    "inverse-on-surface",
]


def _without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def _style_sources() -> list[tuple[str, str]]:
    """SCSS-Dateien und Inline-Styles der Komponenten, je als (Pfad relativ zu src, Text)."""
    sources = [
        (path.relative_to(SRC).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SRC.rglob("*.scss"))
        if path != PAPER
    ]
    for path in sorted((SRC / "app").rglob("*.ts")):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith("app/api/") or relative.endswith(".spec.ts"):
            continue
        for block in re.findall(r"styles:\s*`(.*?)`", path.read_text(encoding="utf-8"), re.DOTALL):
            sources.append((relative, block))
    return sources


def _literals(text: str) -> list[str]:
    found = []
    for line in _without_comments(text).splitlines():
        if HEX.search(line) or FUNCTION.search(line) or NAMED.search(line):
            found.append(line.strip())
    return found


SOURCES = _style_sources()


def test_sources_are_found() -> None:
    names = {name for name, _ in SOURCES}
    assert "styles/_patterns.scss" in names
    assert "app/shared/ui/run-status.ts" in names


@pytest.mark.parametrize(("name", "text"), SOURCES, ids=[name for name, _ in SOURCES])
def test_no_colour_literal_outside_the_palette(name: str, text: str) -> None:
    unexpected = [line for line in _literals(text) if (name, line) not in ALLOWED]
    assert unexpected == [], f"{name}: Farbwerte nur in _paper.scss, sonst --mat-sys-*"


def test_the_check_finds_literals() -> None:
    assert _literals("a { color: #fff; }")
    assert _literals("a { background: rgb(0 0 0 / 50%); }")
    assert _literals("a { border: 1px solid grey; }")
    assert not _literals("a { color: var(--mat-sys-on-surface); color-scheme: light dark; }")
    assert not _literals("// Kommentar mit #fff\na { margin: 0; }")


def _channels(value: str) -> tuple[int, int, int]:
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def test_palette_has_only_greys() -> None:
    values = HEX.findall(_without_comments(PAPER.read_text(encoding="utf-8")))
    assert values, "_paper.scss enthält keine Farben"
    colourful = [value for value in values if max(_channels(value)) - min(_channels(value)) > 16]
    assert colourful == [], "nur Grautöne und Papierfarbe (Kanäle höchstens 16 auseinander)"


def test_palette_sets_every_role_light_and_dark() -> None:
    text = _without_comments(PAPER.read_text(encoding="utf-8"))
    pairs = dict(
        re.findall(
            r"^\s*([a-z-]+):\s*light-dark\((#[0-9a-f]{6}),\s*#[0-9a-f]{6}\)", text, re.MULTILINE
        )
    )
    missing = [role for role in ROLES if role not in pairs]
    assert missing == [], "jede Rolle der Palette braucht light-dark(hell, dunkel)"
