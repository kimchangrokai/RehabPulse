"""캡차 풀이 — 화면 숫자를 읽어 입력한다.

토큰·쿠키를 훔치지 않는다. 이전 캡차 문자열을 재사용하지 않는다.
"""

from __future__ import annotations

import base64
import logging
import re
import sys
import tempfile
from typing import Callable

from .ssgo import CaptchaError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
_DIGIT_RE = re.compile(r"\D+")


def parse_digits(text: str, min_len: int = 4, max_len: int = 8) -> str:
    """모델 응답에서 숫자만 남긴다."""
    digits = _DIGIT_RE.sub("", text or "")
    if not (min_len <= len(digits) <= max_len):
        raise CaptchaError(f"캡차 숫자 파싱 실패: {text!r}")
    return digits


def _media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "image/png"


def solve_vision(
    image_bytes: bytes,
    model: str = DEFAULT_MODEL,
    client=None,
) -> str:
    """캡차 이미지 바이트 → 숫자 문자열. Anthropic 비전 API."""
    if not image_bytes:
        raise CaptchaError("캡차 이미지가 비어 있습니다")

    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    kwargs = dict(
        model=model,
        max_tokens=1024,
        output_config={"effort": "low"},
        system=(
            "You read numeric CAPTCHA images from a Korean court website. "
            "Reply with the digits only. No words, spaces, or punctuation."
        ),
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _media_type(image_bytes),
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": "Read the CAPTCHA. Reply with digits only.",
                },
            ],
        }],
    )
    beta_messages = getattr(getattr(client, "beta", None), "messages", None)
    if beta_messages is not None:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
        response = beta_messages.create(**kwargs)
    else:
        response = client.messages.create(**kwargs)

    if getattr(response, "stop_reason", None) == "refusal":
        raise CaptchaError("비전 모델이 캡차 판독을 거부했습니다")

    text = "".join(
        getattr(block, "text", "")
        for block in (response.content or [])
        if getattr(block, "type", "") == "text"
    )
    digits = parse_digits(text)
    logger.info("비전 캡차 판독: %s자리", len(digits))
    return digits


def solve_manual(image_bytes: bytes) -> str:
    """캡차 이미지를 임시 파일로 남기고 사람이 숫자를 입력한다."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(image_bytes)
        tmp_path = f.name
    print(f"\n[CAPTCHA] 이미지: {tmp_path}")
    answer = input("캡차 숫자를 입력하세요: ").strip()
    return parse_digits(answer)


def make_solver(settings: dict) -> Callable[[bytes], str]:
    """settings.yaml captcha 절에서 solver 콜백을 만든다."""
    cfg = settings.get("captcha") or {}
    mode = (cfg.get("mode") or "vision").strip().lower()
    model = cfg.get("model") or DEFAULT_MODEL
    fallback_manual = bool(cfg.get("fallback_manual", True))

    if mode == "manual":
        return solve_manual

    def vision_solver(image_bytes: bytes) -> str:
        try:
            return solve_vision(image_bytes, model=model)
        except CaptchaError:
            raise
        except Exception as e:
            logger.warning("비전 캡차 실패: %s", e)
            if fallback_manual and sys.stdin.isatty():
                logger.info("수동 입력으로 폴백")
                return solve_manual(image_bytes)
            raise CaptchaError(f"비전 캡차 실패: {e}") from e

    return vision_solver
