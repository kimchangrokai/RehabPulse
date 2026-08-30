"""differ 테스트 — 스냅샷 비교 로직."""

from rehabpulse.models import GeneralContent, OrderRow
from rehabpulse.diff.differ import diff_general, diff_orders, diff_case


class TestDiffGeneral:
    """일반내용 변경 탐지."""

    def test_no_change(self):
        old = {"commencement_date": "2025.01.15", "plan_approved_date": ""}
        new = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            commencement_date="2025.01.15", plan_approved_date="",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 0

    def test_plan_approved(self):
        old = {"plan_approved_date": ""}
        new = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            plan_approved_date="2025.06.01",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "PLAN_APPROVED"
        assert "박미리" in events[0].party

    def test_commenced(self):
        old = {"commencement_date": ""}
        new = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            commencement_date="2025.01.15",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "COMMENCED"

    def test_discharged(self):
        old = {"discharge_date": ""}
        new = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            discharge_date="2026.03.01",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "DISCHARGED"

    def test_terminal_result(self):
        old = {"terminal_result": ""}
        new = GeneralContent(
            court="인천지방법원", case_no="2024개회176313",
            terminal_result="종국",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "TERMINAL"

    def test_old_none_returns_empty(self):
        """old=None은 첫 수집으로 INITIAL_LOAD에서 처리."""
        new = GeneralContent(court="인천", case_no="2024개회1")
        events = diff_general(None, new, "박미리")
        assert len(events) == 0

    def test_multiple_changes(self):
        old = {"commencement_date": "", "plan_approved_date": ""}
        new = GeneralContent(
            court="인천", case_no="2024개회1",
            commencement_date="2025.01.15",
            plan_approved_date="2025.06.01",
        )
        events = diff_general(old, new, "박미리")
        assert len(events) == 2
        event_types = {e.event for e in events}
        assert "COMMENCED" in event_types
        assert "PLAN_APPROVED" in event_types


class TestDiffOrders:
    """진행명령 변경 탐지."""

    def test_no_change(self):
        old = [{"court": "인천", "case_no": "2024개회1",
                "date": "2025.02.18", "content": "기각결정", "result": ""}]
        new = [OrderRow(court="인천", case_no="2024개회1",
                        date="2025.02.18", category="기각결정",
                        content="기각결정", result="")]
        events = diff_orders(old, new, "박미리")
        assert len(events) == 0

    def test_new_order(self):
        old = []
        new = [OrderRow(court="인천", case_no="2024개회1",
                        date="2025.06.01", category="변제계획인가결정",
                        content="변제계획인가결정", result="")]
        events = diff_orders(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "NEW_ORDER"

    def test_order_updated(self):
        old = [{"court": "인천", "case_no": "2024개회1",
                "date": "2025.02.18", "content": "기각결정", "result": ""}]
        new = [OrderRow(court="인천", case_no="2024개회1",
                        date="2025.02.18", category="기각결정",
                        content="기각결정", result="확정")]
        events = diff_orders(old, new, "박미리")
        assert len(events) == 1
        assert events[0].event == "ORDER_UPDATED"

    def test_multiple_new_orders(self):
        old = []
        new = [
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.02.18", category="기각결정",
                     content="기각결정", result=""),
            OrderRow(court="인천", case_no="2024개회1",
                     date="2025.03.05", category="기각취소결정",
                     content="기각취소결정", result=""),
        ]
        events = diff_orders(old, new, "박미리")
        assert len(events) == 2
        assert all(e.event == "NEW_ORDER" for e in events)


class TestDiffCase:
    """전체 사건 비교."""

    def test_initial_load(self):
        events, is_initial = diff_case(None, [],
                                        GeneralContent(court="인천", case_no="2024개회1"),
                                        [], "박미리")
        assert is_initial is True
        assert len(events) == 1
        assert events[0].event == "INITIAL_LOAD"

    def test_not_initial_with_old_data(self):
        old_gen = {"commencement_date": "2025.01.15"}
        events, is_initial = diff_case(
            old_gen, [],
            GeneralContent(court="인천", case_no="2024개회1",
                          commencement_date="2025.01.15"),
            [], "박미리",
        )
        assert is_initial is False
        assert len(events) == 0
