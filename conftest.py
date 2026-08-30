"""pytest 루트 설정 — tests/에서 패키지 import 가능하게."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
