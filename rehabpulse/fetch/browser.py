"""Playwright 브라우저 관리 — ssgo.scourt.go.kr 접속용"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

SSGO_URL = "https://ssgo.scourt.go.kr/ssgo/index.on?cortId=www"


@contextmanager
def launch_browser(headless: bool = True) -> Generator[BrowserContext, None, None]:
    """Playwright 브라우저 컨텍스트 매니저.

    사용 예:
        with launch_browser() as ctx:
            page = ctx.new_page()
            page.goto(SSGO_URL)
    """
    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                locale="ko-KR",
                viewport={"width": 1280, "height": 900},
            )
            context.set_default_timeout(30_000)
            yield context
        finally:
            browser.close()


def navigate_to_search(page: Page) -> None:
    """사건번호로 검색 탭으로 이동 (이미 해당 탭이면 스킵)."""
    page.goto(SSGO_URL, wait_until="networkidle")
    # 사건번호로 검색 탭 클릭 (기본 탭일 수 있으므로 확인)
    tab = page.locator("text=사건번호로 검색")
    if tab.count() > 0:
        tab.first.click()
        page.wait_for_timeout(500)
