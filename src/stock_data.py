"""KOSPI 종목 데이터 수집 — DART/KRX에서 결정적으로 가져오는 순수 함수들.

과거 tools.py의 MCP 도구 로직을 LLM 백엔드와 무관한 순수 함수로 옮긴 것이다.
`gather(ticker)`가 분석·리포트에 필요한 모든 데이터를 한 번에 수집하며,
일부 소스 실패는 우아하게 처리(해당 필드 None/빈값 + errors에 기록)한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import DART_API_KEY
from .data.dart_client import DartClient
from .data.krx_client import (
    KrxClient,
    compute_technical_indicators,
    ohlcv_for_chart,
)

_dart: DartClient | None = None
_krx = KrxClient()


def _dart_client() -> DartClient:
    global _dart
    if _dart is None:
        _dart = DartClient(DART_API_KEY)
    return _dart


# ── DART 재무제표 항목 정규화 규칙 (tools.py에서 이전) ──────────────────────
#
# 회사별 변형 예:
#   - 손실 기재: "영업이익(손실)", "당기순이익(손실)"
#   - 연결 prefix: "당기연결순이익" (SK), "연결당기순이익" (현대차) — 같은 개념
#   - 현금흐름 표기: "영업활동현금흐름" vs "영업활동으로 인한 현금흐름"
# sj_div: BS=재무상태표, IS=손익계산서, CIS=포괄손익계산서, CF=현금흐름표
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


# ── 개별 데이터 조회 함수 ────────────────────────────────────────────────


def company_overview_from_raw(raw: dict[str, Any] | None, ticker: str) -> dict[str, Any] | None:
    """DART 원본 회사 정보를 LLM 친화적인 개요 dict로 정리."""
    if not raw or raw.get("status") != "000":
        return None
    return {
        "ticker": ticker,
        "name_kr": raw.get("corp_name"),
        "name_en": raw.get("corp_name_eng"),
        "ceo": raw.get("ceo_nm"),
        "industry": raw.get("induty_code"),
        "address": raw.get("adres"),
        "homepage": raw.get("hm_url"),
        "established_date": raw.get("est_dt"),
        "accounting_month": raw.get("acc_mt"),
        "is_listed": raw.get("corp_cls") == "Y",
    }


def market_snapshot(ticker: str) -> dict[str, Any]:
    """종목의 최근 영업일 기준 시가총액·현재가·PER·PBR 등."""
    ticker = ticker.zfill(6)
    name = _krx.get_name(ticker)
    snap = _krx.get_market_snapshot(ticker)
    return {"ticker": ticker, "name": name, **snap}


def financial_statements(ticker: str, years: int = 3) -> dict[str, Any]:
    """최근 N개 사업연도 주요 재무제표 항목. CFS 우선, 부재 시 OFS 폴백."""
    ticker = ticker.zfill(6)
    dart = _dart_client()
    statements, fs_basis = dart.get_latest_annual_statements_with_fallback(ticker, years=years)
    if not statements:
        raise RuntimeError("재무제표를 찾을 수 없습니다 (CFS·OFS 모두 부재).")
    annual: list[dict[str, Any]] = []
    for stmt in statements:
        annual.append({"year": stmt["year"], "items": _extract_financial_items(stmt.get("list", []))})
    return {"ticker": ticker, "fs_basis": fs_basis, "annual_statements": annual}


def recent_disclosures(ticker: str, days: int = 30) -> list[dict[str, Any]]:
    """최근 N일간 공시 목록(보고서명·접수일·문서번호)."""
    ticker = ticker.zfill(6)
    dart = _dart_client()
    data = dart.get_recent_disclosures(ticker, days=days)
    if data.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART 공시 조회 실패: {data.get('message')}")
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
    return items


def empty_market(indicators: dict[str, Any]) -> dict[str, Any]:
    """시장 스냅샷 조회 실패 시 리포트 렌더링용 폴백 dict."""
    return {
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


# ── 통합 수집 ────────────────────────────────────────────────────────────


@dataclass
class StockData:
    """분석·리포트에 필요한 종목 데이터 묶음."""

    ticker: str
    name: str
    company_raw: dict[str, Any] | None      # DART 원본 (리포트 렌더링용)
    company_overview: dict[str, Any] | None  # 정리본 (LLM 컨텍스트용)
    market: dict[str, Any] | None
    financials: dict[str, Any] | None
    indicators: dict[str, Any]              # 실패 시 {}
    chart_data: list[dict[str, Any]]        # 실패 시 []
    disclosures: list[dict[str, Any]]       # 실패 시 []
    errors: dict[str, str] = field(default_factory=dict)


def gather(ticker: str) -> StockData:
    """분석에 필요한 모든 데이터를 한 번에 수집. 부분 실패는 errors에 기록."""
    ticker = ticker.zfill(6)
    errors: dict[str, str] = {}

    # 회사 개요 (DART) — 리포트/개요 공용
    try:
        company_raw = _dart_client().get_company_info(ticker)
        if company_raw.get("status") != "000":
            errors["company"] = f"DART: {company_raw.get('message')}"
    except Exception as e:  # noqa: BLE001
        company_raw = None
        errors["company"] = str(e)
    company_overview = company_overview_from_raw(company_raw, ticker)

    # 시장 스냅샷 (KRX) — 종목명도 여기서 확보
    try:
        market = market_snapshot(ticker)
        name = market.get("name") or ""
    except Exception as e:  # noqa: BLE001
        market = None
        name = ""
        errors["market"] = str(e)
    if not name:
        try:
            name = _krx.get_name(ticker) or ""
        except Exception:  # noqa: BLE001
            name = ""
    if not name:
        name = (company_overview or {}).get("name_kr") or ticker

    # 재무제표 (DART)
    try:
        financials = financial_statements(ticker, years=3)
    except Exception as e:  # noqa: BLE001
        financials = None
        errors["financials"] = str(e)

    # 기술적 지표 + 차트 (KRX OHLCV 1회 조회 재사용)
    indicators: dict[str, Any] = {}
    chart_data: list[dict[str, Any]] = []
    try:
        ohlcv = _krx.get_ohlcv(ticker, days=365)
        indicators = compute_technical_indicators(ohlcv)
        chart_data = ohlcv_for_chart(ohlcv, max_points=120)
    except Exception as e:  # noqa: BLE001
        errors["technical"] = str(e)

    # 최근 공시 (DART)
    try:
        disclosures = recent_disclosures(ticker, days=30)
    except Exception as e:  # noqa: BLE001
        disclosures = []
        errors["disclosures"] = str(e)

    return StockData(
        ticker=ticker,
        name=name,
        company_raw=company_raw,
        company_overview=company_overview,
        market=market,
        financials=financials,
        indicators=indicators,
        chart_data=chart_data,
        disclosures=disclosures,
        errors=errors,
    )
