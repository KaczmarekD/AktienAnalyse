"""Tags der Images in GHCR (docker/image_tags.py, P0.6b/P0.8).

Das Skript laeuft in der CI vor dem Push. Ein Fehler hier bricht den Push ab, bevor
irgendein Tag in GHCR landet.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "docker" / "image_tags.py"
SHA = "0123456789abcdef0123456789abcdef01234567"


def _load():
    spec = importlib.util.spec_from_file_location("image_tags", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image_tags = _load().image_tags


class TestMain:
    def test_head_of_main_gets_sha_and_latest(self):
        tags = image_tags("refs/heads/main", SHA, version="0.3.0", main_head=SHA)
        assert tags == ["sha-0123456", "latest"]

    def test_rerun_of_an_older_main_run_keeps_latest(self):
        """Ein nachgeholter alter Lauf darf latest nicht auf einen alten Commit zuruecksetzen."""
        tags = image_tags("refs/heads/main", SHA, version="0.3.0", main_head="f" * 40)
        assert tags == ["sha-0123456"]


class TestVersionTags:
    def test_version_tag_matching_pyproject(self):
        assert image_tags("refs/tags/v0.3.0", SHA, version="0.3.0", main_head=None) == [
            "sha-0123456",
            "0.3.0",
        ]

    def test_version_must_match_pyproject(self):
        with pytest.raises(ValueError, match=r"pyproject"):
            image_tags("refs/tags/v0.4.0", SHA, version="0.3.0", main_head=None)

    @pytest.mark.parametrize("tag", ["v1.0", "v1.0.0+build", "v1.0.0-rc1", "vx.y.z", "1.0.0"])
    def test_only_plain_versions(self, tag):
        with pytest.raises(ValueError, match=r"vX\.Y\.Z"):
            image_tags(f"refs/tags/{tag}", SHA, version="1.0.0", main_head=None)


class TestOtherRefs:
    @pytest.mark.parametrize("ref", ["refs/heads/feat/p0-8-infra", "refs/pull/1/merge"])
    def test_no_image(self, ref):
        assert image_tags(ref, SHA, version="0.3.0", main_head=None) == []
