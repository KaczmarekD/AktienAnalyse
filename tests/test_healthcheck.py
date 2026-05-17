"""Tests fuer den Healthcheck-Ping."""

from __future__ import annotations

from unittest.mock import patch

import requests

from src.healthcheck import ping


class TestPing:
    def test_no_url_is_noop(self):
        # Sollte ohne Exception zurueckkehren
        ping(None, success=True)
        ping("", success=False)

    def test_success_pings_base_url(self):
        with patch("src.healthcheck.requests.post") as mock_post:
            ping("https://hc-ping.com/abc", success=True, message="ok")
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "https://hc-ping.com/abc"

    def test_failure_appends_fail(self):
        with patch("src.healthcheck.requests.post") as mock_post:
            ping("https://hc-ping.com/abc", success=False, message="err")
            args, kwargs = mock_post.call_args
            assert args[0] == "https://hc-ping.com/abc/fail"

    def test_failure_swallows_exception(self):
        with patch("src.healthcheck.requests.post", side_effect=requests.RequestException("boom")):
            # Sollte NICHT crashen - Healthcheck darf den Run nie zum Scheitern bringen
            ping("https://hc-ping.com/abc", success=True)
