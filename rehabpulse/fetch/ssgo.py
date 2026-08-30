"""ssgo.scourt.go.kr 나의 사건검색 — 브라우저 폼 조작 + 파싱.

사이트 의존 코드는 이 파일 안에만 둔다.
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

    WebSquare 환경: 라벨 텍스트로 찾는다.
    """
    # 법원 select/combo 찾기 — 라벨 '법원 선택' 근처
    court_select = _find_select_by_label(page, "법원")
    if court_select is None:
        raise SsgoError("법원 선택 드롭다운을 찾을 수 없습니다")

    _select_option(page, court_select, court)
    page.wait_for_timeout(500)  # 사건구분 목록 갱신 대기


def select_year(page: Page, year: str) -> None:
    """년도 선택."""
    year_select = _find_select_by_label(page, "년도")
    if year_select is None:
        raise SsgoError("년도 선택 드롭다운을 찾을 수 없습니다")
    _select_option(page, year_select, year)


def select_case_type(page: Page, case_type: str) -> None:
    """사건구분 선택 (예: 개회). 법원 변경 후 목록이 바뀌므로 반드시 법원 이후에 호출."""
    type_select = _find_select_by_label(page, "사건구분")
    if type_select is None:
        raise SsgoError("사건구분 선택 드롭다운을 찾을 수 없습니다")
    _select_option(page, type_select, case_type)


def fill_serial(page: Page, serial: str) -> None:
    """사건일련번호 입력."""
    serial_input = _find_input_by_label(page, "사건일련번호")
    if serial_input is None:
        # 대안: '일련번호' 라벨
        serial_input = _find_input_by_label(page, "일련번호")
    if serial_input is None:
        raise SsgoError("사건일련번호 입력란을 찾을 수 없습니다")
    serial_input.fill("")
    serial_input.fill(serial)


def fill_party(page: Page, party: str) -> None:
    """당사자명 입력 (빈칸 금지)."""
    if not party or not party.strip():
        raise SsgoError("당사자명은 필수 입력값입니다")
    party_input = _find_input_by_label(page, "당사자명")
    if party_input is None:
        raise SsgoError("당사자명 입력란을 찾을 수 없습니다")
    party_input.fill("")
    party_input.fill(party.strip())


def get_captcha_image(page: Page) -> bytes:
    """캡차 이미지의 스크린샷 바이트를 반환한다.

    매 검색마다 새 이미지가 생성되므로, 이전 이미지를 재사용하지 않는다.
    """
    # 캡차 이미지 요소 찾기
    captcha_img = page.locator("img[alt*='보안'], img[alt*='캡차'], img[alt*='자동입력']")
    if captcha_img.count() == 0:
        # 대안: src에 captcha/security 키워드
        captcha_img = page.locator("img[src*='captcha'], img[src*='Captcha'], img[src*='security']")
    if captcha_img.count() == 0:
        raise CaptchaError("캡차 이미지를 찾을 수 없습니다")

    img_bytes = captcha_img.first.screenshot()
    if not img_bytes:
        raise CaptchaError("캡차 이미지 스크린샷 실패")
    return img_bytes


def fill_captcha(page: Page, answer: str) -> None:
    """캡차 답 입력."""
    captcha_input = _find_input_by_label(page, "자동입력 방지문자")
    if captcha_input is None:
        # 대안: 보안문자, 캡차
        captcha_input = _find_input_by_label(page, "보안문자")
    if captcha_input is None:
        captcha_input = _find_input_by_label(page, "방지문자")
    if captcha_input is None:
        raise CaptchaError("캡차 입력란을 찾을 수 없습니다")
    captcha_input.fill("")
    captcha_input.fill(answer)


def click_search(page: Page) -> None:
    """검색 버튼 클릭."""
    search_btn = page.locator("button:has-text('검색'), input[value='검색'], a:has-text('검색')")
    if search_btn.count() == 0:
        raise SsgoError("검색 버튼을 찾을 수 없습니다")
    search_btn.first.click()
    page.wait_for_timeout(2000)  # 결과 로드 대기


def check_not_found(page: Page) -> bool:
    """검색 결과가 '사건이 존재하지 않습니다'인지 확인."""
    body_text = page.inner_text("body")
    return "사건이 존재하지 않습니다" in body_text


def check_captcha_error(page: Page) -> bool:
    """캡차 오답 여부 확인."""
    body_text = page.inner_text("body")
    return any(kw in body_text for kw in ["자동입력 방지문자가 일치하지", "보안문자가 일치하지", "방지문자"])


# ── 결과 파싱 ────────────────────────────────────────────────────────

def parse_general_content(page: Page, court: str, case_no: str) -> GeneralContent:
    """일반내용(기본내용) 탭에서 핵심 일자를 파싱한다.

    성공 시 결과 탭이 생기며, 일반내용 / 진행내용 탭이 나타난다.
    """
    # 일반내용 탭 클릭 (이미 활성일 수 있음)
    general_tab = page.locator("text=일반내용, text=기본내용")
    if general_tab.count() > 0:
        general_tab.first.click()
        page.wait_for_timeout(500)

    gc = GeneralContent(court=court, case_no=case_no)

    # 필드 매핑: 화면 라벨 → 속성
    field_map = {
        "사건번호": "case_name",     # 사건번호는 이미 알고 있으나 화면 값도 저장
        "사건명": "case_name",
        "재판부": "panel",
        "회생위원": "panel",
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
    """진행내용 탭 → 진행구분=명령 필터 → 명령 행을 파싱한다."""
    # 진행내용 탭 클릭
    order_tab = page.locator("text=진행내용")
    if order_tab.count() == 0:
        logger.warning("진행내용 탭을 찾을 수 없습니다")
        return []
    order_tab.first.click()
    page.wait_for_timeout(500)

    # 진행구분 드롭다운을 '명령'으로 변경
    cat_select = _find_select_by_label(page, "진행구분")
    if cat_select is not None:
        _select_option(page, cat_select, "명령")
        page.wait_for_timeout(500)

    # 명령 테이블 파싱
    rows: list[OrderRow] = []
    table = _find_order_table(page)
    if table is None:
        logger.warning("명령 테이블을 찾을 수 없습니다")
        return []

    tr_elements = table.locator("tbody tr")
    for i in range(tr_elements.count()):
        tr = tr_elements.nth(i)
        cells = tr.locator("td")
        cell_count = cells.count()
        if cell_count < 2:
            continue

        # 열 구조: 일자 | 진행구분/내용 | 결과 (사이트마다 다를 수 있음)
        date_text = cells.nth(0).inner_text().strip()
        content_text = cells.nth(1).inner_text().strip() if cell_count > 1 else ""
        result_text = cells.nth(2).inner_text().strip() if cell_count > 2 else ""

        if not date_text and not content_text:
            continue

        rows.append(OrderRow(
            court=court,
            case_no=case_no,
            date=date_text,
            category=content_text,  # 진행구분이 곧 내용
            content=content_text,
            result=result_text,
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

            # 4. 결과 확인
            if check_captcha_error(page):
                logger.warning(f"[{case_no}] 캡차 오답 (시도 {attempt + 1})")
                if attempt < max_captcha_retries:
                    page.reload(wait_until="networkidle")
                    continue
                raise CaptchaError(f"[{case_no}] 캡차 {1 + max_captcha_retries}회 오답")

            if check_not_found(page):
                logger.info(f"[{case_no}] 사건이 존재하지 않습니다")
                return CaseSnapshot(
                    general=GeneralContent(court=court, case_no=case_no),
                    not_found=True,
                    fetched_at=datetime.now(),
                )

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

    # 여기까지 오면 안 됨 (루프에서 처리됨)
    raise SsgoError(f"[{case_no}] 예상치 못한 상태")


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _find_select_by_label(page: Page, label_text: str) -> Optional[Locator]:
    """라벨 텍스트로 select/combo 요소를 찾는다 (WebSquare 호환)."""
    # label + select 패턴
    labels = page.locator(f"label:has-text('{label_text}')")
    for i in range(labels.count()):
        label = labels.nth(i)
        for_attr = label.get_attribute("for")
        if for_attr:
            sel = page.locator(f"select#{for_attr}, select[name='{for_attr}']")
            if sel.count() > 0:
                return sel.first

    # 대안: 라벨 텍스트 근처의 select
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        parent = sel.locator("xpath=..")
        if label_text in (parent.inner_text() or ""):
            return sel

    # WebSquare: 콤보박스 div
    combos = page.locator(f"[class*='combo']:has-text('{label_text}')")
    if combos.count() > 0:
        return combos.first

    return None


def _find_input_by_label(page: Page, label_text: str) -> Optional[Locator]:
    """라벨 텍스트로 input 요소를 찾는다."""
    labels = page.locator(f"label:has-text('{label_text}')")
    for i in range(labels.count()):
        label = labels.nth(i)
        for_attr = label.get_attribute("for")
        if for_attr:
            inp = page.locator(f"input#{for_attr}, input[name='{for_attr}']")
            if inp.count() > 0:
                return inp.first

    # 대안: 라벨 근처 input
    inputs = page.locator("input[type='text'], input:not([type])")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        parent = inp.locator("xpath=..")
        if label_text in (parent.inner_text() or ""):
            return inp

    return None


def _select_option(page: Page, select_el: Locator, value: str) -> None:
    """select/combo에서 value 또는 텍스트로 옵션을 선택한다."""
    tag = select_el.evaluate("el => el.tagName.toLowerCase()")
    if tag == "select":
        # select 태그: option value 또는 text로 선택
        try:
            select_el.select_option(label=value)
        except Exception:
            select_el.select_option(value=value)
    else:
        # WebSquare combo: 클릭 후 옵션 텍스트 클릭
        select_el.click()
        page.wait_for_timeout(300)
        option = page.locator(f"text='{value}'").first
        if option.count() > 0:
            option.click()
        else:
            # 부분 매칭
            option = page.locator(f"li:has-text('{value}'), option:has-text('{value}')")
            if option.count() > 0:
                option.first.click()


def _read_field_value(page: Page, label: str) -> Optional[str]:
    """일반내용 화면에서 라벨 옆 값을 읽는다.

    WebSquare 환경: 테이블 행 구조 (th: 라벨, td: 값) 또는 label + span.
    """
    # th/td 패턴
    th = page.locator(f"th:has-text('{label}')")
    if th.count() > 0:
        row = th.first.locator("xpath=..")
        td = row.locator("td")
        if td.count() > 0:
            return td.first.inner_text().strip()

    # label + span/input 패턴
    labels = page.locator(f"label:has-text('{label}')")
    if labels.count() > 0:
        parent = labels.first.locator("xpath=..")
        span = parent.locator("span, input")
        if span.count() > 0:
            return span.first.inner_text().strip()

    return None


def _find_order_table(page: Page) -> Optional[Locator]:
    """진행내용 영역의 명령 테이블을 찾는다."""
    # 테이블에 '일자' 헤더가 있는 것
    tables = page.locator("table")
    for i in range(tables.count()):
        table = tables.nth(i)
        header_text = table.locator("thead, tr:first-child").inner_text() or ""
        if "일자" in header_text and ("내용" in header_text or "진행구분" in header_text):
            return table

    # 대안: 가장 큰 테이블
    if tables.count() > 0:
        return tables.first

    return None


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
