"""Gemini(google-genai) LLM 클라이언트.

분석 markdown 생성(`analyze`)과 구조화된 종합 결과 생성(`synthesize`)을 제공한다.
과거 claude-agent-sdk의 에이전트 호출을 대체하며, LLM은 순수 분석·작문만 담당한다.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

# 일시적 오류 재시도:
#   - rate limit (429 / RESOURCE_EXHAUSTED) — 무료 티어 분당 한도
#   - 일시적 서버 오류 (503 UNAVAILABLE / 500 INTERNAL 등) — 모델 과부하 스파이크
_MAX_RETRIES = 4
_RETRY_BACKOFF_SEC = 10

# str(err)에 나타나는 재시도 대상 키워드 (버전 무관하게 견고하도록 문자열 매칭)
_RETRYABLE_MARKERS = (
    "429",
    "RESOURCE_EXHAUSTED",
    "RATE LIMIT",
    "UNAVAILABLE",       # 503
    "INTERNAL",          # 500
    "DEADLINE_EXCEEDED",
    "OVERLOADED",
    "HIGH DEMAND",
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _is_retryable(err: Exception) -> bool:
    msg = str(err).upper()
    return any(marker in msg for marker in _RETRYABLE_MARKERS)


def _generate(config: types.GenerateContentConfig, contents: str) -> str:
    """rate limit 재시도를 포함한 단일 생성 호출. 응답 텍스트를 반환."""
    client = _get_client()
    last_err: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001 — SDK 예외 종류가 버전마다 달라 광범위 처리
            last_err = e
            if _is_retryable(e) and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_SEC * attempt
                logger.warning(
                    "Gemini 일시적 오류, %d초 후 재시도 (%d/%d): %s",
                    wait, attempt, _MAX_RETRIES, str(e)[:120],
                )
                time.sleep(wait)
                continue
            raise
    assert last_err is not None
    raise last_err


def analyze(system_prompt: str, data_context: str, *, use_web_search: bool = False) -> str:
    """시스템 프롬프트 + 데이터 컨텍스트로 분석 markdown을 생성."""
    config_kwargs: dict[str, Any] = {"system_instruction": system_prompt}
    if use_web_search:
        config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    return _generate(types.GenerateContentConfig(**config_kwargs), data_context)


_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": [
        "investment_opinion",
        "target_price",
        "investment_horizon",
        "one_line_summary",
        "key_risks",
        "master_synthesis",
    ],
    "properties": {
        "investment_opinion": {"type": "STRING", "enum": ["매수", "중립", "매도"]},
        "target_price": {"type": "INTEGER"},
        "investment_horizon": {"type": "STRING", "enum": ["단기", "중기", "장기"]},
        "one_line_summary": {"type": "STRING"},
        "key_risks": {"type": "ARRAY", "items": {"type": "STRING"}},
        "master_synthesis": {"type": "STRING"},
    },
}


def synthesize(system_prompt: str, data_context: str) -> dict[str, Any]:
    """4개 분석을 종합해 구조화된 투자의견 dict를 생성."""
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=_SYNTHESIS_SCHEMA,
    )
    text = _generate(config, data_context)
    return json.loads(text)
