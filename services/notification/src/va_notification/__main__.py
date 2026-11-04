"""``python -m va_notification``: notification als eigener Service (P5.1a)."""

import sys

from va_notification.entrypoints.service import main

if __name__ == "__main__":
    sys.exit(main())
