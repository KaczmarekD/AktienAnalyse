"""``python -m src.regression`` - siehe ``src.regression.cli``."""

from __future__ import annotations

import logging
import sys

from .cli import main

if __name__ == "__main__":
    # Die Handler loggen jeden Schritt; fuer den Vergleich reicht, was schiefgeht
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s | %(message)s")
    sys.exit(main())
