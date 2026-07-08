"""환경 설정 및 상수."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DART_API_KEY = os.getenv("DART_API_KEY", "")

REPORT_OUTPUT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", PROJECT_ROOT / "reports"))
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 분석·종합에 사용할 Gemini 모델 (무료 티어: gemini-2.5-flash / gemini-2.0-flash)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 뉴스·공시 분석 시 Google Search grounding 사용 여부.
# 무료 티어 grounding 한도를 소모하며, 실패 시 DART 공시만으로 자동 폴백한다.
NEWS_USE_WEB_SEARCH = os.getenv("NEWS_USE_WEB_SEARCH", "true").lower() in ("1", "true", "yes")


def require_keys() -> None:
    """필수 API 키 확인. 누락 시 친절한 에러."""
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not DART_API_KEY:
        missing.append("DART_API_KEY")
    if missing:
        raise RuntimeError(
            f"필수 환경 변수 누락: {', '.join(missing)}. "
            ".env 파일을 확인하세요 (.env.example 참고)."
        )
