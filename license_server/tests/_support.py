from __future__ import annotations

import sys
from pathlib import Path

LICENSE_SERVER_ROOT = Path(__file__).resolve().parents[1]
root_text = str(LICENSE_SERVER_ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)
