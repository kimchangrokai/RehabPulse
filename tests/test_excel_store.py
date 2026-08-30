"""excel_store 테스트 — 엑셀 업서트."""

import pytest
from pathlib import Path

from rehabpulse.models import CaseRecord, GeneralContent, OrderRow, ChangeEvent
from rehabpulse.store.excel_store import ExcelStore


@pytest.fixture
def store(tmp_path):
    """임시 디렉터리의 ExcelStore."""
    s = ExcelStore(
        path=tmp_path / "test.xlsx",
        backup_dir=tmp_path / "backup",
    )
    s.load()
    return s


class TestAddCase:
    """사건 등록."""

    def test_add_new(self, store):
        record = CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리",
        )
        assert store.add_case(record) is True

    def test_add_duplicate(self, store):
        record = CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리",
        )
        store.add_case(record)
        assert store.add_case(record) is False


class TestRemoveCase:
    """사건 비활성화/삭제."""

    def test_deactivate(self, store):
        record = CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리",
        )
        store.add_case(record)
        assert store.remove_case("인천지방법원", "2024개회176313") is True
        cases = store.get_active_cases()
        assert len(cases) == 0

    def test_purge(self, store):
        record = CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리",
        )
        store.add_case(record)
        assert store.remove_case("인천지방법원", "2024개회176313", purge=True) is True
        # 사건목록에 행이 없어야 함
        ws = store.wb["사건목록"]
        assert ws.max_row == 1  # 헤더만


class TestGetActiveCases:
    """활성 사건 조회."""

    def test_returns_active_only(self, store):
        store.add_case(CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리", active="Y",
        ))
        store.add_case(CaseRecord(
            court="서울회생법원", case_no="2024개회1082687",
            year="2024", case_type="개회", serial="1082687",
            party="이지혜", active="N",
        ))
        cases = store.get_active_cases()
        assert len(cases) == 1
        assert cases[0].party == "박미리"


class TestGeneralUpsert:
    """일반내용 업서트."""

    def test_insert_new(self, store):
        g = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            case_name="개인회생", commencement_date="2025.01.15",
        )
        result = store.upsert_general(g, "박미리")
        assert result["changed"] is True
        assert result["old_hash"] is None

    def test_idempotent(self, store):
        g = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            case_name="개인회생", commencement_date="2025.01.15",
        )
        store.upsert_general(g, "박미리")
        result = store.upsert_general(g, "박미리")
        assert result["changed"] is False

    def test_update_on_change(self, store):
        g1 = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            plan_approved_date="",
        )
        store.upsert_general(g1, "박미리")

        g2 = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            plan_approved_date="2025.06.01",
        )
        result = store.upsert_general(g2, "박미리")
        assert result["changed"] is True

    def test_read_general(self, store):
        g = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            case_name="개인회생", plan_approved_date="2025.06.01",
        )
        store.upsert_general(g, "박미리")
        data = store.read_general("인천지방법원", "2024개회176313")
        assert data is not None
        assert data["plan_approved_date"] == "2025.06.01"


class TestOrderUpsert:
    """진행명령 업서트."""

    def test_insert_new(self, store):
        orders = [
            OrderRow(court="인천지방법원", case_no="2024개회176313",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ]
        result = store.upsert_orders(orders, "박미리")
        assert result["added"] == 1

    def test_idempotent(self, store):
        orders = [
            OrderRow(court="인천지방법원", case_no="2024개회176313",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ]
        store.upsert_orders(orders, "박미리")
        result = store.upsert_orders(orders, "박미리")
        assert result["added"] == 0
        assert result["updated"] == 0

    def test_update_on_change(self, store):
        orders1 = [
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ]
        store.upsert_orders(orders1, "박미리")

        orders2 = [
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result="확정"),
        ]
        result = store.upsert_orders(orders2, "박미리")
        assert result["updated"] == 1

    def test_removed_flag(self, store):
        orders = [
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ]
        store.upsert_orders(orders, "박미리")
        result = store.upsert_orders([], "박미리", court="인천", case_no="2024개회1")
        assert result["removed"] == 1

    def test_other_case_untouched(self, store):
        store.upsert_orders([
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ], "박미리")
        store.upsert_orders([
            OrderRow(court="서울회생법원", case_no="2024개회2",
                     date="2025.01.01", category="개시결정",
                     content="개인회생절차개시결정", result=""),
        ], "이지혜")
        store.upsert_orders([], "박미리", court="인천", case_no="2024개회1")
        other = store.read_orders("서울회생법원", "2024개회2")
        assert len(other) == 1
        assert other[0]["content"] == "개인회생절차개시결정"

    def test_read_orders(self, store):
        orders = [
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
        ]
        store.upsert_orders(orders, "박미리")
        data = store.read_orders("인천", "2024개회1")
        assert len(data) == 1
        assert data[0]["content"] == "기각결정"


class TestHistoryAndRunlog:
    """이력·로그."""

    def test_append_history(self, store):
        ev = ChangeEvent(
            court="인천", case_no="2024개회1",
            party="박미리", event="PLAN_APPROVED", detail="test",
        )
        store.append_history(ev)
        ws = store.wb["변경이력"]
        assert ws.max_row == 2  # 헤더 + 1행

    def test_append_runlog(self, store):
        store.append_runlog(6, 5, 1, 0, "test run")
        ws = store.wb["실행로그"]
        assert ws.max_row == 2


class TestArchiveCase:
    """종료목록."""

    def test_archive(self, store):
        store.archive_case("인천", "2024개회1", "박미리")
        ws = store.wb["종료목록"]
        assert ws.max_row == 2


class TestSaveAndLoad:
    """저장·로드."""

    def test_save_and_reload(self, store):
        record = CaseRecord(
            court="인천지방법원", case_no="2024개회176313",
            year="2024", case_type="개회", serial="176313",
            party="박미리",
        )
        store.add_case(record)
        store.save()

        # 다시 로드
        store2 = ExcelStore(store.path, store.backup_dir)
        store2.load()
        cases = store2.get_active_cases()
        assert len(cases) == 1
        assert cases[0].party == "박미리"


class TestBackup:
    """백업."""

    def test_backup_created(self, store):
        store.save()
        # 데이터 추가 후 다시 저장
        store.add_case(CaseRecord(
            court="인천", case_no="2024개회1",
            year="2024", case_type="개회", serial="1",
            party="테스트",
        ))
        store.save()
        backups = list(store.backup_dir.glob("*.xlsx"))
        assert len(backups) >= 1
