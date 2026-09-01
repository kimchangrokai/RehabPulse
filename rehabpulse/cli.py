"""RehabPulse CLI — add/remove/list/sync/report/mail/init 명령.

사용:
    python -m rehabpulse init
    python -m rehabpulse add "인천지방법원 2024개회176313" --party "박미리" --company 대신증권 --project 2608계약건
    python -m rehabpulse list --company 대신증권 --project 2608계약건
    python -m rehabpulse sync --company 대신증권 --project 2608계약건
    python -m rehabpulse report --company 대신증권 --project 2608계약건 --email
    python -m rehabpulse mail --company 대신증권 --project 2608계약건
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import random
import re
import subprocess
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
from .projects import (
    ProjectRef, resolve_scope, project_ref, write_sidecar, is_weekday,
    INITIAL_COMPANIES, INITIAL_PROJECT, DEFAULT_MAILING,
)
from .health import (
    report_file, write_report_file, collect_issues, notify_operator, SMTP_RETRIES,
)

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
    _add_scope(p_add)

    # remove
    p_rm = sub.add_parser("remove", help="사건 비활성화/삭제")
    p_rm.add_argument("case", help="법원명 사건번호")
    p_rm.add_argument("--purge", action="store_true", help="완전 삭제")
    _add_scope(p_rm)

    # list
    p_list = sub.add_parser("list", help="사건 목록 조회")
    _add_scope(p_list)

    # sync
    p_sync = sub.add_parser("sync", help="조회·저장")
    p_sync.add_argument("--case", help="특정 사건만 조회")
    p_sync.add_argument("--dry-run", action="store_true", help="실제 저장/발송 없이 미리보기")
    _add_scope(p_sync)

    # report
    p_report = sub.add_parser("report", help="현황 보고서")
    p_report.add_argument("--email", action="store_true", help="이메일 발송")
    _add_scope(p_report)

    # mail (07:00 창)
    p_mail = sub.add_parser("mail", help="보고서 메일·점검")
    _add_scope(p_mail)

    # init
    sub.add_parser("init", help="TEST 회사·프로젝트 생성")

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
        if args.command == "init":
            return cmd_init(settings)
        elif args.command == "add":
            return cmd_add(args.case, args.party, settings, args.company, args.project)
        elif args.command == "remove":
            return cmd_remove(args.case, args.purge, settings, args.company, args.project)
        elif args.command == "list":
            return cmd_list(settings, args.company, args.project)
        elif args.command == "sync":
            return cmd_sync(
                settings, case_filter=args.case, dry_run=args.dry_run,
                company=args.company, project=args.project,
            )
        elif args.command == "report":
            return cmd_report(
                settings, email=args.email,
                company=args.company, project=args.project,
            )
        elif args.command == "mail":
            return cmd_mail(settings, args.company, args.project)
    except Exception as e:
        logger.error(f"명령 실행 실패: {e}", exc_info=True)
        return 1

    return 0


# ── 설정 ─────────────────────────────────────────────────────────────

def _add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--company", help="회사명")
    parser.add_argument("--project", help="프로젝트명")


def _load_settings() -> dict:
    """config/settings.yaml 로드."""
    path = Path("config/settings.yaml")
    if not path.exists():
        logger.error(f"설정 파일 없음: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_store(settings: dict, ref: ProjectRef) -> ExcelStore:
    """프로젝트 워크북 ExcelStore."""
    backup = settings.get("backup", {})
    backup_dir = Path(settings.get("paths", {}).get("backup", "backup/")) / ref.company / ref.project
    return ExcelStore(
        path=ref.workbook,
        backup_dir=backup_dir,
        retention=backup.get("retention", 30),
    )


def _require_refs(settings: dict, company: Optional[str], project: Optional[str]) -> list[ProjectRef]:
    try:
        return resolve_scope(settings, company, project)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERR] {e}")
        return []


def _spawn_projects(command: str, refs: list[ProjectRef], extra: list[str] | None = None) -> int:
    """회사의 여러 프로젝트를 독립 프로세스로 병렬 실행."""
    extra = extra or []
    procs = []
    for ref in refs:
        cmd = [
            sys.executable, "-m", "rehabpulse", command,
            "--company", ref.company, "--project", ref.project,
            *extra,
        ]
        logger.info("병렬 세션 시작: %s/%s", ref.company, ref.project)
        procs.append(subprocess.Popen(cmd))
    codes = [p.wait() for p in procs]
    return max(codes) if codes else 0


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

def cmd_init(settings: dict) -> int:
    """TEST 회사·프로젝트를 생성한다."""
    for company in INITIAL_COMPANIES:
        ref = project_ref(settings, company, INITIAL_PROJECT)
        write_sidecar(ref)
        store = _build_store(settings, ref)
        store.load()
        for addr in DEFAULT_MAILING:
            store.add_mailing(addr)
        store.save()
        print(f"[OK] {company}/{INITIAL_PROJECT}")
    return 0


def cmd_add(case_str: str, party: str, settings: dict,
            company: Optional[str], project: Optional[str]) -> int:
    """사건 등록."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    if len(refs) != 1:
        print("[ERR] add 는 --company 와 --project 가 모두 필요합니다")
        return 1
    court, year, case_type, serial, case_no = _parse_case_arg(case_str)

    store = _build_store(settings, refs[0])
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


def cmd_remove(case_str: str, purge: bool, settings: dict,
               company: Optional[str], project: Optional[str]) -> int:
    """사건 비활성화/삭제."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    if len(refs) != 1:
        print("[ERR] remove 는 --company 와 --project 가 모두 필요합니다")
        return 1
    court, _, _, _, case_no = _parse_case_arg(case_str)

    store = _build_store(settings, refs[0])
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


def cmd_list(settings: dict, company: Optional[str], project: Optional[str]) -> int:
    """사건 목록 조회."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    any_cases = False
    for ref in refs:
        store = _build_store(settings, ref)
        store.load()
        cases = store.get_active_cases()
        print(f"\n# {ref.company}/{ref.project}")
        if not cases:
            print("등록된 활성 사건이 없습니다.")
            continue
        any_cases = True
        print(f"{'법원':<15} {'사건번호':<20} {'당사자':<10} {'변제계획인가':<8} {'miss':<5} {'최근결과':<10}")
        print("-" * 70)
        for c in cases:
            print(f"{c.court:<15} {c.case_no:<20} {c.party:<10} "
                  f"{c.plan_approved or '-':<6} {c.consecutive_miss_days:<5} "
                  f"{c.last_result or '-':<10}")
    return 0 if any_cases or refs else 1


def cmd_sync(
    settings: dict,
    case_filter: Optional[str] = None,
    dry_run: bool = False,
    company: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """조회·저장 — 메일 발송은 mail 명령(메일 시각)에서 한다."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    if len(refs) > 1:
        extra = []
        if case_filter:
            extra += ["--case", case_filter]
        if dry_run:
            extra.append("--dry-run")
        return _spawn_projects("sync", refs, extra)

    if not dry_run and not is_weekday():
        logger.info("주말: 조회 생략")
        print("[SKIP] 주말 — 조회하지 않습니다")
        return 0

    ref = refs[0]
    store = _build_store(settings, ref)
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

    # 조회 시각에는 메일을 보내지 않는다. 07:00 mail 명령이 발송한다.
    notify_events = notifiable(all_events)
    if notify_events and dry_run:
        print(f"\n[DRY-RUN] 알림 {len(notify_events)}건:")
        for ev in notify_events:
            print(f"  - {ev.party}: {ev.event} -- {ev.detail}")

    logger.info(
        f"조회 완료: 성공 {success_count}, 실패 {fail_count}, "
        f"결번 {miss_count}, 이벤트 {len(notify_events)}건"
    )
    print(f"\n[DONE] 성공 {success_count}, 실패 {fail_count}, "
          f"결번 {miss_count}, 알림 {len(notify_events)}건")

    return 0


def cmd_report(
    settings: dict,
    email: bool = False,
    company: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """현황 보고서."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    if len(refs) > 1:
        extra = ["--email"] if email else []
        return _spawn_projects("report", refs, extra)

    ref = refs[0]
    store = _build_store(settings, ref)
    store.load()

    cases = store.get_active_cases()
    lines = [
        f"# RehabPulse 현황 보고서",
        f"회사: {ref.company}  프로젝트: {ref.project}",
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
    write_report_file(report_file(settings, ref), report)

    if email:
        email_cfg = settings.get("email", {})
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = (
            f"[RehabPulse] {ref.company}/{ref.project} "
            f"{datetime.now().strftime('%Y-%m-%d')} 현황 보고서"
        )
        html = build_report_html(generated, cases)
        mailing = store.list_mailing()
        ok = send_mail(
            subject, report, email_cfg, html=html,
            recipients=mailing, retries=SMTP_RETRIES,
            attachments=_workbook_attachments(settings, ref.workbook),
        )
        if not ok:
            notify_operator(settings, ref, ["SMTP 실패: 현황 보고서"])

    return 0


def cmd_mail(settings: dict, company: Optional[str], project: Optional[str]) -> int:
    """메일 시각: 보고서 준비·발송·점검·관리자 알림."""
    refs = _require_refs(settings, company, project)
    if not refs:
        return 1
    if len(refs) > 1:
        return _spawn_projects("mail", refs)
    if not is_weekday():
        logger.info("주말: 메일·점검 생략")
        print("[SKIP] 주말 — 메일을 보내지 않습니다")
        return 0

    ref = refs[0]
    issues: list[str] = []
    path = report_file(settings, ref)
    if not path.exists():
        logger.warning("보고서 없음 — sync 후 report 1회 재실행")
        cmd_sync(settings, company=ref.company, project=ref.project)
        cmd_report(settings, email=False, company=ref.company, project=ref.project)
        if not report_file(settings, ref).exists():
            issues.append("보고서 없음")

    store = _build_store(settings, ref)
    store.load()
    mailing = store.list_mailing()
    email_cfg = settings.get("email", {})
    cases = store.get_active_cases()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = report_file(settings, ref).read_text(encoding="utf-8") if report_file(settings, ref).exists() else "보고서 없음"
    html = build_report_html(generated, cases)
    subject = f"[RehabPulse] {ref.company}/{ref.project} {datetime.now().strftime('%Y-%m-%d')} 현황 보고서"
    sent = send_mail(
        subject, text, email_cfg, html=html,
        recipients=mailing, retries=SMTP_RETRIES,
        attachments=_workbook_attachments(settings, ref.workbook),
    )
    if not sent:
        issues.append("SMTP 실패")
    change_events = notifiable(store.list_history())
    if change_events:
        _send_notifications(change_events, store, email_cfg, settings, ref.workbook)
    issues.extend(collect_issues(store))
    if issues:
        notify_operator(settings, ref, issues)
        print(f"[WARN] 점검 이슈 {len(issues)}건, 관리자 알림")
        return 1
    print("[OK] 메일 발송·점검 완료")
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
    settings: dict | None = None,
    workbook: Path | None = None,
) -> None:
    """이벤트별로 메일을 발송한다. 수신자는 프로젝트 메일링 리스트."""
    mailing = store.list_mailing()
    wb_attachment = _workbook_attachments(settings or {}, workbook)
    by_case: dict[tuple[str, str], list[ChangeEvent]] = {}
    for ev in events:
        key = (ev.court, ev.case_no)
        by_case.setdefault(key, []).append(ev)

    for (court, case_no), case_events in by_case.items():
        party = case_events[0].party
        subject = build_email_subject(case_events, party)
        general = store.read_general(court, case_no)
        orders = store.read_orders(court, case_no)
        body = build_email_body(case_events, general, orders)
        send_mail(
            subject, body, email_cfg,
            recipients=mailing, retries=SMTP_RETRIES,
            attachments=wb_attachment,
        )


def _make_captcha_solver(settings: dict):
    """캡차 solver — vision(기본) 또는 manual."""
    from .fetch.captcha import make_solver
    return make_solver(settings)


def _workbook_attachments(
    settings: dict,
    workbook: Path | str | None = None,
) -> list[tuple[str, bytes]] | None:
    """email.attach_workbook이 true일 때만 워크북을 첨부한다. 기본 false."""
    email_cfg = settings.get("email", {})
    if not email_cfg.get("attach_workbook", False):
        return None
    path = Path(workbook) if workbook else Path(
        settings.get("paths", {}).get("workbook", "rehabpulse.xlsx")
    )
    if not path.exists():
        logger.warning(f"워크북 파일 없음, 첨부 생략: {path}")
        return None
    return [(path.name, path.read_bytes())]
