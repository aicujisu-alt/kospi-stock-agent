"""수정된 _extract_financial_items 검증."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from src.config import DART_API_KEY  # noqa: E402
from src.data.dart_client import DartClient  # noqa: E402
from src.tools import _extract_financial_items  # noqa: E402


def main() -> None:
    client = DartClient(DART_API_KEY)
    out_path = Path(__file__).parent / "diag_extract_out.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for ticker in ("005380", "034730", "096770"):
            stmts, basis = client.get_latest_annual_statements_with_fallback(ticker, years=3)
            f.write(f"\n=== {ticker}  fs_basis={basis}  연도수={len(stmts)} ===\n")
            for s in stmts:
                items = _extract_financial_items(s.get("list", []))
                f.write(f"  {s['year']}: {json.dumps(items, ensure_ascii=False)}\n")
    print(f"결과: {out_path}")


if __name__ == "__main__":
    main()
