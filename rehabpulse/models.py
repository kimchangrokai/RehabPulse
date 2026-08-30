"""데이터클래스 — 사건 정보, 일반내용, 진행명령, 스냅샷, 변경이벤트"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


@dataclass
class GeneralContent:
    """일반내용 (기본내용) — 날짜 필드 모음"""
    court: str
    case_no: str
    case_name: str = ""
    panel: str = ""              # 재판부/회생위원
    filed_date: str = ""         # 접수일
    commencement_date: str = ""  # 개시결정일
    plan_approved_date: str = "" # 변제계획인가일
    discharge_date: str = ""     # 면책결정일
    revocation_date: str = ""    # 절차폐지결정일
    terminal_result: str = ""    # 종국결과


@dataclass
class OrderRow:
    """진행내용 — 명령 한 행"""
    court: str
    case_no: str
    date: str           # 일자 (YYYY.MM.DD)
    category: str       # 진행구분
    content: str        # 내용
    result: str = ""    # 결과


@dataclass
class CaseSnapshot:
    """한 사건의 조회 결과"""
    general: GeneralContent
    orders: list[OrderRow] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.now)
    not_found: bool = False      # "사건이 존재하지 않습니다"
    error: Optional[str] = None  # 파싱 실패 등 오류 메시지


@dataclass
class ChangeEvent:
    """변경 이벤트"""
    court: str
    case_no: str
    party: str
    event: str          # PLAN_APPROVED, DISMISSED, NEW_ORDER 등
    detail: str = ""


@dataclass
class CaseRecord:
    """사건목록 레코드 (엑셀 저장용)"""
    court: str
    case_no: str
    year: str
    case_type: str
    serial: str
    party: str
    active: str = "Y"
    plan_approved: str = ""      # 인가여부
    consecutive_miss_days: int = 0
    last_check: str = ""
    last_result: str = ""        # success / not_found / error
    last_error: str = ""
