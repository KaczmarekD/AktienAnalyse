"""``python -m va_scoring``: scoring als eigener Service (P5.1a)."""

import sys

from va_scoring.entrypoints.service import main

if __name__ == "__main__":
    sys.exit(main())
