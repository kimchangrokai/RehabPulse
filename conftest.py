"""pytest 루트 설정 — tests/에서 패키지 import 가능하게."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def pytest_configure(config):
    config.addinivalue_line("markers", "live: 실제 ssgo 사이트에 접속하는 테스트")
