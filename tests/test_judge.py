"""judge 테스트 — 인가·종료 판정."""

from rehabpulse.judge.judge import (
    Rules, judge_miss_day, should_archive,
    build_email_subject, build_email_body, summarize_stage,
)
from rehabpulse.models import ChangeEvent, GeneralContent, OrderRow


class TestJudgeMissDay:
    """결번 판정."""

    def test_both_not_found(self):
        assert judge_miss_day(True, True) is True

    def test_one_success(self):
        assert judge_miss_day(True, False) is False
        assert judge_miss_day(False, True) is False

    def test_both_success(self):
        assert judge_miss_day(False, False) is False


class TestShouldArchive:
    """종료 판정."""

    def test_threshold_reached(self):
        assert should_archive(3) is True
        assert should_archive(4) is True

    def test_below_threshold(self):
        assert should_archive(0) is False
        assert should_archive(1) is False
        assert should_archive(2) is False

    def test_custom_threshold(self):
        assert should_archive(2, threshold=2) is True
        assert should_archive(1, threshold=2) is False


class TestRules:
    """rules.yaml 기반 분류."""

    def test_classify_plan_approved(self):
        rules = Rules()
        event = rules.classify_order("변제계획인가결정")
        assert event == "PLAN_APPROVED"

    def test_classify_commenced(self):
        rules = Rules()
        event = rules.classify_order("개인회생절차개시결정")
        assert event == "COMMENCED"

    def test_classify_dismissed(self):
        rules = Rules()
        event = rules.classify_order("개인회생절차개시신청 기각결정")
        assert event == "DISMISSED"

    def test_classify_dismissal_vacated(self):
        rules = Rules()
        event = rules.classify_order("기각취소결정")
        assert event == "DISMISSAL_VACATED"

    def test_classify_unknown(self):
        rules = Rules()
        event = rules.classify_order("보정권고")
        assert event is None

    def test_event_label(self):
        rules = Rules()
        assert rules.event_label("PLAN_APPROVED") == "변제계획인가결정"
        assert rules.event_label("UNKNOWN") == "UNKNOWN"


class TestEmailSubject:
    """메일 제목 생성."""

    def test_plan_approved_priority(self):
        events = [
            ChangeEvent(court="인천", case_no="2024개회1",
                       party="박미리", event="NEW_ORDER", detail=""),
            ChangeEvent(court="인천", case_no="2024개회1",
                       party="박미리", event="PLAN_APPROVED", detail=""),
        ]
        subject = build_email_subject(events, "박미리")
        assert "변제계획인가결정" in subject
        assert "박미리" in subject

    def test_generic_change(self):
        events = [
            ChangeEvent(court="인천", case_no="2024개회1",
                       party="박미리", event="NEW_ORDER", detail=""),
        ]
        subject = build_email_subject(events, "박미리")
        assert "진행 변경" in subject


class TestEmailBody:
    """메일 본문 생성."""

    def test_basic_body(self):
        events = [
            ChangeEvent(court="인천", case_no="2024개회1",
                       party="박미리", event="PLAN_APPROVED",
                       detail="plan_approved_date: '' → '2025.06.01'"),
        ]
        general = {
            "commencement_date": "2025.01.15",
            "plan_approved_date": "2025.06.01",
            "discharge_date": "",
            "terminal_result": "",
        }
        body = build_email_body(events, general, [])
        assert "PLAN_APPROVED" not in body  # 한글 라벨 사용
        assert "변제계획인가결정" in body
        assert "2025.06.01" in body
        assert "(공란)" in body

    def test_with_orders(self):
        events = [
            ChangeEvent(court="인천", case_no="2024개회1",
                       party="박미리", event="NEW_ORDER",
                       detail="[2025.02.18] 기각결정"),
        ]
        orders = [
            {"date": "2025.02.18", "content": "기각결정", "result": ""},
            {"date": "2025.03.05", "content": "기각취소결정", "result": ""},
        ]
        body = build_email_body(events, None, orders)
        assert "기각결정" in body
        assert "기각취소결정" in body


class TestSummarizeStage:
    def test_discharge(self):
        g = GeneralContent(court="인천", case_no="1", discharge_date="2026.06.25")
        assert summarize_stage(g, []) == "면책결정"

    def test_approved(self):
        g = GeneralContent(court="인천", case_no="1", plan_approved_date="2026.06.01")
        assert "변제계획인가" in summarize_stage(g, [])

    def test_appeal_after_dismiss(self):
        g = GeneralContent(court="인천", case_no="1")
        orders = [
            OrderRow(court="인천", case_no="1", date="2025.09.08",
                     category="명령", content="기각결정"),
            OrderRow(court="인천", case_no="1", date="2025.09.19",
                     category="신청", content="즉시항고장 제출"),
        ]
        assert "즉시항고" in summarize_stage(g, orders)

    def test_commenced(self):
        g = GeneralContent(court="인천", case_no="1", commencement_date="2026.03.27")
        assert "개시결정" in summarize_stage(g, [])
