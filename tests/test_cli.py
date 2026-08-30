"""CLI 테스트 — 명령어 파싱."""

import pytest
from rehabpulse.cli import _parse_case_arg


class TestParseCaseArg:
    """사건번호 파싱."""

    def test_standard(self):
        court, year, case_type, serial, case_no = _parse_case_arg(
            "인천지방법원 2024개회176313"
        )
        assert court == "인천지방법원"
        assert year == "2024"
        assert case_type == "개회"
        assert serial == "176313"
        assert case_no == "2024개회176313"

    def test_seoul_rehab(self):
        court, year, case_type, serial, case_no = _parse_case_arg(
            "서울회생법원 2024개회1082687"
        )
        assert court == "서울회생법원"
        assert case_no == "2024개회1082687"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="사건번호 형식 오류"):
            _parse_case_arg("invalid")

    def test_missing_serial(self):
        with pytest.raises(ValueError):
            _parse_case_arg("인천지방법원 2024개회")
