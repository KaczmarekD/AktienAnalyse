"""``python -m va_portfolio``: portfolio als eigener Service (D3.1)."""

import sys

from va_portfolio.entrypoints.service import main

if __name__ == "__main__":
    sys.exit(main())
