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

# 무료 티어 rate limit(429/RESOURCE_EXHAUSTED) 대비 재시도
_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 20


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _is_rate_limit(err: Exception) -> bool:
    msg = str(err).upper()
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "RATE" in msg


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
            if _is_rate_limit(e) and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_SEC * attempt
                logger.warning("Gemini rate limit, %d초 후 재시도 (%d/%d)", wait, attempt, _MAX_RETRIES)
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
