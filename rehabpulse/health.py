"""메일 시각 점검: 보고서 재생성, SMTP 재시도, 관리자 알림."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .notify.mailer import send_mail
from .projects import ProjectRef
from .store.excel_store import ExcelStore

logger = logging.getLogger(__name__)

SMTP_RETRIES = 2  # 추가 재시도 2회


def report_file(settings: dict, ref: ProjectRef, day: str | None = None) -> Path:
    day = day or datetime.now().strftime("%Y-%m-%d")
    root = Path(settings.get("paths", {}).get("reports", "reports"))
    return root / ref.company / ref.project / f"{day}.md"


def write_report_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def collect_issues(store: ExcelStore) -> list[str]:
    issues = []
    for c in store.get_active_cases():
        if c.last_result == "error":
            issues.append(f"조회 error: {c.court} {c.case_no} {c.last_error}")
        if c.last_result == "not_found":
            issues.append(f"결번 miss: {c.court} {c.case_no}")
    return issues


def operator_address(settings: dict) -> str:
    return settings.get("email", {}).get("operator", "realtyscope.ai@gmail.com")


def notify_operator(settings: dict, ref: ProjectRef, issues: list[str]) -> bool:
    if not issues:
        return True
    body = (
        f"프로젝트 {ref.company}/{ref.project} 점검 실패\n\n"
        + "\n".join(f"- {i}" for i in issues)
    )
    return send_mail(
        f"[RehabPulse][관리자] {ref.company}/{ref.project} 점검 실패",
        body,
        settings.get("email", {}),
        recipients=[operator_address(settings)],
        retries=SMTP_RETRIES,
    )
