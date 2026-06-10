"""DART 재무제표 응답 진단 (UTF-8 파일로 출력)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")
from src.config import DART_API_KEY  # noqa: E402
from src.data.dart_client import DartClient  # noqa: E402


def inspect(client: DartClient, ticker: str, year: int, out) -> None:
    out.write(f"\n=== {ticker} / 사업연도 {year} ===\n")
    for fs_div in ("CFS", "OFS"):
        try:
            data = client.get_financial_statements(ticker, year, fs_div=fs_div)
        except Exception as e:
            out.write(f"  [{fs_div}] 예외: {type(e).__name__}: {e}\n")
            continue
        rows = data.get("list") or []
        out.write(
            f"  [{fs_div}] status={data.get('status')} msg={data.get('message')} rows={len(rows)}\n"
        )
        if not rows:
            continue
        names = Counter((r.get("account_nm") or "").strip() for r in rows)
        fs_divs = Counter((r.get("fs_div") or "") for r in rows)
        sj_divs = Counter((r.get("sj_div") or "") for r in rows)
        out.write(f"    fs_div 분포: {dict(fs_divs)}\n")
        out.write(f"    sj_div 분포: {dict(sj_divs)}\n")
        for kw in ["매출", "영업이익", "순이익", "자산총계", "부채총계", "자본총계", "영업활동"]:
            matched = [n for n in names if kw in n]
            out.write(f"    '{kw}' 후보: {matched[:8]}\n")
        # 영업이익 한 줄 raw 보기
        for r in rows:
            if (r.get("account_nm") or "").strip() == "영업이익":
                out.write(
                    f"    [영업이익 row] fs_div={r.get('fs_div')!r} sj_div={r.get('sj_div')!r} "
                    f"thstrm_amount={r.get('thstrm_amount')!r}\n"
                )
                break


if __name__ == "__main__":
    out_path = Path(__file__).parent.parent / "scripts" / "diag_dart_out.txt"
    with out_path.open("w", encoding="utf-8") as f:
        client = DartClient(DART_API_KEY)
        for ticker in ("034730", "096770", "005380"):
            for year in (2024, 2023):
                inspect(client, ticker, year, f)
    print(f"결과 저장: {out_path}")
