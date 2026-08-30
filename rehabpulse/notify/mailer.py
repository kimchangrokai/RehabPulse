"""SMTP 이메일 발송 — AuctionPulse와 동일한 패턴.

비밀번호는 환경변수 REHABPULSE_SMTP_PASSWORD
(없으면 AUCTIONPULSE_SMTP_PASSWORD fallback).
발송 실패는 예외를 올리지 않고 False를 반환한다.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

logger = logging.getLogger(__name__)

PASSWORD_ENV = "REHABPULSE_SMTP_PASSWORD"
PASSWORD_ENV_FALLBACK = "AUCTIONPULSE_SMTP_PASSWORD"


def smtp_password() -> str:
    return os.environ.get(PASSWORD_ENV) or os.environ.get(PASSWORD_ENV_FALLBACK) or ""


def build_report_html(generated_at: str, cases: list) -> str:
    """현황 보고서 HTML. 실선 테두리 표."""
    rows = []
    for c in cases:
        result = c.last_result or "-"
        result_label = {
            "success": "조회 성공",
            "not_found": "결번",
            "error": "오류",
        }.get(result, result)
        rows.append(
            "<tr>"
            f"<td style='border:1px solid #333;padding:6px 10px'>{escape(str(c.court))}</td>"
            f"<td style='border:1px solid #333;padding:6px 10px'>{escape(str(c.case_no))}</td>"
            f"<td style='border:1px solid #333;padding:6px 10px'>{escape(str(c.party))}</td>"
            f"<td style='border:1px solid #333;padding:6px 10px;text-align:center'>{escape(str(c.plan_approved or '-'))}</td>"
            f"<td style='border:1px solid #333;padding:6px 10px;text-align:center'>{int(c.consecutive_miss_days)}</td>"
            f"<td style='border:1px solid #333;padding:6px 10px'>{escape(result_label)}</td>"
            "</tr>"
        )
    body_rows = "\n".join(rows) or (
        "<tr><td colspan='6' style='border:1px solid #333;padding:6px 10px;text-align:center'>등록된 활성 사건이 없습니다.</td></tr>"
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:'Malgun Gothic',sans-serif;font-size:14px;color:#222">
  <h2 style="margin:0 0 8px">RehabPulse 현황 보고서</h2>
  <p style="margin:0 0 12px">생성일: {escape(generated_at)} · 등록 사건: {len(cases)}건</p>
  <table style="border-collapse:collapse;border:1px solid #333">
    <thead>
      <tr>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">법원</th>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">사건번호</th>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">당사자</th>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">변제계획인가</th>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">miss</th>
        <th style="border:1px solid #333;padding:6px 10px;background:#f2f2f2">최근결과</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body></html>
"""


def send_mail(
    subject: str,
    body: str,
    config: dict,
    html: str | None = None,
) -> bool:
    """이메일을 발송한다. 실패 시 False 반환 (예외를 올리지 않음)."""
    if not config.get("enabled", False):
        logger.info("이메일 비활성화 상태")
        return False

    password = smtp_password()
    if not password:
        logger.warning("SMTP 비밀번호 미설정 (REHABPULSE_SMTP_PASSWORD)")
        return False

    sender = config.get("sender", "")
    recipients = config.get("recipients", [])
    if not sender or not recipients:
        logger.warning("이메일 발신자/수신자 미설정")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))

    host = config.get("smtp_host", "smtp.gmail.com")
    port = config.get("smtp_port", 587)
    use_tls = config.get("use_tls", True)

    try:
        if use_tls:
            server = smtplib.SMTP(host, port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port)

        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        logger.info(f"이메일 발송 완료: {subject}")
        return True
    except Exception as e:
        logger.error(f"이메일 발송 실패: {e}")
        return False
