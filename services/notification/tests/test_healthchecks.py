"""Heartbeat-Adapter fuer Healthchecks.io (P1.6), gegen ein Fake-HTTP (requests gepatcht)."""

from __future__ import annotations

from unittest.mock import patch

import requests

from va_notification.adapters.healthchecks import HealthchecksHeartbeat, ping, ping_target


class TestPing:
    def test_no_url_is_noop(self):
        # Sollte ohne Exception zurueckkehren
        assert ping(None, success=True) is None
        assert ping("", success=False) is None

    def test_success_pings_base_url(self):
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            assert ping("https://hc-ping.com/abc", success=True, message="ok") is True
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "https://hc-ping.com/abc"

    def test_failure_appends_fail(self):
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            ping("https://hc-ping.com/abc", success=False, message="err")
            args, kwargs = mock_post.call_args
            assert args[0] == "https://hc-ping.com/abc/fail"

    def test_failure_swallows_exception(self):
        with patch(
            "va_notification.adapters.healthchecks.requests.post",
            side_effect=requests.RequestException("boom"),
        ):
            # Sollte NICHT crashen - Healthcheck darf den Run nie zum Scheitern bringen
            assert ping("https://hc-ping.com/abc", success=True) is False

    def test_http_error_counts_as_failure(self):
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("404")
            assert ping("https://hc-ping.com/abc", success=True) is False


class TestPingLogging:
    URL = "https://hc-ping.com/1234-geheim-abcd"

    def test_failure_log_contains_no_uuid(self, caplog):
        error = requests.HTTPError(f"404 Client Error for url: {self.URL}/fail")
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = error
            ping(self.URL, success=False)
        assert "geheim" not in caplog.text
        assert "hc-ping.com" in caplog.text

    def test_connection_error_log_contains_no_uuid(self, caplog):
        error = requests.ConnectionError(f"Max retries exceeded with url: {self.URL}")
        with patch("va_notification.adapters.healthchecks.requests.post", side_effect=error):
            ping(self.URL, success=True)
        assert "geheim" not in caplog.text


class TestPingTarget:
    def test_only_host_is_exposed(self):
        # Die UUID in der URL ist ein Geheimnis und darf nicht in die DB
        assert ping_target("https://hc-ping.com/1234-abcd") == "hc-ping.com"
        assert ping_target(None) is None


class TestHeartbeatPort:
    def test_heartbeat_pings_its_url(self):
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            assert HealthchecksHeartbeat("https://hc-ping.com/abc").ping(False, "kaputt") is True
        assert mock_post.call_args.args[0] == "https://hc-ping.com/abc/fail"

    def test_without_url_nothing_happens(self):
        with patch("va_notification.adapters.healthchecks.requests.post") as mock_post:
            assert HealthchecksHeartbeat(None).ping(True) is None
        mock_post.assert_not_called()
