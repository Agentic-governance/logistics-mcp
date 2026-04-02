"""IR（投資家向け情報）スクレイパー — Tier-1サプライヤー自動抽出
EDINET（有価証券報告書）および SEC EDGAR（10-K / SD）から
企業のサプライヤー開示情報を取得し、サプライチェーングラフの
ノード/エッジに変換する。

データソース:
  A) EDINET API v2 — 有報から「主要仕入先」「関係会社」セクション
  B) SEC EDGAR     — 10-K Annual Reports: Supplier / Supply Chain sections
  C) SEC SD filings — Exhibit 1.01 Conflict Minerals Reports
"""
import asyncio
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# pdfplumber はオプション（インストール済みの場合のみ）
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    pdfplumber = None
    HAS_PDFPLUMBER = False

# RapidFuzz — 名寄せに使用
try:
    from rapidfuzz import fuzz, process as rfprocess
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EDINET_API_BASE = "https://disclosure.edinet-api.go.jp/api/v2"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SEC_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEC_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

SEC_USER_AGENT = "SCRI-Research/0.9 (research@example.com)"

# Rate-limit intervals (seconds)
EDINET_RATE_LIMIT = 2.0   # 1 req per 2 sec
SEC_RATE_LIMIT = 0.1       # 10 req/sec ⇒ 0.1s between requests

# Japanese regex patterns for supplier extraction
RE_JP_SUPPLIER_SECTION = re.compile(
    r"(?:主要(?:な)?(?:仕入先|取引先|購入先|調達先|サプライヤー|原材料仕入先))"
    r"|(?:主要(?:な)?事業上の関係会社)"
    r"|(?:原材料の調達)"
    r"|(?:仕入先の状況)"
    r"|(?:外注先)",
    re.IGNORECASE,
)

# Match Japanese company names — typical patterns:
# 株式会社○○ / ○○株式会社 / ○○(株) / (株)○○ / ○○工業 / ○○製作所 etc.
# Note: \s is replaced with [ \t] to avoid matching across newlines.
_JP_CHARS = r"[\u4e00-\u9fff\u30a0-\u30ffA-Za-z0-9\-・]"
RE_JP_COMPANY_NAME = re.compile(
    rf"(?:株式会社[ \t]*{_JP_CHARS}{{2,20}})"
    rf"|(?:{_JP_CHARS}{{2,20}}[ \t]*株式会社)"
    rf"|(?:{_JP_CHARS}{{2,20}}[ \t]*[（(]株[)）])"
    rf"|(?:[（(]株[)）][ \t]*{_JP_CHARS}{{2,20}})"
    rf"|(?:[\u4e00-\u9fff\u30a0-\u30ff]{{1,10}}(?:工業|製作所|化学|電機|電子|鉄鋼|製鉄|鉱山|鉱業|金属|物産|商事|通商|精密|電気|重工業|電工|製薬|建設|運輸|倉庫|繊維|セメント|ガス|石油))"
    rf"|(?:有限会社[ \t]*{_JP_CHARS}{{2,20}})"
    rf"|(?:合同会社[ \t]*{_JP_CHARS}{{2,20}})",
)

# SEC 10-K supplier-related section patterns
RE_SEC_SUPPLIER_SECTION = re.compile(
    r"\b(?:suppliers?|supply\s+chain|vendors?|principal\s+suppliers?|sole\s+source"
    r"|single[\-\s]source|raw\s+materials?|procurement|sourcing)\b",
    re.IGNORECASE,
)

# Match Western company names in SEC text (heuristic)
# Only match within a single line (use [ \t] instead of \s for word gaps).
_EN_SUFFIX = (
    r"(?:Inc\.?|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|Limited"
    r"|LLC|L\.L\.C\.|LP|L\.P\.|PLC|plc|SA|S\.A\.|AG|GmbH|SE"
    r"|N\.V\.|B\.V\.|Pty|Holdings?|Group|International|Technologies"
    r"|Semiconductor|Electronics|Chemical|Materials)"
)
RE_EN_COMPANY_NAME = re.compile(
    rf"\b([A-Z][A-Za-z&\-']+(?:[ \t]+[A-Z][A-Za-z&\-']+){{0,4}}"
    rf"[ \t]+{_EN_SUFFIX})\b",
)

# Words to ignore when they appear as the full "company name"
_EN_FALSE_POSITIVES = {
    "The Company", "Our Company", "Raw Materials", "Annual Report",
    "United States", "New York", "Risk Factors", "Item Business",
}

# Conflict minerals list
CONFLICT_MINERALS = {"tin", "tantalum", "tungsten", "gold", "cobalt"}

# Smelter row regex — matches a single line like:
#   "PT Timah, Indonesia, Tin"  or  "PT Timah | Indonesia | Tin"
RE_SMELTER_ROW = re.compile(
    r"^[ \t]*"
    r"([A-Za-z\u4e00-\u9fff][\w \t\-&.()]{3,60}?)"  # smelter name (non-greedy)
    r"[ \t]*[|,\t][ \t]*"
    r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*)"           # country
    r"[ \t]*[|,\t][ \t]*"
    r"(Tin|Tantalum|Tungsten|Gold|Cobalt)"             # mineral (full word only)
    r"[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class SupplierDisclosure:
    """有報/10-Kから抽出されたサプライヤー開示"""
    supplier_name: str
    disclosure_type: str                  # "有報_関係会社" / "10K_supplier_section" / etc.
    relationship: str                     # "supplier" / "subsidiary" / "関係会社" / etc.
    country: Optional[str] = None
    source: str = "EDINET"                # "EDINET" | "SEC_10K"
    confidence: str = "DISCLOSED"         # "DISCLOSED" | "INFERRED"
    filing_date: Optional[str] = None


@dataclass
class ConflictMineralsReport:
    """SEC SD (Exhibit 1.01) Conflict Minerals Report"""
    company: str
    filing_year: Optional[int] = None
    minerals_in_scope: list[str] = field(default_factory=list)
    smelters: list[dict] = field(default_factory=list)   # [{name, country, mineral}]
    drc_sourcing: Optional[str] = None    # "yes" / "no" / "unknown" / "undeterminable"
    conflict_free_certified: Optional[bool] = None


# ---------------------------------------------------------------------------
# Rate-limiter helper
# ---------------------------------------------------------------------------
class _RateLimiter:
    """Per-domain simple token-bucket rate limiter."""
    def __init__(self):
        self._last: dict[str, float] = {}

    def wait(self, domain: str, interval: float):
        now = time.monotonic()
        last = self._last.get(domain, 0.0)
        diff = now - last
        if diff < interval:
            time.sleep(interval - diff)
        self._last[domain] = time.monotonic()


_rate = _RateLimiter()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _get_edinet(url: str, params: dict | None = None, **kwargs) -> requests.Response:
    """EDINET API request with rate limiting."""
    _rate.wait("edinet", EDINET_RATE_LIMIT)
    resp = requests.get(url, params=params, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def _get_sec(url: str, params: dict | None = None, stream: bool = False,
             **kwargs) -> requests.Response:
    """SEC EDGAR request with required User-Agent and rate limiting."""
    _rate.wait("sec", SEC_RATE_LIMIT)
    headers = kwargs.pop("headers", {})
    headers["User-Agent"] = SEC_USER_AGENT
    headers["Accept-Encoding"] = "gzip, deflate"
    resp = requests.get(url, params=params, headers=headers,
                        timeout=30, stream=stream, **kwargs)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# IRScraper
# ---------------------------------------------------------------------------
class IRScraper:
    """EDINET / SEC EDGAR からサプライヤー開示を抽出するスクレイパー。

    すべての公開メソッドは同期で実装されるが、
    ``asyncio.to_thread`` でラップする非同期ヘルパーも用意する。
    """

    # ---- EDINET (Japan) ------------------------------------------------

    def scrape_edinet_suppliers(
        self,
        company_name: str,
        edinetCode: str = "",
    ) -> list[SupplierDisclosure]:
        """有価証券報告書からサプライヤー情報を抽出。

        Parameters
        ----------
        company_name : str
            対象企業名（例: "トヨタ自動車"）
        edinetCode : str, optional
            EDINET提出者コード。省略時はAPI検索で特定を試みる。

        Returns
        -------
        list[SupplierDisclosure]
        """
        try:
            doc_id, filing_date = self._find_edinet_yuho(company_name, edinetCode)
            if not doc_id:
                return []

            text = self._download_edinet_document_text(doc_id)
            if not text:
                return []

            return self._extract_jp_suppliers(text, filing_date)
        except Exception as e:
            print(f"[IR Scraper] EDINET error for {company_name}: {e}")
            return []

    def _find_edinet_yuho(
        self, company_name: str, edinetCode: str = ""
    ) -> tuple[str | None, str | None]:
        """EDINET文書一覧から最新の有価証券報告書のdocIDを取得。

        直近90日分を日付降順で探索し、最初にマッチしたものを返す。
        """
        today = datetime.utcnow().date()
        for offset in range(0, 90):
            search_date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            try:
                resp = _get_edinet(
                    f"{EDINET_API_BASE}/documents.json",
                    params={"date": search_date, "type": "2"},
                )
                data = resp.json()
            except Exception:
                continue

            results = data.get("results", [])
            for doc in results:
                # 有報: docTypeCode == "120" (有価証券報告書)
                doc_type = doc.get("docTypeCode", "")
                if doc_type not in ("120",):
                    continue

                filer = doc.get("filerName", "")
                edinet_code = doc.get("edinetCode", "")

                # Match by edinetCode if supplied, else by name
                if edinetCode and edinet_code == edinetCode:
                    return doc.get("docID"), search_date
                if not edinetCode and company_name in filer:
                    return doc.get("docID"), search_date

        return None, None

    def _download_edinet_document_text(self, doc_id: str) -> str:
        """EDINET API v2 でドキュメントをダウンロードしテキスト抽出。

        type=2 (PDF) を取得し、pdfplumber で読む。
        pdfplumber が無い場合は type=5 (XBRL/HTML) にフォールバック。
        """
        # --- Try XBRL/HTML first (type=5) for better text extraction ---
        try:
            resp = _get_edinet(
                f"{EDINET_API_BASE}/documents/{doc_id}",
                params={"type": "5"},   # 5 = 添付書類ZIP (XBRL + HTML)
            )
            if resp.status_code == 200 and len(resp.content) > 1000:
                return self._extract_text_from_edinet_zip(resp.content)
        except Exception:
            pass

        # --- Fallback: PDF (type=2) ---
        if HAS_PDFPLUMBER:
            try:
                resp = _get_edinet(
                    f"{EDINET_API_BASE}/documents/{doc_id}",
                    params={"type": "2"},   # 2 = PDF
                )
                if resp.status_code == 200 and len(resp.content) > 1000:
                    return self._extract_text_from_pdf(resp.content)
            except Exception:
                pass

        return ""

    @staticmethod
    def _extract_text_from_edinet_zip(content: bytes) -> str:
        """EDINET ZIP (XBRL + HTML) からテキスト抽出。"""
        import zipfile

        text_parts: list[str] = []
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith((".htm", ".html", ".xbrl")):
                        raw = zf.read(name)
                        # Try UTF-8, then shift_jis
                        for enc in ("utf-8", "shift_jis", "cp932", "euc-jp"):
                            try:
                                html_text = raw.decode(enc)
                                break
                            except (UnicodeDecodeError, LookupError):
                                continue
                        else:
                            html_text = raw.decode("utf-8", errors="replace")
                        soup = BeautifulSoup(html_text, "html.parser")
                        text_parts.append(soup.get_text(separator="\n"))
        except Exception:
            pass
        return "\n".join(text_parts)

    @staticmethod
    def _extract_text_from_pdf(content: bytes) -> str:
        """PDF バイナリからテキスト抽出 (pdfplumber)。"""
        if not HAS_PDFPLUMBER:
            return ""
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                return "\n".join(pages_text)
        except Exception:
            return ""

    # Generic JP terms that look like company names but are not
    _JP_BLOCKLIST = {
        "非鉄金属", "鉄鋼金属", "貴金属", "軽金属", "希少金属",
        "有色金属", "合成化学", "有機化学", "無機化学", "石油化学",
        "情報通信", "国内製鉄", "海外製鉄", "一般電気",
    }

    def _extract_jp_suppliers(
        self, text: str, filing_date: str | None
    ) -> list[SupplierDisclosure]:
        """日本語テキストから仕入先・関係会社名を抽出。"""
        results: list[SupplierDisclosure] = []
        seen: set[str] = set()

        # 関連セクションを見つけ、その前後3000文字を対象にする
        for m in RE_JP_SUPPLIER_SECTION.finditer(text):
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 3000)
            section = text[start:end]
            section_label = m.group()

            for cm in RE_JP_COMPANY_NAME.finditer(section):
                name = cm.group().strip()
                # 短すぎる名前を除外（日本語は3文字から有効: 旭化学 etc.）
                if len(name) < 3:
                    continue
                # ブロックリスト照合
                if name in self._JP_BLOCKLIST:
                    continue
                if name in seen:
                    continue
                seen.add(name)

                # 関係会社 vs 仕入先の判定
                if "関係会社" in section_label:
                    relationship = "関係会社"
                    dtype = "有報_関係会社"
                elif "外注" in section_label:
                    relationship = "外注先"
                    dtype = "有報_外注先"
                else:
                    relationship = "仕入先"
                    dtype = "有報_仕入先"

                results.append(SupplierDisclosure(
                    supplier_name=name,
                    disclosure_type=dtype,
                    relationship=relationship,
                    country="JP",
                    source="EDINET",
                    confidence="DISCLOSED",
                    filing_date=filing_date,
                ))

        return results

    # ---- SEC EDGAR (US) — 10-K ----------------------------------------

    def scrape_sec_10k_suppliers(
        self,
        ticker: str,
        cik: str = "",
    ) -> list[SupplierDisclosure]:
        """SEC 10-K Annual Report からサプライヤー情報を抽出。

        Parameters
        ----------
        ticker : str
            ティッカーシンボル（例: "AAPL"）
        cik : str, optional
            CIK番号。省略時はSEC APIで解決。

        Returns
        -------
        list[SupplierDisclosure]
        """
        try:
            cik = cik or self._resolve_cik(ticker)
            if not cik:
                print(f"[IR Scraper] Could not resolve CIK for {ticker}")
                return []

            filing_url, filing_date = self._find_latest_10k(cik)
            if not filing_url:
                return []

            text = self._download_sec_filing_text(filing_url)
            if not text:
                return []

            return self._extract_en_suppliers(text, ticker, filing_date)
        except Exception as e:
            print(f"[IR Scraper] SEC 10-K error for {ticker}: {e}")
            return []

    def _resolve_cik(self, ticker: str) -> str:
        """ティッカーからCIK番号を取得。"""
        try:
            resp = _get_sec("https://www.sec.gov/cgi-bin/browse-edgar",
                            params={
                                "company": ticker,
                                "CIK": ticker,
                                "type": "10-K",
                                "dateb": "",
                                "owner": "include",
                                "count": "1",
                                "search_text": "",
                                "action": "getcompany",
                                "output": "atom",
                            })
            # ATOM XML から CIK 抽出
            match = re.search(r"CIK=(\d+)", resp.text)
            if match:
                return match.group(1).lstrip("0") or match.group(1)

            # Fallback: company_tickers.json
            resp2 = _get_sec("https://www.sec.gov/files/company_tickers.json")
            tickers_data = resp2.json()
            ticker_upper = ticker.upper()
            for _key, entry in tickers_data.items():
                if entry.get("ticker", "").upper() == ticker_upper:
                    return str(entry.get("cik_str", ""))
        except Exception:
            pass
        return ""

    def _find_latest_10k(self, cik: str) -> tuple[str | None, str | None]:
        """CIK の submission 履歴から最新 10-K の URL を取得。"""
        padded_cik = cik.zfill(10)
        try:
            resp = _get_sec(f"{SEC_SUBMISSIONS_BASE}/CIK{padded_cik}.json")
            data = resp.json()
        except Exception:
            return None, None

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        filing_dates = recent.get("filingDate", [])

        for i, form_type in enumerate(forms):
            if form_type in ("10-K", "10-K/A"):
                accession = accessions[i].replace("-", "")
                doc_name = primary_docs[i]
                filing_date = filing_dates[i] if i < len(filing_dates) else None
                url = f"{SEC_ARCHIVES_BASE}/{cik}/{accession}/{doc_name}"
                return url, filing_date

        return None, None

    def _download_sec_filing_text(self, url: str) -> str:
        """SEC filing をダウンロードしテキスト化。"""
        try:
            resp = _get_sec(url)
            content_type = resp.headers.get("Content-Type", "")

            if "html" in content_type or url.endswith(".htm") or url.endswith(".html"):
                soup = BeautifulSoup(resp.content, "html.parser")
                return soup.get_text(separator="\n")
            else:
                return resp.text
        except Exception:
            return ""

    def _extract_en_suppliers(
        self, text: str, ticker: str, filing_date: str | None
    ) -> list[SupplierDisclosure]:
        """英語 10-K テキストからサプライヤー名を抽出。"""
        results: list[SupplierDisclosure] = []
        seen: set[str] = set()

        # Find supplier-related sections (context windows)
        for m in RE_SEC_SUPPLIER_SECTION.finditer(text):
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 3000)
            section = text[start:end]

            for cm in RE_EN_COMPANY_NAME.finditer(section):
                name = cm.group().strip()
                # 自社名を除外
                if ticker.upper() in name.upper():
                    continue
                if len(name) < 5:
                    continue
                name_normalized = name.rstrip("., ")
                # Skip false positives
                if name_normalized in _EN_FALSE_POSITIVES:
                    continue
                if name_normalized in seen:
                    continue
                seen.add(name_normalized)

                # Determine confidence based on surrounding context
                context_lower = section[max(0, cm.start() - 100):cm.end() + 100].lower()
                if any(kw in context_lower for kw in
                       ("sole source", "single source", "principal supplier",
                        "primary supplier", "key supplier", "critical supplier")):
                    confidence = "DISCLOSED"
                else:
                    confidence = "INFERRED"

                # Determine relationship
                if "sole source" in context_lower or "single source" in context_lower:
                    relationship = "sole_source_supplier"
                elif "raw material" in context_lower:
                    relationship = "raw_material_supplier"
                elif "vendor" in context_lower:
                    relationship = "vendor"
                else:
                    relationship = "supplier"

                results.append(SupplierDisclosure(
                    supplier_name=name_normalized,
                    disclosure_type="10K_supplier_section",
                    relationship=relationship,
                    country="US",
                    source="SEC_10K",
                    confidence=confidence,
                    filing_date=filing_date,
                ))

        return results

    # ---- SEC Conflict Minerals Report (SD / Exhibit 1.01) ---------------

    def scrape_conflict_minerals_report(
        self, ticker: str
    ) -> ConflictMineralsReport:
        """SEC SD filing (Exhibit 1.01) から紛争鉱物レポートを取得。

        Parameters
        ----------
        ticker : str
            ティッカーシンボル

        Returns
        -------
        ConflictMineralsReport
        """
        report = ConflictMineralsReport(company=ticker)
        try:
            cik = self._resolve_cik(ticker)
            if not cik:
                return report

            filing_url, filing_year = self._find_latest_sd_filing(cik)
            if not filing_url:
                return report

            report.filing_year = filing_year
            text = self._download_sec_filing_text(filing_url)
            if not text:
                return report

            self._parse_conflict_minerals_text(text, report)
        except Exception as e:
            print(f"[IR Scraper] Conflict minerals error for {ticker}: {e}")

        return report

    def _find_latest_sd_filing(self, cik: str) -> tuple[str | None, int | None]:
        """CIK から最新の SD (Specialized Disclosure) / Exhibit 1.01 を取得。"""
        padded_cik = cik.zfill(10)
        try:
            resp = _get_sec(f"{SEC_SUBMISSIONS_BASE}/CIK{padded_cik}.json")
            data = resp.json()
        except Exception:
            return None, None

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        filing_dates = recent.get("filingDate", [])

        for i, form_type in enumerate(forms):
            if form_type in ("SD", "SD/A"):
                accession = accessions[i].replace("-", "")
                doc_name = primary_docs[i]
                filing_year = None
                if i < len(filing_dates):
                    try:
                        filing_year = int(filing_dates[i][:4])
                    except (ValueError, IndexError):
                        pass

                # Try to find Exhibit 1.01 (the actual CMR)
                exhibit_url = self._find_exhibit_101(cik, accession)
                if exhibit_url:
                    return exhibit_url, filing_year

                # Fallback to primary doc
                url = f"{SEC_ARCHIVES_BASE}/{cik}/{accession}/{doc_name}"
                return url, filing_year

        return None, None

    def _find_exhibit_101(self, cik: str, accession: str) -> str | None:
        """Filing index から Exhibit 1.01 の URL を特定。"""
        index_url = f"{SEC_ARCHIVES_BASE}/{cik}/{accession}/index.json"
        try:
            resp = _get_sec(index_url)
            index_data = resp.json()
            items = index_data.get("directory", {}).get("item", [])
            for item in items:
                name = item.get("name", "")
                # Exhibit 1.01 is typically named with "ex" or "exhibit" and "101"
                if re.search(r"(?:ex|exhibit).*1[\-_.]?01", name, re.IGNORECASE):
                    return f"{SEC_ARCHIVES_BASE}/{cik}/{accession}/{name}"
                # Also check description field
                desc = str(item.get("description", "")).lower()
                if "exhibit 1.01" in desc or "conflict minerals" in desc:
                    return f"{SEC_ARCHIVES_BASE}/{cik}/{accession}/{name}"
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_conflict_minerals_text(text: str, report: ConflictMineralsReport):
        """紛争鉱物レポートテキストからデータ抽出。"""
        text_lower = text.lower()

        # --- minerals in scope ---
        # Full-word names matched case-insensitively in text_lower
        _mineral_words = {
            "tin": "tin", "tantalum": "tantalum", "coltan": "tantalum",
            "tungsten": "tungsten", "wolfram": "tungsten",
            "gold": "gold", "cobalt": "cobalt",
        }
        # Chemical symbols matched case-sensitively against original text
        # (e.g. "Sn" not "sn"; avoids false positives with "co", "w")
        _mineral_symbols = {
            "Sn": "tin", "Ta": "tantalum",
            "Au": "gold", "3TG": "gold",  # 3TG = tin/tantalum/tungsten/gold
        }
        found_minerals: set[str] = set()
        for word, mineral in _mineral_words.items():
            if re.search(rf"\b{re.escape(word)}\b", text_lower):
                found_minerals.add(mineral)
        for symbol, mineral in _mineral_symbols.items():
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                found_minerals.add(mineral)
                if symbol == "3TG":
                    found_minerals.update({"tin", "tantalum", "tungsten", "gold"})
        report.minerals_in_scope = sorted(found_minerals)

        # --- smelters ---
        smelters: list[dict] = []
        seen_smelters: set[str] = set()
        for m in RE_SMELTER_ROW.finditer(text):
            smelter_name = m.group(1).strip()
            country = m.group(2).strip()
            mineral_raw = m.group(3).strip().lower()
            mineral = _mineral_words.get(mineral_raw, mineral_raw)

            key = f"{smelter_name}|{mineral}"
            if key not in seen_smelters:
                seen_smelters.add(key)
                smelters.append({
                    "name": smelter_name,
                    "country": country,
                    "mineral": mineral,
                })
        report.smelters = smelters

        # --- DRC sourcing status ---
        if re.search(r"did\s+not\s+originate.*(?:drc|congo|covered\s+countr)", text_lower):
            report.drc_sourcing = "no"
        elif re.search(r"(?:originat|sourced?).*(?:drc|congo|covered\s+countr)", text_lower):
            report.drc_sourcing = "yes"
        elif "undeterminable" in text_lower or "unable to determine" in text_lower:
            report.drc_sourcing = "undeterminable"
        else:
            report.drc_sourcing = "unknown"

        # --- conflict-free certification ---
        if re.search(r"conflict[\-\s]?free", text_lower):
            if re.search(r"(?:certified|determined).*conflict[\-\s]?free", text_lower):
                report.conflict_free_certified = True
            elif re.search(r"not.*conflict[\-\s]?free", text_lower):
                report.conflict_free_certified = False
            else:
                report.conflict_free_certified = None

    # ---- Batch graph builder -------------------------------------------

    def batch_build_tier1_graph(
        self, companies: list[str]
    ) -> dict:
        """複数企業を処理し Tier-1 サプライチェーングラフを構築。

        Parameters
        ----------
        companies : list[str]
            企業名またはティッカーのリスト。
            英大文字のみ → ティッカーとみなし SEC 検索、
            日本語含む → EDINET 検索。

        Returns
        -------
        dict
            {"nodes": [...], "edges": [...], "stats": {...}}
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()
        all_suppliers: list[SupplierDisclosure] = []

        for company in companies:
            # 企業ノード追加
            if company not in node_ids:
                nodes.append({
                    "id": company,
                    "label": company,
                    "tier": 0,
                    "type": "buyer",
                })
                node_ids.add(company)

            # Detect language / market
            is_jp = any("\u4e00" <= ch <= "\u9fff" or "\u30a0" <= ch <= "\u30ff"
                        for ch in company)
            is_ticker = company.isascii() and company.replace("-", "").replace(".", "").isalpha()

            disclosures: list[SupplierDisclosure] = []
            if is_jp:
                disclosures.extend(self.scrape_edinet_suppliers(company))
            if is_ticker and not is_jp:
                disclosures.extend(self.scrape_sec_10k_suppliers(company))
            # If company is ticker-like but may also be JP listed, try both
            if not disclosures and not is_jp:
                disclosures.extend(self.scrape_edinet_suppliers(company))

            for sd in disclosures:
                all_suppliers.append(sd)

                # Name normalization with RapidFuzz
                supplier_id = self._normalize_name(sd.supplier_name, node_ids)

                if supplier_id not in node_ids:
                    nodes.append({
                        "id": supplier_id,
                        "label": sd.supplier_name,
                        "tier": 1,
                        "type": "supplier",
                        "country": sd.country,
                        "source": sd.source,
                    })
                    node_ids.add(supplier_id)

                edges.append({
                    "source": company,
                    "target": supplier_id,
                    "relationship": sd.relationship,
                    "confidence": sd.confidence,
                    "disclosure_type": sd.disclosure_type,
                    "filing_date": sd.filing_date,
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "companies_processed": len(companies),
                "total_suppliers_found": len(all_suppliers),
                "unique_supplier_nodes": sum(1 for n in nodes if n.get("tier") == 1),
                "edges": len(edges),
            },
        }

    @staticmethod
    def _normalize_name(name: str, existing_ids: set[str]) -> str:
        """既存ノードとの名寄せを試行。RapidFuzz で高類似度なら既存IDを返す。"""
        if not HAS_RAPIDFUZZ or not existing_ids:
            return name

        candidates = list(existing_ids)
        result = rfprocess.extractOne(
            name,
            candidates,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=85,
        )
        if result is not None:
            matched_name, score, _idx = result
            return matched_name
        return name

    # ---- Async wrappers ------------------------------------------------

    async def async_scrape_edinet_suppliers(
        self, company_name: str, edinetCode: str = ""
    ) -> list[SupplierDisclosure]:
        """scrape_edinet_suppliers の非同期ラッパー。"""
        return await asyncio.to_thread(
            self.scrape_edinet_suppliers, company_name, edinetCode
        )

    async def async_scrape_sec_10k_suppliers(
        self, ticker: str, cik: str = ""
    ) -> list[SupplierDisclosure]:
        """scrape_sec_10k_suppliers の非同期ラッパー。"""
        return await asyncio.to_thread(
            self.scrape_sec_10k_suppliers, ticker, cik
        )

    async def async_scrape_conflict_minerals_report(
        self, ticker: str
    ) -> ConflictMineralsReport:
        """scrape_conflict_minerals_report の非同期ラッパー。"""
        return await asyncio.to_thread(
            self.scrape_conflict_minerals_report, ticker
        )

    async def async_batch_build_tier1_graph(
        self, companies: list[str]
    ) -> dict:
        """batch_build_tier1_graph の非同期ラッパー。"""
        return await asyncio.to_thread(
            self.batch_build_tier1_graph, companies
        )


# ---------------------------------------------------------------------------
# CLI entry point (for manual testing)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="IR Scraper — extract Tier-1 suppliers from corporate filings"
    )
    parser.add_argument("--edinet", type=str, help="Company name for EDINET search (JP)")
    parser.add_argument("--edinet-code", type=str, default="", help="EDINET code")
    parser.add_argument("--sec", type=str, help="Ticker for SEC 10-K search (US)")
    parser.add_argument("--cik", type=str, default="", help="SEC CIK number")
    parser.add_argument("--conflict", type=str, help="Ticker for conflict minerals report")
    parser.add_argument("--batch", nargs="+", help="Multiple companies for graph build")
    args = parser.parse_args()

    scraper = IRScraper()

    if args.edinet:
        print(f"\n=== EDINET: {args.edinet} ===")
        suppliers = scraper.scrape_edinet_suppliers(args.edinet, args.edinet_code)
        for s in suppliers:
            print(f"  [{s.confidence}] {s.supplier_name} ({s.relationship}) — {s.filing_date}")
        if not suppliers:
            print("  (no suppliers found)")

    if args.sec:
        print(f"\n=== SEC 10-K: {args.sec} ===")
        suppliers = scraper.scrape_sec_10k_suppliers(args.sec, args.cik)
        for s in suppliers:
            print(f"  [{s.confidence}] {s.supplier_name} ({s.relationship}) — {s.filing_date}")
        if not suppliers:
            print("  (no suppliers found)")

    if args.conflict:
        print(f"\n=== Conflict Minerals: {args.conflict} ===")
        report = scraper.scrape_conflict_minerals_report(args.conflict)
        print(f"  Filing year:   {report.filing_year}")
        print(f"  Minerals:      {report.minerals_in_scope}")
        print(f"  Smelters:      {len(report.smelters)}")
        print(f"  DRC sourcing:  {report.drc_sourcing}")
        print(f"  Conflict-free: {report.conflict_free_certified}")

    if args.batch:
        print(f"\n=== Batch graph: {args.batch} ===")
        graph = scraper.batch_build_tier1_graph(args.batch)
        print(f"  Nodes: {graph['stats']['unique_supplier_nodes']} suppliers")
        print(f"  Edges: {graph['stats']['edges']}")
        print(json.dumps(graph, indent=2, ensure_ascii=False, default=str))
