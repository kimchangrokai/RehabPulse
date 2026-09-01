"""RehabPulse CLI — add/remove/list/sync/report 명령.

사용:
    python -m rehabpulse add "인천지방법원 2024개회176313" --party "박미리"
    python -m rehabpulse list
    python -m rehabpulse sync
    python -m rehabpulse sync --case "인천지방법원 2024개회176313"
    python -m rehabpulse sync --dry-run
    python -m rehabpulse remove "인천지방법원 2024개회176313"
    python -m rehabpulse report
    python -m rehabpulse report --email
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .models import CaseRecord, ChangeEvent
from .store.excel_store import ExcelStore
from .judge.judge import (
    Rules,
    build_email_subject, build_email_body,
    judge_snapshot, classify_attempts, apply_miss_day, notifiable,
)
from .notify.mailer import send_mail, build_report_html

logger = logging.getLogger("rehabpulse")


def main() -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        prog="rehabpulse",
        description="개인회생 인가 감시기",
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="사건 등록")
    p_add.add_argument("case", help="법원명 사건번호 (예: 인천지방법원 2024개회176313)")
    p_add.add_argument("--party", required=True, help="당사자명")

    # remove
    p_rm = sub.add_parser("remove", help="사건 비활성화/삭제")
    p_rm.add_argument("case", help="법원명 사건번호")
    p_rm.add_argument("--purge", action="store_true", help="완전 삭제")

    # list
    sub.add_parser("list", help="사건 목록 조회")

    # sync
    p_sync = sub.add_parser("sync", help="조회·저장·알림")
    p_sync.add_argument("--case", help="특정 사건만 조회")
    p_sync.add_argument("--dry-run", action="store_true", help="실제 저장/발송 없이 미리보기")

    # report
    p_report = sub.add_parser("report", help="현황 보고서")
    p_report.add_argument("--email", action="store_true", help="이메일 발송")

    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    if not args.command:
        parser.print_help()
        return 1

    # 로깅 설정
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.handlers.RotatingFileHandler(
                "logs/rehabpulse.log",
                encoding="utf-8",
                maxBytes=5_000_000,
                backupCount=5,
            ),
        ],
    )

    # 설정 로드
    settings = _load_settings()

    try:
        if args.command == "add":
            return cmd_add(args.case, args.party, settings)
        elif args.command == "remove":
            return cmd_remove(args.case, args.purge, settings)
        elif args.command == "list":
            return cmd_list(settings)
        elif args.command == "sync":
            return cmd_sync(settings, case_filter=args.case, dry_run=args.dry_run)
        elif args.command == "report":
            return cmd_report(settings, email=args.email)
    except Exception as e:
        logger.error(f"명령 실행 실패: {e}", exc_info=True)
        return 1

    return 0


# ── 설정 ─────────────────────────────────────────────────────────────

def _load_settings() -> dict:
    """config/settings.yaml 로드."""
    path = Path("config/settings.yaml")
    if not path.exists():
        logger.error(f"설정 파일 없음: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_store(settings: dict) -> ExcelStore:
    """ExcelStore 인스턴스 생성."""
    paths = settings.get("paths", {})
    backup = settings.get("backup", {})
    return ExcelStore(
        path=paths.get("workbook", "rehabpulse.xlsx"),
        backup_dir=paths.get("backup", "backup/"),
        retention=backup.get("retention", 30),
    )


# ── 사건번호 파싱 ────────────────────────────────────────────────────

_CASE_RE = re.compile(
    r"^(?P<court>.+?)\s+(?P<year>\d{4})(?P<type>[가-힣]+)(?P<serial>\d+)$"
)


def _parse_case_arg(case_str: str) -> tuple[str, str, str, str, str]:
    """'인천지방법원 2024개회176313' → (court, year, case_type, serial, case_no)."""
    m = _CASE_RE.match(case_str.strip())
    if not m:
        raise ValueError(
            f"사건번호 형식 오류: '{case_str}'. "
            f"예: 인천지방법원 2024개회176313"
        )
    court = m.group("court")
    year = m.group("year")
    case_type = m.group("type")
    serial = m.group("serial")
    case_no = f"{year}{case_type}{serial}"
    return court, year, case_type, serial, case_no


# ── 명령 구현 ────────────────────────────────────────────────────────

def cmd_add(case_str: str, party: str, settings: dict) -> int:
    """사건 등록."""
    court, year, case_type, serial, case_no = _parse_case_arg(case_str)

    store = _build_store(settings)
    store.load()

    record = CaseRecord(
        court=court, case_no=case_no,
        year=year, case_type=case_type, serial=serial,
        party=party.strip(),
    )

    if store.add_case(record):
        store.save()
        logger.info(f"사건 등록: {court} {case_no} ({party})")
        print(f"[OK] 등록 완료: {court} {case_no} ({party})")
    else:
        print(f"[SKIP] 이미 등록된 사건: {court} {case_no}")
        return 1

    return 0


def cmd_remove(case_str: str, purge: bool, settings: dict) -> int:
    """사건 비활성화/삭제."""
    court, _, _, _, case_no = _parse_case_arg(case_str)

    store = _build_store(settings)
    store.load()

    if store.remove_case(court, case_no, purge=purge):
        store.save()
        action = "삭제" if purge else "비활성화"
        logger.info(f"사건 {action}: {court} {case_no}")
        print(f"[OK] {action} 완료: {court} {case_no}")
    else:
        print(f"[ERR] 사건을 찾을 수 없음: {court} {case_no}")
        return 1

    return 0


def cmd_list(settings: dict) -> int:
    """사건 목록 조회."""
    store = _build_store(settings)
    store.load()

    cases = store.get_active_cases()
    if not cases:
        print("등록된 활성 사건이 없습니다.")
        return 0

    print(f"{'법원':<15} {'사건번호':<20} {'당사자':<10} {'변제계획인가':<8} {'miss':<5} {'최근결과':<10}")
    print("-" * 70)
    for c in cases:
        print(f"{c.court:<15} {c.case_no:<20} {c.party:<10} "
              f"{c.plan_approved or '-':<6} {c.consecutive_miss_days:<5} "
              f"{c.last_result or '-':<10}")

    return 0


def cmd_sync(
    settings: dict,
    case_filter: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    """조회·저장·알림 — 핵심 파이프라인.

    사건마다 2회 조회 (60초 간격). 두 번 모두 not-found → miss.
    3일 연속 miss → 종료.
    """
    store = _build_store(settings)
    store.load()
    rules = Rules()
    fetch_cfg = settings.get("fetch", {})
    email_cfg = settings.get("email", {})
    archive_cfg = settings.get("archive", {})
    raw_dir = Path(settings.get("paths", {}).get("raw", "raw/"))

    # 활성 사건 목록
    cases = store.get_active_cases()
    if case_filter:
        court, _, _, _, case_no = _parse_case_arg(case_filter)
        cases = [c for c in cases if c.court == court and c.case_no == case_no]
        if not cases:
            logger.error(f"사건을 찾을 수 없음: {case_filter}")
            return 1

    if not cases:
        logger.info("조회할 활성 사건이 없습니다.")
        return 0

    logger.info(f"조회 시작: {len(cases)}건")

    # 브라우저 시작
    from .fetch.browser import launch_browser, navigate_to_search
    from .fetch.ssgo import fetch_case, SsgoError, CaseNotFoundError, CaptchaError

    total = len(cases)
    success_count = 0
    fail_count = 0
    miss_count = 0
    all_events: list[ChangeEvent] = []

    with launch_browser(headless=True) as ctx:
        page = ctx.new_page()
        navigate_to_search(page)

        for i, case in enumerate(cases):
            logger.info(f"[{i+1}/{total}] {case.court} {case.case_no} ({case.party})")
            navigate_to_search(page)

            captcha_solver = _make_captcha_solver(settings)

            # 2회 조회 (60초 간격)
            attempt_results = []
            for attempt in range(2):
                if attempt > 0:
                    wait = fetch_cfg.get("retry_interval", 60)
                    logger.info(f"  재시도 대기: {wait}초")
                    time.sleep(wait)
                    navigate_to_search(page)

                try:
                    snapshot = fetch_case(
                        page=page,
                        court=case.court,
                        year=case.year,
                        case_type=case.case_type,
                        serial=case.serial,
                        party=case.party,
                        captcha_solver=captcha_solver,
                        raw_dir=raw_dir,
                    )

                    if snapshot.not_found:
                        attempt_results.append("not_found")
                    elif snapshot.error:
                        attempt_results.append("error")
                        logger.warning(f"  시도 {attempt+1} 오류: {snapshot.error}")
                    else:
                        attempt_results.append("success")
                        # 첫 성공 시 즉시 처리
                        if attempt_results[-1] == "success":
                            _process_success(
                                store, rules, case, snapshot,
                                all_events, dry_run,
                            )
                            break

                except CaptchaError as e:
                    attempt_results.append("captcha_error")
                    logger.warning(f"  시도 {attempt+1} 캡차 오류: {e}")
                except SsgoError as e:
                    attempt_results.append("error")
                    logger.warning(f"  시도 {attempt+1} 사이트 오류: {e}")
                except CaseNotFoundError:
                    attempt_results.append("not_found")

            # 결과 판정
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            day_result = classify_attempts(attempt_results)

            if day_result == "success":
                success_count += 1
                store.update_case_status(
                    case.court, case.case_no,
                    consecutive_miss_days=0,
                    last_result="success", last_error="",
                    last_check=now,
                )
            elif day_result == "miss":
                miss_count += 1
                new_miss, miss_events = apply_miss_day(
                    case.court, case.case_no, case.party,
                    case.consecutive_miss_days,
                    archive_cfg.get("miss_days", 3),
                )
                store.update_case_status(
                    case.court, case.case_no,
                    consecutive_miss_days=new_miss,
                    last_result="not_found", last_error="",
                    last_check=now,
                )
                for ev in miss_events:
                    all_events.append(ev)
                    if not dry_run:
                        store.append_history(ev)
                    if ev.event == "CASE_ARCHIVED":
                        store.update_case_status(
                            case.court, case.case_no, active="N",
                        )
                        store.archive_case(
                            case.court, case.case_no, case.party,
                        )
                        logger.info(f"  사건 종료: {case.case_no}")
            else:
                # 오류 (캡차 실패, 파싱 실패 등) — miss가 아님
                fail_count += 1
                error_msg = "; ".join(attempt_results) if attempt_results else "no_attempt"
                store.update_case_status(
                    case.court, case.case_no,
                    last_result="error", last_error=error_msg,
                    last_check=now,
                )

            # 사건 간 딜레이
            if i < total - 1:
                delay = random.uniform(
                    fetch_cfg.get("delay_min", 2.0),
                    fetch_cfg.get("delay_max", 3.0),
                )
                time.sleep(delay)

    # 저장
    if not dry_run:
        store.beautify()
        store.save()

    # 실행로그
    store.append_runlog(total, success_count, fail_count, miss_count)
    if not dry_run:
        store.save()

    # 이메일 발송
    workbook_path = settings.get("paths", {}).get("workbook", "rehabpulse.xlsx")
    notify_events = notifiable(all_events)
    if notify_events and not dry_run:
        _send_notifications(notify_events, store, email_cfg, workbook_path)
    elif notify_events and dry_run:
        print(f"\n[DRY-RUN] 알림 {len(notify_events)}건:")
        for ev in notify_events:
            print(f"  - {ev.party}: {ev.event} -- {ev.detail}")
    elif not notify_events and email_cfg.get("send_empty") and not dry_run:
        send_mail(
            f"[RehabPulse] {datetime.now().strftime('%Y-%m-%d')} 변경 없음",
            "조회 완료. 변경 사항이 없습니다.",
            email_cfg,
        )

    logger.info(
        f"조회 완료: 성공 {success_count}, 실패 {fail_count}, "
        f"결번 {miss_count}, 이벤트 {len(notify_events)}건"
    )
    print(f"\n[DONE] 성공 {success_count}, 실패 {fail_count}, "
          f"결번 {miss_count}, 알림 {len(notify_events)}건")

    return 0


def cmd_report(settings: dict, email: bool = False) -> int:
    """현황 보고서."""
    store = _build_store(settings)
    store.load()

    cases = store.get_active_cases()
    lines = [
        f"# RehabPulse 현황 보고서",
        f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"등록 사건: {len(cases)}건",
        "",
        "| 법원 | 사건번호 | 당사자 | 변제계획인가 | miss | 최근결과 |",
        "|------|----------|--------|------|------|----------|",
    ]

    for c in cases:
        lines.append(
            f"| {c.court} | {c.case_no} | {c.party} | "
            f"{c.plan_approved or '-'} | {c.consecutive_miss_days} | "
            f"{c.last_result or '-'} |"
        )

    report = "\n".join(lines)
    print(report)

    if email:
        email_cfg = settings.get("email", {})
        workbook_path = settings.get("paths", {}).get("workbook", "rehabpulse.xlsx")
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"[RehabPulse] {datetime.now().strftime('%Y-%m-%d')} 현황 보고서"
        html = build_report_html(generated, cases)
        wb_attachment = _read_workbook_attachment(workbook_path)
        send_mail(subject, report, email_cfg, html=html, attachments=wb_attachment)

    return 0


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _process_success(
    store: ExcelStore,
    rules: Rules,
    case: CaseRecord,
    snapshot,
    all_events: list[ChangeEvent],
    dry_run: bool,
) -> None:
    """조회 성공 시: diff → judge → upsert → 이벤트 수집."""
    # 이전 스냅샷 읽기
    old_general = store.read_general(case.court, case.case_no)
    old_orders = store.read_orders(case.court, case.case_no)

    events, _is_initial = judge_snapshot(
        old_general, old_orders,
        snapshot.general, snapshot.orders,
        case.party, rules,
    )

    # 인가여부 업데이트 — 공란으로 기존 Y를 지우지 않는다
    plan_approved = case.plan_approved
    if snapshot.general.plan_approved_date:
        plan_approved = "Y"
    elif any(e.event == "PLAN_APPROVED" for e in events):
        plan_approved = "Y"

    if not dry_run:
        # 엑셀 업서트
        store.upsert_general(snapshot.general, case.party)
        store.upsert_orders(
            snapshot.orders or [],
            case.party,
            court=case.court,
            case_no=case.case_no,
        )

        # 사건목록 업데이트
        store.update_case_status(
            case.court, case.case_no,
            plan_approved=plan_approved,
        )

        # 변경이력 기록
        for ev in events:
            store.append_history(ev)

    all_events.extend(events)


def _send_notifications(
    events: list[ChangeEvent],
    store: ExcelStore,
    email_cfg: dict,
    workbook_path: str = "rehabpulse.xlsx",
) -> None:
    """이벤트별로 메일을 발송한다. 워크북을 첨부한다."""
    # 워크북 첨부파일 읽기
    wb_attachment = _read_workbook_attachment(workbook_path)

    # 사건별로 그룹핑
    by_case: dict[tuple[str, str], list[ChangeEvent]] = {}
    for ev in events:
        key = (ev.court, ev.case_no)
        by_case.setdefault(key, []).append(ev)

    for (court, case_no), case_events in by_case.items():
        party = case_events[0].party
        subject = build_email_subject(case_events, party)

        # 일반내용 읽기
        general = store.read_general(court, case_no)
        orders = store.read_orders(court, case_no)

        body = build_email_body(case_events, general, orders)
        send_mail(subject, body, email_cfg, attachments=wb_attachment)


def _make_captcha_solver(settings: dict):
    """캡차 solver — vision(기본) 또는 manual."""
    from .fetch.captcha import make_solver
    return make_solver(settings)


def _read_workbook_attachment(
    workbook_path: str,
) -> list[tuple[str, bytes]] | None:
    """워크북 파일을 읽어 첨부파일 튜플 리스트로 반환. 없으면 None."""
    p = Path(workbook_path)
    if not p.exists():
        logger.warning(f"워크북 파일 없음, 첨부 생략: {workbook_path}")
        return None
    return [(p.name, p.read_bytes())]
