"""캡차 풀이 — 화면 숫자를 읽어 입력한다.

토큰·쿠키를 훔치지 않는다. 이전 캡차 문자열을 재사용하지 않는다.
비전 기본: Xiaomi MiMo v2.5 (Token Plan, OpenAI 호환).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
import tempfile
from typing import Callable

from .ssgo import CaptchaError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5"
DEFAULT_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"
PASSWORD_ENV = "MIMO_API_KEY"
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
    if image_bytes.startswith(b"GIF8"):
        return "image/gif"
    return "image/png"


def solve_vision(
    image_bytes: bytes,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    client=None,
) -> str:
    """캡차 이미지 바이트 → 숫자 문자열. MiMo OpenAI 호환 비전 API."""
    if not image_bytes:
        raise CaptchaError("캡차 이미지가 비어 있습니다")

    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        api_key = os.environ.get(PASSWORD_ENV, "").strip()
        if not api_key:
            raise CaptchaError(
                f"{PASSWORD_ENV} 미설정. Token Plan 키(tp-...)를 환경변수로 넣으세요."
            )
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"api-key": api_key},
        )

    mime = _media_type(image_bytes)
    data_url = f"data:{mime};base64,{base64.standard_b64encode(image_bytes).decode('utf-8')}"
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=256,
        extra_body={"thinking": {"type": "disabled"}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {
                    "type": "text",
                    "text": (
                        "This is a numeric CAPTCHA from a Korean court website. "
                        "Reply with the digits only. No words, spaces, or punctuation."
                    ),
                },
            ],
        }],
    )
    text = ""
    try:
        text = response.choices[0].message.content or ""
    except (AttributeError, IndexError) as e:
        raise CaptchaError(f"비전 응답 형식 오류: {e}") from e

    digits = parse_digits(text)
    logger.info("비전 캡차 판독: %s자리", len(digits))
    return digits


def solve_manual(image_bytes: bytes) -> str:
    """캡차 이미지를 임시 파일로 남기고 사람이 숫자를 입력한다."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(image_bytes)
        tmp_path = f.name
    print(f"\n[CAPTCHA] 이미지: {tmp_path}")
    try:
        answer = input("캡차 숫자를 입력하세요: ").strip()
    except EOFError as e:
        raise CaptchaError("수동 캡차 입력을 받을 수 없습니다") from e
    return parse_digits(answer)


def make_solver(settings: dict) -> Callable[[bytes], str]:
    """settings.yaml captcha 절에서 solver 콜백을 만든다."""
    cfg = settings.get("captcha") or {}
    mode = (cfg.get("mode") or "vision").strip().lower()
    model = cfg.get("model") or DEFAULT_MODEL
    base_url = cfg.get("base_url") or os.environ.get("MIMO_BASE_URL") or DEFAULT_BASE_URL
    fallback_manual = bool(cfg.get("fallback_manual", False))

    if mode == "manual":
        return solve_manual

    def vision_solver(image_bytes: bytes) -> str:
        try:
            return solve_vision(image_bytes, model=model, base_url=base_url)
        except CaptchaError:
            raise
        except Exception as e:
            logger.warning("비전 캡차 실패: %s", e)
            if fallback_manual and sys.stdin.isatty():
                logger.info("수동 입력으로 폴백")
                return solve_manual(image_bytes)
            raise CaptchaError(f"비전 캡차 실패: {e}") from e

    return vision_solver
