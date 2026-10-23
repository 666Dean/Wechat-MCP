# SPDX-License-Identifier: MIT
"""Fixed development bootstrap for isolated Python; no caller module argument."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop.windows_setup import main
if __name__=='__main__':raise SystemExit(main())
