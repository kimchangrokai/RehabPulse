"""스냅샷 비교 → ChangeEvent 생성.

비교 기준은 직전 성공 스냅샷 (엑셀에 저장된 값).
"""

from __future__ import annotations

from ..models import GeneralContent, OrderRow, ChangeEvent


def diff_general(old: dict | None, new: GeneralContent,
                 party: str) -> list[ChangeEvent]:
    """일반내용 변경을 탐지한다.

    비교 대상: 개시결정일, 변제계획인가일, 면책결정일,
              절차폐지결정일, 종국결과
    """
    events: list[ChangeEvent] = []

    if old is None:
        # 첫 수집 — 별도 INITIAL_LOAD에서 처리
        return events

    field_event_map = {
        "commencement_date": "COMMENCED",
        "plan_approved_date": "PLAN_APPROVED",
        "discharge_date": "DISCHARGED",
        "revocation_date": "TERMINAL",
        "terminal_result": "TERMINAL",
    }

    for field, event_type in field_event_map.items():
        old_val = (old.get(field) or "").strip()
        new_val = (getattr(new, field) or "").strip()
        if old_val != new_val and new_val:
            events.append(ChangeEvent(
                court=new.court,
                case_no=new.case_no,
                party=party,
                event=event_type,
                detail=f"{field}: '{old_val}' → '{new_val}'",
            ))

    return events


def diff_orders(old: list[dict], new: list[OrderRow],
                party: str) -> list[ChangeEvent]:
    """진행명령 변경을 탐지한다.

    키: (법원, 사건번호, 일자, 내용)
    """
    events: list[ChangeEvent] = []

    # 기존 행 인덱스
    old_index = {}
    for r in old:
        key = (r["court"], r["case_no"], r["date"], r["content"])
        old_index[key] = r

    new_keys = set()

    for order in new:
        key = (order.court, order.case_no, order.date, order.content)
        new_keys.add(key)

        if key in old_index:
            old_row = old_index[key]
            # 결과 변경 체크
            if (old_row.get("result") or "").strip() != (order.result or "").strip():
                events.append(ChangeEvent(
                    court=order.court,
                    case_no=order.case_no,
                    party=party,
                    event="ORDER_UPDATED",
                    detail=f"[{order.date}] {order.content}: "
                           f"'{old_row.get('result', '')}' → '{order.result}'",
                ))
        else:
            # 신규 명령
            events.append(ChangeEvent(
                court=order.court,
                case_no=order.case_no,
                party=party,
                event="NEW_ORDER",
                detail=f"[{order.date}] {order.content} {order.result}".strip(),
            ))

    return events


def diff_case(old_general: dict | None,
              old_orders: list[dict],
              new_general: GeneralContent,
              new_orders: list[OrderRow],
              party: str) -> tuple[list[ChangeEvent], bool]:
    """한 사건의 전체 변경을 비교한다.

    Returns:
        (events, is_initial): 이벤트 목록, 첫 수집 여부
    """
    is_initial = old_general is None and not old_orders

    events: list[ChangeEvent] = []

    if is_initial:
        events.append(ChangeEvent(
            court=new_general.court,
            case_no=new_general.case_no,
            party=party,
            event="INITIAL_LOAD",
            detail="최초 수집",
        ))
        return events, True

    events.extend(diff_general(old_general, new_general, party))
    events.extend(diff_orders(old_orders, new_orders, party))

    return events, False
