"""Regeln der nginx-Konfiguration des frontend-Containers (P3.6, ADR-0007).

Statisch geprueft, ohne Docker. Den laufenden Container pruefen die E2E-Tests (U5.2,
``docker/e2e.sh`` in der CI und mit ``make local-e2e``): nginx -t, Routen, /api ueber nginx,
Sicherheits-Header, return 444.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
CONF = FRONTEND / "nginx" / "default.conf.template"


def _conf() -> str:
    # Kommentare raus, damit nur wirksame Direktiven zaehlen
    return "\n".join(
        line.split("#", 1)[0] for line in CONF.read_text(encoding="utf-8").splitlines()
    )


def _server_blocks() -> list[str]:
    return [
        block for block in re.split(r"\n(?=server\s*\{)", _conf()) if block.startswith("server")
    ]


def test_unknown_hosts_get_no_answer():
    # DNS-Rebinding: nur bekannte Hostnamen bekommen eine Antwort
    [default] = [b for b in _server_blocks() if "default_server" in b]
    assert "return 444;" in default
    assert "listen 8080 default_server;" in default


def test_known_hosts_come_from_the_environment():
    [app] = [b for b in _server_blocks() if "default_server" not in b]
    assert "server_name ${VA_SERVER_NAMES};" in app


def test_api_goes_to_the_web_api_resolved_per_request():
    conf = _conf()
    # Variable + resolver: nginx startet auch, wenn das web-api noch nicht laeuft
    assert "resolver 127.0.0.11" in conf
    # ^~: Vorrang vor den Regex-Abschnitten fuer statische Dateien
    assert re.search(r"location \^~ /api/ \{[^}]*proxy_pass http://\$web_api", conf)
    assert 'set $web_api "web-api:8000";' in conf


def test_websocket_goes_to_the_web_api_with_upgrade():
    """P4.5: Upgrade-Header, Host mit Port fuer die Origin-Pruefung, lange Timeouts."""
    match = re.search(r"location = /ws \{(.*?)\n    \}", _conf(), re.S)
    assert match is not None
    block = match.group(1)
    assert "proxy_pass http://$web_api;" in block
    assert "proxy_set_header Upgrade $http_upgrade;" in block
    assert 'proxy_set_header Connection "upgrade";' in block
    assert "proxy_set_header Host $http_host;" in block
    timeout = re.search(r"proxy_read_timeout (\d+)s;", block)
    assert timeout is not None
    assert int(timeout.group(1)) > 60  # Uvicorn pingt alle 20 s


def test_angular_routes_fall_back_to_index_html():
    assert "try_files $uri $uri/ /index.html;" in _conf()


def test_security_headers():
    conf = _conf()
    for header in (
        'X-Content-Type-Options "nosniff"',
        'X-Frame-Options "DENY"',
        'Referrer-Policy "same-origin"',
        "Content-Security-Policy",
    ):
        assert f"add_header {header}" in conf, header
    csp = re.search(r'Content-Security-Policy "([^"]+)"', conf)
    assert csp
    assert "default-src 'self'" in csp.group(1)
    assert "script-src 'self'" in csp.group(1)
    assert "connect-src 'self'" in csp.group(1)


def test_production_build_needs_no_inline_script():
    # Die CSP erlaubt nur Skripte von 'self'. Angulars Critical-CSS-Inlining laedt das
    # Stylesheet mit media="print" und schaltet es per Inline-Skript um. Blockiert die CSP das,
    # greifen die globalen Styles nie (gefunden vom Browser-Test, U5.3).
    angular = json.loads((FRONTEND / "angular.json").read_text(encoding="utf-8"))
    build = angular["projects"]["va-frontend"]["architect"]["build"]
    production = build["configurations"]["production"]
    assert production["optimization"]["styles"]["inlineCritical"] is False


def test_index_html_is_never_cached():
    # expires statt add_header: Ein add_header in der location verwuerfe die Sicherheits-Header
    block = re.search(r"location = /index.html \{([^}]*)\}", _conf())
    assert block
    assert "expires -1;" in block.group(1)


class TestTrustChain:
    """D1.5 (nutzer.md Regel 10): Die Client-Adresse kommt nur vom DSM-Proxy, sonst sperrte die
    Sperre je IP alle gemeinsam, und ein Angreifer koennte ``X-Forwarded-For`` faelschen."""

    def test_the_real_address_only_from_the_trusted_proxy(self):
        conf = _conf()
        assert re.findall(r"set_real_ip_from ([^;]+);", conf) == ["${VA_TRUSTED_PROXY}"]
        assert "real_ip_header X-Forwarded-For;" in conf

    def test_not_recursive_so_the_last_address_counts(self):
        """Haengt der DSM-Proxy die echte Adresse an einen gefaelschten Kopf an, zaehlt sie."""
        assert "real_ip_recursive on" not in _conf()

    def test_the_web_api_gets_exactly_this_address(self):
        """Ueberschreiben statt anhaengen: Nichts vom Client reist bis zum web-api durch."""
        conf = _conf()
        assert "$proxy_add_x_forwarded_for" not in conf
        for location in ("location ^~ /api/", "location = /ws"):
            block = re.search(re.escape(location) + r" \{(.*?)\n    \}", conf, re.S)
            assert block is not None, location
            assert "proxy_set_header X-Forwarded-For $remote_addr;" in block.group(1)


def test_no_add_header_inside_locations():
    # nginx erbt add_header nur, wenn die location selbst keins setzt
    for location in re.findall(r"location [^{]+\{([^}]*)\}", _conf()):
        assert "add_header" not in location
