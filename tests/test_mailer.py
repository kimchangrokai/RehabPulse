"""메일 발송 테스트 (FR-7). 실패는 실행 실패가 아니다."""

from rehabpulse.notify import mailer


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

    def __init__(self, host, port, timeout=None):
        FakeSMTP.last = {"conn": (host, port)}

    def starttls(self):
        FakeSMTP.last["tls"] = True

    def login(self, user, pw):
        FakeSMTP.last["login"] = (user, pw)

    def sendmail(self, frm, to, msg):
        FakeSMTP.last["mail"] = (frm, to)

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

    def test_send_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv(mailer.PASSWORD_ENV, "pw")

        def boom(*a, **k):
            raise OSError("connection failed")

        monkeypatch.setattr(mailer.smtplib, "SMTP", boom)
        assert mailer.send_mail("제목", "본문", CFG) is False
