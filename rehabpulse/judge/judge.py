"""인가·종료 판정 — rules.yaml 기반.

핵심 명령(변제계획인가결정 등)을 ChangeEvent에서 식별하고,
3일 연속 결번 종료 규칙을 판정한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..models import ChangeEvent

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
