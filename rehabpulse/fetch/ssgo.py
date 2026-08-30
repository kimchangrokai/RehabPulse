"""ssgo.scourt.go.kr 나의 사건검색 — 브라우저 폼 조작 + 파싱.

사이트 의존 코드는 이 파일 안에만 둔다.
실제 DOM ID 기반 (2026-08-30 실측).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, Locator

from ..models import GeneralContent, OrderRow, CaseSnapshot

logger = logging.getLogger(__name__)

SSGO_URL = "https://ssgo.scourt.go.kr/ssgo/index.on?cortId=www"

# ── 실제 DOM ID (2026-08-30 실측) ────────────────────────────────────

ID_COURT = "mf_ssgoTopMainTab_contents_content1_body_sbx_cortCd"
ID_YEAR = "mf_ssgoTopMainTab_contents_content1_body_sbx_csYr"
ID_CASE_TYPE = "mf_ssgoTopMainTab_contents_content1_body_sbx_csDvsCd"
ID_SERIAL = "mf_ssgoTopMainTab_contents_content1_body_ibx_csSerial"
ID_PARTY = "mf_ssgoTopMainTab_contents_content1_body_ibx_btprNm"
ID_CAPTCHA_ANSWER = "mf_ssgoTopMainTab_contents_content1_body_ibx_answer"
ID_SEARCH_BTN = "mf_ssgoTopMainTab_contents_content1_body_btn_srchCs"
ID_CAPTCHA_IMG = "mf_ssgoTopMainTab_contents_content1_body_img_captcha"
ID_PROG_DVS = "sbx_progCttDvs"  # 진행내용 진행구분 드롭다운 id 접미사


class SsgoError(Exception):
    """사이트 조회 오류 (파싱 실패, 타임아웃 등). 결번(miss)이 아니다."""
    pass


class CaptchaError(SsgoError):
    """캡차 관련 오류."""
    pass


class CaseNotFoundError(Exception):
    """사건이 존재하지 않습니다 — 캡차·입력이 유효한 검색 응답."""
    pass


# ── 폼 조작 ──────────────────────────────────────────────────────────

def select_court(page: Page, court: str) -> None:
    """법원 선택 드롭다운에서 court를 선택한다.

    WebSquare select: value가 비어있으므로 label 텍스트로 선택.
    """
    sel = page.locator(f"#{ID_COURT}")
    try:
        sel.wait_for(state="visible", timeout=15_000)
    except Exception as e:
        raise SsgoError("법원 선택 드롭다운을 찾을 수 없습니다") from e
    if sel.count() == 0:
        raise SsgoError("법원 선택 드롭다운을 찾을 수 없습니다")
    _select_by_label(page, sel, court)
    page.wait_for_timeout(800)  # 사건구분 목록 갱신 대기


def select_year(page: Page, year: str) -> None:
    """년도 선택."""
    sel = page.locator(f"#{ID_YEAR}")
    if sel.count() == 0:
        raise SsgoError("년도 선택 드롭다운을 찾을 수 없습니다")
    _select_by_label(page, sel, year)


def select_case_type(page: Page, case_type: str) -> None:
    """사건구분 선택 (예: 개회). 법원 변경 후 목록이 바뀌므로 반드시 법원 이후에 호출."""
    sel = page.locator(f"#{ID_CASE_TYPE}")
    if sel.count() == 0:
        raise SsgoError("사건구분 선택 드롭다운을 찾을 수 없습니다")
    _select_by_label(page, sel, case_type)


def fill_serial(page: Page, serial: str) -> None:
    """사건일련번호 입력."""
    inp = page.locator(f"#{ID_SERIAL}")
    if inp.count() == 0:
        raise SsgoError("사건일련번호 입력란을 찾을 수 없습니다")
    inp.fill("")
    inp.fill(serial)


def fill_party(page: Page, party: str) -> None:
    """당사자명 입력 (빈칸 금지)."""
    if not party or not party.strip():
        raise SsgoError("당사자명은 필수 입력값입니다")
    inp = page.locator(f"#{ID_PARTY}")
    if inp.count() == 0:
        raise SsgoError("당사자명 입력란을 찾을 수 없습니다")
    inp.fill("")
    inp.fill(party.strip())


def get_captcha_image(page: Page) -> bytes:
    """캡차 이미지의 스크린샷 바이트를 반환한다.

    매 검색마다 새 이미지가 생성되므로, 이전 이미지를 재사용하지 않는다.
    """
    img = page.locator(f"#{ID_CAPTCHA_IMG}")
    if img.count() == 0:
        # 대안: alt 텍스트로 찾기
        img = page.locator("img[alt*='방지'], img[alt*='자동입력']")
    if img.count() == 0:
        raise CaptchaError("캡차 이미지를 찾을 수 없습니다")

    img_bytes = img.first.screenshot()
    if not img_bytes:
        raise CaptchaError("캡차 이미지 스크린샷 실패")
    return img_bytes


def fill_captcha(page: Page, answer: str) -> None:
    """캡차 답 입력."""
    inp = page.locator(f"#{ID_CAPTCHA_ANSWER}")
    if inp.count() == 0:
        raise CaptchaError("캡차 입력란을 찾을 수 없습니다")
    inp.fill("")
    inp.fill(answer)


CAPTCHA_MISMATCH_PHRASES = (
    "자동입력 방지문자가 일치하지",
    "보안문자가 일치하지",
    "방지문자가 일치하지",
)
NOT_FOUND_PHRASE = "사건이 존재하지 않습니다"


def is_case_not_found(text: str) -> bool:
    return NOT_FOUND_PHRASE in (text or "")


def is_captcha_mismatch(text: str) -> bool:
    """검색 폼 안내('방지문자 입력')는 오답이 아니다. 일치 실패 문구만."""
    t = text or ""
    return any(kw in t for kw in CAPTCHA_MISMATCH_PHRASES)


def attach_dialog_capture(page: Page) -> None:
    """네이티브 alert/confirm 메시지를 받아 둔다."""
    if getattr(page, "_rehab_dialog_hooked", False):
        return
    page._rehab_dialog = []
    page._rehab_dialog_hooked = True

    def _on_dialog(dialog) -> None:
        page._rehab_dialog.append(dialog.message)
        dialog.accept()

    page.on("dialog", _on_dialog)


def _visible_alert_text(page: Page) -> str:
    parts = list(getattr(page, "_rehab_dialog", []) or [])
    try:
        parts.append(page.inner_text("body") or "")
    except Exception:
        pass
    return "\n".join(parts)


def click_search(page: Page) -> None:
    """검색 버튼 클릭."""
    btn = page.locator(f"#{ID_SEARCH_BTN}")
    if btn.count() == 0:
        raise SsgoError("검색 버튼을 찾을 수 없습니다")
    if getattr(page, "_rehab_dialog", None) is not None:
        page._rehab_dialog.clear()
    btn.click()
    page.wait_for_timeout(3000)  # 결과 로드 대기


def check_not_found(page: Page) -> bool:
    """검색 결과가 '사건이 존재하지 않습니다'인지 확인 (팝업 포함)."""
    return is_case_not_found(_visible_alert_text(page))


def check_captcha_error(page: Page) -> bool:
    """캡차 오답 여부. '일치하지' 문구만 본다."""
    return is_captcha_mismatch(_visible_alert_text(page))


# ── 결과 파싱 ────────────────────────────────────────────────────────

def parse_general_content(page: Page, court: str, case_no: str) -> GeneralContent:
    """일반내용(기본내용) 탭에서 핵심 일자를 파싱한다.

    성공 시 결과 탭이 생기며, 일반내용 / 진행내용 탭이 나타난다.
    WebSquare 환경: th(라벨) + td(값) 테이블 구조.
    """
    # 일반내용 탭 클릭 (이미 활성일 수 있음)
    _click_result_tab(page, "일반내용")
    page.wait_for_timeout(500)

    gc = GeneralContent(court=court, case_no=case_no)

    # 필드 매핑: 화면 라벨 → 속성
    field_map = {
        "사건명": "case_name",
        "접수일": "filed_date",
        "개시결정일": "commencement_date",
        "변제계획인가일": "plan_approved_date",
        "면책결정일": "discharge_date",
        "절차폐지결정일": "revocation_date",
        "종국결과": "terminal_result",
    }

    for label, attr in field_map.items():
        value = _read_field_value(page, label)
        if value is not None:
            setattr(gc, attr, value)

    return gc


def parse_orders(page: Page, court: str, case_no: str) -> list[OrderRow]:
    """진행내용 탭 → 진행구분=명령 → 보이는 명령 행만 파싱한다.

    표 헤더는 일자 | 내용 | 결과. 진행구분은 드롭다운 값(명령)이다.
    """
    _click_result_tab(page, "진행내용")
    page.wait_for_timeout(800)

    dvs = page.locator(f"select[id$='{ID_PROG_DVS}']")
    if dvs.count() == 0:
        dvs = page.locator("select").filter(has=page.locator("option", has_text="명령"))
    if dvs.count() > 0:
        _select_by_label(page, dvs.first, "명령")
        page.wait_for_timeout(800)

    rows: list[OrderRow] = []
    table = _find_order_table(page)
    if table is None:
        logger.warning("명령 테이블을 찾을 수 없습니다")
        return []

    header_idx = _order_header_index(table)
    tr_elements = table.locator("tbody tr")
    if tr_elements.count() == 0:
        tr_elements = table.locator("tr")
    for i in range(tr_elements.count()):
        tr = tr_elements.nth(i)
        if not tr.is_visible():
            continue
        cells = tr.locator("td")
        if cells.count() < 2:
            continue

        date_text = _cell(cells, header_idx.get("일자", 0))
        if date_text in ("일자", "날짜") or not date_text:
            continue
        content_i = header_idx.get("내용", 1)
        content_text = _cell(cells, content_i)
        cat_i = header_idx.get("진행구분")
        category_text = _cell(cells, cat_i) if cat_i is not None else "명령"
        if not category_text:
            category_text = "명령"

        if not content_text:
            continue

        rows.append(OrderRow(
            court=court,
            case_no=case_no,
            date=date_text,
            category=category_text,
            content=content_text,
            result="",
        ))

    return rows


def fetch_case(
    page: Page,
    court: str,
    year: str,
    case_type: str,
    serial: str,
    party: str,
    captcha_solver,
    raw_dir: Optional[Path] = None,
    max_captcha_retries: int = 1,
) -> CaseSnapshot:
    """한 사건을 조회하고 결과를 반환한다.

    Args:
        page: Playwright 페이지
        court: 법원명 (예: 인천지방법원)
        year: 년도 (예: 2024)
        case_type: 사건구분 (예: 개회)
        serial: 일련번호 (예: 176313)
        party: 당사자명 (예: 박미리)
        captcha_solver: 캡차 이미지 바이트 → 숫자 문자열 콜백
        raw_dir: 파싱 실패 시 원본 HTML 저장 디렉터리
        max_captcha_retries: 캡차 오답 시 재시도 횟수

    Returns:
        CaseSnapshot (not_found 또는 error 포함 가능)

    Raises:
        SsgoError: 사이트 오류 (결번이 아님)
        CaseNotFoundError: 사건이 존재하지 않음 (유효한 검색 응답)
    """
    case_no = f"{year}{case_type}{serial}"
    attach_dialog_capture(page)

    for attempt in range(1 + max_captcha_retries):
        try:
            # 1. 법원 → 년도 → 사건구분 → 일련번호 → 당사자명
            select_court(page, court)
            select_year(page, year)
            select_case_type(page, case_type)
            fill_serial(page, serial)
            fill_party(page, party)

            # 2. 캡차
            captcha_bytes = get_captcha_image(page)
            captcha_answer = captcha_solver(captcha_bytes)
            fill_captcha(page, captcha_answer)

            # 3. 검색
            click_search(page)

            # 4. 결과 확인 — 결번 팝업을 캡차 오답보다 먼저 본다
            if check_not_found(page):
                logger.info(f"[{case_no}] 사건이 존재하지 않습니다")
                return CaseSnapshot(
                    general=GeneralContent(court=court, case_no=case_no),
                    not_found=True,
                    fetched_at=datetime.now(),
                )

            if check_captcha_error(page):
                logger.warning(f"[{case_no}] 캡차 오답 (시도 {attempt + 1})")
                if attempt < max_captcha_retries:
                    page.reload(wait_until="networkidle")
                    continue
                raise CaptchaError(f"[{case_no}] 캡차 {1 + max_captcha_retries}회 오답")

            # 5. 성공 — 일반내용 + 진행명령 파싱
            general = parse_general_content(page, court, case_no)
            orders = parse_orders(page, court, case_no)

            return CaseSnapshot(
                general=general,
                orders=orders,
                fetched_at=datetime.now(),
            )

        except (CaptchaError, CaseNotFoundError):
            raise
        except Exception as e:
            # 파싱 실패 시 원본 HTML 저장
            if raw_dir:
                _save_raw_html(page, court, case_no, raw_dir)
            raise SsgoError(f"[{case_no}] 조회 실패: {e}") from e

    raise SsgoError(f"[{case_no}] 예상치 못한 상태")


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _select_by_label(page: Page, select_el: Locator, label_text: str) -> None:
    """WebSquare select에서 label 텍스트로 옵션을 선택한다.

    value가 비어있으므로 option의 innerText로 매칭.
    """
    # select_option(label=...) 시도
    try:
        select_el.select_option(label=label_text)
        return
    except Exception:
        pass

    # JavaScript로 직접 선택
    try:
        select_el.evaluate("""
            (el, text) => {
                for (let opt of el.options) {
                    if (opt.text.trim() === text) {
                        el.value = opt.value;
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return;
                    }
                }
                // 부분 매칭
                for (let opt of el.options) {
                    if (opt.text.trim().includes(text)) {
                        el.value = opt.value;
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return;
                    }
                }
            }
        """, label_text)
        return
    except Exception:
        pass

    # 최후 수단: option 클릭
    options = select_el.locator("option")
    for i in range(options.count()):
        opt = options.nth(i)
        if label_text in opt.inner_text().strip():
            opt.click()
            return

    logger.warning(f"옵션 '{label_text}'을 찾을 수 없습니다")


def _click_result_tab(page: Page, tab_text: str) -> None:
    """결과 화면의 WebSquare 탭(일반내용/진행내용)을 연다."""
    tab = page.locator(".w2tabcontrol_tab_center", has_text=tab_text)
    if tab.count() > 0:
        tab.last.click()
        page.wait_for_timeout(500)
        return
    _click_tab(page, tab_text)


def _click_tab(page: Page, tab_text: str) -> None:
    """탭 텍스트로 탭을 클릭한다."""
    tab = page.locator(f"li:has-text('{tab_text}'), [role='tab']:has-text('{tab_text}')")
    if tab.count() > 0:
        tab.first.click()
        return
    tab = page.locator(f"text={tab_text}")
    if tab.count() > 0:
        tab.first.click()


def _read_field_value(page: Page, label: str) -> Optional[str]:
    """일반내용에서 라벨의 **바로 옆** td만 읽는다.

    한 행에 사건번호|값|사건명|값 처럼 칸이 여러 쌍이면 td.first는 틀린 값이다.
    """
    ths = page.locator("th")
    for i in range(ths.count()):
        th = ths.nth(i)
        text = (th.inner_text() or "").strip()
        if text != label:
            continue
        nxt = th.locator("xpath=following-sibling::*[1]")
        if nxt.count() == 0:
            continue
        val = nxt.first.inner_text().strip()
        return val

    labels = page.locator("label")
    for i in range(labels.count()):
        lab = labels.nth(i)
        if (lab.inner_text() or "").strip() != label:
            continue
        nxt = lab.locator("xpath=following-sibling::*[1]")
        if nxt.count() > 0:
            return nxt.first.inner_text().strip()
    return None


def _cell(cells: Locator, idx: int) -> str:
    if idx is None or idx < 0 or idx >= cells.count():
        return ""
    return cells.nth(idx).inner_text().strip()


def _order_header_index(table: Locator) -> dict[str, int]:
    """헤더 텍스트 → 열 번호."""
    idx: dict[str, int] = {}
    header_row = table.locator("thead tr").first
    if header_row.count() == 0:
        header_row = table.locator("tr").first
    heads = header_row.locator("th, td")
    for i in range(heads.count()):
        name = heads.nth(i).inner_text().strip()
        if name and name not in idx:
            idx[name] = i
    return idx


def _find_order_table(page: Page) -> Optional[Locator]:
    """진행내용 명령 표: 일자 + 내용 + 결과 헤더를 우선한다."""
    tables = page.locator("table")
    scored: list[tuple[int, Locator]] = []
    for i in range(tables.count()):
        table = tables.nth(i)
        header = table.locator("thead")
        if header.count() > 0:
            header_text = header.first.inner_text() or ""
        else:
            header_text = table.locator("tr").first.inner_text() or ""
        score = 0
        if "일자" in header_text:
            score += 1
        if "내용" in header_text:
            score += 1
        if "결과" in header_text:
            score += 2
        if "공시문" in header_text:
            score += 1
        if score >= 2:
            scored.append((score, table))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _save_raw_html(page: Page, court: str, case_no: str, raw_dir: Path) -> None:
    """파싱 실패 시 원본 HTML을 raw/에 저장."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{court}_{case_no}_{ts}.html"
    try:
        html = page.content()
        (raw_dir / filename).write_text(html, encoding="utf-8")
        logger.info(f"원본 HTML 저장: {raw_dir / filename}")
    except Exception as e:
        logger.error(f"원본 HTML 저장 실패: {e}")
