"""CLI 진입점.

사용법:
    python -m src.main <종목코드>
    python -m src.main 005930          # 삼성전자
    python -m src.main 005930 -v       # 상세 로그
"""
from __future__ import annotations

import argparse
import logging
import sys

# Windows 콘솔(cp949)에서 유니코드 문자(em-dash 등) 출력 시 예외 방지
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

import anyio

from .config import require_keys
from .master_agent import analyze_stock


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="KOSPI 개별 종목 투자 분석 리포트 생성 (Multi-agent)",
    )
    parser.add_argument("ticker", help="6자리 종목코드 (예: 005930 = 삼성전자)")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 로그 출력")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    try:
        require_keys()
    except RuntimeError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    ticker = args.ticker.strip().zfill(6)
    print(f"=== {ticker} 분석 시작 ===")

    async def _run() -> str | None:
        return await analyze_stock(ticker, verbose=True)

    try:
        report_path = anyio.run(_run)
    except KeyboardInterrupt:
        print("\n중단됨.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n분석 실패: {type(e).__name__}: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 2

    if report_path:
        print(f"\n[OK] 리포트 생성 완료: {report_path}")
        return 0

    print(
        "\n[FAIL] 리포트 생성 실패: Master agent가 save_final_report를 호출하지 않았습니다.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
