"""분석 오케스트레이션.

데이터를 결정적으로 수집한 뒤 Gemini로 4개 분야를 분석하고, 결과를 종합해
HTML 리포트를 생성한다. (과거의 claude-agent-sdk Master/Sub-agent 구조를 대체)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from . import stock_data
from .agents import (
    FUNDAMENTAL_PROMPT,
    NEWS_DISCLOSURE_PROMPT,
    TECHNICAL_PROMPT,
    VALUATION_PROMPT,
)
from .config import NEWS_USE_WEB_SEARCH, REPORT_OUTPUT_DIR
from .llm import analyze, synthesize
from .report.generator import generate_html_report

logger = logging.getLogger(__name__)


MASTER_SYNTHESIS_PROMPT = (
    "당신은 KOSPI 종목 투자 분석 팀의 수석 분석가입니다.\n"
    "4명의 전문가(펀더멘털/기술적/뉴스·공시/밸류에이션)의 분석 결과가 주어집니다.\n"
    "이를 종합해 다음을 도출하세요:\n"
    "- investment_opinion: '매수' / '중립' / '매도' 중 하나\n"
    "- target_price: 4개 분석의 종합 판단에 따른 단일 목표주가 (KRW 정수)\n"
    "- investment_horizon: '단기' / '중기' / '장기' 중 하나\n"
    "- one_line_summary: 40자 내외의 명확한 평가\n"
    "- key_risks: 가장 중요한 리스크 3개 (각 1줄) 배열\n"
    "- master_synthesis: 4개 분석을 종합한 6~10문장의 markdown. "
    "의견 충돌 시 어떻게 조율했는지 명시.\n"
    "모든 텍스트는 한국어로 작성한다."
)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _news_context(data: stock_data.StockData, *, with_web_search: bool) -> str:
    """뉴스·공시 분석용 데이터 컨텍스트."""
    ctx = (
        "다음은 분석 대상 데이터입니다.\n\n"
        f"## 회사 개요\n{_json(data.company_overview)}\n\n"
        f"## 최근 30일 DART 공시\n{_json(data.disclosures)}\n"
    )
    if with_web_search:
        ctx += "\n추가로 Google 검색으로 최근 1개월 주요 뉴스를 조사해 반영하세요.\n"
    return ctx


def analyze_stock(ticker: str, *, verbose: bool = True) -> str | None:
    """주어진 종목을 분석하고 저장된 HTML 리포트 경로를 반환."""
    ticker = ticker.zfill(6)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # ── 1. 데이터 수집 ──────────────────────────────────────────────────
    log("[data] DART·KRX 데이터 수집 중...")
    data = stock_data.gather(ticker)
    for comp, err in data.errors.items():
        logger.warning("데이터 일부 누락 (%s): %s", comp, err)
    log(f"[data] 완료: {data.name}({ticker})  누락={list(data.errors) or '없음'}")

    analyses: dict[str, str] = {}

    # ── 2. 펀더멘털 ─────────────────────────────────────────────────────
    log("[fundamental] 분석 중...")
    analyses["fundamental"] = analyze(
        FUNDAMENTAL_PROMPT,
        "다음은 분석 대상 데이터입니다.\n\n"
        f"## 회사 개요\n{_json(data.company_overview)}\n\n"
        f"## 시장 스냅샷\n{_json(data.market)}\n\n"
        f"## 재무제표 (최근 3년)\n{_json(data.financials)}",
    )

    # ── 3. 기술적 ───────────────────────────────────────────────────────
    log("[technical] 분석 중...")
    analyses["technical"] = analyze(
        TECHNICAL_PROMPT,
        "다음은 분석 대상 데이터입니다.\n\n"
        f"## 시장 스냅샷\n{_json(data.market)}\n\n"
        f"## 기술적 지표\n{_json(data.indicators)}",
    )

    # ── 4. 뉴스·공시 (웹 검색 실패 시 DART 공시만으로 폴백) ─────────────
    log("[news-disclosure] 분석 중...")
    try:
        analyses["news_disclosure"] = analyze(
            NEWS_DISCLOSURE_PROMPT,
            _news_context(data, with_web_search=NEWS_USE_WEB_SEARCH),
            use_web_search=NEWS_USE_WEB_SEARCH,
        )
    except Exception as e:  # noqa: BLE001
        if NEWS_USE_WEB_SEARCH:
            logger.warning("웹 검색 grounding 실패, DART 공시만으로 재시도: %s", e)
            analyses["news_disclosure"] = analyze(
                NEWS_DISCLOSURE_PROMPT,
                _news_context(data, with_web_search=False),
                use_web_search=False,
            )
        else:
            raise

    # ── 5. 밸류에이션 ───────────────────────────────────────────────────
    log("[valuation] 분석 중...")
    analyses["valuation"] = analyze(
        VALUATION_PROMPT,
        "다음은 분석 대상 데이터입니다.\n\n"
        f"## 회사 개요\n{_json(data.company_overview)}\n\n"
        f"## 시장 스냅샷\n{_json(data.market)}\n\n"
        f"## 재무제표 (최근 3년)\n{_json(data.financials)}",
    )

    # ── 6. 종합 ─────────────────────────────────────────────────────────
    log("[master] 4개 분석 종합 중...")
    synthesis = synthesize(
        MASTER_SYNTHESIS_PROMPT,
        f"종목: {data.name}({ticker})\n\n"
        f"## 펀더멘털 분석\n{analyses['fundamental']}\n\n"
        f"## 기술적 분석\n{analyses['technical']}\n\n"
        f"## 뉴스·공시 분석\n{analyses['news_disclosure']}\n\n"
        f"## 밸류에이션 분석\n{analyses['valuation']}",
    )

    report = {
        "investment_opinion": synthesis.get("investment_opinion"),
        "target_price": synthesis.get("target_price"),
        "investment_horizon": synthesis.get("investment_horizon"),
        "one_line_summary": synthesis.get("one_line_summary"),
        "key_risks": synthesis.get("key_risks", []),
        "fundamental_analysis": analyses["fundamental"],
        "technical_analysis": analyses["technical"],
        "news_disclosure_analysis": analyses["news_disclosure"],
        "valuation_analysis": analyses["valuation"],
        "master_synthesis": synthesis.get("master_synthesis"),
    }

    # ── 7. HTML 리포트 저장 ─────────────────────────────────────────────
    out_path = generate_html_report(
        ticker=ticker,
        name=data.name,
        generated_at=datetime.now(),
        company=data.company_raw or {"corp_name": data.name, "status": "N/A"},
        market=data.market or stock_data.empty_market(data.indicators),
        indicators=data.indicators,
        chart_data=data.chart_data,
        report=report,
        output_dir=REPORT_OUTPUT_DIR,
    )
    log(f"[master] [OK] 리포트 저장: {out_path}")
    return str(out_path)
