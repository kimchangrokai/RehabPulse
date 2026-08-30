"""비전 캡차 solver 테스트. API는 Fake client로 대체."""

from types import SimpleNamespace

import pytest

from rehabpulse.fetch.captcha import (
    DEFAULT_MODEL,
    make_solver,
    parse_digits,
    solve_vision,
)
from rehabpulse.fetch.ssgo import CaptchaError

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeMessages:
    last = {}
    reply = "123456"
    stop_reason = "end_turn"

    def create(self, **kwargs):
        FakeMessages.last = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.reply)],
        )


class FakeBeta:
    def __init__(self):
        self.messages = FakeMessages()


class FakeClient:
    def __init__(self):
        self.beta = FakeBeta()
        self.messages = FakeMessages()


class TestParseDigits:
    def test_strips_noise(self):
        assert parse_digits("답: 12 34 56") == "123456"

    def test_rejects_too_short(self):
        with pytest.raises(CaptchaError):
            parse_digits("12")

    def test_rejects_empty(self):
        with pytest.raises(CaptchaError):
            parse_digits("abc")


class TestSolveVision:
    def test_reads_digits(self):
        FakeMessages.reply = "384291"
        FakeMessages.stop_reason = "end_turn"
        digits = solve_vision(PNG, client=FakeClient())
        assert digits == "384291"
        kwargs = FakeMessages.last
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["output_config"]["effort"] == "low"
        image = kwargs["messages"][0]["content"][0]
        assert image["type"] == "image"
        assert image["source"]["media_type"] == "image/png"
        assert kwargs["fallbacks"] == "default"

    def test_refusal_raises(self):
        FakeMessages.stop_reason = "refusal"
        FakeMessages.reply = ""
        with pytest.raises(CaptchaError, match="거부"):
            solve_vision(PNG, client=FakeClient())
        FakeMessages.stop_reason = "end_turn"

    def test_empty_image_raises(self):
        with pytest.raises(CaptchaError):
            solve_vision(b"", client=FakeClient())


class TestMakeSolver:
    def test_vision_mode(self, monkeypatch):
        monkeypatch.setattr(
            "rehabpulse.fetch.captcha.solve_vision",
            lambda image_bytes, model="claude-opus-5": "999888",
        )
        solver = make_solver({"captcha": {"mode": "vision", "fallback_manual": False}})
        assert solver(PNG) == "999888"

    def test_vision_failure_without_tty_raises(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no key")

        monkeypatch.setattr("rehabpulse.fetch.captcha.solve_vision", boom)
        monkeypatch.setattr("rehabpulse.fetch.captcha.sys.stdin.isatty", lambda: False)
        solver = make_solver({"captcha": {"mode": "vision", "fallback_manual": True}})
        with pytest.raises(CaptchaError, match="비전 캡차 실패"):
            solver(PNG)
