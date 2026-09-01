"""CLI 테스트 — 명령어 파싱."""

from pathlib import Path

import pytest
from rehabpulse.cli import _parse_case_arg, _workbook_attachments


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


class TestWorkbookAttachments:
    def test_default_false(self, tmp_path: Path):
        wb = tmp_path / "rehabpulse.xlsx"
        wb.write_bytes(b"xlsx")
        assert _workbook_attachments({"paths": {"workbook": str(wb)}}) is None

    def test_explicit_false(self, tmp_path: Path):
        wb = tmp_path / "rehabpulse.xlsx"
        wb.write_bytes(b"xlsx")
        settings = {
            "paths": {"workbook": str(wb)},
            "email": {"attach_workbook": False},
        }
        assert _workbook_attachments(settings) is None

    def test_true_attaches_file(self, tmp_path: Path):
        wb = tmp_path / "rehabpulse.xlsx"
        wb.write_bytes(b"xlsx")
        settings = {
            "paths": {"workbook": str(wb)},
            "email": {"attach_workbook": True},
        }
        result = _workbook_attachments(settings)
        assert result == [("rehabpulse.xlsx", b"xlsx")]

    def test_true_missing_file(self, tmp_path: Path):
        settings = {
            "paths": {"workbook": str(tmp_path / "missing.xlsx")},
            "email": {"attach_workbook": True},
        }
        assert _workbook_attachments(settings) is None
