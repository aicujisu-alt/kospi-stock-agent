"""DART (전자공시시스템) OpenAPI 클라이언트."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


class DartClient:
    BASE = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: str, cache_dir: Path | None = None) -> None:
        if not api_key:
            raise ValueError("DART_API_KEY가 비어있습니다.")
        self.api_key = api_key
        self.cache_dir = cache_dir or Path(__file__).resolve().parent / "_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._corp_code_map: dict[str, str] | None = None

    def _load_corp_code_map(self) -> dict[str, str]:
        """6자리 종목코드 → 8자리 DART corp_code 매핑.

        파일이 일주일 이상 오래되면 자동 갱신.
        """
        if self._corp_code_map is not None:
            return self._corp_code_map

        cache_file = self.cache_dir / "corp_codes.xml"
        stale = (
            not cache_file.exists()
            or (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days > 7
        )
        if stale:
            resp = requests.get(
                f"{self.BASE}/corpCode.xml",
                params={"crtfc_key": self.api_key},
                timeout=30,
            )
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = zf.namelist()[0]
                cache_file.write_bytes(zf.read(name))

        tree = ET.parse(cache_file)
        mapping: dict[str, str] = {}
        for elem in tree.findall("list"):
            stock_code = (elem.findtext("stock_code") or "").strip()
            corp_code = (elem.findtext("corp_code") or "").strip()
            if stock_code and corp_code and stock_code != " ":
                mapping[stock_code] = corp_code
        self._corp_code_map = mapping
        return mapping

    def get_corp_code(self, ticker: str) -> str:
        ticker = ticker.zfill(6)
        mapping = self._load_corp_code_map()
        if ticker not in mapping:
            raise ValueError(f"종목코드 {ticker}에 해당하는 DART 코드를 찾을 수 없습니다.")
        return mapping[ticker]

    def get_company_info(self, ticker: str) -> dict[str, Any]:
        """기업 개황."""
        corp_code = self.get_corp_code(ticker)
        resp = requests.get(
            f"{self.BASE}/company.json",
            params={"crtfc_key": self.api_key, "corp_code": corp_code},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_financial_statements(
        self,
        ticker: str,
        year: int,
        reprt_code: str = "11011",
        fs_div: str = "CFS",
    ) -> dict[str, Any]:
        """단일 회사 전체 재무제표.

        reprt_code: 11011=사업보고서, 11014=3분기, 11012=반기, 11013=1분기
        fs_div: CFS=연결, OFS=별도
        """
        corp_code = self.get_corp_code(ticker)
        resp = requests.get(
            f"{self.BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def get_latest_annual_statements(
        self, ticker: str, years: int = 3, fs_div: str = "CFS"
    ) -> list[dict[str, Any]]:
        """최근 N개 사업연도의 사업보고서 재무제표.

        가장 최근 연도부터 역순으로 시도하여 데이터 존재하는 연도 수집.
        """
        results: list[dict[str, Any]] = []
        current_year = datetime.now().year
        for offset in range(0, years + 2):
            year = current_year - 1 - offset
            try:
                data = self.get_financial_statements(ticker, year, reprt_code="11011", fs_div=fs_div)
                if data.get("status") == "000" and data.get("list"):
                    results.append({"year": year, **data})
                    if len(results) >= years:
                        break
            except requests.HTTPError:
                continue
        return results

    def get_latest_annual_statements_with_fallback(
        self, ticker: str, years: int = 3
    ) -> tuple[list[dict[str, Any]], str]:
        """CFS 우선, 비어 있으면 OFS로 폴백.

        Returns:
            (statements, fs_basis) — fs_basis는 "CFS" | "OFS" | "none"
        """
        cfs = self.get_latest_annual_statements(ticker, years=years, fs_div="CFS")
        if cfs:
            return cfs, "CFS"
        ofs = self.get_latest_annual_statements(ticker, years=years, fs_div="OFS")
        if ofs:
            return ofs, "OFS"
        return [], "none"

    def get_recent_disclosures(self, ticker: str, days: int = 30) -> dict[str, Any]:
        """최근 공시 목록."""
        corp_code = self.get_corp_code(ticker)
        end = datetime.now()
        start = end - timedelta(days=days)
        resp = requests.get(
            f"{self.BASE}/list.json",
            params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bgn_de": start.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "page_count": 50,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
