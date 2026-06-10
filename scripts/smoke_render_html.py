"""HTML 렌더링 파이프라인 스모크 테스트.

실제 API 호출 없이 더미 데이터로 generate_html_report를 호출해
템플릿이 깨지지 않고 HTML이 생성되는지 확인한다.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REPORT_OUTPUT_DIR  # noqa: E402
from src.report.generator import generate_html_report  # noqa: E402


def main() -> None:
    company = {
        "corp_name": "삼성전자",
        "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
        "ceo_nm": "한종희, 노태문",
        "induty_code": "264",
        "adres": "경기도 수원시 영통구 ...",
        "hm_url": "www.samsung.com/sec",
        "est_dt": "19690113",
    }

    market = {
        "date": "20260522",
        "market_cap_krw": 422_000_000_000_000,
        "listed_shares": 5_969_782_550,
        "trading_volume": 12_345_678,
        "trading_value_krw": 800_000_000_000,
        "PER": 11.2,
        "PBR": 1.32,
        "EPS": 6300,
        "BPS": 53_500,
        "DIV_yield": 2.1,
        "DPS": 1500,
    }

    indicators = {
        "current_price": 70_700,
        "ma5": 70_200,
        "ma20": 69_500,
        "ma60": 67_800,
        "ma120": 65_000,
        "rsi14": 58.2,
        "macd": 320.0,
        "macd_signal": 250.0,
        "macd_histogram": 70.0,
        "volatility_20d_annualized_pct": 24.5,
        "price_change_1d_pct": 0.71,
        "price_change_1w_pct": 2.3,
        "price_change_1m_pct": 5.8,
        "price_change_3m_pct": 9.4,
        "price_change_1y_pct": 18.2,
        "high_52w": 84_000,
        "low_52w": 58_000,
        "high_52w_distance_pct": -15.8,
        "low_52w_distance_pct": 21.9,
        "avg_volume_20d": 14_500_000,
        "avg_volume_60d": 13_200_000,
    }

    # 30일치 가상 OHLCV
    import random
    random.seed(42)
    base = 70000
    chart_data = []
    for i in range(120):
        base = max(1000, base + random.randint(-1000, 1100))
        chart_data.append(
            {
                "date": f"2026-{((i // 30) + 1):02d}-{(i % 30 + 1):02d}",
                "open": base - 200,
                "high": base + 500,
                "low": base - 400,
                "close": base,
                "volume": random.randint(5_000_000, 25_000_000),
            }
        )

    report = {
        "investment_opinion": "매수",
        "target_price": 85_000,
        "investment_horizon": "중기",
        "one_line_summary": "AI 메모리 사이클 진입 + 견조한 펀더멘털, 12개월 +20% 상승여력.",
        "key_risks": [
            "HBM 경쟁사(SK하이닉스/마이크론) 추격에 따른 점유율 침식 가능성",
            "글로벌 경기 둔화로 인한 IT 수요 위축",
            "원/달러 환율 급변에 따른 환차익·환차손 변동성",
        ],
        "fundamental_analysis": (
            "### 1. 핵심 재무 지표\n"
            "| 항목 | 2023 | 2024 | 2025 |\n"
            "|---|---|---|---|\n"
            "| 매출액 | 259조 | 301조 | 338조 |\n"
            "| 영업이익 | 6.6조 | 32.7조 | 45.0조 |\n"
            "| ROE | 4.1% | 12.5% | 14.8% |\n\n"
            "### 2. 성장성\n메모리 업황 회복과 HBM 매출 확대로 영업이익이 빠르게 정상화.\n"
            "### 3. 종합 평가\n- 점수: ★★★★☆\n- 강점: 메모리 1위 점유율, 압도적 현금성 자산.\n"
        ),
        "technical_analysis": (
            "### 1. 추세\nMA5 > MA20 > MA60 > MA120 정배열, 단기·중기·장기 모두 상승추세.\n\n"
            "### 2. 모멘텀\nRSI14 58.2 (중립~강세), MACD 골든크로스 유효.\n\n"
            "### 4. 종합 평가\n- 점수: ★★★★☆\n- 매매 신호: 매수\n"
        ),
        "news_disclosure_analysis": (
            "### 1. 주요 공시\n- 2026-05-15 자기주식취득결과보고서 (호재)\n\n"
            "### 5. 종합 평가\n- 센티멘트: 긍정\n- 점수: ★★★★☆\n"
        ),
        "valuation_analysis": (
            "### 1. 현재 밸류에이션\n- PER 11.2배 / PBR 1.32배\n\n"
            "### 5. 종합 목표주가\n- Bear: 75,000원 / Base: 85,000원 / Bull: 95,000원\n"
            "- 점수: ★★★★☆\n"
        ),
        "master_synthesis": (
            "**종합 의견**\n\n"
            "4명의 분석가가 일관되게 긍정 의견을 제시했다. 펀더멘털 분석가는 메모리 업황 회복과 "
            "HBM 매출 확대로 영업이익이 빠르게 정상화된 점을 강조했고, 기술적 분석가는 정배열·골든크로스를 근거로 "
            "매수 신호를 확인했다. 뉴스·공시 측면에서도 자사주 매입 등 주주환원 시그널이 우호적이며, "
            "밸류에이션 측면에서 PER 11배는 절대·상대 모두 합리적 수준이다.\n\n"
            "다만 단기 RSI는 다소 높은 60에 근접하므로, 일시적 조정 시 분할 매수 접근을 권고한다. "
            "12개월 목표 85,000원, 중기 매수 의견."
        ),
    }

    path = generate_html_report(
        ticker="005930",
        name="삼성전자",
        generated_at=datetime(2026, 5, 23, 15, 30),
        company=company,
        market=market,
        indicators=indicators,
        chart_data=chart_data,
        report=report,
        output_dir=REPORT_OUTPUT_DIR,
    )
    print(f"OK: {path}")
    print(f"파일 크기: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
