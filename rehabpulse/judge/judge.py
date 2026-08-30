"""인가·종료 판정 — rules.yaml 기반.

핵심 명령(변제계획인가결정 등)을 ChangeEvent에서 식별하고,
3일 연속 결번 종료 규칙을 판정한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..models import ChangeEvent, GeneralContent, OrderRow
from ..diff.differ import diff_case

logger = logging.getLogger(__name__)


class Rules:
    """rules.yaml 래퍼."""

    def __init__(self, path: str | Path = "config/rules.yaml"):
        with open(path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

        # 핵심 명령 이름 → 이벤트 매핑
        self._critical_map: dict[str, str] = {}
        for item in self._data.get("critical_orders", []):
            self._critical_map[item["name"]] = item["event"]

        # 일반내용 필드 → 이벤트 매핑
        self._date_events: dict[str, str] = self._data.get("date_field_events", {})

        # 이벤트 한글 이름
        self._labels: dict[str, str] = self._data.get("event_labels", {})

    @property
    def critical_orders(self) -> dict[str, str]:
        return self._critical_map

    def event_label(self, event: str) -> str:
        """이벤트의 한글 이름을 반환한다."""
        return self._labels.get(event, event)

    def classify_order(self, content: str) -> Optional[str]:
        """명령 내용에서 핵심 이벤트를 식별한다."""
        for name, event in self._critical_map.items():
            if name in content:
                return event
        return None


def summarize_stage(general: GeneralContent, orders: list[OrderRow]) -> str:
    """진행구분·내용·일자 필드로 개인회생 현재 단계를 한 줄 요약한다."""
    blob = " ".join(f"{o.category} {o.content}" for o in orders)
    latest = ""
    if orders:
        latest_row = max(orders, key=lambda o: o.date or "")
        latest = (latest_row.content or latest_row.category or "").strip()

    if (general.discharge_date or "").strip() or "면책결정" in blob:
        return "면책결정"
    if (general.revocation_date or "").strip():
        return "절차폐지"
    if (general.terminal_result or "").strip():
        return f"종국({general.terminal_result.strip()})"
    if (general.plan_approved_date or "").strip() or "변제계획인가결정" in blob:
        return "변제계획인가 — 변제 진행"
    if "즉시항고" in blob:
        if "기각" in blob:
            return "개시신청 기각 후 즉시항고 진행"
        return "즉시항고 진행"
    if "기각취소" in blob:
        return "기각취소 — 절차 속행"
    if "기각결정" in blob:
        return "개시신청 기각"
    if (general.commencement_date or "").strip() or "개시결정" in blob:
        if "채권자목록수정" in blob or "변제계획" in blob:
            return "개시결정 — 인가 전 (목록·계획 보정 중)"
        return "개시결정 — 인가 전"
    if latest:
        short = latest if len(latest) <= 40 else latest[:40] + "…"
        return f"신청 진행 중 (최근: {short})"
    return "신청 진행 중"


def judge_miss_day(
    attempt1_not_found: bool,
    attempt2_not_found: bool,
) -> bool:
    """하루 2회 조회 모두 결번이면 True.

    캡차 실패·타임아웃·파싱 실패·5xx는 miss가 아니다.
    오직 '사건이 존재하지 않습니다'만 not-found로 친다.
    """
    return attempt1_not_found and attempt2_not_found


def should_archive(consecutive_miss_days: int, threshold: int = 3) -> bool:
    """3일 연속 결번이면 종료 대상."""
    return consecutive_miss_days >= threshold


NOTIFIABLE_EXCLUDE = frozenset({"INITIAL_LOAD", "MISS_DAY"})


def notifiable(events: list[ChangeEvent]) -> list[ChangeEvent]:
    """메일 대상 이벤트. 최초 수집·1~2일 결번은 제외."""
    return [e for e in events if e.event not in NOTIFIABLE_EXCLUDE]


def classify_attempts(attempts: list[str]) -> str:
    """하루 시도 목록 → success | miss | error.

    miss는 두 번 이상 모두 not-found일 때만. 캡차·파싱 실패는 error.
    """
    if "success" in attempts:
        return "success"
    if len(attempts) >= 2 and all(r == "not_found" for r in attempts):
        return "miss"
    return "error"


def apply_miss_day(
    court: str,
    case_no: str,
    party: str,
    prev_miss_days: int,
    threshold: int = 3,
) -> tuple[int, list[ChangeEvent]]:
    """결번 하루를 반영한다. 3일이면 CASE_ARCHIVED를 추가한다."""
    new_miss = prev_miss_days + 1
    events = [ChangeEvent(
        court=court, case_no=case_no, party=party,
        event="MISS_DAY", detail=f"연속 결번: {new_miss}일",
    )]
    if should_archive(new_miss, threshold):
        events.append(ChangeEvent(
            court=court, case_no=case_no, party=party,
            event="CASE_ARCHIVED",
            detail=f"{new_miss}일 연속 조회 없음",
        ))
    return new_miss, events


def promote_critical(events: list[ChangeEvent], rules: Rules | None = None) -> list[ChangeEvent]:
    """신규 명령(NEW_ORDER)이 핵심 명령이면 대응 이벤트를 추가한다.

    이미 있던 명령 행은 재실행해도 알림을 내지 않는다.
    """
    rules = rules or Rules()
    extra: list[ChangeEvent] = []
    for ev in events:
        if ev.event != "NEW_ORDER":
            continue
        classified = rules.classify_order(ev.detail)
        if not classified:
            continue
        already = any(
            e.event == classified and e.case_no == ev.case_no
            for e in events + extra
        )
        if already:
            continue
        extra.append(ChangeEvent(
            court=ev.court, case_no=ev.case_no, party=ev.party,
            event=classified, detail=ev.detail,
        ))
    return events + extra


def judge_snapshot(
    old_general: dict | None,
    old_orders: list[dict],
    new_general: GeneralContent,
    new_orders: list[OrderRow],
    party: str,
    rules: Rules | None = None,
) -> tuple[list[ChangeEvent], bool]:
    """스냅샷 비교 후 핵심 명령을 승격한다. 첫 수집은 INITIAL_LOAD만."""
    rules = rules or Rules()
    events, is_initial = diff_case(
        old_general, old_orders, new_general, new_orders, party,
    )
    if is_initial:
        return events, True
    return promote_critical(events, rules), False


def build_email_subject(events: list[ChangeEvent], party: str) -> str:
    """이벤트 목록으로 메일 제목을 만든다."""
    rules = Rules()

    # 우선순위: PLAN_APPROVED > COMMENCED > DISMISSED > etc.
    priority = [
        "PLAN_APPROVED", "COMMENCED", "DISMISSED", "DISMISSAL_VACATED",
        "DISCHARGED", "TERMINAL", "CASE_ARCHIVED",
    ]
    for p in priority:
        for ev in events:
            if ev.event == p:
                if p == "CASE_ARCHIVED":
                    return f"[RehabPulse] {party} 사건 종료(3일 연속 조회 없음)"
                return f"[RehabPulse] {party} {rules.event_label(p)}"

    # 그 외: 진행 변경
    return f"[RehabPulse] {party} 진행 변경"


def build_email_body(events: list[ChangeEvent], general: dict | None,
                     new_orders: list[dict]) -> str:
    """이벤트 메일 본문을 만든다 (한글)."""
    rules = Rules()
    lines = []

    for ev in events:
        label = rules.event_label(ev.event)
        lines.append(f"• {label}: {ev.detail}")

    if general:
        lines.append("")
        lines.append("── 일반내용 ──")
        date_fields = [
            ("개시결정일", general.get("commencement_date", "")),
            ("변제계획인가일", general.get("plan_approved_date", "")),
            ("면책결정일", general.get("discharge_date", "")),
            ("종국결과", general.get("terminal_result", "")),
        ]
        for label, val in date_fields:
            lines.append(f"  {label}: {val or '(공란)'}")

    if new_orders:
        lines.append("")
        lines.append("── 신규/변경 명령 ──")
        for o in new_orders[-10:]:  # 최근 10건
            lines.append(f"  [{o.get('date', '')}] {o.get('content', '')} {o.get('result', '')}")

    return "\n".join(lines)
