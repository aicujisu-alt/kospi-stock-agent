"""환경 설정 및 상수."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DART_API_KEY = os.getenv("DART_API_KEY", "")

REPORT_OUTPUT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", PROJECT_ROOT / "reports"))
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUBAGENT_MODEL = os.getenv("SUBAGENT_MODEL", "haiku")
MASTER_AGENT_MODEL = os.getenv("MASTER_AGENT_MODEL", "sonnet")


def require_keys() -> None:
    """필수 API 키 확인. 누락 시 친절한 에러."""
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not DART_API_KEY:
        missing.append("DART_API_KEY")
    if missing:
        raise RuntimeError(
            f"필수 환경 변수 누락: {', '.join(missing)}. "
            ".env 파일을 확인하세요 (.env.example 참고)."
        )
