"""フライト供給量クライアント — 航空路線の座席供給量をルート別に取得
OpenFlights.org のルート・空港データから日本向け週次座席数を推定。
取得失敗時はハードコードの容量インデックス（2019=100）にフォールバック。
"""
import csv
import io
import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ========== 定数 ==========

OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OPENFLIGHTS_AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.3"}
REQUEST_TIMEOUT = 30

# 日本の主要空港 IATA コード
JAPAN_AIRPORTS = ["NRT", "HND", "KIX", "NGO", "CTS", "FUK", "OKA"]

# IATA → ISO3国コード マッピング（主要空港）
AIRPORT_COUNTRY_ISO3 = {
    # 中国
    "PEK": "CHN", "PVG": "CHN", "CAN": "CHN", "CTU": "CHN", "SZX": "CHN",
    "XIY": "CHN", "HGH": "CHN", "KMG": "CHN", "WUH": "CHN", "NKG": "CHN",
    "TAO": "CHN", "DLC": "CHN", "CSX": "CHN", "SHA": "CHN", "TSN": "CHN",
    "PKX": "CHN",
    # 韓国
    "ICN": "KOR", "GMP": "KOR", "PUS": "KOR", "CJU": "KOR",
    # 台湾
    "TPE": "TWN", "KHH": "TWN", "TSA": "TWN",
    # 米国
    "LAX": "USA", "JFK": "USA", "SFO": "USA", "ORD": "USA", "DFW": "USA",
    "ATL": "USA", "SEA": "USA", "IAD": "USA", "EWR": "USA", "HNL": "USA",
    # タイ
    "BKK": "THA", "DMK": "THA", "CNX": "THA", "HKT": "THA",
    # シンガポール
    "SIN": "SGP",
    # オーストラリア
    "SYD": "AUS", "MEL": "AUS", "BNE": "AUS", "PER": "AUS", "CBR": "AUS",
    # 香港
    "HKG": "HKG",
    # フィリピン
    "MNL": "PHL", "CEB": "PHL",
    # マレーシア
    "KUL": "MYS", "PEN": "MYS", "BKI": "MYS",
    # ドイツ
    "FRA": "DEU", "MUC": "DEU", "DUS": "DEU", "TXL": "DEU", "BER": "DEU",
    # 英国
    "LHR": "GBR", "LGW": "GBR", "MAN": "GBR", "STN": "GBR",
    # フランス
    "CDG": "FRA", "ORY": "FRA",
    # インド
    "DEL": "IND", "BOM": "IND", "MAA": "IND", "BLR": "IND", "CCU": "IND",
    # ベトナム
    "SGN": "VNM", "HAN": "VNM", "DAD": "VNM",
    # インドネシア
    "CGK": "IDN", "DPS": "IDN",
    # カナダ
    "YVR": "CAN", "YYZ": "CAN",
}

# ISO3 → 国名（表示用）
ISO3_TO_NAME = {
    "CHN": "中国", "KOR": "韓国", "TWN": "台湾", "USA": "米国",
    "THA": "タイ", "SGP": "シンガポール", "AUS": "オーストラリア",
    "HKG": "香港", "PHL": "フィリピン", "MYS": "マレーシア",
    "DEU": "ドイツ", "GBR": "英国", "FRA": "フランス",
    "IND": "インド", "VNM": "ベトナム", "IDN": "インドネシア",
    "CAN": "カナダ",
}

# 機材タイプ別座席数（標準的なコンフィグ）
AIRCRAFT_SEATS = {
    "B777": 360, "777": 360,
    "B787": 280, "787": 280,
    "A380": 500, "380": 500,
    "A350": 310, "350": 310,
    "A330": 270, "330": 270,
    "B767": 220, "767": 220,
    "A321": 185, "321": 185,
    "B737": 160, "737": 160,
    "A320": 150, "320": 150,
    "B747": 410, "747": 410,
    "A340": 280, "340": 280,
    "E190": 100, "E90": 100,
    "CRJ": 70,
    "ATR": 50,
    "DH8": 50,
}

# 機材不明時のデフォルト座席数
DEFAULT_SEATS = 180

# ハードコード容量データ（2019=100としたインデックス）
# COVID-19からの回復パターンを反映
CAPACITY_INDEX = {
    "CHN": {"2019": 100, "2020": 5, "2021": 8, "2022": 15, "2023": 65, "2024": 85, "2025": 92},
    "KOR": {"2019": 100, "2020": 8, "2021": 12, "2022": 35, "2023": 88, "2024": 105, "2025": 110},
    "TWN": {"2019": 100, "2020": 5, "2021": 8, "2022": 20, "2023": 75, "2024": 95, "2025": 100},
    "USA": {"2019": 100, "2020": 10, "2021": 25, "2022": 55, "2023": 85, "2024": 95, "2025": 100},
    "THA": {"2019": 100, "2020": 5, "2021": 10, "2022": 40, "2023": 80, "2024": 90, "2025": 95},
    "SGP": {"2019": 100, "2020": 8, "2021": 15, "2022": 45, "2023": 85, "2024": 95, "2025": 100},
    "AUS": {"2019": 100, "2020": 5, "2021": 10, "2022": 40, "2023": 78, "2024": 88, "2025": 93},
    "HKG": {"2019": 100, "2020": 5, "2021": 8, "2022": 25, "2023": 80, "2024": 95, "2025": 100},
    "PHL": {"2019": 100, "2020": 8, "2021": 12, "2022": 35, "2023": 75, "2024": 85, "2025": 90},
    "MYS": {"2019": 100, "2020": 5, "2021": 10, "2022": 30, "2023": 70, "2024": 82, "2025": 88},
    "DEU": {"2019": 100, "2020": 10, "2021": 20, "2022": 50, "2023": 80, "2024": 90, "2025": 95},
    "GBR": {"2019": 100, "2020": 10, "2021": 18, "2022": 48, "2023": 78, "2024": 88, "2025": 93},
    "FRA": {"2019": 100, "2020": 8, "2021": 15, "2022": 42, "2023": 75, "2024": 85, "2025": 90},
    "IND": {"2019": 100, "2020": 5, "2021": 12, "2022": 38, "2023": 80, "2024": 100, "2025": 115},
    "VNM": {"2019": 100, "2020": 5, "2021": 8, "2022": 30, "2023": 78, "2024": 92, "2025": 98},
}

# 2019年基準の週次座席数推定（OpenFlightsデータ+業界統計ベース）
BASELINE_WEEKLY_SEATS_2019 = {
    "CHN": 152_000,  # 中国→日本: 週約152,000席（2019年ピーク）
    "KOR": 125_000,  # 韓国→日本: 週約125,000席
    "TWN": 62_000,   # 台湾→日本: 週約62,000席
    "USA": 48_000,   # 米国→日本: 週約48,000席
    "THA": 32_000,   # タイ→日本: 週約32,000席
    "SGP": 18_000,   # シンガポール→日本: 週約18,000席
    "AUS": 22_000,   # オーストラリア→日本: 週約22,000席
    "HKG": 58_000,   # 香港→日本: 週約58,000席
    "PHL": 24_000,   # フィリピン→日本: 週約24,000席
    "MYS": 16_000,   # マレーシア→日本: 週約16,000席
    "DEU": 12_000,   # ドイツ→日本: 週約12,000席
    "GBR": 10_000,   # 英国→日本: 週約10,000席
    "FRA": 8_000,    # フランス→日本: 週約8,000席
    "IND": 6_000,    # インド→日本: 週約6,000席
    "VNM": 18_000,   # ベトナム→日本: 週約18,000席
}


class FlightSupplyClient:
    """航空路線の座席供給量を推定するクライアント

    データソース:
    1. OpenFlights.org routes.dat + airports.dat（静的ルートDB）
    2. フォールバック: ハードコードの容量インデックス（2019=100）
    """

    def __init__(self):
        self._airports = None    # IATA → {country_iso3, name, ...}
        self._routes = None      # 日本向けルートのリスト
        self._loaded = False

    # ========== データロード ==========

    def _load_data(self):
        """OpenFlightsデータをダウンロード・パース"""
        if self._loaded:
            return
        try:
            self._airports = self._fetch_airports()
            self._routes = self._fetch_routes_to_japan()
            self._loaded = True
            logger.info(
                "OpenFlightsデータ取得成功: 空港%d件, 日本向けルート%d件",
                len(self._airports), len(self._routes),
            )
        except Exception as e:
            logger.warning("OpenFlightsデータ取得失敗 → ハードコードにフォールバック: %s", e)
            self._airports = {}
            self._routes = []
            self._loaded = True

    def _fetch_airports(self) -> dict:
        """airports.dat をダウンロードしてIATA→情報のマップを構築

        CSVフォーマット（ヘッダなし）:
        0: Airport ID, 1: Name, 2: City, 3: Country, 4: IATA,
        5: ICAO, 6: Latitude, 7: Longitude, 8: Altitude, 9: Timezone,
        10: DST, 11: Tz database, 12: Type, 13: Source
        """
        resp = requests.get(
            OPENFLIGHTS_AIRPORTS_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        airports = {}
        reader = csv.reader(io.StringIO(resp.text))
        for row in reader:
            if len(row) < 8:
                continue
            iata = row[4].strip().strip('"')
            if not iata or iata == "\\N":
                continue
            airports[iata] = {
                "id": row[0].strip().strip('"'),
                "name": row[1].strip().strip('"'),
                "city": row[2].strip().strip('"'),
                "country": row[3].strip().strip('"'),
                "iata": iata,
                "icao": row[5].strip().strip('"'),
                "lat": _safe_float(row[6]),
                "lon": _safe_float(row[7]),
            }
        return airports

    def _fetch_routes_to_japan(self) -> list:
        """routes.dat から日本の空港を発着するルートを抽出

        CSVフォーマット（ヘッダなし）:
        0: Airline, 1: Airline ID, 2: Source airport, 3: Source airport ID,
        4: Destination airport, 5: Destination airport ID,
        6: Codeshare, 7: Stops, 8: Equipment
        """
        resp = requests.get(
            OPENFLIGHTS_ROUTES_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        japan_set = set(JAPAN_AIRPORTS)
        routes = []
        reader = csv.reader(io.StringIO(resp.text))
        for row in reader:
            if len(row) < 9:
                continue
            src = row[2].strip().strip('"')
            dst = row[4].strip().strip('"')
            equipment = row[8].strip().strip('"') if row[8].strip() != "\\N" else ""
            codeshare = row[6].strip().strip('"')

            # 日本着（インバウンド）または日本発（アウトバウンド）のルート
            is_inbound = dst in japan_set and src not in japan_set
            is_outbound = src in japan_set and dst not in japan_set

            if not (is_inbound or is_outbound):
                continue

            # 出発国のISO3を特定
            foreign_airport = src if is_inbound else dst
            origin_iso3 = self._resolve_country_iso3(foreign_airport)

            routes.append({
                "airline": row[0].strip().strip('"'),
                "src": src,
                "dst": dst,
                "codeshare": codeshare == "Y",
                "stops": _safe_int(row[7]),
                "equipment": equipment,
                "direction": "inbound" if is_inbound else "outbound",
                "foreign_airport": foreign_airport,
                "origin_iso3": origin_iso3,
            })

        return routes

    def _resolve_country_iso3(self, iata_code: str) -> Optional[str]:
        """IATAコードから国ISO3を解決"""
        # まずハードコードマッピングで検索
        if iata_code in AIRPORT_COUNTRY_ISO3:
            return AIRPORT_COUNTRY_ISO3[iata_code]
        # OpenFlightsデータで国名から推定
        if self._airports and iata_code in self._airports:
            country_name = self._airports[iata_code].get("country", "")
            return _country_name_to_iso3(country_name)
        return None

    # ========== 公開API ==========

    async def get_weekly_seats(self, origin_country: str, destination: str = "Japan") -> dict:
        """指定国→日本の週次推定座席数を返す

        Args:
            origin_country: ISO3国コード（例: "CHN", "KOR"）
            destination: 目的地（現在は "Japan" のみ対応）

        Returns:
            {
                "origin": "CHN",
                "destination": "Japan",
                "weekly_seats_estimated": 139840,
                "route_count": 42,
                "data_source": "openflights" | "hardcoded",
                "routes": [...],  # ルート詳細（openflightsの場合）
                "timestamp": "2026-04-02T..."
            }
        """
        iso3 = origin_country.upper().strip()
        self._load_data()

        # OpenFlightsデータでルート集計を試みる
        if self._routes:
            country_routes = [
                r for r in self._routes
                if r["origin_iso3"] == iso3 and r["direction"] == "inbound"
            ]
            if country_routes:
                total_seats = 0
                route_details = []
                for r in country_routes:
                    seats = self._estimate_seats_per_route(r)
                    total_seats += seats
                    route_details.append({
                        "airline": r["airline"],
                        "from": r["src"],
                        "to": r["dst"],
                        "equipment": r["equipment"],
                        "codeshare": r["codeshare"],
                        "estimated_weekly_seats": seats,
                    })

                return {
                    "origin": iso3,
                    "origin_name": ISO3_TO_NAME.get(iso3, iso3),
                    "destination": destination,
                    "weekly_seats_estimated": total_seats,
                    "route_count": len(country_routes),
                    "data_source": "openflights",
                    "routes": route_details,
                    "timestamp": datetime.utcnow().isoformat(),
                }

        # フォールバック: ハードコードデータ
        return self._hardcoded_weekly_seats(iso3, destination)

    async def detect_route_changes(self, origin_country: str, lookback_months: int = 6) -> list:
        """ルート変動を検出（容量インデックスの変化ベース）

        Args:
            origin_country: ISO3国コード
            lookback_months: 遡及月数（デフォルト6）

        Returns:
            変動イベントのリスト
        """
        iso3 = origin_country.upper().strip()
        cap_data = CAPACITY_INDEX.get(iso3)
        if not cap_data:
            return [{
                "type": "no_data",
                "message": f"{iso3}の容量データなし",
                "timestamp": datetime.utcnow().isoformat(),
            }]

        # 年次データから変動を検出
        changes = []
        years = sorted(cap_data.keys())
        for i in range(1, len(years)):
            prev_val = cap_data[years[i - 1]]
            curr_val = cap_data[years[i]]
            delta = curr_val - prev_val
            pct_change = (delta / prev_val * 100) if prev_val > 0 else 0

            if abs(pct_change) >= 20:  # 20%以上の変動を検出
                change_type = "increase" if delta > 0 else "decrease"
                severity = "major" if abs(pct_change) >= 50 else "moderate"
                changes.append({
                    "type": change_type,
                    "severity": severity,
                    "period": f"{years[i - 1]}→{years[i]}",
                    "from_index": prev_val,
                    "to_index": curr_val,
                    "change_pct": round(pct_change, 1),
                    "description": f"{ISO3_TO_NAME.get(iso3, iso3)}: "
                                   f"容量{years[i - 1]}→{years[i]}で{pct_change:+.1f}%変動",
                })

        # 現在年の推定（最新データとの比較）
        current_year = str(datetime.utcnow().year)
        if current_year in cap_data and len(years) >= 2:
            latest = cap_data[current_year]
            prev_year = str(int(current_year) - 1)
            if prev_year in cap_data:
                prev_val = cap_data[prev_year]
                yoy_change = ((latest - prev_val) / prev_val * 100) if prev_val > 0 else 0
                changes.append({
                    "type": "current_trend",
                    "period": f"{prev_year}→{current_year}",
                    "from_index": prev_val,
                    "to_index": latest,
                    "change_pct": round(yoy_change, 1),
                    "description": f"{ISO3_TO_NAME.get(iso3, iso3)}: "
                                   f"直近YoY {yoy_change:+.1f}%",
                })

        return changes

    async def get_historical_capacity_index(self, origin_country: str, base_year: int = 2019) -> list:
        """ハードコード容量インデックスの時系列データを返す

        Args:
            origin_country: ISO3国コード
            base_year: 基準年（デフォルト2019、=100）

        Returns:
            [{year, index, weekly_seats_estimated}, ...]
        """
        iso3 = origin_country.upper().strip()
        cap_data = CAPACITY_INDEX.get(iso3)
        if not cap_data:
            return []

        baseline_seats = BASELINE_WEEKLY_SEATS_2019.get(iso3, 10_000)
        result = []
        for year in sorted(cap_data.keys()):
            index_val = cap_data[year]
            estimated_seats = int(baseline_seats * index_val / 100)
            result.append({
                "year": int(year),
                "index": index_val,
                "base_year": base_year,
                "weekly_seats_estimated": estimated_seats,
                "origin": iso3,
                "origin_name": ISO3_TO_NAME.get(iso3, iso3),
            })

        return result

    async def get_current_capacity_ratio(self, origin_country: str) -> float:
        """現在の2019年比容量比率を返す

        Args:
            origin_country: ISO3国コード

        Returns:
            2019年比の比率（例: 0.92 = 2019年の92%）
            データなしの場合は 1.0（変化なしと仮定）
        """
        iso3 = origin_country.upper().strip()
        cap_data = CAPACITY_INDEX.get(iso3)
        if not cap_data:
            return 1.0

        # 現在年のデータがあればそれを使用、なければ最新年
        current_year = str(datetime.utcnow().year)
        if current_year in cap_data:
            return cap_data[current_year] / 100.0

        # 最新年のデータを使用
        latest_year = max(cap_data.keys())
        return cap_data[latest_year] / 100.0

    # ========== 内部メソッド ==========

    def _estimate_seats_per_route(self, route: dict) -> int:
        """ルートの週次座席数を推定

        推定ロジック:
        - 機材タイプから座席数を特定
        - OpenFlightsの1ルート = 1日1便と仮定（保守的）
        - 週7便 × 座席数 = 週次供給量
        - コードシェア便は0.3倍で計上（重複回避）
        """
        equipment_str = route.get("equipment", "")
        seats = self._parse_equipment_seats(equipment_str)
        weekly_frequency = 7  # 1日1便×7日

        # コードシェア便は重複カウント回避のため係数0.3
        if route.get("codeshare"):
            return int(seats * weekly_frequency * 0.3)

        return seats * weekly_frequency

    def _parse_equipment_seats(self, equipment_str: str) -> int:
        """機材文字列から座席数を推定

        equipment_str は "738 320" のようにスペース区切りの場合がある
        → 最初にマッチした機材の座席数を返す
        """
        if not equipment_str:
            return DEFAULT_SEATS

        # スペース区切りで複数機材が列挙されている場合がある
        tokens = equipment_str.replace("/", " ").split()
        for token in tokens:
            token_upper = token.upper().strip()
            # 完全一致
            if token_upper in AIRCRAFT_SEATS:
                return AIRCRAFT_SEATS[token_upper]
            # 部分一致（例: "73H" → "737"系列）
            for key, seats in AIRCRAFT_SEATS.items():
                if token_upper.startswith(key[:2]) and len(token_upper) >= 2:
                    return seats

        return DEFAULT_SEATS

    def _hardcoded_weekly_seats(self, iso3: str, destination: str) -> dict:
        """ハードコードデータから週次座席数を推定"""
        cap_data = CAPACITY_INDEX.get(iso3)
        baseline = BASELINE_WEEKLY_SEATS_2019.get(iso3)

        if cap_data and baseline:
            # 最新年のインデックスで2019年ベースラインを補正
            current_year = str(datetime.utcnow().year)
            latest_year = current_year if current_year in cap_data else max(cap_data.keys())
            ratio = cap_data[latest_year] / 100.0
            estimated = int(baseline * ratio)
        elif baseline:
            estimated = baseline
        else:
            estimated = 0

        return {
            "origin": iso3,
            "origin_name": ISO3_TO_NAME.get(iso3, iso3),
            "destination": destination,
            "weekly_seats_estimated": estimated,
            "route_count": 0,
            "data_source": "hardcoded",
            "capacity_index": cap_data.get(str(datetime.utcnow().year)) if cap_data else None,
            "routes": [],
            "timestamp": datetime.utcnow().isoformat(),
        }


# ========== ユーティリティ ==========

def _safe_float(val: str) -> Optional[float]:
    """安全にfloatに変換"""
    try:
        return float(val.strip().strip('"'))
    except (ValueError, AttributeError):
        return None


def _safe_int(val: str) -> int:
    """安全にintに変換"""
    try:
        return int(val.strip().strip('"'))
    except (ValueError, AttributeError):
        return 0


# 国名→ISO3の簡易マッピング
_COUNTRY_NAME_ISO3 = {
    "china": "CHN", "south korea": "KOR", "korea": "KOR",
    "taiwan": "TWN", "united states": "USA",
    "thailand": "THA", "singapore": "SGP", "australia": "AUS",
    "hong kong": "HKG", "philippines": "PHL", "malaysia": "MYS",
    "germany": "DEU", "united kingdom": "GBR",
    "france": "FRA", "india": "IND", "vietnam": "VNM", "viet nam": "VNM",
    "indonesia": "IDN", "canada": "CAN", "japan": "JPN",
    "russia": "RUS", "brazil": "BRA", "mexico": "MEX",
    "italy": "ITA", "spain": "ESP", "netherlands": "NLD",
    "turkey": "TUR", "saudi arabia": "SAU",
    "united arab emirates": "ARE",
    "new zealand": "NZL", "mongolia": "MNG", "myanmar": "MMR",
    "cambodia": "KHM", "laos": "LAO",
}


def _country_name_to_iso3(name: str) -> Optional[str]:
    """国名からISO3コードに変換（簡易版）"""
    if not name:
        return None
    return _COUNTRY_NAME_ISO3.get(name.lower().strip())


# ========== テスト用エントリポイント ==========

async def _test():
    """動作確認"""
    import asyncio
    client = FlightSupplyClient()

    print("=" * 60)
    print("フライト供給量クライアント テスト")
    print("=" * 60)

    # 主要国の週次座席数
    for iso3 in ["CHN", "KOR", "TWN", "USA", "THA"]:
        result = await client.get_weekly_seats(iso3)
        print(f"\n{ISO3_TO_NAME.get(iso3, iso3)}→日本:")
        print(f"  週次座席数: {result['weekly_seats_estimated']:,}")
        print(f"  ルート数: {result['route_count']}")
        print(f"  データソース: {result['data_source']}")

    # 容量比率
    print("\n--- 2019年比容量比率 ---")
    for iso3 in CAPACITY_INDEX:
        ratio = await client.get_current_capacity_ratio(iso3)
        print(f"  {ISO3_TO_NAME.get(iso3, iso3)}: {ratio:.0%}")

    # ルート変動検出
    print("\n--- ルート変動（中国） ---")
    changes = await client.detect_route_changes("CHN")
    for c in changes:
        print(f"  {c['description']}")

    # 履歴
    print("\n--- 韓国 容量インデックス履歴 ---")
    history = await client.get_historical_capacity_index("KOR")
    for h in history:
        print(f"  {h['year']}: index={h['index']}, 週次{h['weekly_seats_estimated']:,}席")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_test())
