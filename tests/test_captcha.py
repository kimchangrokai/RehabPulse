"""비전 캡차 solver 테스트. MiMo API는 Fake client로 대체."""

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


class FakeCompletions:
    last = {}
    reply = "123456"

    def create(self, **kwargs):
        FakeCompletions.last = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.reply),
            )],
        )


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


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
        FakeCompletions.reply = "384291"
        digits = solve_vision(PNG, client=FakeClient())
        assert digits == "384291"
        kwargs = FakeCompletions.last
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["extra_body"]["thinking"]["type"] == "disabled"
        content = kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_empty_image_raises(self):
        with pytest.raises(CaptchaError):
            solve_vision(b"", client=FakeClient())

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("MIMO_API_KEY", raising=False)
        with pytest.raises(CaptchaError, match="MIMO_API_KEY"):
            solve_vision(PNG, client=None)


class TestMakeSolver:
    def test_vision_mode(self, monkeypatch):
        monkeypatch.setattr(
            "rehabpulse.fetch.captcha.solve_vision",
            lambda image_bytes, model="mimo-v2.5", base_url="": "999888",
        )
        solver = make_solver({"captcha": {"mode": "vision", "fallback_manual": False}})
        assert solver(PNG) == "999888"

    def test_vision_failure_without_fallback_raises(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no key")

        monkeypatch.setattr("rehabpulse.fetch.captcha.solve_vision", boom)
        solver = make_solver({"captcha": {"mode": "vision", "fallback_manual": False}})
        with pytest.raises(CaptchaError, match="비전 캡차 실패"):
            solver(PNG)
