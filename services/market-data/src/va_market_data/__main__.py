"""``python -m va_market_data``: market-data als eigener Service (P5.1a)."""

import sys

from va_market_data.entrypoints.service import main

if __name__ == "__main__":
    sys.exit(main())
