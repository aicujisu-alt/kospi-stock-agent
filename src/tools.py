"""MCP 도구 정의 — sub-agent들과 master agent가 호출할 도구.

도구 이름은 자동으로 ``mcp__stockdata__{이름}`` 형식으로 노출된다.
"""
from __future__ import annotations

import json
import traceback
from datetime import datetime
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .config import DART_API_KEY, REPORT_OUTPUT_DIR
from .data.dart_client import DartClient
from .data.krx_client import KrxClient, compute_technical_indicators, ohlcv_for_chart


_dart: DartClient | None = None
_krx = KrxClient()


def _dart_client() -> DartClient:
    global _dart
    if _dart is None:
        _dart = DartClient(DART_API_KEY)
    return _dart


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON 본문을 텍스트로 직렬화해 MCP content block에 담는다."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ]
    }


def _err(message: str, **extra: Any) -> dict[str, Any]:
    payload = {"error": message, **extra}
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
        ],
        "is_error": True,
    }


@tool(
    "get_company_overview",
    "종목의 회사 개황(상호, 업종, 대표자, 설립일 등)을 반환한다. ticker는 6자리 종목코드.",
    {"ticker": str},
)
async def get_company_overview(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).zfill(6)
    try:
        dart = _dart_client()
        info = dart.get_company_info(ticker)
        if info.get("status") != "000":
            return _err(f"DART 회사 정보 조회 실패: {info.get('message')}")
        return _ok(
            {
                "ticker": ticker,
                "name_kr": info.get("corp_name"),
                "name_en": info.get("corp_name_eng"),
                "ceo": info.get("ceo_nm"),
                "industry": info.get("induty_code"),
                "address": info.get("adres"),
                "homepage": info.get("hm_url"),
                "established_date": info.get("est_dt"),
                "accounting_month": info.get("acc_mt"),
                "is_listed": info.get("corp_cls") == "Y",
            }
        )
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", traceback=traceback.format_exc())


@tool(
    "get_market_snapshot",
    "종목의 최근 영업일 기준 시가총액·현재가·PER·PBR·EPS·BPS·배당수익률·거래량을 반환한다.",
    {"ticker": str},
)
async def get_market_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).zfill(6)
    try:
        name = _krx.get_name(ticker)
        snap = _krx.get_market_snapshot(ticker)
        return _ok({"ticker": ticker, "name": name, **snap})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# account_nm 정규화 매핑 — DART 재무제표 표기 다양성 대응
#
# 회사별 변형 예:
#   - 손실 기재: "영업이익(손실)", "당기순이익(손실)"
#   - 연결 prefix: "당기연결순이익" (SK), "연결당기순이익" (현대차) — 같은 개념
#   - 현금흐름 표기: "영업활동현금흐름" vs "영업활동으로 인한 현금흐름"
# sj_div: BS=재무상태표, IS=손익계산서, CIS=포괄손익계산서, CF=현금흐름표, SCE=자본변동
#
# 각 룰의 candidates는 우선순위 리스트 — 위에 있을수록 선호. mode="exact_strip"는
# 접미어 "(손실)" 등을 떼고 정확히 일치해야 하고, mode="contains"는 부분 일치.
_FINANCIAL_ITEM_RULES: dict[str, dict[str, Any]] = {
    # 손익 항목 (IS/CIS)
    "매출액": {
        "candidates": [("매출액", "exact_strip")],
        "sj_div": {"IS", "CIS"},
        "exclude": ["주당"],
    },
    "매출원가": {
        "candidates": [("매출원가", "exact_strip")],
        "sj_div": {"IS", "CIS"},
    },
    "매출총이익": {
        "candidates": [("매출총이익", "exact_strip")],
        "sj_div": {"IS", "CIS"},
    },
    "판매비와관리비": {
        "candidates": [("판매비와관리비", "exact_strip")],
        "sj_div": {"IS", "CIS"},
    },
    "영업이익": {
        "candidates": [("영업이익", "exact_strip")],
        "sj_div": {"IS", "CIS"},
        "exclude": ["주당", "계속영업", "중단영업"],
    },
    "법인세비용차감전순이익": {
        # 우선순위: 표준 → 계속영업 표기 변형
        "candidates": [
            ("법인세비용차감전순이익", "exact_strip"),
            ("법인세차감전순이익", "exact_strip"),
            ("법인세비용차감전계속영업순이익", "contains"),
            ("계속영업법인세비용차감전순이익", "contains"),
        ],
        "sj_div": {"IS", "CIS"},
        "exclude": ["주당", "중단영업"],
    },
    "당기순이익": {
        # 우선순위: 표준 → 연결 변형
        "candidates": [
            ("당기순이익", "exact_strip"),
            ("연결당기순이익", "exact_strip"),
            ("당기연결순이익", "exact_strip"),
        ],
        "sj_div": {"IS", "CIS"},
        "exclude": ["주당", "계속영업", "중단영업", "지배기업", "비지배"],
    },
    # 재무상태표 (BS)
    "자산총계": {
        "candidates": [("자산총계", "exact_strip")],
        "sj_div": {"BS"},
    },
    "부채총계": {
        "candidates": [("부채총계", "exact_strip")],
        "sj_div": {"BS"},
        "exclude": ["자본과", "자본및"],
    },
    "자본총계": {
        "candidates": [("자본총계", "exact_strip")],
        "sj_div": {"BS"},
        "exclude": ["부채와", "부채및"],
    },
    "유동자산": {
        "candidates": [("유동자산", "exact_strip")],
        "sj_div": {"BS"},
        "exclude": ["비유동"],
    },
    "유동부채": {
        "candidates": [("유동부채", "exact_strip")],
        "sj_div": {"BS"},
        "exclude": ["비유동"],
    },
    "이익잉여금": {
        "candidates": [("이익잉여금", "exact_strip")],
        "sj_div": {"BS"},
    },
    # 현금흐름표 (CF)
    "영업활동현금흐름": {
        "candidates": [
            ("영업활동현금흐름", "exact_strip"),
            ("영업활동으로 인한 현금흐름", "exact_strip"),
        ],
        "sj_div": {"CF"},
    },
    "투자활동현금흐름": {
        "candidates": [
            ("투자활동현금흐름", "exact_strip"),
            ("투자활동으로 인한 현금흐름", "exact_strip"),
        ],
        "sj_div": {"CF"},
    },
    "재무활동현금흐름": {
        "candidates": [
            ("재무활동현금흐름", "exact_strip"),
            ("재무활동으로 인한 현금흐름", "exact_strip"),
        ],
        "sj_div": {"CF"},
    },
}


def _normalize_account_name(name: str) -> str:
    """후행 손익 표기·공백 제거. '영업이익(손실)' → '영업이익'."""
    n = (name or "").strip()
    for suffix in ("(손실)", "(이익)", "(손익)", "(순손실)"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].rstrip()
    return n


def _row_matches(account_nm: str, candidate: str, mode: str) -> bool:
    if mode == "exact_strip":
        return _normalize_account_name(account_nm) == candidate
    if mode == "contains":
        return candidate in account_nm
    return False


def _extract_financial_items(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """단일 사업연도 row 리스트에서 표준 키별 금액 추출.

    각 표준 키마다 candidates를 우선순위 순으로 시도. 같은 우선순위 안에서는
    sj_div가 허용된 첫 row를 채택. exclude 키워드가 포함된 row는 건너뜀.
    """
    items: dict[str, Any] = {}
    for std_key, rule in _FINANCIAL_ITEM_RULES.items():
        allowed_sj = rule.get("sj_div") or set()
        excludes = rule.get("exclude", [])
        found = False
        for candidate, mode in rule["candidates"]:
            for row in rows:
                nm = (row.get("account_nm") or "").strip()
                if not nm:
                    continue
                if allowed_sj and (row.get("sj_div") or "") not in allowed_sj:
                    continue
                if any(ex in nm for ex in excludes):
                    continue
                if not _row_matches(nm, candidate, mode):
                    continue
                raw = (row.get("thstrm_amount") or "").replace(",", "").strip()
                try:
                    items[std_key] = int(raw) if raw else None
                except ValueError:
                    items[std_key] = None
                found = True
                break
            if found:
                break
    return items


@tool(
    "get_financial_statements",
    "최근 N개 사업연도의 사업보고서 기준 주요 재무제표 항목(매출액, 영업이익, 당기순이익, 자산, 자본, 부채, 현금흐름 등)을 반환한다. "
    "CFS(연결) 우선, 부재 시 OFS(별도) 폴백. 결과의 fs_basis 필드에 어떤 기준이 사용됐는지 표시.",
    {"ticker": str, "years": int},
)
async def get_financial_statements(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).zfill(6)
    years = int(args.get("years", 3))
    try:
        dart = _dart_client()
        statements, fs_basis = dart.get_latest_annual_statements_with_fallback(ticker, years=years)
        if not statements:
            return _err("재무제표를 찾을 수 없습니다 (CFS·OFS 모두 부재).")

        annual: list[dict[str, Any]] = []
        for stmt in statements:
            year = stmt["year"]
            items = _extract_financial_items(stmt.get("list", []))
            annual.append({"year": year, "items": items})

        return _ok({"ticker": ticker, "fs_basis": fs_basis, "annual_statements": annual})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", traceback=traceback.format_exc())


@tool(
    "get_technical_analysis",
    "주가 이력으로 산출한 기술적 지표(이동평균 5/20/60/120, RSI14, MACD, 변동성, 52주 고저, 기간별 수익률)를 반환한다.",
    {"ticker": str, "days": int},
)
async def get_technical_analysis(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).zfill(6)
    days = int(args.get("days", 365))
    try:
        ohlcv = _krx.get_ohlcv(ticker, days=days)
        indicators = compute_technical_indicators(ohlcv)
        return _ok({"ticker": ticker, "period_days": days, "indicators": indicators})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@tool(
    "get_recent_disclosures",
    "최근 N일간의 공시 목록(보고서명·접수일·문서번호)을 반환한다.",
    {"ticker": str, "days": int},
)
async def get_recent_disclosures(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).zfill(6)
    days = int(args.get("days", 30))
    try:
        dart = _dart_client()
        data = dart.get_recent_disclosures(ticker, days=days)
        if data.get("status") not in ("000", "013"):
            return _err(f"DART 공시 조회 실패: {data.get('message')}")
        items: list[dict[str, Any]] = []
        for row in data.get("list", [])[:50]:
            items.append(
                {
                    "report_name": row.get("report_nm"),
                    "received_date": row.get("rcept_dt"),
                    "rcept_no": row.get("rcept_no"),
                    "submitter": row.get("flr_nm"),
                }
            )
        return _ok({"ticker": ticker, "period_days": days, "disclosures": items})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@tool(
    "save_final_report",
    (
        "Master agent가 최종 종합 분석을 마쳤을 때 호출. "
        "리포트 데이터를 받아 HTML 파일로 저장하고 파일 경로를 반환한다. "
        "report_json은 다음 키를 포함하는 JSON 문자열: "
        "investment_opinion (매수/중립/매도), target_price (숫자, KRW), "
        "investment_horizon (단기/중기/장기), one_line_summary, "
        "key_risks (리스트), fundamental_analysis, technical_analysis, "
        "news_disclosure_analysis, valuation_analysis, master_synthesis (모두 markdown)."
    ),
    {"ticker": str, "report_json": str},
)
async def save_final_report(args: dict[str, Any]) -> dict[str, Any]:
    from .report.generator import generate_html_report  # 지연 임포트 (순환 방지)

    ticker = str(args["ticker"]).zfill(6)
    try:
        report = json.loads(args["report_json"])
    except json.JSONDecodeError as e:
        return _err(f"report_json 파싱 실패: {e}")

    try:
        # ── DART 회사 개요 ──────────────────────────────────────────────
        try:
            company = _dart_client().get_company_info(ticker)
        except Exception:
            company = {"corp_name": ticker, "status": "N/A"}

        # ── 종목명 ──────────────────────────────────────────────────────
        try:
            name = _krx.get_name(ticker)
            if not name:
                raise ValueError("빈 종목명")
        except Exception:
            # DART에서 이름을 추출하거나 기본값 사용
            name = company.get("corp_name") or ticker

        # ── OHLCV + 기술적 지표 ─────────────────────────────────────────
        try:
            ohlcv = _krx.get_ohlcv(ticker, days=180)
            indicators = compute_technical_indicators(ohlcv)
            chart_data = ohlcv_for_chart(ohlcv, max_points=120)
        except Exception:
            indicators = {}
            chart_data = []

        # ── 시장 스냅샷 (실패 시 폴백) ──────────────────────────────────
        try:
            market = _krx.get_market_snapshot(ticker)
        except Exception:
            market = {
                "date": "N/A (데이터 조회 불가)",
                "market_cap_krw": None,
                "listed_shares": None,
                "trading_volume": indicators.get("avg_volume_20d"),
                "trading_value_krw": None,
                "PER": None,
                "PBR": None,
                "EPS": None,
                "BPS": None,
                "DIV_yield": None,
                "DPS": None,
            }

        out_path = generate_html_report(
            ticker=ticker,
            name=name,
            generated_at=datetime.now(),
            company=company,
            market=market,
            indicators=indicators,
            chart_data=chart_data,
            report=report,
            output_dir=REPORT_OUTPUT_DIR,
        )
        return _ok({"ticker": ticker, "report_path": str(out_path)})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", traceback=traceback.format_exc())


DATA_TOOLS = [
    get_company_overview,
    get_market_snapshot,
    get_financial_statements,
    get_technical_analysis,
    get_recent_disclosures,
]

REPORT_TOOLS = [save_final_report]


def build_mcp_server():
    """모든 도구를 등록한 in-process MCP server."""
    return create_sdk_mcp_server(
        name="stockdata",
        version="0.1.0",
        tools=DATA_TOOLS + REPORT_TOOLS,
    )


MCP_SERVER_NAME = "stockdata"


def mcp_name(tool_name: str) -> str:
    """MCP 도구의 풀네임 (allowed_tools / sub-agent tools에 사용)."""
    return f"mcp__{MCP_SERVER_NAME}__{tool_name}"
