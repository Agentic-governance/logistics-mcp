"""ImportYeti US税関データクライアント
米国税関の船荷証券(Bill of Lading)データを取得し、
実際のシッパー→コンサイニー関係を確認する。
Tier-2サプライヤー情報の裏付けに使用。

データソース: https://www.importyeti.com/
制限事項:
  - 公式APIなし（HTMLスクレイピング）
  - 米国輸入データのみ対象（米国向け出荷のみ）
  - robots.txt を遵守
  - レート制限: 10秒に1リクエスト以下
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import time
import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process as rfprocess

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
IMPORTYETI_BASE_URL = "https://www.importyeti.com"
USER_AGENT = "SCRI-Research/0.9"
RATE_LIMIT_INTERVAL = 10.0  # 秒（リクエスト間の最小待機時間）
REQUEST_TIMEOUT = 30  # 秒
FUZZY_MATCH_THRESHOLD = 75  # RapidFuzz スコア閾値

# ---------------------------------------------------------------------------
# 企業名通称・略称マッピング（表記揺れ対策）
# キー: 正式名称（正規化後）、値: 通称・略称リスト
# ---------------------------------------------------------------------------
COMPANY_ALIASES: dict[str, list[str]] = {
    "FOXCONN": ["HON HAI PRECISION INDUSTRY", "HON HAI", "FOXCONN TECHNOLOGY",
                "FOXCONN INDUSTRIAL INTERNET", "FII", "HONGFUJIN PRECISION"],
    "SAMSUNG ELECTRONICS": ["SAMSUNG", "SEC", "SAMSUNG SDI", "SAMSUNG ELECTRO MECHANICS"],
    "TSMC": ["TAIWAN SEMICONDUCTOR MANUFACTURING", "TAIWAN SEMICONDUCTOR", "TSM"],
    "SK HYNIX": ["SK HYNIX SEMICONDUCTOR", "HYNIX SEMICONDUCTOR", "HYNIX"],
    "LG ELECTRONICS": ["LG CORP", "LG", "LG DISPLAY", "LG CHEM", "LG ENERGY SOLUTION"],
    "TOYOTA MOTOR": ["TOYOTA", "TMC", "TOYOTA MOTOR CORPORATION"],
    "HONDA MOTOR": ["HONDA", "HMC", "HONDA MOTOR CO"],
    "SONY GROUP": ["SONY", "SONY CORPORATION", "SONY SEMICONDUCTOR SOLUTIONS"],
    "PANASONIC": ["PANASONIC HOLDINGS", "PANASONIC CORPORATION", "MATSUSHITA"],
    "DENSO": ["DENSO CORPORATION", "NIPPONDENSO"],
    "MITSUBISHI ELECTRIC": ["MELCO", "MITSUBISHI ELECTRIC CORPORATION"],
    "HITACHI": ["HITACHI LTD", "HITACHI HIGH TECHNOLOGIES"],
    "APPLE": ["APPLE INC", "APPLE COMPUTER"],
    "GOOGLE": ["ALPHABET", "ALPHABET INC", "GOOGLE LLC"],
    "AMAZON": ["AMAZON COM", "AMZN"],
    "HUAWEI": ["HUAWEI TECHNOLOGIES", "HUAWEI TECH"],
    "BYD": ["BYD COMPANY", "BYD AUTO", "BUILD YOUR DREAMS"],
    "CATL": ["CONTEMPORARY AMPEREX TECHNOLOGY", "CONTEMPORARY AMPEREX"],
    "INTEL": ["INTEL CORPORATION", "INTEL CORP"],
    "QUALCOMM": ["QUALCOMM INCORPORATED", "QUALCOMM INC"],
    "BOSCH": ["ROBERT BOSCH", "ROBERT BOSCH GMBH", "BOSCH GMBH"],
    "SIEMENS": ["SIEMENS AG", "SIEMENS CORPORATION"],
    "TOSHIBA": ["TOSHIBA CORPORATION", "TOSHIBA CORP"],
    "MURATA": ["MURATA MANUFACTURING", "MURATA MFG"],
    "TDK": ["TDK CORPORATION", "TDK CORP"],
    "NIPPON STEEL": ["NIPPON STEEL CORPORATION", "NSSMC", "NIPPON STEEL & SUMITOMO METAL"],
    "JFE STEEL": ["JFE HOLDINGS", "JFE STEEL CORPORATION"],
    "POSCO": ["POSCO HOLDINGS", "POSCO INTERNATIONAL"],
    "BASF": ["BASF SE", "BASF CORPORATION"],
    "DOW": ["DOW CHEMICAL", "DOW INC"],
    "DUPONT": ["E I DU PONT DE NEMOURS", "DUPONT DE NEMOURS"],
}

# 逆引きインデックスはモジュール末尾で構築（normalize_company_name 定義後）
_ALIAS_TO_CANONICAL: dict[str, str] = {}

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# 国名 → ISO 3166-1 alpha-3 変換テーブル
# ImportYetiで頻出する国名表記をカバー
# ---------------------------------------------------------------------------
_COUNTRY_TO_ISO3: dict[str, str] = {
    "china": "CHN", "cn": "CHN", "peoples republic of china": "CHN",
    "taiwan": "TWN", "tw": "TWN", "taiwan province of china": "TWN",
    "hong kong": "HKG", "hk": "HKG",
    "japan": "JPN", "jp": "JPN",
    "south korea": "KOR", "korea": "KOR", "korea republic of": "KOR",
    "kr": "KOR", "republic of korea": "KOR",
    "vietnam": "VNM", "vn": "VNM", "viet nam": "VNM",
    "thailand": "THA", "th": "THA",
    "india": "IND", "in": "IND",
    "indonesia": "IDN", "id": "IDN",
    "malaysia": "MYS", "my": "MYS",
    "philippines": "PHL", "ph": "PHL",
    "singapore": "SGP", "sg": "SGP",
    "bangladesh": "BGD", "bd": "BGD",
    "myanmar": "MMR", "mm": "MMR", "burma": "MMR",
    "cambodia": "KHM", "kh": "KHM",
    "pakistan": "PAK", "pk": "PAK",
    "sri lanka": "LKA", "lk": "LKA",
    "united states": "USA", "us": "USA", "usa": "USA",
    "united states of america": "USA",
    "germany": "DEU", "de": "DEU",
    "united kingdom": "GBR", "uk": "GBR", "gb": "GBR",
    "great britain": "GBR",
    "france": "FRA", "fr": "FRA",
    "italy": "ITA", "it": "ITA",
    "netherlands": "NLD", "nl": "NLD", "holland": "NLD",
    "belgium": "BEL", "be": "BEL",
    "spain": "ESP", "es": "ESP",
    "canada": "CAN", "ca": "CAN",
    "mexico": "MEX", "mx": "MEX",
    "brazil": "BRA", "br": "BRA",
    "australia": "AUS", "au": "AUS",
    "turkey": "TUR", "tr": "TUR", "turkiye": "TUR",
    "russia": "RUS", "ru": "RUS", "russian federation": "RUS",
    "saudi arabia": "SAU", "sa": "SAU",
    "uae": "ARE", "ae": "ARE", "united arab emirates": "ARE",
    "egypt": "EGY", "eg": "EGY",
    "south africa": "ZAF", "za": "ZAF",
    "nigeria": "NGA", "ng": "NGA",
    "kenya": "KEN", "ke": "KEN",
    "ethiopia": "ETH", "et": "ETH",
    "ghana": "GHA", "gh": "GHA",
    "morocco": "MAR", "ma": "MAR",
    "colombia": "COL", "co": "COL",
    "chile": "CHL", "cl": "CHL",
    "argentina": "ARG", "ar": "ARG",
    "peru": "PER", "pe": "PER",
    "ukraine": "UKR", "ua": "UKR",
    "poland": "POL", "pl": "POL",
    "czech republic": "CZE", "cz": "CZE", "czechia": "CZE",
    "sweden": "SWE", "se": "SWE",
    "switzerland": "CHE", "ch": "CHE",
    "austria": "AUT", "at": "AUT",
    "israel": "ISR", "il": "ISR",
    "iran": "IRN", "ir": "IRN",
    "iraq": "IRQ", "iq": "IRQ",
    "north korea": "PRK", "kp": "PRK", "dprk": "PRK",
    "new zealand": "NZL", "nz": "NZL",
    "portugal": "PRT", "pt": "PRT",
    "denmark": "DNK", "dk": "DNK",
    "norway": "NOR", "no": "NOR",
    "finland": "FIN", "fi": "FIN",
}

# ---------------------------------------------------------------------------
# HSコード抽出用正規表現
# 例: "8541.40", "8471.30.01", "HS 8542", "HTS 9903.88"
# ---------------------------------------------------------------------------
_HS_CODE_PATTERNS = [
    re.compile(r"\b(?:HS|HTS|HTSUS)[\s:]*(\d{4}(?:\.\d{2}(?:\.\d{2,4})?)?)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4}\.\d{2}(?:\.\d{2,4})?)\b"),
    re.compile(r"\b(\d{6,10})\b"),  # 連続桁のHSコード（6桁以上）
]


# ---------------------------------------------------------------------------
# データクラス定義
# ---------------------------------------------------------------------------
@dataclass
class ShipmentRecord:
    """米国税関の個別出荷レコード"""
    shipper_name: str
    consignee_name: str
    shipper_country: str  # ISO3コード
    product_description: str
    hs_code: str
    shipment_date: str  # ISO 8601形式
    weight_kg: float
    container_count: int


@dataclass
class ImportRecord:
    """スペック互換エイリアス — 通関記録の統合レコード
    ShipmentRecord と相互変換可能。
    """
    shipper: str
    consignee: str
    hs_code: str
    description: str
    weight_kg: float
    port: str
    date: str
    country_origin: str

    @classmethod
    def from_shipment(cls, sr: "ShipmentRecord") -> "ImportRecord":
        return cls(
            shipper=sr.shipper_name,
            consignee=sr.consignee_name,
            hs_code=sr.hs_code,
            description=sr.product_description,
            weight_kg=sr.weight_kg,
            port="",
            date=sr.shipment_date,
            country_origin=sr.shipper_country,
        )


@dataclass
class SupplierRelation:
    """バイヤーに対する実際のサプライヤー関係"""
    supplier_name: str
    supplier_country: str  # ISO3コード
    shipment_count: int
    latest_shipment: str  # ISO 8601形式
    product_description: str
    hs_code_detected: str
    confidence: str = "CONFIRMED"
    data_source: str = "US_CUSTOMS"


@dataclass
class BuyerRelation:
    """サプライヤーに対する実際のバイヤー関係"""
    buyer_name: str
    buyer_country: str  # ISO3コード（米国輸入なので通常 "USA"）
    shipment_count: int
    latest_shipment: str  # ISO 8601形式
    product_description: str


# ---------------------------------------------------------------------------
# ユーティリティ関数
# ---------------------------------------------------------------------------
def normalize_country(raw_country: str) -> str:
    """国名をISO 3166-1 alpha-3コードに正規化する。

    Args:
        raw_country: 生の国名文字列（例: "CHINA", "Viet Nam"）

    Returns:
        ISO3コード（例: "CHN"）。不明な場合は入力をそのまま返す。
    """
    if not raw_country:
        return ""
    normalized = raw_country.strip().lower()
    # 完全一致
    if normalized in _COUNTRY_TO_ISO3:
        return _COUNTRY_TO_ISO3[normalized]
    # 部分一致（長い国名用）
    for key, iso3 in _COUNTRY_TO_ISO3.items():
        if key in normalized or normalized in key:
            return iso3
    # 既にISO3の場合はそのまま返す
    if len(raw_country.strip()) == 3 and raw_country.strip().isalpha():
        return raw_country.strip().upper()
    logger.debug("国名のISO3変換に失敗: %s", raw_country)
    return raw_country.strip()


def extract_hs_codes(text: str) -> list[str]:
    """テキストからHSコードを正規表現で抽出する。

    Args:
        text: 製品説明やBOL記述テキスト

    Returns:
        検出されたHSコードのリスト（重複なし）
    """
    if not text:
        return []
    found: list[str] = []
    for pattern in _HS_CODE_PATTERNS:
        for match in pattern.finditer(text):
            code = match.group(1)
            # 6桁未満の連続数字は除外（日付等の誤検出防止）
            if pattern == _HS_CODE_PATTERNS[2] and len(code) < 6:
                continue
            # 年号の誤検出除外（1900-2099）
            if re.match(r"^(19|20)\d{2}$", code):
                continue
            formatted = _format_hs_code(code)
            if formatted and formatted not in found:
                found.append(formatted)
    return found


def _format_hs_code(raw: str) -> str:
    """HSコードを標準的な 'XXXX.XX' 形式に整形する。"""
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) < 4:
        return ""
    if len(digits) == 4:
        return f"{digits[:4]}"
    if len(digits) >= 6:
        return f"{digits[:4]}.{digits[4:6]}"
    return f"{digits[:4]}.{digits[4:]}"


def normalize_company_name(name: str) -> str:
    """企業名を正規化する（比較用）。

    接尾辞の除去、大文字化、余分な空白の圧縮を行う。
    """
    if not name:
        return ""
    cleaned = name.upper().strip()
    # 一般的な法人格表記を除去
    suffixes = [
        r"\bCO\.?\s*,?\s*LTD\.?\b", r"\bCORP\.?\b", r"\bINC\.?\b",
        r"\bLLC\.?\b", r"\bLTD\.?\b", r"\bLIMITED\b", r"\bGMBH\b",
        r"\bS\.?A\.?\b", r"\bPTE\.?\b", r"\bPVT\.?\b", r"\bB\.?V\.?\b",
        r"\bN\.?V\.?\b", r"\bAG\b", r"\bPLC\b", r"\bL\.?P\.?\b",
        r"\bJSC\b", r"\bOJSC\b",
    ]
    for suffix_pattern in suffixes:
        cleaned = re.sub(suffix_pattern, "", cleaned, flags=re.IGNORECASE)
    # 句読点除去・空白圧縮
    cleaned = re.sub(r"[,.\-()]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def company_names_match(name_a: str, name_b: str) -> bool:
    """2つの企業名がRapidFuzzで類似しているかを判定する。"""
    norm_a = normalize_company_name(name_a)
    norm_b = normalize_company_name(name_b)
    if not norm_a or not norm_b:
        return False
    # エイリアスによる正規名チェック
    canon_a = resolve_canonical_name(norm_a)
    canon_b = resolve_canonical_name(norm_b)
    if canon_a and canon_b and canon_a == canon_b:
        return True
    score = fuzz.token_sort_ratio(norm_a, norm_b)
    return score >= FUZZY_MATCH_THRESHOLD


def resolve_canonical_name(normalized_name: str) -> str:
    """正規化済み企業名をエイリアス辞書で正式名称に解決する。

    Args:
        normalized_name: normalize_company_name() 適用済みの企業名

    Returns:
        正式名称。エイリアス辞書に存在しない場合は空文字列。
    """
    return _ALIAS_TO_CANONICAL.get(normalized_name, "")


def _build_alias_index():
    """COMPANY_ALIASES からエイリアス逆引きインデックスを構築する。
    モジュールロード時に1回だけ呼ばれる。
    """
    for canon, aliases in COMPANY_ALIASES.items():
        norm_canon = normalize_company_name(canon)
        _ALIAS_TO_CANONICAL[norm_canon] = canon
        for alias in aliases:
            norm_alias = normalize_company_name(alias)
            _ALIAS_TO_CANONICAL[norm_alias] = canon


# エイリアスインデックス構築
_build_alias_index()


def deduplicate_shipments(records: list) -> list:
    """出荷レコードの重複を除去する。

    同一シッパー × コンサイニー × 日付 × HSコードの組合せで重複判定。
    RapidFuzz でシッパー名の表記揺れも吸収する。

    Args:
        records: ShipmentRecord のリスト

    Returns:
        重複除去済みリスト
    """
    if not records:
        return records

    seen_keys: list[str] = []
    unique: list = []

    for rec in records:
        # 正規化キー: シッパー名 + コンサイニー名 + 日付 + HSコード
        norm_shipper = normalize_company_name(rec.shipper_name)
        norm_consignee = normalize_company_name(rec.consignee_name)
        # エイリアス解決
        canon_shipper = resolve_canonical_name(norm_shipper) or norm_shipper
        canon_consignee = resolve_canonical_name(norm_consignee) or norm_consignee
        key = f"{canon_shipper}|{canon_consignee}|{rec.shipment_date}|{rec.hs_code}"

        # 完全一致の重複は排除
        if key in seen_keys:
            continue

        # ファジー重複チェック（同日の類似レコード）
        is_dup = False
        for existing_key in seen_keys:
            parts_existing = existing_key.split("|")
            if len(parts_existing) == 4:
                # 日付とHSコードが一致 & シッパー名が類似
                if (parts_existing[2] == rec.shipment_date and
                        parts_existing[3] == rec.hs_code):
                    sim = fuzz.token_sort_ratio(canon_shipper, parts_existing[0])
                    if sim >= 85:
                        is_dup = True
                        break
        if not is_dup:
            seen_keys.append(key)
            unique.append(rec)

    return unique


def quality_score(shipment) -> float:
    """出荷レコードの品質スコアを算出する（0.0〜1.0）。

    以下の要素を評価:
      - シッパー名の有無・品質 (0.25)
      - コンサイニー名の有無・品質 (0.20)
      - HSコードの有無・妥当性 (0.20)
      - 日付の有無・妥当性 (0.15)
      - 国名の有無 (0.10)
      - 重量データの有無 (0.10)

    Args:
        shipment: ShipmentRecord オブジェクト

    Returns:
        品質スコア 0.0（最低）〜 1.0（最高）
    """
    score = 0.0

    # シッパー名 (0.25)
    if hasattr(shipment, 'shipper_name') and shipment.shipper_name:
        name = shipment.shipper_name.strip()
        if len(name) >= 3:
            score += 0.20
            # エイリアスで正式名称に解決できればボーナス
            norm = normalize_company_name(name)
            if resolve_canonical_name(norm):
                score += 0.05
            elif len(name) >= 5:
                score += 0.03
        else:
            score += 0.05
    elif hasattr(shipment, 'shipper') and shipment.shipper:
        score += 0.15

    # コンサイニー名 (0.20)
    consignee = getattr(shipment, 'consignee_name', '') or getattr(shipment, 'consignee', '')
    if consignee and len(consignee.strip()) >= 3:
        score += 0.20
    elif consignee:
        score += 0.05

    # HSコード (0.20)
    hs = getattr(shipment, 'hs_code', '')
    if hs:
        hs_digits = re.sub(r"[^0-9]", "", hs)
        if len(hs_digits) >= 6:
            score += 0.20  # 6桁以上: 最高品質
        elif len(hs_digits) >= 4:
            score += 0.15  # 4桁: 章レベル
        else:
            score += 0.05

    # 日付 (0.15)
    date_str = getattr(shipment, 'shipment_date', '') or getattr(shipment, 'date', '')
    if date_str:
        try:
            # ISO 8601 形式チェック
            if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
                score += 0.15
            else:
                score += 0.08  # 非標準形式
        except Exception:
            score += 0.05

    # 国名 (0.10)
    country = (getattr(shipment, 'shipper_country', '') or
               getattr(shipment, 'country_origin', ''))
    if country:
        if len(country) == 3 and country.isalpha():
            score += 0.10  # ISO3コード
        elif len(country) >= 2:
            score += 0.06

    # 重量 (0.10)
    weight = getattr(shipment, 'weight_kg', 0)
    if weight and weight > 0:
        score += 0.10
    elif weight == 0:
        score += 0.02  # 0は明示的にゼロか欠損か不明

    return min(1.0, round(score, 3))


# ---------------------------------------------------------------------------
# メインクライアントクラス
# ---------------------------------------------------------------------------
class ImportYetiClient:
    """ImportYeti US税関データクライアント

    米国の輸入通関データ（船荷証券）をスクレイピングで取得し、
    実際の取引関係（シッパー→コンサイニー）を確認する。

    注意事項:
      - ImportYetiは米国輸入データのみをカバー。他国の通関データは含まない。
      - 公式APIが存在しないため、HTMLスクレイピングを使用。
      - サイト構造変更時にパース失敗の可能性あり。
      - robots.txt を遵守し、10秒/リクエストのレート制限を適用。
      - サイト到達不能時は空結果を返し、クラッシュしない。

    使用例::

        client = ImportYetiClient()
        shipments = client.get_shipments("FOXCONN")
        suppliers = client.find_suppliers("APPLE INC")
        buyers = client.find_buyers("SAMSUNG ELECTRONICS")
    """

    def __init__(self, rate_limit: float = RATE_LIMIT_INTERVAL):
        """クライアントを初期化する。

        Args:
            rate_limit: リクエスト間の最小待機時間（秒）。デフォルト10秒。
        """
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._rate_limit = rate_limit
        self._last_request_time: float = 0.0
        self._lock = threading.Lock()
        self._robots_checked = False
        self._robots_allowed = True

    # ------------------------------------------------------------------
    # robots.txt チェック
    # ------------------------------------------------------------------
    def _check_robots_txt(self) -> bool:
        """robots.txt を確認し、スクレイピングが許可されているか判定する。

        初回呼び出し時のみ実際にリクエストを行い、結果をキャッシュする。
        取得失敗時はクロール不可と判断する（安全側に倒す）。

        Returns:
            True: クロール許可、False: 拒否
        """
        if self._robots_checked:
            return self._robots_allowed

        try:
            resp = self._session.get(
                f"{IMPORTYETI_BASE_URL}/robots.txt",
                timeout=10,
            )
            if resp.status_code == 200:
                content = resp.text.lower()
                # User-agent: * セクションの Disallow を確認
                # 簡易パーサー: /company/ や /search が明示的に Disallow されていないか
                lines = content.split("\n")
                in_wildcard_section = False
                for line in lines:
                    line = line.strip()
                    if line.startswith("user-agent:"):
                        agent = line.split(":", 1)[1].strip()
                        in_wildcard_section = (agent == "*")
                    elif in_wildcard_section and line.startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path == "/" or path == "/*":
                            logger.warning(
                                "robots.txt: 全パスがDisallow — スクレイピング停止"
                            )
                            self._robots_allowed = False
                            break
                        if path in ("/company", "/search"):
                            logger.warning(
                                "robots.txt: %s がDisallow — スクレイピング停止",
                                path,
                            )
                            self._robots_allowed = False
                            break
            else:
                # robots.txt が 404 等 → 制限なしと判断
                logger.info("robots.txt 取得: HTTP %d — 制限なしと判断", resp.status_code)
                self._robots_allowed = True
        except requests.RequestException as exc:
            logger.warning("robots.txt 取得失敗: %s — 安全のためスクレイピング停止", exc)
            self._robots_allowed = False

        self._robots_checked = True
        return self._robots_allowed

    # ------------------------------------------------------------------
    # レート制限付きリクエスト
    # ------------------------------------------------------------------
    def _rate_limited_get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """レート制限を適用してGETリクエストを行う。

        Args:
            url: リクエスト先URL
            **kwargs: requests.get に渡す追加引数

        Returns:
            Response オブジェクト。失敗時は None。
        """
        # robots.txt チェック
        if not self._check_robots_txt():
            logger.warning("robots.txt によりスクレイピングが制限されています")
            return None

        with self._lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._rate_limit:
                wait = self._rate_limit - elapsed
                logger.debug("レート制限: %.1f秒待機", wait)
                time.sleep(wait)
            self._last_request_time = time.time()

        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        try:
            resp = self._session.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "N/A"
            logger.error("HTTPエラー %s: %s (URL: %s)", status, exc, url)
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.error("接続エラー: %s (URL: %s)", exc, url)
            return None
        except requests.exceptions.Timeout:
            logger.error("タイムアウト: %s秒超過 (URL: %s)", kwargs.get("timeout"), url)
            return None
        except requests.RequestException as exc:
            logger.error("リクエストエラー: %s (URL: %s)", exc, url)
            return None

    # ------------------------------------------------------------------
    # HTMLパース: 出荷レコード抽出
    # ------------------------------------------------------------------
    def _parse_shipment_rows(self, html: str) -> list[ShipmentRecord]:
        """ImportYetiの検索結果HTMLから出荷レコードを抽出する。

        ImportYetiのHTML構造はテーブル形式で出荷データを表示する。
        サイト構造変更時はここを修正する必要がある。

        Args:
            html: レスポンスHTMLの全文

        Returns:
            パースされた ShipmentRecord のリスト
        """
        soup = BeautifulSoup(html, "lxml")
        records: list[ShipmentRecord] = []

        # ImportYetiは出荷データをテーブル行で表示する
        # テーブル行の探索（複数のセレクタを試行）
        table = soup.find("table", class_=re.compile(r"shipment|result|data", re.I))
        if not table:
            # テーブルが見つからない場合、div構造を試行
            table = soup.find("div", class_=re.compile(r"shipment|result", re.I))

        if not table:
            # 全テーブルを探索
            tables = soup.find_all("table")
            for t in tables:
                rows = t.find_all("tr")
                if len(rows) > 1:  # ヘッダー + データ行
                    table = t
                    break

        if not table:
            logger.debug("出荷データテーブルが見つかりません")
            return records

        rows = table.find_all("tr")
        # ヘッダー行を特定
        header_row = rows[0] if rows else None
        headers: list[str] = []
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                headers.append(th.get_text(strip=True).lower())

        # カラムインデックスのマッピング
        col_map = self._map_columns(headers)

        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            record = self._extract_shipment_from_row(cells, col_map)
            if record:
                records.append(record)

        return records

    def _map_columns(self, headers: list[str]) -> dict[str, int]:
        """ヘッダー名からカラムインデックスへのマッピングを生成する。"""
        mapping: dict[str, int] = {}
        keywords = {
            "shipper": ["shipper", "supplier", "exporter", "manufacturer"],
            "consignee": ["consignee", "buyer", "importer", "receiver"],
            "country": ["country", "origin", "shipper country"],
            "product": ["product", "description", "goods", "commodity"],
            "hs_code": ["hs", "hts", "tariff", "code"],
            "date": ["date", "arrival", "shipment date", "bill date"],
            "weight": ["weight", "kg", "net weight", "gross weight"],
            "containers": ["container", "teu", "quantity"],
        }
        for field_name, kw_list in keywords.items():
            for idx, header in enumerate(headers):
                if any(kw in header for kw in kw_list):
                    mapping[field_name] = idx
                    break
        return mapping

    def _extract_shipment_from_row(
        self,
        cells: list,
        col_map: dict[str, int],
    ) -> Optional[ShipmentRecord]:
        """テーブル行から ShipmentRecord を生成する。"""
        def safe_get(field_name: str, default: str = "") -> str:
            idx = col_map.get(field_name)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True)
            return default

        shipper = safe_get("shipper")
        consignee = safe_get("consignee")
        if not shipper and not consignee:
            return None

        product_desc = safe_get("product")
        raw_hs = safe_get("hs_code")
        # HSコードがカラムにない場合、製品説明から抽出
        hs_codes = extract_hs_codes(raw_hs) if raw_hs else extract_hs_codes(product_desc)
        hs_code = hs_codes[0] if hs_codes else ""

        raw_weight = safe_get("weight", "0")
        weight_kg = self._parse_weight(raw_weight)

        raw_containers = safe_get("containers", "0")
        container_count = self._parse_int(raw_containers)

        raw_date = safe_get("date")
        shipment_date = self._parse_date(raw_date)

        country_raw = safe_get("country")
        country_iso = normalize_country(country_raw)

        return ShipmentRecord(
            shipper_name=shipper,
            consignee_name=consignee,
            shipper_country=country_iso,
            product_description=product_desc,
            hs_code=hs_code,
            shipment_date=shipment_date,
            weight_kg=weight_kg,
            container_count=container_count,
        )

    # ------------------------------------------------------------------
    # HTMLパース: サプライヤー/バイヤー関係抽出
    # ------------------------------------------------------------------
    def _parse_company_relations(
        self,
        html: str,
        relation_type: str = "supplier",
    ) -> list[dict]:
        """企業ページからサプライヤーまたはバイヤー関係を抽出する。

        Args:
            html: 企業ページのHTML
            relation_type: "supplier" または "buyer"

        Returns:
            関係情報の辞書リスト
        """
        soup = BeautifulSoup(html, "lxml")
        relations: list[dict] = []

        # ImportYetiの企業ページはサプライヤー/バイヤーの
        # サマリーをテーブルまたはリスト形式で表示する
        # テーブル探索
        tables = soup.find_all("table")
        target_table = None
        for t in tables:
            header_text = t.get_text(strip=True).lower()
            if relation_type == "supplier" and any(
                kw in header_text for kw in ["supplier", "shipper", "exporter"]
            ):
                target_table = t
                break
            elif relation_type == "buyer" and any(
                kw in header_text for kw in ["buyer", "consignee", "importer"]
            ):
                target_table = t
                break

        if not target_table:
            # テーブルが見つからない場合、全テーブルの2番目以降を試行
            if len(tables) >= 2:
                target_table = tables[1]

        if not target_table:
            logger.debug("%s テーブルが見つかりません", relation_type)
            return relations

        rows = target_table.find_all("tr")
        for row in rows[1:]:  # ヘッダー行をスキップ
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            name = cells[0].get_text(strip=True)
            if not name:
                continue

            # 出荷回数の取得を試みる
            shipment_count = 0
            country = ""
            product = ""
            for i, cell in enumerate(cells[1:], 1):
                text = cell.get_text(strip=True)
                if text.isdigit():
                    shipment_count = int(text)
                elif len(text) <= 30 and not text.isdigit():
                    if not country:
                        country = text
                    elif not product:
                        product = text

            relations.append({
                "name": name,
                "country": normalize_country(country),
                "shipment_count": shipment_count,
                "product": product,
            })

        return relations

    # ------------------------------------------------------------------
    # パースヘルパー
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_weight(raw: str) -> float:
        """重量文字列をkg浮動小数点に変換する。"""
        if not raw:
            return 0.0
        cleaned = re.sub(r"[^\d.]", "", raw)
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_int(raw: str) -> int:
        """文字列を整数に変換する。"""
        if not raw:
            return 0
        cleaned = re.sub(r"[^\d]", "", raw)
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_date(raw: str) -> str:
        """日付文字列をISO 8601形式に変換する。"""
        if not raw:
            return ""
        # 複数のフォーマットを試行
        formats = [
            "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y",
            "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y",
            "%B %d, %Y", "%Y/%m/%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # パース不能な場合はそのまま返す
        return raw.strip()

    # ------------------------------------------------------------------
    # 公開メソッド（同期）
    # ------------------------------------------------------------------
    def get_shipments(
        self,
        company_name: str,
        limit: int = 50,
    ) -> list[ShipmentRecord]:
        """米国税関レコードから企業の出荷情報を検索する。

        ImportYetiを使用して、指定企業名に関連する
        船荷証券（Bill of Lading）データを取得する。

        注意: 米国輸入データのみ。米国以外の通関データは含まない。

        Args:
            company_name: 検索する企業名（シッパーまたはコンサイニー）
            limit: 取得する最大レコード数（デフォルト50）

        Returns:
            ShipmentRecord のリスト。取得失敗時は空リスト。
        """
        if not company_name or not company_name.strip():
            logger.warning("企業名が空です")
            return []

        encoded_name = quote_plus(company_name.strip())
        url = f"{IMPORTYETI_BASE_URL}/company/{encoded_name}"
        logger.info("出荷データ取得: %s", company_name)

        resp = self._rate_limited_get(url)
        if resp is None:
            logger.warning(
                "ImportYeti到達不能: %s — 空結果を返します。"
                "サイトがダウンしているか、レート制限の可能性があります。",
                company_name,
            )
            return []

        records = self._parse_shipment_rows(resp.text)

        # 重複排除（表記揺れ吸収付き）
        records = deduplicate_shipments(records)

        # 企業名でフィルタリング（RapidFuzzによるファジーマッチ）
        filtered: list[ShipmentRecord] = []
        for rec in records:
            if (company_names_match(company_name, rec.shipper_name) or
                    company_names_match(company_name, rec.consignee_name)):
                filtered.append(rec)
                if len(filtered) >= limit:
                    break

        # フィルタ結果が少ない場合は全レコードを返す（検索クエリ自体が合致のため）
        if len(filtered) < 3 and records:
            filtered = records[:limit]

        logger.info("出荷レコード取得完了: %d件 (企業: %s)", len(filtered), company_name)
        return filtered[:limit]

    def find_suppliers(
        self,
        buyer_company: str,
        hs_code: str = "",
    ) -> list[SupplierRelation]:
        """バイヤー企業の実際のサプライヤーを特定する。

        米国税関データからバイヤー（コンサイニー）として出現する企業の
        シッパー（サプライヤー）情報を集約する。

        注意: 米国輸入データのみ。バイヤーが米国企業でない場合、
        データが限定的になる可能性がある。

        Args:
            buyer_company: バイヤー企業名（例: "APPLE INC"）
            hs_code: HSコードフィルタ（オプション、例: "8542"）

        Returns:
            SupplierRelation のリスト。取得失敗時は空リスト。
        """
        if not buyer_company or not buyer_company.strip():
            logger.warning("バイヤー企業名が空です")
            return []

        encoded_name = quote_plus(buyer_company.strip())
        url = f"{IMPORTYETI_BASE_URL}/company/{encoded_name}"
        logger.info("サプライヤー検索: バイヤー=%s, HSコード=%s", buyer_company, hs_code or "(なし)")

        resp = self._rate_limited_get(url)
        if resp is None:
            logger.warning(
                "ImportYeti到達不能: サプライヤー検索失敗 (バイヤー: %s) — "
                "空結果を返します。",
                buyer_company,
            )
            return []

        # 方法1: 企業ページのサプライヤーサマリーを取得
        raw_relations = self._parse_company_relations(resp.text, "supplier")

        # 方法2: サマリーが得られない場合、出荷レコードから集約
        if not raw_relations:
            shipments = self._parse_shipment_rows(resp.text)
            raw_relations = self._aggregate_suppliers_from_shipments(
                shipments, buyer_company,
            )

        # HSコードフィルタ適用
        if hs_code:
            raw_relations = [
                r for r in raw_relations
                if hs_code in r.get("hs_code", "") or hs_code in r.get("product", "")
            ]

        # SupplierRelation に変換
        suppliers: list[SupplierRelation] = []
        for rel in raw_relations:
            # 製品説明からHSコード抽出
            product = rel.get("product", "")
            detected_hs = extract_hs_codes(product)
            hs_str = detected_hs[0] if detected_hs else (rel.get("hs_code", ""))

            suppliers.append(SupplierRelation(
                supplier_name=rel["name"],
                supplier_country=rel.get("country", ""),
                shipment_count=rel.get("shipment_count", 0),
                latest_shipment=rel.get("latest_shipment", ""),
                product_description=product,
                hs_code_detected=hs_str,
                confidence="CONFIRMED",
                data_source="US_CUSTOMS",
            ))

        # 出荷回数の降順でソート
        suppliers.sort(key=lambda s: s.shipment_count, reverse=True)
        logger.info(
            "サプライヤー検索完了: %d件 (バイヤー: %s)", len(suppliers), buyer_company,
        )
        return suppliers

    def find_buyers(
        self,
        supplier_company: str,
    ) -> list[BuyerRelation]:
        """サプライヤー企業の実際のバイヤーを特定する。

        米国税関データからシッパー（サプライヤー）として出現する企業の
        コンサイニー（バイヤー）情報を集約する。

        注意: 米国輸入データのみのため、バイヤーは基本的に米国企業。

        Args:
            supplier_company: サプライヤー企業名（例: "SAMSUNG ELECTRONICS"）

        Returns:
            BuyerRelation のリスト。取得失敗時は空リスト。
        """
        if not supplier_company or not supplier_company.strip():
            logger.warning("サプライヤー企業名が空です")
            return []

        encoded_name = quote_plus(supplier_company.strip())
        url = f"{IMPORTYETI_BASE_URL}/company/{encoded_name}"
        logger.info("バイヤー検索: サプライヤー=%s", supplier_company)

        resp = self._rate_limited_get(url)
        if resp is None:
            logger.warning(
                "ImportYeti到達不能: バイヤー検索失敗 (サプライヤー: %s) — "
                "空結果を返します。",
                supplier_company,
            )
            return []

        # 方法1: 企業ページのバイヤーサマリーを取得
        raw_relations = self._parse_company_relations(resp.text, "buyer")

        # 方法2: サマリーが得られない場合、出荷レコードから集約
        if not raw_relations:
            shipments = self._parse_shipment_rows(resp.text)
            raw_relations = self._aggregate_buyers_from_shipments(
                shipments, supplier_company,
            )

        # BuyerRelation に変換
        buyers: list[BuyerRelation] = []
        for rel in raw_relations:
            buyers.append(BuyerRelation(
                buyer_name=rel["name"],
                buyer_country=rel.get("country", "USA"),
                shipment_count=rel.get("shipment_count", 0),
                latest_shipment=rel.get("latest_shipment", ""),
                product_description=rel.get("product", ""),
            ))

        buyers.sort(key=lambda b: b.shipment_count, reverse=True)
        logger.info(
            "バイヤー検索完了: %d件 (サプライヤー: %s)", len(buyers), supplier_company,
        )
        return buyers

    # ------------------------------------------------------------------
    # 公開メソッド（非同期ラッパー）
    # ------------------------------------------------------------------
    async def async_get_shipments(
        self,
        company_name: str,
        limit: int = 50,
    ) -> list[ShipmentRecord]:
        """get_shipments の非同期ラッパー。

        asyncio.to_thread を使用して同期メソッドを非同期コンテキストで実行する。
        """
        return await asyncio.to_thread(self.get_shipments, company_name, limit)

    async def async_find_suppliers(
        self,
        buyer_company: str,
        hs_code: str = "",
    ) -> list[SupplierRelation]:
        """find_suppliers の非同期ラッパー。"""
        return await asyncio.to_thread(self.find_suppliers, buyer_company, hs_code)

    async def async_find_buyers(
        self,
        supplier_company: str,
    ) -> list[BuyerRelation]:
        """find_buyers の非同期ラッパー。"""
        return await asyncio.to_thread(self.find_buyers, supplier_company)

    # ------------------------------------------------------------------
    # スペック互換エイリアス（v0.9.0仕様に準拠）
    # ------------------------------------------------------------------
    async def search_company(self, company_name: str) -> list[ImportRecord]:
        """企業名で通関記録を検索し、ImportRecord リストを返す。
        v0.9.0 仕様のエイリアス（内部は get_shipments を使用）。
        """
        shipments = await self.async_get_shipments(company_name)
        return [ImportRecord.from_shipment(s) for s in shipments]

    async def get_suppliers(self, company_name: str) -> list[SupplierRelation]:
        """バイヤー企業のサプライヤー一覧を返す。
        v0.9.0 仕様のエイリアス（内部は find_suppliers を使用）。
        """
        return await self.async_find_suppliers(company_name)

    async def get_hs_details(
        self, company_name: str, hs_code: str,
    ) -> list[ShipmentRecord]:
        """企業 + HSコードで絞り込んだ出荷レコードを返す。
        v0.9.0 仕様のエイリアス。
        """
        shipments = await self.async_get_shipments(company_name, limit=100)
        return [s for s in shipments if hs_code in (s.hs_code or "")]

    # ------------------------------------------------------------------
    # 出荷レコードからの関係集約
    # ------------------------------------------------------------------
    def _aggregate_suppliers_from_shipments(
        self,
        shipments: list[ShipmentRecord],
        buyer_company: str,
    ) -> list[dict]:
        """出荷レコードからサプライヤー関係を集約する。

        バイヤー名に一致するコンサイニーのレコードを抽出し、
        シッパー（サプライヤー）ごとに集約する。
        """
        supplier_map: dict[str, dict] = {}

        for ship in shipments:
            # コンサイニーがバイヤーに一致するレコードを抽出
            if not company_names_match(buyer_company, ship.consignee_name):
                # 全レコードがバイヤーのページなら、全て該当と見なす
                if shipments and not any(
                    company_names_match(buyer_company, s.consignee_name)
                    for s in shipments[:5]
                ):
                    pass  # ページ全体がバイヤーのデータ
                else:
                    continue

            key = normalize_company_name(ship.shipper_name)
            if not key:
                continue

            if key not in supplier_map:
                supplier_map[key] = {
                    "name": ship.shipper_name,
                    "country": ship.shipper_country,
                    "shipment_count": 0,
                    "latest_shipment": ship.shipment_date,
                    "product": ship.product_description,
                    "hs_code": ship.hs_code,
                }
            supplier_map[key]["shipment_count"] += 1
            # 最新日付を更新
            if ship.shipment_date > supplier_map[key]["latest_shipment"]:
                supplier_map[key]["latest_shipment"] = ship.shipment_date

        return list(supplier_map.values())

    def _aggregate_buyers_from_shipments(
        self,
        shipments: list[ShipmentRecord],
        supplier_company: str,
    ) -> list[dict]:
        """出荷レコードからバイヤー関係を集約する。

        シッパー名にサプライヤー名が一致するレコードを抽出し、
        コンサイニー（バイヤー）ごとに集約する。
        """
        buyer_map: dict[str, dict] = {}

        for ship in shipments:
            # シッパーがサプライヤーに一致するレコードを抽出
            if not company_names_match(supplier_company, ship.shipper_name):
                if shipments and not any(
                    company_names_match(supplier_company, s.shipper_name)
                    for s in shipments[:5]
                ):
                    pass
                else:
                    continue

            key = normalize_company_name(ship.consignee_name)
            if not key:
                continue

            if key not in buyer_map:
                buyer_map[key] = {
                    "name": ship.consignee_name,
                    "country": "USA",  # 米国輸入データのため
                    "shipment_count": 0,
                    "latest_shipment": ship.shipment_date,
                    "product": ship.product_description,
                }
            buyer_map[key]["shipment_count"] += 1
            if ship.shipment_date > buyer_map[key]["latest_shipment"]:
                buyer_map[key]["latest_shipment"] = ship.shipment_date

        return list(buyer_map.values())


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
def get_customs_supplier_evidence(buyer: str, supplier: str) -> dict:
    """税関データによるサプライヤー関係の裏付け確認。

    バイヤーのサプライヤーリストに指定サプライヤーが存在するかを確認し、
    エビデンス付きでリスクスコアに貢献できる結果を返す。

    Args:
        buyer: バイヤー企業名
        supplier: 確認するサプライヤー企業名

    Returns:
        dict: confirmed (bool), evidence (list[str]), shipment_count (int)
    """
    client = ImportYetiClient()
    suppliers = client.find_suppliers(buyer)

    if not suppliers:
        return {
            "confirmed": False,
            "evidence": [
                f"[US税関] {buyer} のサプライヤーデータ取得不可 "
                "(ImportYeti到達不能または該当なし)"
            ],
            "shipment_count": 0,
        }

    # RapidFuzzでサプライヤー名を照合
    supplier_names = [s.supplier_name for s in suppliers]
    match_result = rfprocess.extractOne(
        normalize_company_name(supplier),
        [normalize_company_name(n) for n in supplier_names],
        scorer=fuzz.token_sort_ratio,
        score_cutoff=FUZZY_MATCH_THRESHOLD,
    )

    if match_result:
        matched_idx = match_result[2]
        matched_supplier = suppliers[matched_idx]
        return {
            "confirmed": True,
            "evidence": [
                f"[US税関/確認済] {buyer} ← {matched_supplier.supplier_name} "
                f"({matched_supplier.supplier_country})",
                f"[US税関] 出荷回数: {matched_supplier.shipment_count}件, "
                f"最新: {matched_supplier.latest_shipment}",
                f"[US税関] 品目: {matched_supplier.product_description or 'N/A'}",
            ],
            "shipment_count": matched_supplier.shipment_count,
        }

    return {
        "confirmed": False,
        "evidence": [
            f"[US税関] {buyer} のサプライヤーに {supplier} は検出されず "
            f"(検出済サプライヤー: {len(suppliers)}社)"
        ],
        "shipment_count": 0,
    }


# ---------------------------------------------------------------------------
# メイン（動作確認用）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    print("=" * 60)
    print("ImportYeti US税関データクライアント — 動作確認")
    print("注意: 米国輸入データのみ対象")
    print("=" * 60)

    # ユーティリティ関数のテスト
    print("\n--- 国名正規化テスト ---")
    for country in ["China", "VIET NAM", "usa", "TAIWAN", "korea", "DEU"]:
        print(f"  {country} -> {normalize_country(country)}")

    print("\n--- HSコード抽出テスト ---")
    test_texts = [
        "ELECTRONIC COMPONENTS HS 8542.31",
        "PLASTIC PARTS HTS 3926.90.99",
        "SEMICONDUCTOR DEVICES 854231",
        "FURNITURE items for office use",
    ]
    for text in test_texts:
        codes = extract_hs_codes(text)
        print(f"  '{text}' -> {codes}")

    print("\n--- 企業名照合テスト ---")
    pairs = [
        ("FOXCONN TECHNOLOGY CO., LTD", "FOXCONN TECHNOLOGY"),
        ("SAMSUNG ELECTRONICS CO LTD", "Samsung Electronics Corp"),
        ("APPLE INC", "GOOGLE LLC"),
    ]
    for a, b in pairs:
        result = company_names_match(a, b)
        print(f"  '{a}' vs '{b}' -> {result}")

    print("\n--- クライアント初期化 ---")
    client = ImportYetiClient()
    print(f"  レート制限: {client._rate_limit}秒/リクエスト")
    print("  注意: 実際のスクレイピングはImportYetiサイトへのアクセスが必要です")
