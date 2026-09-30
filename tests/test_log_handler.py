"""Tests fuer den Log-Puffer, der die Log-Zeilen eines Laufs in die DB bringt."""

from __future__ import annotations

import logging

from src.db.log_handler import BufferingLogHandler


def _logger(handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger("test.buffer")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


class TestBufferingLogHandler:
    def test_collects_formatted_records_from_info_upwards(self):
        handler = BufferingLogHandler()
        log = _logger(handler)
        log.debug("nicht speichern")
        log.info("(%d/%d) %s", 1, 2, "SAP.DE")
        log.warning("yfinance zickt")

        assert [(e.level, e.logger, e.message) for e in handler.entries] == [
            ("INFO", "test.buffer", "(1/2) SAP.DE"),
            ("WARNING", "test.buffer", "yfinance zickt"),
        ]
        assert handler.entries[0].ts.tzinfo is not None

    def test_exception_text_is_kept(self):
        handler = BufferingLogHandler()
        log = _logger(handler)
        try:
            raise ValueError("kaputt")
        except ValueError:
            log.exception("Fehler im Run")
        assert "ValueError: kaputt" in handler.entries[0].message

    def test_buffer_is_bounded(self):
        handler = BufferingLogHandler(max_entries=3)
        log = _logger(handler)
        for i in range(5):
            log.info("zeile %d", i)
        assert [e.message for e in handler.entries][-1].startswith("Log-Puffer voll")
        assert len(handler.entries) == 4
