"""実効飛行距離クライアント — Effective Flight Distance (EFD)
OpenFlights.org のルート・空港データから日本向け実効飛行距離を算出。
EFD = 加重平均ルート距離 × 乗り継ぎペナルティ × 頻度ペナルティ
取得失敗時はハードコードフォールバックを使用。
"""
import csv
import io
import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, List

import requests

logger = logging.getLogger(__name__)

# ========== 定数 ==========

OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OPENFLIGHTS_AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.4"}
REQUEST_TIMEOUT = 30

EARTH_RADIUS_KM = 6371.0

# 日本の主要空港 IATA コード
JAPAN_AIRPORTS = ["NRT", "HND", "KIX", "NGO", "CTS", "FUK", "OKA"]

# 機材タイプ別巡航速度（km/h）
CRUISE_SPEEDS = {
    "B777": 905, "777": 905,
    "B787": 900, "787": 900,
    "B737": 840, "737": 840,
    "A380": 920, "380": 920,
    "A321": 840, "321": 840,
    "A320": 840, "320": 840,
    "B747": 910, "747": 910,
    "A350": 910, "350": 910,
    "A330": 870, "330": 870,
    "B767": 860, "767": 860,
    "A340": 870, "340": 870,
    "E190": 830, "E90": 830,
    "DEFAULT": 860,
}

# 機材タイプ別標準座席数（週次座席推定用）
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
    "DEFAULT": 180,
}

# ISO2 → ISO3 マッピング（EFDフォールバックキーはISO2）
ISO2_TO_ISO3 = {
    "KR": "KOR", "CN": "CHN", "TW": "TWN", "HK": "HKG",
    "US": "USA", "AU": "AUS", "DE": "DEU", "GB": "GBR",
    "FR": "FRA", "TH": "THA", "SG": "SGP", "IN": "IND",
    "VN": "VNM", "ID": "IDN", "MY": "MYS", "PH": "PHL",
    "RU": "RUS", "TR": "TUR", "JP": "JPN", "CA": "CAN",
    "IT": "ITA", "ES": "ESP", "NL": "NLD", "BR": "BRA",
    "MX": "MEX", "SA": "SAU", "AE": "ARE", "NZ": "NZL",
}
ISO3_TO_ISO2 = {v: k for k, v in ISO2_TO_ISO3.items()}

# IATA → ISO3 マッピング（主要空港）
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
    "SYD": "AUS", "MEL": "AUS", "BNE": "AUS", "PER": "AUS",
    # 香港
    "HKG": "HKG",
    # フィリピン
    "MNL": "PHL", "CEB": "PHL",
    # マレーシア
    "KUL": "MYS", "PEN": "MYS", "BKI": "MYS",
    # ドイツ
    "FRA": "DEU", "MUC": "DEU", "DUS": "DEU", "BER": "DEU",
    # 英国
    "LHR": "GBR", "LGW": "GBR", "MAN": "GBR",
    # フランス
    "CDG": "FRA", "ORY": "FRA",
    # インド
    "DEL": "IND", "BOM": "IND", "MAA": "IND", "BLR": "IND", "CCU": "IND",
    # ベトナム
    "SGN": "VNM", "HAN": "VNM", "DAD": "VNM",
    # インドネシア
    "CGK": "IDN", "DPS": "IDN",
    # ロシア
    "SVO": "RUS", "DME": "RUS", "VVO": "RUS",
    # トルコ
    "IST": "TUR", "SAW": "TUR",
    # カナダ
    "YVR": "CAN", "YYZ": "CAN",
}

# ハードコードフォールバック（ISO2キー、単位km）
# OpenFlights取得失敗時に使用
EFD_FALLBACK = {
    "KR": 1200, "CN": 2800, "TW": 2500, "HK": 2900, "US": 13000, "AU": 11000,
    "DE": 13500, "GB": 13000, "FR": 13500, "TH": 6500, "SG": 7200, "IN": 8500,
    "VN": 5500, "ID": 7000, "MY": 7000, "PH": 4500, "RU": 12000, "TR": 12000,
}

# バリデーション用の既知フライト時間データ（時間単位）
# ソース: 各航空会社の公表フライト時間
VALIDATION_FLIGHT_HOURS = {
    "KR": 2.5,    # ソウル→東京 約2.5h
    "CN": 4.0,    # 北京/上海→東京 約3.5-4.5h
    "TW": 3.5,    # 台北→東京 約3.5h
    "HK": 4.5,    # 香港→東京 約4.5h
    "TH": 7.0,    # バンコク→東京 約7h
    "SG": 7.5,    # シンガポール→東京 約7.5h
    "VN": 5.5,    # ハノイ→東京 約5.5h
    "PH": 4.5,    # マニラ→東京 約4.5h
    "ID": 7.5,    # ジャカルタ→東京 約7.5h
    "MY": 7.0,    # クアラルンプール→東京 約7h
    "IN": 9.5,    # デリー→東京 約9.5h
    "AU": 9.5,    # シドニー→東京 約9.5h
    "US": 12.5,   # LA/SF→東京 約10-12h, NY→東京 約14h → 加重平均
    "DE": 12.0,   # フランクフルト→東京 約12h
    "GB": 12.0,   # ロンドン→東京 約12h
    "FR": 12.5,   # パリ→東京 約12.5h
    "RU": 10.0,   # モスクワ→東京 約10h
    "TR": 12.0,   # イスタンブール→東京 約12h
}


@dataclass
class EffectiveDistance:
    """実効飛行距離の算出結果"""
    source_country: str        # ISO2 or ISO3
    km_equivalent: float       # 加重平均ルート距離（km）
    connection_penalty: float  # 乗り継ぎペナルティ係数
    frequency_penalty: float   # 頻度ペナルティ係数
    final_efd: float           # 最終EFD（km相当）
    weekly_seats: int          # 週次座席数（推定）
    direct_route_ratio: float  # 直行便比率（0-1）
    data_source: str           # "openflights" | "fallback"
    timestamp: str             # ISO8601

    def to_dict(self) -> dict:
        return asdict(self)


class EffectiveFlightDistanceClient:
    """実効飛行距離（EFD）クライアント

    EFD = 加重平均ルート距離 × 乗り継ぎペナルティ × 頻度ペナルティ
    - 加重平均: 週次便数（座席数ベース）で重み付けした大圏距離
    - 乗り継ぎペナルティ: 1 + (1 - 直行便比率) * 0.4
    - 頻度ペナルティ: max(1.0, 2.0 - weekly_seats / 1000)

    データソース:
    1. OpenFlights.org routes.dat + airports.dat（空港座標 + ルートDB）
    2. フォールバック: ハードコードEFD値
    """

    def __init__(self):
        self._airports = None    # IATA → {lat, lon, country, ...}
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
            logger.warning("OpenFlightsデータ取得失敗 → フォールバック: %s", e)
            self._airports = {}
            self._routes = []
            self._loaded = True

    def _fetch_airports(self) -> dict:
        """airports.dat をダウンロードしてIATA→情報のマップを構築"""
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
            lat = _safe_float(row[6])
            lon = _safe_float(row[7])
            if lat is None or lon is None:
                continue
            airports[iata] = {
                "name": row[1].strip().strip('"'),
                "city": row[2].strip().strip('"'),
                "country": row[3].strip().strip('"'),
                "iata": iata,
                "lat": lat,
                "lon": lon,
            }
        return airports

    def _fetch_routes_to_japan(self) -> list:
        """routes.dat から日本の空港を発着するルートを抽出"""
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
            stops = _safe_int(row[7])

            # 日本着のルートのみ（インバウンド）
            is_inbound = dst in japan_set and src not in japan_set
            if not is_inbound:
                continue

            origin_iso3 = self._resolve_country_iso3(src)

            routes.append({
                "airline": row[0].strip().strip('"'),
                "src": src,
                "dst": dst,
                "codeshare": codeshare == "Y",
                "stops": stops,
                "equipment": equipment,
                "origin_iso3": origin_iso3,
            })

        return routes

    def _resolve_country_iso3(self, iata_code: str) -> Optional[str]:
        """IATAコードから国ISO3を解決"""
        if iata_code in AIRPORT_COUNTRY_ISO3:
            return AIRPORT_COUNTRY_ISO3[iata_code]
        if self._airports and iata_code in self._airports:
            country_name = self._airports[iata_code].get("country", "")
            return _country_name_to_iso3(country_name)
        return None

    # ========== 距離計算 ==========

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """2点間の大圏距離（km）"""
        rlat1, rlon1, rlat2, rlon2 = (
            math.radians(lat1), math.radians(lon1),
            math.radians(lat2), math.radians(lon2),
        )
        dlat = rlat2 - rlat1
        dlon = rlon2 - rlon1
        a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return EARTH_RADIUS_KM * c

    def _route_distance(self, src_iata: str, dst_iata: str) -> Optional[float]:
        """空港ペア間の大圏距離（km）"""
        if not self._airports:
            return None
        src_info = self._airports.get(src_iata)
        dst_info = self._airports.get(dst_iata)
        if not src_info or not dst_info:
            return None
        return self._haversine(
            src_info["lat"], src_info["lon"],
            dst_info["lat"], dst_info["lon"],
        )

    def _equipment_speed(self, equipment_str: str) -> float:
        """機材文字列から巡航速度を取得"""
        if not equipment_str:
            return CRUISE_SPEEDS["DEFAULT"]
        tokens = equipment_str.replace("/", " ").split()
        for token in tokens:
            t = token.upper().strip()
            if t in CRUISE_SPEEDS:
                return CRUISE_SPEEDS[t]
            for key, speed in CRUISE_SPEEDS.items():
                if key != "DEFAULT" and t.startswith(key[:2]) and len(t) >= 2:
                    return speed
        return CRUISE_SPEEDS["DEFAULT"]

    def _equipment_seats(self, equipment_str: str) -> int:
        """機材文字列から座席数を推定"""
        if not equipment_str:
            return AIRCRAFT_SEATS["DEFAULT"]
        tokens = equipment_str.replace("/", " ").split()
        for token in tokens:
            t = token.upper().strip()
            if t in AIRCRAFT_SEATS:
                return AIRCRAFT_SEATS[t]
            for key, seats in AIRCRAFT_SEATS.items():
                if key != "DEFAULT" and t.startswith(key[:2]) and len(t) >= 2:
                    return seats
        return AIRCRAFT_SEATS["DEFAULT"]

    # ========== 公開API ==========

    def calculate_effective_distance(self, source_country: str, destination: str = "Japan") -> EffectiveDistance:
        """実効飛行距離を算出

        Args:
            source_country: ISO2 or ISO3 国コード（例: "KR", "KOR", "US", "USA"）
            destination: 目的地（現在は "Japan" のみ）

        Returns:
            EffectiveDistance dataclass
        """
        # ISO3に正規化
        sc = source_country.upper().strip()
        iso3 = ISO2_TO_ISO3.get(sc, sc)
        iso2 = ISO3_TO_ISO2.get(iso3, sc)

        self._load_data()

        # OpenFlightsデータでルート解析を試みる
        if self._routes and self._airports:
            country_routes = [
                r for r in self._routes
                if r["origin_iso3"] == iso3
            ]
            if country_routes:
                return self._calculate_from_routes(country_routes, iso2, iso3)

        # フォールバック
        return self._fallback_efd(iso2, iso3)

    def _calculate_from_routes(self, routes: list, iso2: str, iso3: str) -> EffectiveDistance:
        """OpenFlightsルートデータからEFDを算出"""
        weighted_distance_sum = 0.0
        total_weight = 0.0
        total_seats = 0
        direct_count = 0
        total_count = 0

        for r in routes:
            dist = self._route_distance(r["src"], r["dst"])
            if dist is None or dist < 100:  # 100km未満は異常値として除外
                continue

            seats = self._equipment_seats(r.get("equipment", ""))
            # コードシェア便は0.3倍で計上
            weight = seats * 7  # 週7便想定
            if r.get("codeshare"):
                weight = int(weight * 0.3)

            weighted_distance_sum += dist * weight
            total_weight += weight
            total_seats += weight
            total_count += 1
            if r.get("stops", 0) == 0:
                direct_count += 1

        if total_weight == 0:
            return self._fallback_efd(iso2, iso3)

        # 加重平均距離
        km_equivalent = weighted_distance_sum / total_weight

        # 直行便比率
        direct_ratio = direct_count / total_count if total_count > 0 else 0.0

        # 乗り継ぎペナルティ: 1 + (1 - 直行便比率) * 0.4
        connection_penalty = 1.0 + (1.0 - direct_ratio) * 0.4

        # 頻度ペナルティ: max(1.0, 2.0 - weekly_seats / 1000)
        frequency_penalty = max(1.0, 2.0 - total_seats / 1000)

        # 最終EFD
        final_efd = km_equivalent * connection_penalty * frequency_penalty

        return EffectiveDistance(
            source_country=iso2,
            km_equivalent=round(km_equivalent, 1),
            connection_penalty=round(connection_penalty, 4),
            frequency_penalty=round(frequency_penalty, 4),
            final_efd=round(final_efd, 1),
            weekly_seats=total_seats,
            direct_route_ratio=round(direct_ratio, 4),
            data_source="openflights",
            timestamp=datetime.utcnow().isoformat(),
        )

    def _fallback_efd(self, iso2: str, iso3: str) -> EffectiveDistance:
        """ハードコードフォールバックからEFDを返す"""
        efd_val = EFD_FALLBACK.get(iso2, 10000)  # 不明国はデフォルト10,000km
        return EffectiveDistance(
            source_country=iso2,
            km_equivalent=float(efd_val),
            connection_penalty=1.0,
            frequency_penalty=1.0,
            final_efd=float(efd_val),
            weekly_seats=0,
            direct_route_ratio=0.0,
            data_source="fallback",
            timestamp=datetime.utcnow().isoformat(),
        )

    def validate(self) -> Dict[str, dict]:
        """既知のフライト時間と±20%で照合してバリデーション

        短距離路線（<4h）は離着陸・上昇降下で巡航速度に到達しない時間が
        大きいため、実効速度を600km/hに補正して比較する。

        Returns:
            {iso2: {"expected_km", "actual_efd", "ratio", "pass", "flight_hours"}}
        """
        results = {}
        for iso2, hours in VALIDATION_FLIGHT_HOURS.items():
            # 短距離フライトは実効速度が低い（離着陸・上昇降下の影響）
            if hours <= 4.0:
                effective_speed = 600  # 短距離の実効速度
            elif hours <= 6.0:
                effective_speed = 720  # 中距離
            else:
                effective_speed = CRUISE_SPEEDS["DEFAULT"]  # 長距離は巡航速度

            expected_km = hours * effective_speed

            efd_result = self.calculate_effective_distance(iso2)
            actual_efd = efd_result.final_efd

            ratio = actual_efd / expected_km if expected_km > 0 else 0
            passed = 0.8 <= ratio <= 1.2  # ±20%

            results[iso2] = {
                "flight_hours": hours,
                "expected_km": round(expected_km, 0),
                "actual_efd": actual_efd,
                "ratio": round(ratio, 3),
                "pass": passed,
                "data_source": efd_result.data_source,
            }

            status = "OK" if passed else "WARN"
            logger.info(
                "[%s] %s: 期待%.0fkm vs 実効%.0fkm (%.1f%%) [%s]",
                status, iso2, expected_km, actual_efd, ratio * 100,
                efd_result.data_source,
            )

        return results


# ========== ユーティリティ ==========

def _safe_float(val: str) -> Optional[float]:
    try:
        return float(val.strip().strip('"'))
    except (ValueError, AttributeError):
        return None


def _safe_int(val: str) -> int:
    try:
        return int(val.strip().strip('"'))
    except (ValueError, AttributeError):
        return 0


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
    "united arab emirates": "ARE", "new zealand": "NZL",
}


def _country_name_to_iso3(name: str) -> Optional[str]:
    if not name:
        return None
    return _COUNTRY_NAME_ISO3.get(name.lower().strip())


# ========== テスト用エントリポイント ==========

def _test():
    """動作確認"""
    client = EffectiveFlightDistanceClient()

    print("=" * 60)
    print("実効飛行距離（EFD）クライアント テスト")
    print("=" * 60)

    # 主要国のEFD算出
    test_countries = ["KR", "CN", "TW", "US", "TH", "SG", "AU", "DE", "GB", "VN"]
    for iso2 in test_countries:
        result = client.calculate_effective_distance(iso2)
        print(f"\n{iso2}→Japan:")
        print(f"  加重平均距離: {result.km_equivalent:,.0f} km")
        print(f"  乗り継ぎペナルティ: {result.connection_penalty:.4f}")
        print(f"  頻度ペナルティ: {result.frequency_penalty:.4f}")
        print(f"  最終EFD: {result.final_efd:,.0f} km")
        print(f"  週次座席数: {result.weekly_seats:,}")
        print(f"  直行便比率: {result.direct_route_ratio:.1%}")
        print(f"  データソース: {result.data_source}")

    # バリデーション
    print("\n" + "=" * 60)
    print("バリデーション（±20%照合）")
    print("=" * 60)
    validation = client.validate()
    pass_count = sum(1 for v in validation.values() if v["pass"])
    total = len(validation)
    print(f"\n合格: {pass_count}/{total}")
    for iso2, v in sorted(validation.items(), key=lambda x: x[1]["ratio"]):
        status = "OK  " if v["pass"] else "WARN"
        print(
            f"  [{status}] {iso2}: "
            f"期待{v['expected_km']:,.0f}km vs 実効{v['actual_efd']:,.0f}km "
            f"({v['ratio']:.1%}) [{v['data_source']}]"
        )


if __name__ == "__main__":
    _test()
