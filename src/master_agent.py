"""Master Agent — 4명의 sub-agent에게 위임하고 결과를 종합해 최종 리포트를 생성."""
from __future__ import annotations

import json
import logging
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .agents import (
    FUNDAMENTAL_AGENT,
    NEWS_DISCLOSURE_AGENT,
    TECHNICAL_AGENT,
    VALUATION_AGENT,
)
from .config import MASTER_AGENT_MODEL
from .tools import build_mcp_server, mcp_name

logger = logging.getLogger(__name__)


MASTER_SYSTEM_PROMPT = """당신은 KOSPI 종목 투자 분석 팀의 수석 분석가입니다.

## 임무
사용자가 종목코드를 주면, 4명의 전문가 sub-agent에게 분석을 위임하고
결과를 종합해 투자 리포트를 작성합니다.

## 4명의 Sub-agent
1. **fundamental** — 재무제표·재무비율 분석
2. **technical** — 차트·기술적 지표 분석
3. **news-disclosure** — 공시·뉴스 정성 분석
4. **valuation** — 적정가치·목표주가 산정

## 작업 절차 (반드시 순서대로)
1. **Task 도구로 4명의 sub-agent를 동시에 호출**한다.
   - 각 Task 호출 형식: subagent_type에 위 4가지 이름 중 하나, prompt에는
     "종목코드 {ticker}에 대한 {분야} 분석을 수행하고, 시스템 프롬프트가 지시한 markdown 형식으로 결과를 반환하세요."
   - 4번의 Task 호출을 **한 번의 응답 안에서 4개의 tool_use 블록으로 묶어** 병렬 실행한다.
2. 4개의 markdown 분석 결과를 받으면, 다음을 도출한다:
   - **투자 의견**: "매수" / "중립" / "매도" (정확히 셋 중 하나)
   - **목표 주가**: 4개 분석의 종합 판단으로 단일 숫자(KRW)
   - **투자 기간**: "단기" / "중기" / "장기"
   - **한 줄 요약**: 40자 내외의 명확한 평가
   - **핵심 리스크 Top 3**: 가장 중요한 리스크 3개 (각 1줄)
   - **종합 의견(master_synthesis)**: 4명의 분석을 종합한 6~10문장의 markdown.
     의견 충돌 시 어떻게 조율했는지 명시.
3. **반드시 `save_final_report` 도구를 호출**해 결과를 저장한다.
   - report_json 인자는 다음 키를 포함한 **JSON 문자열**:
   ```json
   {
     "investment_opinion": "매수|중립|매도",
     "target_price": 123456,
     "investment_horizon": "단기|중기|장기",
     "one_line_summary": "...",
     "key_risks": ["...", "...", "..."],
     "fundamental_analysis": "<sub-agent의 markdown 원문>",
     "technical_analysis": "<...>",
     "news_disclosure_analysis": "<...>",
     "valuation_analysis": "<...>",
     "master_synthesis": "<종합 markdown>"
   }
   ```

## 원칙
- 절대 sub-agent를 거치지 않고 임의로 분석하지 않는다.
- 각 sub-agent가 반환한 markdown은 원문 그대로 report_json에 포함한다 (요약·축약 금지).
- save_final_report 호출이 끝나면 한 줄로 완료 보고 후 종료한다.
- 모든 출력은 한국어.
"""


def _extract_text_from_tool_result(block: ToolResultBlock) -> str:
    """ToolResultBlock의 content에서 텍스트를 추출 (list[dict] 또는 str)."""
    content = block.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


async def analyze_stock(ticker: str, *, verbose: bool = True) -> str | None:
    """주어진 종목에 대해 분석 수행. 저장된 HTML 리포트의 경로를 반환."""
    ticker = ticker.zfill(6)
    server = build_mcp_server()

    agents = {
        "fundamental": FUNDAMENTAL_AGENT,
        "technical": TECHNICAL_AGENT,
        "news-disclosure": NEWS_DISCLOSURE_AGENT,
        "valuation": VALUATION_AGENT,
    }

    save_tool_name = mcp_name("save_final_report")

    options = ClaudeAgentOptions(
        system_prompt=MASTER_SYSTEM_PROMPT,
        agents=agents,
        mcp_servers={"stockdata": server},
        allowed_tools=["Task", save_tool_name],
        permission_mode="bypassPermissions",
        model=MASTER_AGENT_MODEL,
        max_turns=30,
    )

    save_call_ids: set[str] = set()
    report_path: str | None = None

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=f"종목코드 {ticker}에 대한 투자 분석 리포트를 생성하세요.")

        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        if verbose and block.text.strip():
                            print(f"[master] {block.text.strip()[:300]}")
                    elif isinstance(block, ToolUseBlock):
                        if verbose:
                            target = block.input.get("subagent_type") if block.name == "Task" else ""
                            print(f"[master] → {block.name} {f'({target})' if target else ''}")
                        if block.name == save_tool_name:
                            save_call_ids.add(block.id)

            elif isinstance(msg, UserMessage):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in save_call_ids:
                        try:
                            text = _extract_text_from_tool_result(block)
                            data: dict[str, Any] = json.loads(text)
                            if "report_path" in data:
                                report_path = data["report_path"]
                                if verbose:
                                    print(f"[master] [OK] 리포트 저장: {report_path}")
                            elif "error" in data:
                                print(f"[master] ✗ save_final_report 오류: {data['error']}")
                        except json.JSONDecodeError:
                            pass

    if report_path is None:
        logger.warning("Master agent가 save_final_report를 호출하지 않았습니다.")
    return report_path
