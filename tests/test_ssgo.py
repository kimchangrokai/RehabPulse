"""ssgo 파서·폼 ID 테스트.

파서는 fixture HTML로 고정한다. 라이브 폼 채우기는 네트워크가 있을 때만 실행.
"""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from rehabpulse.fetch.ssgo import (
    ID_CAPTCHA_ANSWER,
    ID_CAPTCHA_IMG,
    ID_CASE_TYPE,
    ID_COURT,
    ID_PARTY,
    ID_SEARCH_BTN,
    ID_SERIAL,
    ID_YEAR,
    SSGO_URL,
    fill_party,
    fill_serial,
    is_captcha_mismatch,
    is_case_not_found,
    parse_general_content,
    parse_orders,
    select_case_type,
    select_court,
    select_year,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestAlertClassification:
    def test_form_hint_is_not_captcha_error(self):
        assert is_captcha_mismatch("자동입력 방지문자를 입력하세요") is False
        assert is_captcha_mismatch("자동 입력 방지 문자") is False

    def test_mismatch_is_captcha_error(self):
        assert is_captcha_mismatch("자동입력 방지문자가 일치하지 않습니다") is True

    def test_not_found_popup(self):
        assert is_case_not_found("사건이 존재하지 않습니다") is True
        assert is_captcha_mismatch("사건이 존재하지 않습니다") is False


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="ko-KR")
        page = ctx.new_page()
        yield page
        browser.close()


class TestParseGeneralContent:
    def test_reads_blank_dates(self, browser_page):
        html = (FIXTURES / "general_content.html").read_text(encoding="utf-8")
        browser_page.set_content(html)
        gc = parse_general_content(browser_page, "인천지방법원", "2024개회176313")
        assert gc.case_name == "개인회생"
        assert gc.filed_date == "2024.05.12"
        assert gc.commencement_date == ""
        assert gc.plan_approved_date == ""
        assert gc.discharge_date == ""
        assert gc.terminal_result == ""


class TestParseOrders:
    def test_park_miri_orders(self, browser_page):
        html = (FIXTURES / "orders_명령.html").read_text(encoding="utf-8")
        browser_page.set_content(html)
        rows = parse_orders(browser_page, "인천지방법원", "2024개회176313")
        contents = [r.content for r in rows]
        assert "개인회생절차개시신청 기각결정" in contents
        assert "기각취소결정" in contents
        assert [r.date for r in rows] == ["2025.02.18", "2025.03.05", "2025.09.08"]


@pytest.mark.live
class TestLiveFormFill:
    """실제 ssgo 검색 폼. 캡차는 입력하지 않고 제출하지 않는다."""

    def test_fill_park_miri_form(self, browser_page):
        browser_page.goto(SSGO_URL, wait_until="networkidle", timeout=30000)

        assert browser_page.locator(f"#{ID_COURT}").count() == 1
        assert browser_page.locator(f"#{ID_YEAR}").count() == 1
        assert browser_page.locator(f"#{ID_CASE_TYPE}").count() == 1
        assert browser_page.locator(f"#{ID_SERIAL}").count() == 1
        assert browser_page.locator(f"#{ID_PARTY}").count() == 1
        assert browser_page.locator(f"#{ID_CAPTCHA_IMG}").count() == 1
        assert browser_page.locator(f"#{ID_CAPTCHA_ANSWER}").count() == 1
        assert browser_page.locator(f"#{ID_SEARCH_BTN}").count() == 1

        select_court(browser_page, "인천지방법원")
        select_year(browser_page, "2024")
        select_case_type(browser_page, "개회")
        fill_serial(browser_page, "176313")
        fill_party(browser_page, "박미리")

        assert browser_page.locator(f"#{ID_SERIAL}").input_value() == "176313"
        assert browser_page.locator(f"#{ID_PARTY}").input_value() == "박미리"

        type_opts = [
            o.inner_text().strip()
            for o in browser_page.locator(f"#{ID_CASE_TYPE} option").all()
        ]
        assert "개회" in type_opts
