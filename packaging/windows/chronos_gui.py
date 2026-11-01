"""Chronos.exe — the window. `Chronos.exe --selftest report.txt` checks the build."""
import sys

from chronos.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
