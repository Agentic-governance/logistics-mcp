"""輸送リスク分析エンジン (SCRI v1.1.0 ROLE-C)

TMS輸送計画 × SCRIチョークポイントリスクを統合した輸送リスク分析。
今後90日のスケジュール便についてルートリスク評価、コスト試算、
ネットワーク最適化を行う。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2, inf
from typing import Optional

from features.route_risk.analyzer import (
    RouteRiskAnalyzer,
    CHOKEPOINTS,
    PORT_COORDS,
    SEA_ROUTES,
    _haversine,
    _resolve_port,
    _get_region,
)
from features.route_risk.enhanced_analyzer import (
    EnhancedRouteAnalyzer,
    SEASONAL_ADJUSTMENTS,
    ALTERNATIVE_ROUTES,
    CARGO_TYPE_MULTIPLIERS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数: チョークポイント拡張データ
# ---------------------------------------------------------------------------

# 6大チョークポイント定義（仕様に明示されたもの）
MAJOR_CHOKEPOINTS = {
    "suez": {
        "name": "スエズ運河",
        "name_en": "Suez Canal",
        "lat": 30.42, "lon": 32.35,
        "passage_probability": 0.85,  # 通航確率（直近情勢ベース）
        "delay_days_if_blocked": 12,
        "insurance_surcharge_pct": 0.15,
    },
    "malacca": {
        "name": "マラッカ海峡",
        "name_en": "Strait of Malacca",
        "lat": 1.25, "lon": 103.82,
        "passage_probability": 0.95,
        "delay_days_if_blocked": 3,
        "insurance_surcharge_pct": 0.05,
    },
    "hormuz": {
        "name": "ホルムズ海峡",
        "name_en": "Strait of Hormuz",
        "lat": 26.57, "lon": 56.25,
        "passage_probability": 0.88,
        "delay_days_if_blocked": 7,
        "insurance_surcharge_pct": 0.12,
    },
    "panama": {
        "name": "パナマ運河",
        "name_en": "Panama Canal",
        "lat": 9.08, "lon": -79.68,
        "passage_probability": 0.90,
        "delay_days_if_blocked": 8,
        "insurance_surcharge_pct": 0.08,
    },
    "taiwan_strait": {
        "name": "台湾海峡",
        "name_en": "Taiwan Strait",
        "lat": 24.5, "lon": 119.5,
        "passage_probability": 0.92,
        "delay_days_if_blocked": 2,
        "insurance_surcharge_pct": 0.10,
    },
    "bab_el_mandeb": {
        "name": "バブ・エル・マンデブ海峡",
        "name_en": "Bab el-Mandeb",
        "lat": 12.58, "lon": 43.47,
        "passage_probability": 0.70,
        "delay_days_if_blocked": 12,
        "insurance_surcharge_pct": 0.20,
    },
}

# 国→代表港マッピング
COUNTRY_PORT_MAP = {
    "JP": "tokyo", "CN": "shanghai", "KR": "busan",
    "TW": "kaohsiung", "SG": "singapore", "VN": "ho_chi_minh",
    "TH": "bangkok", "ID": "jakarta", "IN": "mumbai",
    "AE": "dubai", "NL": "rotterdam", "DE": "hamburg",
    "US": "los_angeles", "EG": "suez_port",
    # 日本語国名もサポート
    "日本": "tokyo", "中国": "shanghai", "韓国": "busan",
    "台湾": "kaohsiung", "シンガポール": "singapore",
    "ベトナム": "ho_chi_minh", "タイ": "bangkok",
    "インドネシア": "jakarta", "インド": "mumbai",
    "UAE": "dubai", "オランダ": "rotterdam", "ドイツ": "hamburg",
    "アメリカ": "los_angeles", "エジプト": "suez_port",
}

# 基本運賃テーブル（仕様から）
BASE_FREIGHT_RATES = {
    "sea": {
        "rate_per_teu": 3500,        # USD/TEU (20ftコンテナ) 中央値
        "rate_range": (2000, 5000),
        "unit": "TEU",
    },
    "air": {
        "rate_per_kg": 6.0,          # USD/kg 中央値
        "rate_range": (4, 8),
        "unit": "kg",
    },
    "truck": {
        "rate_per_km": 2.25,         # USD/km 中央値
        "rate_range": (1.5, 3.0),
        "unit": "km",
    },
    "rail": {
        "rate_per_teu": 4000,        # USD/TEU (中欧鉄道) 中央値
        "rate_range": (3000, 5000),
        "unit": "TEU",
    },
}

# リスクベース保険率テーブル (リスクスコア帯→保険料率%)
RISK_INSURANCE_RATES = {
    (0, 20):   0.05,   # 最小リスク: 貨物価値の0.05%
    (20, 40):  0.10,
    (40, 60):  0.20,
    (60, 80):  0.40,
    (80, 101): 0.80,   # 最高リスク: 貨物価値の0.80%
}

# 港湾混雑サーチャージ概算 (USD/TEU)
PORT_CONGESTION_SURCHARGES = {
    "shanghai": 350, "shenzhen": 300, "ningbo": 250,
    "singapore": 150, "rotterdam": 200, "hamburg": 180,
    "los_angeles": 400, "long_beach": 380,
    "tokyo": 100, "yokohama": 100, "kobe": 80,
    "nagoya": 80, "osaka": 80,
    "busan": 120, "kaohsiung": 100,
    "mumbai": 200, "dubai": 150,
    "ho_chi_minh": 130, "bangkok": 140, "jakarta": 160,
}

# 季節性リスクイベント (月→影響地域)
SEASONAL_RISK_EVENTS = {
    "typhoon": {
        "months": [6, 7, 8, 9, 10, 11],
        "affected_regions": ["east_asia"],
        "risk_delta": 20,
        "description": "台風シーズン",
    },
    "monsoon": {
        "months": [6, 7, 8, 9],
        "affected_regions": ["south_asia", "southeast_asia"],
        "risk_delta": 15,
        "description": "モンスーン",
    },
    "winter_storm": {
        "months": [12, 1, 2],
        "affected_regions": ["europe", "us_east"],
        "risk_delta": 10,
        "description": "冬季暴風",
    },
    "fog_season": {
        "months": [11, 12, 1, 2],
        "affected_regions": ["east_asia"],
        "risk_delta": 5,
        "description": "濃霧シーズン",
    },
}

# 為替レート (USD→JPY) — 静的フォールバック
_DEFAULT_USD_JPY = 150.0


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _resolve_country_port(country_or_port: str) -> Optional[str]:
    """国名/国コード/港名 → PORT_COORDS のキーに解決"""
    key = country_or_port.strip()
    # まず直接PORT_COORDSにあるか
    if key.lower().replace(" ", "_") in PORT_COORDS:
        return key.lower().replace(" ", "_")
    # 国コード/国名→代表港
    if key.upper() in COUNTRY_PORT_MAP:
        return COUNTRY_PORT_MAP[key.upper()]
    if key in COUNTRY_PORT_MAP:
        return COUNTRY_PORT_MAP[key]
    # 部分一致
    for name in PORT_COORDS:
        if key.lower() in name or name in key.lower():
            return name
    return None


def _get_insurance_rate(risk_score: float) -> float:
    """リスクスコアに基づく保険料率を返す"""
    for (lo, hi), rate in RISK_INSURANCE_RATES.items():
        if lo <= risk_score < hi:
            return rate
    return 0.40  # デフォルト


def _get_usd_jpy() -> float:
    """USD/JPY レートを取得（フォールバック付き）。0や負値はデフォルトに置換。"""
    try:
        from pipeline.economic.exchange_rate_client import get_exchange_rate
        result = get_exchange_rate("USD", "JPY")
        if result and result.get("rate"):
            rate = float(result["rate"])
            if rate > 0:
                return rate
            logger.warning("USD/JPY レートが不正値 (%s)、デフォルト値を使用", rate)
    except Exception:
        pass
    return _DEFAULT_USD_JPY


def _get_month_from_date(date_str: Optional[str]) -> int:
    """日付文字列から月を抽出。None なら現在月。"""
    if date_str:
        try:
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            return dt.month
        except (ValueError, TypeError):
            pass
    return datetime.utcnow().month


def _identify_chokepoints_on_route(origin_port: str, dest_port: str) -> list:
    """出発港→目的港の航路上のチョークポイントIDリストを特定"""
    origin_coords = PORT_COORDS.get(origin_port)
    dest_coords = PORT_COORDS.get(dest_port)
    if not origin_coords or not dest_coords:
        return []

    origin_region = _get_region(*origin_coords)
    dest_region = _get_region(*dest_coords)

    route_key = (origin_region, dest_region)
    reverse_key = (dest_region, origin_region)
    routes = SEA_ROUTES.get(route_key) or SEA_ROUTES.get(reverse_key)

    if routes:
        return routes.get("primary", [])

    # フォールバック: 距離ベースでチョークポイント通過を推定
    chokepoints = []
    for cp_id, cp_data in MAJOR_CHOKEPOINTS.items():
        cp_lat, cp_lon = cp_data["lat"], cp_data["lon"]
        d_origin = _haversine(*origin_coords, cp_lat, cp_lon)
        d_dest = _haversine(*dest_coords, cp_lat, cp_lon)
        d_total = _haversine(*origin_coords, *dest_coords)
        # チョークポイントが出発地〜目的地の経路上（距離和が直線距離の1.5倍以内）
        if (d_origin + d_dest) < d_total * 1.5 and d_total > 1000:
            chokepoints.append(cp_id)

    return chokepoints


# ---------------------------------------------------------------------------
# メインクラス
# ---------------------------------------------------------------------------

class TransportRiskAnalyzer:
    """輸送リスク分析エンジン

    TMS輸送計画とSCRIチョークポイントリスクを統合し、
    スケジュール便のリスク評価・コスト試算・ネットワーク最適化を提供。
    """

    def __init__(self):
        self._route_analyzer = RouteRiskAnalyzer()
        self._enhanced_analyzer = EnhancedRouteAnalyzer()

    # ------------------------------------------------------------------
    # C-1-1: スケジュール便リスク分析
    # ------------------------------------------------------------------

    def analyze_scheduled_shipments(
        self,
        shipments: list,
        lookahead_days: int = 90,
    ) -> list:
        """今後 lookahead_days 日の予定輸送便のリスクを一括分析。

        Args:
            shipments: 輸送便リスト。各要素は dict:
                {
                    "shipment_id": str,
                    "origin": str,          # 国コード/港名/国名
                    "destination": str,
                    "departure_date": str,   # ISO形式 (optional)
                    "cargo_value_jpy": float, # (optional)
                    "transport_mode": str,   # "sea"/"air"/"truck"/"rail" (optional)
                }
            lookahead_days: 先読み日数 (デフォルト90日)

        Returns:
            リスク評価結果リスト: [{
                shipment_id, origin, destination, planned_route,
                chokepoints_on_route, route_risk_score,
                alternative_route, recommendation
            }]
        """
        results = []
        cutoff = datetime.utcnow() + timedelta(days=lookahead_days)

        for shipment in shipments:
            try:
                result = self._analyze_single_shipment(shipment, cutoff)
                results.append(result)
            except Exception as e:
                logger.warning(
                    "輸送便 %s の分析に失敗: %s",
                    shipment.get("shipment_id", "?"), e,
                )
                results.append({
                    "shipment_id": shipment.get("shipment_id", "unknown"),
                    "error": str(e),
                    "recommendation": "MONITOR",
                    "timestamp": datetime.utcnow().isoformat(),
                })

        # リスクスコア降順でソート（高リスク便を優先）
        results.sort(
            key=lambda x: x.get("route_risk_score", 0),
            reverse=True,
        )

        return results

    def _analyze_single_shipment(self, shipment: dict, cutoff: datetime) -> dict:
        """単一輸送便のリスク分析"""
        sid = shipment.get("shipment_id", "unknown")
        origin_raw = shipment.get("origin", "")
        dest_raw = shipment.get("destination", "")
        departure = shipment.get("departure_date")
        cargo_value = shipment.get("cargo_value_jpy", 0)
        mode = shipment.get("transport_mode", "sea")

        # 日付フィルタ: lookahead_days 以内のみ
        if departure:
            try:
                dep_dt = datetime.fromisoformat(
                    str(departure).replace("Z", "+00:00")
                )
                if dep_dt.replace(tzinfo=None) > cutoff:
                    return {
                        "shipment_id": sid,
                        "skipped": True,
                        "reason": f"出発日 ({departure}) が先読み期間外",
                        "recommendation": "PROCEED",
                        "route_risk_score": 0,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
            except (ValueError, TypeError):
                pass

        # 港名解決
        origin_port = _resolve_country_port(origin_raw) or origin_raw
        dest_port = _resolve_country_port(dest_raw) or dest_raw

        # 座標解決不能時の警告
        data_quality_warning = None
        if not PORT_COORDS.get(origin_port):
            logger.warning("座標解決不能: origin=%s (raw=%s)", origin_port, origin_raw)
            data_quality_warning = f"出発地 '{origin_raw}' の座標を解決できません"
        if not PORT_COORDS.get(dest_port):
            logger.warning("座標解決不能: dest=%s (raw=%s)", dest_port, dest_raw)
            dw = f"目的地 '{dest_raw}' の座標を解決できません"
            data_quality_warning = (
                f"{data_quality_warning}; {dw}" if data_quality_warning else dw
            )

        # チョークポイント特定
        chokepoints = _identify_chokepoints_on_route(origin_port, dest_port)

        # 各チョークポイントのリスクスコア取得
        cp_details = []
        max_cp_risk = 0
        for cp_id in chokepoints:
            cp_risk = self._route_analyzer.get_chokepoint_risk(cp_id)
            risk_score = cp_risk.get("risk_score", 0)
            max_cp_risk = max(max_cp_risk, risk_score)
            cp_details.append({
                "id": cp_id,
                "name": MAJOR_CHOKEPOINTS.get(cp_id, {}).get("name_en", cp_id),
                "name_ja": MAJOR_CHOKEPOINTS.get(cp_id, {}).get("name", cp_id),
                "risk_score": risk_score,
                "passage_probability": MAJOR_CHOKEPOINTS.get(
                    cp_id, {}
                ).get("passage_probability", 1.0),
            })

        # 季節性リスク調整
        month = _get_month_from_date(departure)
        seasonal_delta = self._get_seasonal_delta(origin_port, dest_port, month)

        # 総合リスクスコア
        route_risk_score = min(100, max(0, max_cp_risk + seasonal_delta))

        # 代替ルート提案
        alternative_route = self._find_best_alternative(chokepoints, route_risk_score)

        # レコメンデーション判定
        recommendation = self._determine_recommendation(
            route_risk_score, chokepoints, cargo_value
        )

        # 計画ルート説明文
        planned_route = self._describe_route(origin_port, dest_port, chokepoints, mode)

        return {
            "shipment_id": sid,
            "origin": origin_raw,
            "destination": dest_raw,
            "origin_port": origin_port,
            "destination_port": dest_port,
            "transport_mode": mode,
            "departure_date": departure,
            "planned_route": planned_route,
            "chokepoints_on_route": cp_details,
            "chokepoint_count": len(chokepoints),
            "route_risk_score": round(route_risk_score, 1),
            "risk_level": self._risk_level(route_risk_score),
            "seasonal_adjustment": round(seasonal_delta, 1),
            "month": month,
            "alternative_route": alternative_route,
            "recommendation": recommendation,
            "data_quality_warning": data_quality_warning,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # C-1-2: 輸送コスト（リスク込み）算出
    # ------------------------------------------------------------------

    def calculate_transport_cost_with_risk(
        self,
        origin_country: str,
        dest_country: str,
        cargo_value_jpy: float,
        transport_mode: str = "sea",
    ) -> dict:
        """リスク加味した輸送コスト全要素を算出。

        Args:
            origin_country: 出発国コード/名称
            dest_country: 目的国コード/名称
            cargo_value_jpy: 貨物価額 (JPY)
            transport_mode: "sea" / "air" / "truck" / "rail"

        Returns:
            {
                base_freight, insurance_premium, chokepoint_reroute_cost,
                port_congestion_surcharge, total_cost_jpy, total_cost_usd,
                cost_breakdown, risk_factors
            }
        """
        try:
            usd_jpy = _get_usd_jpy()
            cargo_value_usd = cargo_value_jpy / usd_jpy

            # 港解決
            origin_port = _resolve_country_port(origin_country) or origin_country
            dest_port = _resolve_country_port(dest_country) or dest_country

            origin_coords = PORT_COORDS.get(origin_port)
            dest_coords = PORT_COORDS.get(dest_port)

            if not origin_coords or not dest_coords:
                return {
                    "error": f"港の座標を解決できません: {origin_country} / {dest_country}",
                    "timestamp": datetime.utcnow().isoformat(),
                }

            distance_km = _haversine(*origin_coords, *dest_coords)

            # --- 1. 基本運賃 ---
            base_freight_usd = self._calc_base_freight(
                transport_mode, distance_km
            )

            # --- 2. 保険料（リスクベース） ---
            chokepoints = _identify_chokepoints_on_route(origin_port, dest_port)
            max_risk = 0
            cp_risks = []
            for cp_id in chokepoints:
                cp_risk = self._route_analyzer.get_chokepoint_risk(cp_id)
                score = cp_risk.get("risk_score", 0)
                max_risk = max(max_risk, score)
                cp_risks.append({
                    "chokepoint": cp_id,
                    "risk_score": score,
                })

            insurance_rate = _get_insurance_rate(max_risk)
            insurance_premium_usd = cargo_value_usd * (insurance_rate / 100)

            # チョークポイント追加保険
            # insurance_surcharge_pct は % 表記（例: 0.15 = 0.15%）なので /100 で小数に変換
            cp_insurance_surcharge = 0.0
            for cp_id in chokepoints:
                cp_data = MAJOR_CHOKEPOINTS.get(cp_id, {})
                surcharge_pct = cp_data.get("insurance_surcharge_pct", 0)
                # 通過不可確率 × サーチャージ率（% → 小数変換）
                fail_prob = 1.0 - cp_data.get("passage_probability", 1.0)
                cp_insurance_surcharge += cargo_value_usd * (surcharge_pct / 100) * fail_prob

            total_insurance_usd = insurance_premium_usd + cp_insurance_surcharge

            # --- 3. チョークポイント迂回コスト（確率的） ---
            reroute_expected_cost_usd = 0.0
            reroute_details = []
            for cp_id in chokepoints:
                cp_data = MAJOR_CHOKEPOINTS.get(cp_id, {})
                fail_prob = 1.0 - cp_data.get("passage_probability", 1.0)
                # ALTERNATIVE_ROUTES から迂回コスト取得
                cp_name = CHOKEPOINTS.get(cp_id, {}).get("name", "")
                alt_info = ALTERNATIVE_ROUTES.get(cp_name)
                if not alt_info:
                    # 部分一致検索
                    for key, val in ALTERNATIVE_ROUTES.items():
                        if cp_name.lower() in key.lower() or key.lower() in cp_name.lower():
                            alt_info = val
                            break
                if alt_info:
                    reroute_cost = alt_info["extra_cost_usd"]
                    expected_cost = reroute_cost * fail_prob
                    reroute_expected_cost_usd += expected_cost
                    reroute_details.append({
                        "chokepoint": cp_id,
                        "name": cp_name,
                        "failure_probability": round(fail_prob, 3),
                        "reroute_cost_if_blocked_usd": reroute_cost,
                        "expected_cost_usd": round(expected_cost, 2),
                        "alternative": alt_info["alt"],
                        "extra_days": alt_info["extra_days"],
                    })

            # --- 4. 港湾混雑サーチャージ ---
            origin_surcharge = PORT_CONGESTION_SURCHARGES.get(origin_port, 0)
            dest_surcharge = PORT_CONGESTION_SURCHARGES.get(dest_port, 0)

            # リアルタイム混雑データ取得を試みる
            try:
                from pipeline.infrastructure.port_congestion_client import (
                    get_port_congestion_risk,
                )
                for port_name, surcharge_ref in [
                    (origin_port, "origin"), (dest_port, "dest")
                ]:
                    congestion = get_port_congestion_risk(port_name)
                    if congestion and congestion.get("score", 0) > 50:
                        # 混雑度が高い場合はサーチャージ加算
                        multiplier = 1.0 + (congestion["score"] - 50) / 100
                        if surcharge_ref == "origin":
                            origin_surcharge = int(origin_surcharge * multiplier)
                        else:
                            dest_surcharge = int(dest_surcharge * multiplier)
            except Exception:
                pass  # フォールバック: 静的データ使用

            port_surcharge_usd = origin_surcharge + dest_surcharge

            # --- 合計 ---
            total_cost_usd = (
                base_freight_usd
                + total_insurance_usd
                + reroute_expected_cost_usd
                + port_surcharge_usd
            )
            total_cost_jpy = total_cost_usd * usd_jpy

            return {
                "origin": origin_country,
                "destination": dest_country,
                "transport_mode": transport_mode,
                "distance_km": round(distance_km),
                "cargo_value_jpy": cargo_value_jpy,
                "cargo_value_usd": round(cargo_value_usd, 2),
                "usd_jpy_rate": usd_jpy,
                "cost_breakdown": {
                    "base_freight_usd": round(base_freight_usd, 2),
                    "insurance_premium_usd": round(insurance_premium_usd, 2),
                    "chokepoint_insurance_surcharge_usd": round(
                        cp_insurance_surcharge, 2
                    ),
                    "total_insurance_usd": round(total_insurance_usd, 2),
                    "reroute_expected_cost_usd": round(
                        reroute_expected_cost_usd, 2
                    ),
                    "port_congestion_surcharge_usd": port_surcharge_usd,
                    "origin_port_surcharge": origin_surcharge,
                    "dest_port_surcharge": dest_surcharge,
                },
                "reroute_details": reroute_details,
                "chokepoint_risks": cp_risks,
                "route_risk_score": max_risk,
                "insurance_rate_pct": insurance_rate,
                "total_cost_usd": round(total_cost_usd, 2),
                "total_cost_jpy": round(total_cost_jpy),
                "risk_adjusted_cost_ratio": round(
                    total_cost_usd / base_freight_usd, 3
                ) if base_freight_usd > 0 else None,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("輸送コスト算出に失敗: %s", e)
            return {
                "error": str(e),
                "origin": origin_country,
                "destination": dest_country,
                "timestamp": datetime.utcnow().isoformat(),
            }

    # ------------------------------------------------------------------
    # C-1-3: 輸送ネットワーク最適化
    # ------------------------------------------------------------------

    def optimize_transport_network(
        self,
        locations: list,
        demand_matrix: dict,
    ) -> dict:
        """全拠点間の輸送ネットワークをリスク×コスト×リードタイムで最適化。

        Args:
            locations: 拠点リスト ["JP", "CN", "SG", "DE", ...]
            demand_matrix: 需要行列
                {"JP->CN": {"volume_teu": 100, "cargo_value_jpy": 5e8}, ...}

        Returns:
            {
                optimal_routes: [{origin, dest, route, cost, risk, lead_time}],
                network_risk_score: float,
                total_cost_jpy: float,
                recommendations: [str]
            }
        """
        try:
            month = datetime.utcnow().month
            optimal_routes = []
            total_cost_jpy = 0
            all_risks = []

            # 全需要ペアについて最適ルート選択
            for lane_key, demand in demand_matrix.items():
                parts = lane_key.split("->")
                if len(parts) != 2:
                    continue
                origin, dest = parts[0].strip(), parts[1].strip()

                volume_teu = demand.get("volume_teu", 1)
                cargo_value = demand.get("cargo_value_jpy", 0)

                # 各輸送モードの評価
                candidates = self._evaluate_transport_candidates(
                    origin, dest, cargo_value, volume_teu, month
                )

                if not candidates:
                    optimal_routes.append({
                        "lane": lane_key,
                        "origin": origin,
                        "destination": dest,
                        "error": "候補ルートなし",
                    })
                    continue

                # 3軸スコア（リスク、コスト、リードタイム）で最適選択
                best = min(candidates, key=lambda c: c["composite_score"])

                optimal_routes.append({
                    "lane": lane_key,
                    "origin": origin,
                    "destination": dest,
                    "optimal_mode": best["mode"],
                    "route_description": best["route_description"],
                    "chokepoints": best["chokepoints"],
                    "risk_score": best["risk_score"],
                    "cost_per_unit_usd": round(best["cost_usd"], 2),
                    "total_cost_jpy": round(best["total_cost_jpy"]),
                    "lead_time_days": best["lead_time_days"],
                    "composite_score": round(best["composite_score"], 2),
                    "seasonal_risk": best.get("seasonal_delta", 0),
                    "all_candidates": [
                        {
                            "mode": c["mode"],
                            "risk_score": c["risk_score"],
                            "cost_usd": round(c["cost_usd"], 2),
                            "lead_time_days": c["lead_time_days"],
                            "composite_score": round(c["composite_score"], 2),
                        }
                        for c in candidates
                    ],
                })

                total_cost_jpy += best["total_cost_jpy"]
                all_risks.append(best["risk_score"])

            # ネットワーク全体のリスクスコア
            network_risk = (
                max(all_risks) * 0.4  # 最大リスク
                + (sum(all_risks) / len(all_risks)) * 0.6  # 平均リスク
            ) if all_risks else 0

            # 推奨事項生成
            recommendations = self._generate_network_recommendations(
                optimal_routes, network_risk, month
            )

            return {
                "locations": locations,
                "lane_count": len(demand_matrix),
                "optimal_routes": optimal_routes,
                "network_risk_score": round(network_risk, 1),
                "network_risk_level": self._risk_level(network_risk),
                "total_cost_jpy": round(total_cost_jpy),
                "total_cost_usd": round(total_cost_jpy / _get_usd_jpy(), 2),
                "evaluation_month": month,
                "recommendations": recommendations,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("ネットワーク最適化に失敗: %s", e)
            return {
                "error": str(e),
                "locations": locations,
                "timestamp": datetime.utcnow().isoformat(),
            }

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _calc_base_freight(self, mode: str, distance_km: float) -> float:
        """輸送モード別の基本運賃 (USD)"""
        rate_info = BASE_FREIGHT_RATES.get(mode, BASE_FREIGHT_RATES["sea"])
        if mode == "sea":
            return rate_info["rate_per_teu"]
        elif mode == "air":
            # 航空: 概算 1TEU = 約4,000kg として計算
            return rate_info["rate_per_kg"] * 4000
        elif mode == "truck":
            return rate_info["rate_per_km"] * distance_km
        elif mode == "rail":
            return rate_info["rate_per_teu"]
        return rate_info.get("rate_per_teu", 3500)

    def _get_seasonal_delta(
        self, origin_port: str, dest_port: str, month: int
    ) -> float:
        """出発港・目的港の地域に基づく季節性リスク加算"""
        delta = 0
        origin_coords = PORT_COORDS.get(origin_port)
        dest_coords = PORT_COORDS.get(dest_port)

        regions = set()
        if origin_coords:
            regions.add(_get_region(*origin_coords))
        if dest_coords:
            regions.add(_get_region(*dest_coords))

        # enhanced_analyzer の季節性もチェック
        for event_name, event in SEASONAL_RISK_EVENTS.items():
            if month in event["months"]:
                for affected in event["affected_regions"]:
                    if affected in regions:
                        delta = max(delta, event["risk_delta"])

        return delta

    def _find_best_alternative(
        self, chokepoints: list, current_risk: float
    ) -> Optional[dict]:
        """最もリスクの高いチョークポイントの代替ルートを提案"""
        if not chokepoints or current_risk < 40:
            return None

        # リスク最大のチョークポイントを特定
        worst_cp = None
        worst_risk = 0
        for cp_id in chokepoints:
            cp_risk = self._route_analyzer.get_chokepoint_risk(cp_id)
            score = cp_risk.get("risk_score", 0)
            if score > worst_risk:
                worst_risk = score
                worst_cp = cp_id

        if not worst_cp:
            return None

        cp_name = CHOKEPOINTS.get(worst_cp, {}).get("name", "")
        alt_info = ALTERNATIVE_ROUTES.get(cp_name)
        if not alt_info:
            for key, val in ALTERNATIVE_ROUTES.items():
                if cp_name.lower() in key.lower() or key.lower() in cp_name.lower():
                    alt_info = val
                    break

        if not alt_info:
            return {
                "blocked_chokepoint": cp_name,
                "message": "代替ルート情報なし",
            }

        return {
            "blocked_chokepoint": cp_name,
            "alternative_route": alt_info["alt"],
            "extra_days": alt_info["extra_days"],
            "extra_cost_usd": alt_info["extra_cost_usd"],
            "description": alt_info["description"],
            "risk_reduction_estimate": max(0, worst_risk - 15),
        }

    def _determine_recommendation(
        self, risk_score: float, chokepoints: list, cargo_value: float
    ) -> str:
        """リスクスコアと状況からレコメンデーションを決定

        Returns:
            "REROUTE" / "PROCEED" / "MONITOR"
        """
        if risk_score >= 75:
            return "REROUTE"
        if risk_score >= 50:
            # 高額貨物はより保守的に
            if cargo_value and cargo_value > 1_000_000_000:  # 10億円以上
                return "REROUTE"
            return "MONITOR"
        if risk_score >= 30 and len(chokepoints) >= 3:
            return "MONITOR"
        return "PROCEED"

    def _describe_route(
        self, origin: str, dest: str, chokepoints: list, mode: str
    ) -> str:
        """ルート説明文を生成"""
        if mode != "sea":
            mode_ja = {"air": "航空", "truck": "トラック", "rail": "鉄道"}.get(
                mode, mode
            )
            return f"{origin} → {dest} ({mode_ja}直送)"

        if not chokepoints:
            return f"{origin} → {dest} (直航)"

        cp_names = []
        for cp_id in chokepoints:
            name = MAJOR_CHOKEPOINTS.get(cp_id, {}).get("name", cp_id)
            cp_names.append(name)

        return f"{origin} → {'→'.join(cp_names)} → {dest}"

    def _risk_level(self, score: float) -> str:
        """リスクレベル文字列"""
        if score >= 80:
            return "CRITICAL"
        if score >= 60:
            return "HIGH"
        if score >= 40:
            return "MEDIUM"
        if score >= 20:
            return "LOW"
        return "MINIMAL"

    def _evaluate_transport_candidates(
        self,
        origin: str,
        dest: str,
        cargo_value_jpy: float,
        volume_teu: int,
        month: int,
    ) -> list:
        """指定レーンの全輸送モード候補を評価"""
        candidates = []
        usd_jpy = _get_usd_jpy()

        origin_port = _resolve_country_port(origin) or origin
        dest_port = _resolve_country_port(dest) or dest

        origin_coords = PORT_COORDS.get(origin_port)
        dest_coords = PORT_COORDS.get(dest_port)

        if not origin_coords or not dest_coords:
            return candidates

        distance_km = _haversine(*origin_coords, *dest_coords)

        for mode in ["sea", "air", "rail", "truck"]:
            # トラックは3000km以上は非現実的、鉄道はユーラシア大陸限定
            if mode == "truck" and distance_km > 3000:
                continue
            if mode == "rail" and distance_km < 2000:
                continue

            try:
                cost_result = self.calculate_transport_cost_with_risk(
                    origin, dest, cargo_value_jpy, mode
                )
                if "error" in cost_result:
                    continue

                total_cost_usd = cost_result.get("total_cost_usd", 0)
                risk_score = cost_result.get("route_risk_score", 0)

                # リードタイム概算
                lead_time = self._estimate_lead_time(mode, distance_km)

                # 季節性調整
                seasonal_delta = self._get_seasonal_delta(
                    origin_port, dest_port, month
                )
                risk_score = min(100, risk_score + seasonal_delta)

                # 複合スコア: リスク(0.4) × コスト(0.35) × リードタイム(0.25)
                # 各軸を0-100に正規化
                cost_normalized = min(100, (total_cost_usd / 100000) * 100)
                time_normalized = min(100, (lead_time / 60) * 100)

                composite = (
                    risk_score * 0.40
                    + cost_normalized * 0.35
                    + time_normalized * 0.25
                )

                # チョークポイント情報
                chokepoints = []
                if mode == "sea":
                    cp_ids = _identify_chokepoints_on_route(origin_port, dest_port)
                    for cp_id in cp_ids:
                        cp_name = MAJOR_CHOKEPOINTS.get(
                            cp_id, {}
                        ).get("name_en", cp_id)
                        chokepoints.append(cp_name)

                candidates.append({
                    "mode": mode,
                    "risk_score": round(risk_score, 1),
                    "cost_usd": total_cost_usd * volume_teu if mode in ("sea", "rail") else total_cost_usd,
                    "total_cost_jpy": (total_cost_usd * volume_teu * usd_jpy) if mode in ("sea", "rail") else (total_cost_usd * usd_jpy),
                    "lead_time_days": lead_time,
                    "composite_score": composite,
                    "seasonal_delta": seasonal_delta,
                    "route_description": self._describe_route(
                        origin_port, dest_port,
                        _identify_chokepoints_on_route(origin_port, dest_port) if mode == "sea" else [],
                        mode,
                    ),
                    "chokepoints": chokepoints,
                })

            except Exception as e:
                logger.debug("候補評価失敗 %s %s→%s: %s", mode, origin, dest, e)
                continue

        return candidates

    def _estimate_lead_time(self, mode: str, distance_km: float) -> int:
        """輸送モード別リードタイム概算 (日数)"""
        if mode == "sea":
            # 平均15ノット = 27.78 km/h、24h稼働 + 港湾処理2日
            sea_days = distance_km / (27.78 * 24)
            return max(3, int(sea_days + 2))
        elif mode == "air":
            # 800km/h + 通関・積替1日
            return max(1, int(distance_km / (800 * 12) + 1))
        elif mode == "truck":
            # 60km/h × 10h/日
            return max(1, int(distance_km / 600))
        elif mode == "rail":
            # 中欧鉄道: 約800km/日
            return max(5, int(distance_km / 800 + 2))
        return 30  # デフォルト

    def _generate_network_recommendations(
        self,
        routes: list,
        network_risk: float,
        month: int,
    ) -> list:
        """ネットワーク全体の推奨事項を生成"""
        recs = []

        # 高リスクレーン
        high_risk_lanes = [
            r for r in routes
            if r.get("risk_score", 0) >= 60 and "error" not in r
        ]
        if high_risk_lanes:
            lanes_str = ", ".join(r["lane"] for r in high_risk_lanes[:5])
            recs.append(
                f"高リスクレーン ({len(high_risk_lanes)}件): {lanes_str}。"
                "代替ルートまたは航空輸送への切替を検討してください。"
            )

        # 季節性警告
        for event_name, event in SEASONAL_RISK_EVENTS.items():
            if month in event["months"]:
                recs.append(
                    f"季節性リスク: {event['description']} "
                    f"(リスク +{event['risk_delta']}pt)。"
                    "該当地域の輸送スケジュールに余裕を持たせてください。"
                )

        # チョークポイント集中度
        cp_usage = {}
        for r in routes:
            for cp in r.get("chokepoints", []):
                cp_usage[cp] = cp_usage.get(cp, 0) + 1
        concentrated = [
            (cp, cnt) for cp, cnt in cp_usage.items() if cnt >= 3
        ]
        if concentrated:
            for cp, cnt in concentrated:
                recs.append(
                    f"チョークポイント集中: {cp} を {cnt}レーンが通過。"
                    "一部レーンの代替ルート化でリスク分散を推奨。"
                )

        # ネットワーク全体
        if network_risk >= 60:
            recs.append(
                "ネットワーク全体のリスクが高水準です。"
                "サプライチェーン BCP の発動基準を確認してください。"
            )
        elif network_risk < 30:
            recs.append(
                "ネットワーク全体のリスクは許容範囲内です。"
                "定期モニタリングを継続してください。"
            )

        return recs
