"""HTML 리포트 렌더링."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).resolve().parent


def _krw(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return "-"


def _krw_compact(value: Any) -> str:
    """원 단위 숫자를 조원/억원으로 압축."""
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    abs_v = abs(v)
    if abs_v >= 1_0000_0000_0000:  # 1조
        jo = v / 1_0000_0000_0000
        return f"{jo:,.2f}조원"
    if abs_v >= 1_0000_0000:  # 1억
        eok = v / 1_0000_0000
        return f"{eok:,.0f}억원"
    if abs_v >= 1_0000:  # 1만
        return f"{v / 1_0000:,.0f}만원"
    return f"{v:,.0f}원"


def _num_compact(value: Any) -> str:
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(v) >= 1_0000_0000:
        return f"{v / 1_0000_0000:,.1f}억"
    if abs(v) >= 1_0000:
        return f"{v / 1_0000:,.0f}만"
    return f"{v:,.0f}"


def _render_markdown(text: str | None) -> str:
    if not text:
        return ""
    return md.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def _verdict_class(opinion: str | None) -> str:
    if not opinion:
        return "hold"
    o = opinion.strip()
    if o in ("매수", "BUY", "Buy"):
        return "buy"
    if o in ("매도", "SELL", "Sell"):
        return "sell"
    return "hold"


_FILENAME_INVALID = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    """Windows에서 사용 불가능한 문자를 제거."""
    cleaned = "".join("_" if ch in _FILENAME_INVALID else ch for ch in name)
    return cleaned.strip().strip(".") or "report"


def generate_html_report(
    *,
    ticker: str,
    name: str,
    generated_at: datetime,
    company: dict[str, Any],
    market: dict[str, Any],
    indicators: dict[str, Any],
    chart_data: list[dict[str, Any]],
    report: dict[str, Any],
    output_dir: Path,
) -> Path:
    """리포트를 HTML로 렌더링하고 ``output_dir/{종목명}_{YYYY-MM-DD}.html`` 로 저장."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(disabled_extensions=("html",)),
    )
    env.filters["krw"] = _krw
    env.filters["krw_compact"] = _krw_compact
    env.filters["num_compact"] = _num_compact
    env.filters["markdown"] = _render_markdown

    target_price = report.get("target_price")
    current_price = indicators.get("current_price")
    upside = None
    if isinstance(target_price, (int, float)) and isinstance(current_price, (int, float)) and current_price > 0:
        upside = (target_price / current_price - 1) * 100

    template = env.get_template("template.html")
    html = template.render(
        ticker=ticker,
        name=name,
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M"),
        company=company,
        market=market,
        indicators=indicators,
        chart_data_json=json.dumps(chart_data, ensure_ascii=False),
        report=report,
        verdict_class=_verdict_class(report.get("investment_opinion")),
        upside=upside,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(name or ticker)
    out_path = output_dir / f"{safe_name}_{generated_at.strftime('%Y-%m-%d')}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
