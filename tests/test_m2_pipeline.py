"""M2 고정 테스트 — PLAN_APPROVED, DISMISSED, CASE_ARCHIVED.

PRD §6.3: 이 세 이벤트를 테스트로 고정한다.
재실행 시 동일 스냅샷은 알림 이벤트가 없어야 한다.
"""

from rehabpulse.models import GeneralContent, OrderRow
from rehabpulse.judge.judge import (
    judge_snapshot,
    classify_attempts,
    apply_miss_day,
    notifiable,
    build_email_subject,
    build_email_body,
)
from rehabpulse.store.excel_store import ExcelStore


COURT = "인천지방법원"
CASE_NO = "2024개회176313"
PARTY = "박미리"


def _general(**kwargs) -> GeneralContent:
    defaults = dict(court=COURT, case_no=CASE_NO)
    defaults.update(kwargs)
    return GeneralContent(**defaults)


def _order(date: str, content: str, result: str = "") -> OrderRow:
    return OrderRow(
        court=COURT, case_no=CASE_NO,
        date=date, category=content, content=content, result=result,
    )


PARK_MIRI_ORDERS = [
    _order("2025.02.18", "개인회생절차개시신청 기각결정"),
    _order("2025.03.05", "기각취소결정"),
    _order("2025.09.08", "개인회생절차개시신청 기각결정"),
]


def _as_dicts(orders: list[OrderRow]) -> list[dict]:
    return [
        {"court": o.court, "case_no": o.case_no, "date": o.date,
         "content": o.content, "result": o.result}
        for o in orders
    ]


class TestInitialLoad:
    def test_first_collect_is_initial_only(self):
        events, initial = judge_snapshot(
            None, [], _general(), PARK_MIRI_ORDERS, PARTY,
        )
        assert initial is True
        assert [e.event for e in events] == ["INITIAL_LOAD"]
        assert notifiable(events) == []


class TestResyncIdempotent:
    def test_same_snapshot_no_notify(self):
        """같은 데이터를 다시 비교하면 신규 알림이 없다."""
        old_g = {
            "commencement_date": "", "plan_approved_date": "",
            "discharge_date": "", "revocation_date": "", "terminal_result": "",
        }
        events, initial = judge_snapshot(
            old_g, _as_dicts(PARK_MIRI_ORDERS),
            _general(), PARK_MIRI_ORDERS, PARTY,
        )
        assert initial is False
        assert events == []
        assert notifiable(events) == []


class TestPlanApproved:
    def test_date_blank_to_value(self):
        old_g = {"plan_approved_date": ""}
        events, _ = judge_snapshot(
            old_g, [],
            _general(plan_approved_date="2025.06.01"),
            [], PARTY,
        )
        types = [e.event for e in events]
        assert "PLAN_APPROVED" in types
        assert notifiable(events)

    def test_new_approval_order(self):
        old_g = {"plan_approved_date": ""}
        new_orders = PARK_MIRI_ORDERS + [
            _order("2025.10.01", "변제계획인가결정"),
        ]
        events, _ = judge_snapshot(
            old_g, _as_dicts(PARK_MIRI_ORDERS),
            _general(), new_orders, PARTY,
        )
        types = [e.event for e in events]
        assert "NEW_ORDER" in types
        assert "PLAN_APPROVED" in types
        assert "DISMISSED" not in types  # 기존 기각은 신규가 아님

    def test_date_and_order_deduped(self):
        old_g = {"plan_approved_date": ""}
        events, _ = judge_snapshot(
            old_g, [],
            _general(plan_approved_date="2025.06.01"),
            [_order("2025.06.01", "변제계획인가결정")],
            PARTY,
        )
        approved = [e for e in events if e.event == "PLAN_APPROVED"]
        assert len(approved) == 1

    def test_dry_run_mail_body(self):
        events, _ = judge_snapshot(
            {"plan_approved_date": ""}, [],
            _general(plan_approved_date="2025.06.01"),
            [_order("2025.06.01", "변제계획인가결정")],
            PARTY,
        )
        subject = build_email_subject(notifiable(events), PARTY)
        assert subject == f"[RehabPulse] {PARTY} 변제계획인가결정"
        body = build_email_body(
            notifiable(events),
            {"plan_approved_date": "2025.06.01", "commencement_date": "",
             "discharge_date": "", "terminal_result": ""},
            [{"date": "2025.06.01", "content": "변제계획인가결정", "result": ""}],
        )
        assert "변제계획인가결정" in body
        assert "2025.06.01" in body
        assert "(공란)" in body


class TestDismissed:
    def test_new_dismissal_order(self):
        old_g = {"plan_approved_date": ""}
        old_orders = [
            _order("2025.03.05", "기각취소결정"),
        ]
        new_orders = old_orders + [
            _order("2025.09.08", "개인회생절차개시신청 기각결정"),
        ]
        events, _ = judge_snapshot(
            old_g, _as_dicts(old_orders),
            _general(), new_orders, PARTY,
        )
        types = [e.event for e in events]
        assert "DISMISSED" in types
        assert "NEW_ORDER" in types
        assert notifiable(events)

    def test_existing_dismissal_not_refired(self):
        old_g = {"plan_approved_date": ""}
        events, _ = judge_snapshot(
            old_g, _as_dicts(PARK_MIRI_ORDERS),
            _general(), PARK_MIRI_ORDERS, PARTY,
        )
        assert "DISMISSED" not in [e.event for e in events]


class TestCaseArchived:
    def test_day1_and_day2_not_archived(self):
        d1, ev1 = apply_miss_day(COURT, CASE_NO, PARTY, 0)
        assert d1 == 1
        assert [e.event for e in ev1] == ["MISS_DAY"]
        assert notifiable(ev1) == []

        d2, ev2 = apply_miss_day(COURT, CASE_NO, PARTY, 1)
        assert d2 == 2
        assert [e.event for e in ev2] == ["MISS_DAY"]
        assert notifiable(ev2) == []

    def test_day3_archives(self):
        d3, ev3 = apply_miss_day(COURT, CASE_NO, PARTY, 2)
        assert d3 == 3
        types = [e.event for e in ev3]
        assert "MISS_DAY" in types
        assert "CASE_ARCHIVED" in types
        notify = notifiable(ev3)
        assert [e.event for e in notify] == ["CASE_ARCHIVED"]
        subject = build_email_subject(notify, PARTY)
        assert "사건 종료(3일 연속 조회 없음)" in subject


class TestClassifyAttempts:
    def test_two_not_found_is_miss(self):
        assert classify_attempts(["not_found", "not_found"]) == "miss"

    def test_one_success_is_success(self):
        assert classify_attempts(["not_found", "success"]) == "success"
        assert classify_attempts(["success"]) == "success"

    def test_captcha_is_not_miss(self):
        assert classify_attempts(["captcha_error", "captcha_error"]) == "error"
        assert classify_attempts(["not_found", "error"]) == "error"

    def test_empty_or_single_not_found_is_not_miss(self):
        assert classify_attempts([]) == "error"
        assert classify_attempts(["not_found"]) == "error"


class TestExcelRoundtrip:
    """엑셀에 심고 다시 비교하면 알림이 없고, 인가 행을 심으면 PLAN_APPROVED."""

    def test_upsert_twice_no_notify(self, tmp_path):
        store = ExcelStore(tmp_path / "t.xlsx", tmp_path / "backup")
        store.load()
        g = _general()
        store.upsert_general(g, PARTY)
        store.upsert_orders(PARK_MIRI_ORDERS, PARTY)

        old_g = store.read_general(COURT, CASE_NO)
        old_o = store.read_orders(COURT, CASE_NO)
        events, initial = judge_snapshot(old_g, old_o, g, PARK_MIRI_ORDERS, PARTY)
        assert initial is False
        assert notifiable(events) == []

    def test_inject_approval_order(self, tmp_path):
        store = ExcelStore(tmp_path / "t.xlsx", tmp_path / "backup")
        store.load()
        g = _general()
        store.upsert_general(g, PARTY)
        store.upsert_orders(PARK_MIRI_ORDERS, PARTY)

        old_g = store.read_general(COURT, CASE_NO)
        old_o = store.read_orders(COURT, CASE_NO)
        planted = PARK_MIRI_ORDERS + [_order("2025.10.01", "변제계획인가결정")]
        events, _ = judge_snapshot(old_g, old_o, g, planted, PARTY)
        assert "PLAN_APPROVED" in [e.event for e in notifiable(events)]
