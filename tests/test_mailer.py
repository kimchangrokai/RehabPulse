"""메일 발송 테스트 (FR-7). 실패는 실행 실패가 아니다."""

from rehabpulse.notify import mailer
from rehabpulse.models import CaseRecord


CFG = {
    "enabled": True,
    "smtp_host": "smtp.test",
    "smtp_port": 587,
    "use_tls": True,
    "sender": "a@b.c",
    "recipients": ["x@y.z"],
}


class FakeSMTP:
    last = {}
    messages: list[str] = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.last = {"conn": (host, port)}

    def starttls(self):
        FakeSMTP.last["tls"] = True

    def login(self, user, pw):
        FakeSMTP.last["login"] = (user, pw)

    def sendmail(self, frm, to, msg):
        FakeSMTP.last["mail"] = (frm, to)
        FakeSMTP.messages.append(msg)

    def quit(self):
        FakeSMTP.last["quit"] = True


class TestMailer:
    def test_skip_disabled(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "pw")
        assert mailer.send_mail("제목", "본문", {"enabled": False}) is False

    def test_skip_without_password(self, monkeypatch):
        monkeypatch.delenv(mailer.PASSWORD_ENV, raising=False)
        monkeypatch.delenv(mailer.PASSWORD_ENV_FALLBACK, raising=False)
        assert mailer.send_mail("제목", "본문", CFG) is False

    def test_fallback_password(self, monkeypatch):
        monkeypatch.delenv(mailer.PASSWORD_ENV, raising=False)
        monkeypatch.setenv(mailer.PASSWORD_ENV_FALLBACK, "secret")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
        assert mailer.send_mail("제목", "본문", CFG) is True
        assert FakeSMTP.last["login"] == ("a@b.c", "secret")

    def test_skip_incomplete_config(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "pw")
        assert mailer.send_mail("제목", "본문", {"enabled": True}) is False

    def test_send_success(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "secret")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
        assert mailer.send_mail("제목", "본문", CFG) is True
        assert FakeSMTP.last["conn"] == ("smtp.test", 587)
        assert FakeSMTP.last["tls"] is True
        assert FakeSMTP.last["login"] == ("a@b.c", "secret")
        assert FakeSMTP.last["mail"] == ("a@b.c", ["x@y.z"])
        assert FakeSMTP.last["quit"] is True

    def test_send_custom_recipients(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "secret")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
        assert mailer.send_mail(
            "제목", "본문", CFG, recipients=["sonaba79@gmail.com"],
        ) is True
        assert FakeSMTP.last["mail"][1] == ["sonaba79@gmail.com"]

    def test_send_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "pw")

        def boom(*a, **k):
            raise OSError("connection failed")

        monkeypatch.setattr(mailer.smtplib, "SMTP", boom)
        assert mailer.send_mail("제목", "본문", CFG) is False

    def test_report_html_has_table_border(self):
        cases = [
            CaseRecord(
                court="인천지방법원", case_no="2025개회109323",
                year="2025", case_type="개회", serial="109323",
                party="최은숙", plan_approved="Y", last_result="success",
            ),
        ]
        html = mailer.build_report_html("2026-08-31 00:34", cases)
        assert "border:1px solid" in html
        assert "<table" in html
        assert "최은숙" in html
        assert "조회 성공" in html

    def test_send_with_attachment(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "secret")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
        FakeSMTP.messages = []
        attachment = [("rehabpulse.xlsx", b"fake-excel-data")]
        assert mailer.send_mail("제목", "본문", CFG, attachments=attachment) is True
        raw = FakeSMTP.messages[0]
        assert "rehabpulse.xlsx" in raw
        assert "base64" in raw

    def test_send_without_attachment(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "secret")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
        FakeSMTP.messages = []
        assert mailer.send_mail("제목", "본문", CFG) is True
        raw = FakeSMTP.messages[0]
        assert "rehabpulse.xlsx" not in raw
