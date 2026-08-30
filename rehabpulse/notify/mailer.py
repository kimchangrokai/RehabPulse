"""SMTP 이메일 발송 — AuctionPulse와 동일한 패턴.

비밀번호는 환경변수 REHABPULSE_SMTP_PASSWORD (없으면 AUCTIONPULSE_SMTP_PASSWORD fallback).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


def send_mail(
    subject: str,
    body: str,
    config: dict,
) -> bool:
    """이메일을 발송한다. 실패 시 False 반환 (예외를 올리지 않음)."""
    if not config.get("enabled", False):
        logger.info("이메일 비활성화 상태")
        return False

    password = os.environ.get("REHABPULSE_SMTP_PASSWORD") or \
               os.environ.get("AUCTIONPULSE_SMTP_PASSWORD")
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
