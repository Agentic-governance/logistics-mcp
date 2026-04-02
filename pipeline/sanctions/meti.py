"""METI 外国ユーザーリスト パーサー
差別化ポイント: 日本独自のリストで競合ゼロ

The old URL at /policy/anpo/law05.html now returns 404.
Current list is published via METI press releases.  We maintain a
discovery page URL that links to the latest press release, and a
direct PDF link for the most recently confirmed version.

URL pattern for press-release PDFs:
  https://www.meti.go.jp/press/{fiscal_year}/{mm}/{date}/{date}-1.pdf
"""
import requests
from bs4 import BeautifulSoup
from typing import Iterator, Optional
from .base import SanctionEntry, BaseParser
import re

# ---- Discovery page: METI trade-control English page ----
# Contains a link to "End User List" press releases.
METI_DISCOVERY_URL = (
    "https://www.meti.go.jp/policy/anpo/englishpage.html"
)

# ---- Direct PDF: most recent confirmed version (Sep 2025 revision) ----
METI_PDF_URL = (
    "https://www.meti.go.jp/press/2025/09/20250929006/20250929006-1.pdf"
)

# ---- Press release page (HTML, may contain an inline table) ----
METI_PRESS_URL = (
    "https://www.meti.go.jp/press/2025/09/20250929006/20250929006.html"
)

# Legacy base (kept for reference; currently 404)
METI_BASE_LEGACY = (
    "https://www.meti.go.jp/policy/anpo/law_document/foreignuserlist/"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SCRI-Platform/0.4)",
}

# METI servers sometimes require explicit TLS 1.2
_SESSION_KWARGS = {"timeout": 60, "headers": HEADERS}


def _meti_session() -> requests.Session:
    """Return a session configured for METI connectivity."""
    import ssl
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context

    class TLS12Adapter(HTTPAdapter):
        """Force TLS 1.2 which METI servers require."""
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context(ssl.PROTOCOL_TLS_CLIENT)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.mount("https://", TLS12Adapter())
    session.headers.update(HEADERS)
    return session


class METIParser(BaseParser):
    source = "meti"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching METI Foreign User List...")

        session = _meti_session()

        # Strategy 1: Try the press-release HTML page for an inline table
        try:
            resp = session.get(METI_PRESS_URL, timeout=60)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            entries = list(self._parse_html_table(soup))
            if entries:
                print(f"  Parsed {len(entries)} entries from press-release HTML")
                yield from entries
                return
        except Exception as e:
            print(f"  METI press-release HTML fetch failed: {e}")

        # Strategy 2: Try to discover a newer press-release PDF
        pdf_url = self._discover_latest_pdf(session) or METI_PDF_URL
        try:
            yield from self._parse_pdf(session, pdf_url)
            return
        except Exception as e:
            print(f"  METI PDF parse failed ({pdf_url}): {e}")

        # Strategy 3: Fallback to hardcoded PDF URL
        if pdf_url != METI_PDF_URL:
            try:
                yield from self._parse_pdf(session, METI_PDF_URL)
                return
            except Exception as e:
                print(f"  METI fallback PDF failed: {e}")

        print("  METI Foreign User List: all attempts exhausted")

    def _discover_latest_pdf(self, session: requests.Session) -> Optional[str]:
        """Try to find the latest End User List PDF from the discovery page."""
        try:
            resp = session.get(METI_DISCOVERY_URL, timeout=60)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            # Look for links mentioning "End User List" or "外国ユーザーリスト"
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                href = link["href"]
                if re.search(r"End.User.List|外国ユーザーリスト|user.?list", text, re.I):
                    if href.endswith(".pdf"):
                        if not href.startswith("http"):
                            href = "https://www.meti.go.jp" + href
                        return href
                    # Follow the press-release page to find the PDF
                    if "press" in href:
                        if not href.startswith("http"):
                            href = "https://www.meti.go.jp" + href
                        try:
                            pr = session.get(href, timeout=60)
                            pr.raise_for_status()
                            pr_soup = BeautifulSoup(pr.content, "html.parser")
                            for pdf_link in pr_soup.find_all("a", href=True):
                                if pdf_link["href"].endswith(".pdf"):
                                    pdf_href = pdf_link["href"]
                                    if not pdf_href.startswith("http"):
                                        pdf_href = "https://www.meti.go.jp" + pdf_href
                                    return pdf_href
                        except Exception:
                            pass
        except Exception as exc:
            print(f"  Discovery page failed: {exc}")
        return None

    def _parse_html_table(self, soup) -> Iterator[SanctionEntry]:
        """HTMLテーブル形式のMETIリストをパース"""
        for table in soup.find_all("table"):
            for row in table.find_all("tr")[1:]:  # ヘッダースキップ
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cols) >= 3 and cols[0]:
                    yield SanctionEntry(
                        source="meti",
                        source_id=None,
                        entity_type="entity",
                        name_primary=cols[0],
                        names_aliases=[],
                        country=cols[1] if len(cols) > 1 else None,
                        address=cols[2] if len(cols) > 2 else None,
                        programs=["METI_FOREIGN_USER_LIST"],
                        reason=cols[3] if len(cols) > 3 else None,
                    )

    def _parse_pdf(
        self, session: requests.Session, pdf_url: str
    ) -> Iterator[SanctionEntry]:
        """PDFからテーブル抽出（pdfplumber使用）"""
        import pdfplumber
        import tempfile
        import os

        print(f"  Downloading METI PDF from {pdf_url} ...")
        resp = session.get(pdf_url, timeout=120)
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        count = 0
        try:
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table[1:]:  # ヘッダースキップ
                            if not row or not row[0]:
                                continue
                            name = str(row[0]).strip()
                            if not name:
                                continue
                            count += 1
                            yield SanctionEntry(
                                source="meti",
                                source_id=None,
                                entity_type="entity",
                                name_primary=name,
                                names_aliases=[],
                                country=(
                                    str(row[1]).strip()
                                    if len(row) > 1 and row[1] else None
                                ),
                                address=(
                                    str(row[2]).strip()
                                    if len(row) > 2 and row[2] else None
                                ),
                                programs=["METI_FOREIGN_USER_LIST"],
                                reason=(
                                    str(row[3]).strip()
                                    if len(row) > 3 and row[3] else None
                                ),
                            )
            print(f"  Parsed {count} entries from PDF")
        finally:
            os.unlink(tmp_path)
