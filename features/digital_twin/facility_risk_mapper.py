"""拠点リスクヒートマップ (B-4)
各拠点のGDACS災害アラート・SCRIリスクスコア・チョークポイント距離・在庫曝露額を算出。
地理的集中リスク（同一国資産集中・チョークポイント依存・台風経路）を分析。
"""
from datetime import datetime
from typing import Optional
import math

# --- InternalDataStore フォールバック ---
try:
    from pipeline.internal.internal_data_store import InternalDataStore
    _store = InternalDataStore()
except Exception:
    _store = None

# --- 座標データ ---
try:
    from pipeline.weather.openmeteo_client import LOCATION_COORDS
except ImportError:
    LOCATION_COORDS = {
        "tokyo": (35.68, 139.69), "osaka": (34.69, 135.50), "nagoya": (35.18, 136.91),
        "yokohama": (35.44, 139.64), "bangkok": (13.76, 100.50),
        "shenzhen": (22.54, 114.06), "shanghai": (31.23, 121.47),
        "singapore": (1.35, 103.82), "taipei": (25.03, 121.57),
    }

# --- チョークポイント ---
try:
    from features.route_risk.analyzer import CHOKEPOINTS
except ImportError:
    CHOKEPOINTS = {
        "suez": {"lat": 30.42, "lon": 32.35, "name": "Suez Canal"},
        "malacca": {"lat": 1.25, "lon": 103.82, "name": "Strait of Malacca"},
        "hormuz": {"lat": 26.57, "lon": 56.25, "name": "Strait of Hormuz"},
        "bab_el_mandeb": {"lat": 12.58, "lon": 43.47, "name": "Bab-el-Mandeb"},
        "panama": {"lat": 9.08, "lon": -79.68, "name": "Panama Canal"},
        "turkish_straits": {"lat": 41.12, "lon": 29.07, "name": "Turkish Straits"},
        "taiwan_strait": {"lat": 24.5, "lon": 119.5, "name": "Taiwan Strait"},
    }

# --- SCRIエンジン ---
def _get_risk_score(country: str) -> int:
    try:
        from scoring.engine import calculate_risk_score
        result = calculate_risk_score(
            supplier_id=f"fm_{country.lower()}",
            company_name=f"FM: {country}",
            country=country,
            location=country,
        )
        return result.overall_score
    except Exception:
        return 25


def _get_disaster_alerts(lat: float, lon: float, radius_km: int = 500) -> list:
    """GDACS災害アラートを取得（500km圏内）"""
    try:
        from scoring.disaster import get_disaster_score
        # get_disaster_scoreはlocation文字列を受け取る
        # 直接緯度経度でGDACS APIを叩く
        import requests
        url = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            alerts = []
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [0, 0])
                event_lon, event_lat = coords[0], coords[1]
                dist = _haversine(lat, lon, event_lat, event_lon)
                if dist <= radius_km:
                    alerts.append({
                        "event_type": props.get("eventtype", ""),
                        "event_name": props.get("eventname", ""),
                        "severity": props.get("alertlevel", ""),
                        "distance_km": round(dist),
                        "date": props.get("fromdate", ""),
                        "country": props.get("country", ""),
                    })
            return alerts
    except Exception:
        pass
    return []


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2地点間の距離(km) — Haversine公式"""
    R = 6371  # 地球半径(km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ========================================================================
# サンプル拠点データ（フォールバック）
# ========================================================================
SAMPLE_FACILITIES = [
    {
        "location_id": "PLANT-JP-NAGOYA",
        "name": "名古屋工場",
        "country": "Japan",
        "city": "Nagoya",
        "lat": 35.18, "lon": 136.91,
        "facility_type": "manufacturing",
        "inventory_value_jpy": 2_500_000_000,  # 25億円
        "annual_revenue_jpy": 15_000_000_000,  # 150億円
        "employees": 800,
        "primary_products": ["PROD-EV-01", "PROD-SENSOR-01"],
    },
    {
        "location_id": "PLANT-JP-OSAKA",
        "name": "大阪工場",
        "country": "Japan",
        "city": "Osaka",
        "lat": 34.69, "lon": 135.50,
        "facility_type": "manufacturing",
        "inventory_value_jpy": 1_800_000_000,
        "annual_revenue_jpy": 10_000_000_000,
        "employees": 500,
        "primary_products": ["PROD-BAT-01"],
    },
    {
        "location_id": "PLANT-TH-BANGKOK",
        "name": "バンコク工場",
        "country": "Thailand",
        "city": "Bangkok",
        "lat": 13.76, "lon": 100.50,
        "facility_type": "manufacturing",
        "inventory_value_jpy": 800_000_000,
        "annual_revenue_jpy": 5_000_000_000,
        "employees": 300,
        "primary_products": ["PROD-SENSOR-01"],
    },
    {
        "location_id": "WH-JP-YOKOHAMA",
        "name": "横浜物流センター",
        "country": "Japan",
        "city": "Yokohama",
        "lat": 35.44, "lon": 139.64,
        "facility_type": "warehouse",
        "inventory_value_jpy": 3_200_000_000,
        "annual_revenue_jpy": 0,
        "employees": 120,
        "primary_products": [],
    },
    {
        "location_id": "PLANT-CN-SHENZHEN",
        "name": "深圳工場",
        "country": "China",
        "city": "Shenzhen",
        "lat": 22.54, "lon": 114.06,
        "facility_type": "manufacturing",
        "inventory_value_jpy": 1_200_000_000,
        "annual_revenue_jpy": 8_000_000_000,
        "employees": 600,
        "primary_products": ["PROD-EV-01"],
    },
    {
        "location_id": "WH-SG-SINGAPORE",
        "name": "シンガポール中継倉庫",
        "country": "Singapore",
        "city": "Singapore",
        "lat": 1.35, "lon": 103.82,
        "facility_type": "warehouse",
        "inventory_value_jpy": 500_000_000,
        "annual_revenue_jpy": 0,
        "employees": 30,
        "primary_products": [],
    },
]

# 台風経路上の拠点（北西太平洋台風シーズン: 6-11月）
TYPHOON_PATH_REGIONS = [
    {"name": "北西太平洋台風帯", "lat_min": 10, "lat_max": 40, "lon_min": 120, "lon_max": 150,
     "season_months": [6, 7, 8, 9, 10, 11]},
    {"name": "南シナ海台風帯", "lat_min": 5, "lat_max": 25, "lon_min": 105, "lon_max": 125,
     "season_months": [5, 6, 7, 8, 9, 10, 11]},
]


def _get_facilities(locations: Optional[list] = None) -> list:
    """拠点データ取得"""
    if _store:
        try:
            facs = _store.get_facilities(locations)
            if facs:
                return facs
        except Exception:
            pass
    if locations:
        return [f for f in SAMPLE_FACILITIES if f["location_id"] in locations]
    return SAMPLE_FACILITIES


class FacilityRiskMapper:
    """拠点リスクヒートマップ生成エンジン

    各拠点の複合リスク（災害・国リスク・チョークポイント・在庫曝露）を算出し、
    地理的集中リスクを分析する。
    """

    def __init__(self, risk_cache: Optional[dict] = None):
        self._risk_cache = risk_cache or {}

    def _country_risk(self, country: str) -> int:
        if country in self._risk_cache:
            return self._risk_cache[country]
        score = _get_risk_score(country)
        self._risk_cache[country] = score
        return score

    def _nearest_chokepoint(self, lat: float, lon: float) -> dict:
        """最寄りチョークポイントの距離を算出"""
        nearest = None
        min_dist = float("inf")
        for cp_id, cp in CHOKEPOINTS.items():
            dist = _haversine(lat, lon, cp["lat"], cp["lon"])
            if dist < min_dist:
                min_dist = dist
                nearest = {
                    "chokepoint_id": cp_id,
                    "chokepoint_name": cp["name"],
                    "distance_km": round(dist),
                }
        return nearest or {"chokepoint_id": None, "distance_km": 99999}

    def _in_typhoon_path(self, lat: float, lon: float) -> list:
        """台風経路上にあるか判定"""
        paths = []
        for region in TYPHOON_PATH_REGIONS:
            if (region["lat_min"] <= lat <= region["lat_max"] and
                    region["lon_min"] <= lon <= region["lon_max"]):
                paths.append({
                    "region_name": region["name"],
                    "season_months": region["season_months"],
                })
        return paths

    def map_facility_risks(self, locations: Optional[list] = None) -> list:
        """全拠点のリスクマッピング

        Args:
            locations: 拠点IDリスト（Noneで全拠点）

        Returns:
            list: 各拠点のリスク情報
        """
        facilities = _get_facilities(locations)
        results = []

        for fac in facilities:
            lat = fac.get("lat", 0)
            lon = fac.get("lon", 0)
            country = fac.get("country", "")
            inventory_value = fac.get("inventory_value_jpy", 0)

            # 国リスクスコア
            country_risk = self._country_risk(country)

            # GDACS災害アラート（500km圏内）
            disaster_alerts = _get_disaster_alerts(lat, lon, 500)

            # 最寄りチョークポイント
            nearest_cp = self._nearest_chokepoint(lat, lon)

            # 台風経路判定
            typhoon_paths = self._in_typhoon_path(lat, lon)

            # リスク曝露額 = 在庫金額 × (リスクスコア/100)
            risk_exposure_jpy = int(inventory_value * country_risk / 100)

            # 災害アラートによる追加リスク
            disaster_risk_addon = 0
            for alert in disaster_alerts:
                if alert.get("severity") == "Red":
                    disaster_risk_addon += 20
                elif alert.get("severity") == "Orange":
                    disaster_risk_addon += 10
                elif alert.get("severity") == "Green":
                    disaster_risk_addon += 3

            # 複合リスクレベル
            composite_risk = min(100, country_risk + disaster_risk_addon)
            if composite_risk >= 70:
                risk_level = "CRITICAL"
            elif composite_risk >= 50:
                risk_level = "HIGH"
            elif composite_risk >= 30:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"

            results.append({
                "location_id": fac["location_id"],
                "name": fac.get("name", ""),
                "country": country,
                "city": fac.get("city", ""),
                "lat": lat,
                "lon": lon,
                "facility_type": fac.get("facility_type", ""),
                "country_risk": country_risk,
                "disaster_alerts_nearby": disaster_alerts,
                "disaster_alert_count": len(disaster_alerts),
                "nearest_chokepoint": nearest_cp,
                "distance_to_nearest_chokepoint_km": nearest_cp.get("distance_km", 99999),
                "typhoon_path_exposure": typhoon_paths,
                "inventory_value_jpy": inventory_value,
                "annual_revenue_jpy": fac.get("annual_revenue_jpy", 0),
                "risk_exposure_jpy": risk_exposure_jpy,
                "composite_risk_score": composite_risk,
                "risk_level": risk_level,
                "employees": fac.get("employees", 0),
            })

        # リスクレベル順ソート
        level_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        results.sort(key=lambda x: (level_order.get(x["risk_level"], 4), -x["risk_exposure_jpy"]))

        return {
            "total_facilities": len(results),
            "total_inventory_value_jpy": sum(r["inventory_value_jpy"] for r in results),
            "total_risk_exposure_jpy": sum(r["risk_exposure_jpy"] for r in results),
            "risk_summary": {
                "CRITICAL": sum(1 for r in results if r["risk_level"] == "CRITICAL"),
                "HIGH": sum(1 for r in results if r["risk_level"] == "HIGH"),
                "MEDIUM": sum(1 for r in results if r["risk_level"] == "MEDIUM"),
                "LOW": sum(1 for r in results if r["risk_level"] == "LOW"),
            },
            "facilities": results,
            "calculated_at": datetime.utcnow().isoformat(),
        }

    def identify_concentration_risk(self, locations: Optional[list] = None) -> dict:
        """地理的集中リスクの分析

        検出ルール:
        - 同一国に資産60%以上集中 → WARNING
        - 同一チョークポイント依存70%以上 → CRITICAL
        - 台風経路上の拠点資産合計 → SEASONAL_RISK

        Returns:
            dict: 集中リスク分析結果
        """
        risk_map = self.map_facility_risks(locations)
        facilities = risk_map.get("facilities", [])

        if not facilities:
            return {"error": "分析対象の拠点がありません"}

        total_value = sum(f["inventory_value_jpy"] for f in facilities)
        total_revenue = sum(f["annual_revenue_jpy"] for f in facilities)
        alerts = []

        # === 同一国集中度 ===
        country_values = {}
        country_revenues = {}
        country_facilities = {}
        for f in facilities:
            c = f["country"]
            country_values[c] = country_values.get(c, 0) + f["inventory_value_jpy"]
            country_revenues[c] = country_revenues.get(c, 0) + f["annual_revenue_jpy"]
            country_facilities.setdefault(c, []).append(f["location_id"])

        for country, value in country_values.items():
            share = value / max(total_value, 1)
            if share >= 0.60:
                alerts.append({
                    "type": "COUNTRY_CONCENTRATION",
                    "severity": "WARNING",
                    "country": country,
                    "asset_share_pct": round(share * 100, 1),
                    "asset_value_jpy": value,
                    "facilities": country_facilities[country],
                    "message": f"{country}に資産の{share*100:.1f}%が集中しています",
                    "recommendation": "資産の地理的分散を検討してください",
                })

        # === チョークポイント依存度 ===
        # 各拠点の最寄りチョークポイントごとに集計
        cp_values = {}
        cp_facilities = {}
        for f in facilities:
            cp = f["nearest_chokepoint"]
            cp_id = cp.get("chokepoint_id", "none")
            # 3000km以内のみ依存とみなす
            if cp.get("distance_km", 99999) <= 3000:
                cp_values[cp_id] = cp_values.get(cp_id, 0) + f["inventory_value_jpy"]
                cp_facilities.setdefault(cp_id, []).append(f["location_id"])

        for cp_id, value in cp_values.items():
            share = value / max(total_value, 1)
            cp_name = CHOKEPOINTS.get(cp_id, {}).get("name", cp_id)
            if share >= 0.70:
                alerts.append({
                    "type": "CHOKEPOINT_DEPENDENCY",
                    "severity": "CRITICAL",
                    "chokepoint": cp_name,
                    "chokepoint_id": cp_id,
                    "asset_share_pct": round(share * 100, 1),
                    "asset_value_jpy": value,
                    "facilities": cp_facilities[cp_id],
                    "message": f"{cp_name}に依存する資産が{share*100:.1f}%です",
                    "recommendation": "代替輸送ルートの確保、または拠点配置の見直しを検討してください",
                })

        # === 台風経路リスク ===
        typhoon_exposed_value = 0
        typhoon_exposed_revenue = 0
        typhoon_facilities = []
        for f in facilities:
            if f.get("typhoon_path_exposure"):
                typhoon_exposed_value += f["inventory_value_jpy"]
                typhoon_exposed_revenue += f["annual_revenue_jpy"]
                typhoon_facilities.append({
                    "location_id": f["location_id"],
                    "name": f["name"],
                    "value_jpy": f["inventory_value_jpy"],
                    "paths": [p["region_name"] for p in f["typhoon_path_exposure"]],
                })

        if typhoon_exposed_value > 0:
            typhoon_share = typhoon_exposed_value / max(total_value, 1)
            alerts.append({
                "type": "SEASONAL_RISK",
                "severity": "WARNING" if typhoon_share >= 0.5 else "INFO",
                "risk_type": "台風経路",
                "asset_share_pct": round(typhoon_share * 100, 1),
                "exposed_asset_value_jpy": typhoon_exposed_value,
                "exposed_revenue_jpy": typhoon_exposed_revenue,
                "affected_facilities": typhoon_facilities,
                "peak_months": "6月〜11月",
                "message": f"台風経路上の資産が{typhoon_share*100:.1f}%（{len(typhoon_facilities)}拠点）",
                "recommendation": "台風シーズン前の安全在庫積増し、BCP訓練の実施を推奨",
            })

        # HHI（国別集中度）
        shares = [v / max(total_value, 1) for v in country_values.values()]
        hhi = sum(s ** 2 for s in shares)

        # 集中度レベル判定
        if hhi > 0.40:
            concentration_level = "CRITICAL"
            concentration_message = "極めて高い地理的集中リスクがあります"
        elif hhi > 0.25:
            concentration_level = "HIGH"
            concentration_message = "高い地理的集中リスクがあります"
        elif hhi > 0.15:
            concentration_level = "MODERATE"
            concentration_message = "中程度の地理的集中です"
        else:
            concentration_level = "LOW"
            concentration_message = "地理的に分散されています"

        # アラートをseverity順にソート
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        alerts.sort(key=lambda x: severity_order.get(x["severity"], 3))

        return {
            "total_facilities": len(facilities),
            "total_asset_value_jpy": total_value,
            "total_annual_revenue_jpy": total_revenue,
            "geographic_hhi": round(hhi, 4),
            "concentration_level": concentration_level,
            "concentration_message": concentration_message,
            "country_distribution": {
                c: {
                    "asset_value_jpy": v,
                    "asset_share_pct": round(v / max(total_value, 1) * 100, 1),
                    "facility_count": len(country_facilities.get(c, [])),
                }
                for c, v in sorted(country_values.items(), key=lambda x: -x[1])
            },
            "alerts": alerts,
            "alert_count": {
                "CRITICAL": sum(1 for a in alerts if a["severity"] == "CRITICAL"),
                "WARNING": sum(1 for a in alerts if a["severity"] == "WARNING"),
                "INFO": sum(1 for a in alerts if a["severity"] == "INFO"),
            },
            "calculated_at": datetime.utcnow().isoformat(),
        }


# === 単独動作テスト ===
if __name__ == "__main__":
    import json
    mapper = FacilityRiskMapper(risk_cache={
        "Japan": 12, "Thailand": 35, "China": 48, "Singapore": 8,
    })

    print("=" * 60)
    print("【拠点リスクマップ】")
    risk_map = mapper.map_facility_risks()
    print(f"拠点数: {risk_map['total_facilities']}")
    print(f"在庫総額: ¥{risk_map['total_inventory_value_jpy']:,.0f}")
    print(f"リスク曝露総額: ¥{risk_map['total_risk_exposure_jpy']:,.0f}")
    print(f"リスクサマリ: {risk_map['risk_summary']}")
    for f in risk_map["facilities"]:
        print(f"  {f['name']} ({f['country']}): リスク={f['composite_risk_score']} [{f['risk_level']}]"
              f" 最寄CP={f['nearest_chokepoint']['chokepoint_name']} {f['distance_to_nearest_chokepoint_km']}km")

    print("\n" + "=" * 60)
    print("【地理的集中リスク分析】")
    conc = mapper.identify_concentration_risk()
    print(f"HHI: {conc['geographic_hhi']} ({conc['concentration_level']})")
    print(f"{conc['concentration_message']}")
    print(f"アラート: {conc['alert_count']}")
    for alert in conc["alerts"]:
        print(f"  [{alert['severity']}] {alert['message']}")
