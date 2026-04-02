"""拡張ルートリスク分析エンジン (STREAM D-2)
季節性リスク調整、代替ルート提案、迂回コスト試算を提供。
既存の RouteRiskAnalyzer を拡張し、より詳細なルートリスク分析を行う。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from features.route_risk.analyzer import (
    RouteRiskAnalyzer,
    CHOKEPOINTS,
    PORT_COORDS,
    _haversine,
    _resolve_port,
)


# 季節性リスク調整テーブル
SEASONAL_ADJUSTMENTS = {
    "typhoon_season": {
        "months": [6, 7, 8, 9, 10, 11],
        "routes": ["Pacific"],
        "risk_delta": +20,
        "description": "台風シーズン: 太平洋航路の遅延・欠航リスク増加",
    },
    "monsoon": {
        "months": [6, 7, 8, 9],
        "routes": ["Indian Ocean"],
        "risk_delta": +15,
        "description": "モンスーン: インド洋航路の荒天リスク増加",
    },
    "winter_ice": {
        "months": [12, 1, 2, 3],
        "routes": ["Arctic", "Baltic"],
        "risk_delta": +30,
        "description": "冬季結氷: 北極海・バルト海航路の通航制限",
    },
    "suez_heat": {
        "months": [7, 8],
        "routes": ["Suez"],
        "risk_delta": +5,
        "description": "酷暑: スエズ運河周辺の作業効率低下",
    },
}

# 代替ルートテーブル
ALTERNATIVE_ROUTES = {
    "Suez Canal": {
        "alt": "Cape of Good Hope",
        "extra_days": 12,
        "extra_cost_usd": 180_000,
        "description": "喜望峰経由: アフリカ南端を迂回",
    },
    "Panama Canal": {
        "alt": "Strait of Magellan",
        "extra_days": 8,
        "extra_cost_usd": 120_000,
        "description": "マゼラン海峡経由: 南米南端を迂回",
    },
    "Strait of Malacca": {
        "alt": "Lombok Strait",
        "extra_days": 3,
        "extra_cost_usd": 45_000,
        "description": "ロンボク海峡経由: インドネシア東側を通過",
    },
    "Taiwan Strait": {
        "alt": "Luzon Strait",
        "extra_days": 2,
        "extra_cost_usd": 30_000,
        "description": "ルソン海峡経由: 台湾南側を迂回",
    },
}

# ルート→チョークポイント名のマッピング
_ROUTE_CHOKEPOINT_MAP = {
    "Pacific": ["taiwan_strait"],
    "Indian Ocean": ["malacca", "hormuz", "bab_el_mandeb"],
    "Suez": ["suez"],
    "Arctic": [],
    "Baltic": [],
}

# 貨物タイプ別コスト係数
CARGO_TYPE_MULTIPLIERS = {
    "container": 1.0,
    "bulk": 0.7,
    "tanker": 0.85,
    "reefer": 1.3,
    "ro-ro": 1.15,
    "lng": 1.5,
    "breakbulk": 0.9,
}


@dataclass
class SeasonalRiskResult:
    """季節性リスク評価結果"""
    route: str
    month: int
    base_risk: float
    seasonal_delta: float
    adjusted_risk: float
    active_adjustments: list[dict]
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "route": self.route,
            "month": self.month,
            "base_risk": round(self.base_risk, 1),
            "seasonal_delta": round(self.seasonal_delta, 1),
            "adjusted_risk": round(self.adjusted_risk, 1),
            "active_adjustments": self.active_adjustments,
            "timestamp": self.timestamp,
        }


@dataclass
class AlternativeRouteResult:
    """代替ルート分析結果"""
    blocked_chokepoint: str
    alternative_route: str
    extra_days: int
    extra_cost_usd: float
    total_estimated_cost_usd: float
    risk_comparison: dict
    description: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "blocked_chokepoint": self.blocked_chokepoint,
            "alternative_route": self.alternative_route,
            "extra_days": self.extra_days,
            "extra_cost_usd": round(self.extra_cost_usd, 2),
            "total_estimated_cost_usd": round(self.total_estimated_cost_usd, 2),
            "risk_comparison": self.risk_comparison,
            "description": self.description,
            "timestamp": self.timestamp,
        }


@dataclass
class EnhancedRouteResult:
    """拡張ルートリスク分析結果"""
    origin: str
    destination: str
    via_points: list[str]
    base_analysis: dict
    seasonal_risk: Optional[SeasonalRiskResult]
    alternative_routes: list[AlternativeRouteResult]
    total_risk_score: float
    risk_level: str
    recommendations: list[str]
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "via_points": self.via_points,
            "base_analysis": self.base_analysis,
            "seasonal_risk": self.seasonal_risk.to_dict() if self.seasonal_risk else None,
            "alternative_routes": [a.to_dict() for a in self.alternative_routes],
            "total_risk_score": round(self.total_risk_score, 1),
            "risk_level": self.risk_level,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
        }


class EnhancedRouteAnalyzer:
    """拡張ルートリスク分析エンジン

    既存の RouteRiskAnalyzer を拡張し、以下の機能を追加:
    - 季節性リスク調整
    - 代替ルート提案とコスト試算
    - 迂回コスト試算
    """

    def __init__(self):
        self._base_analyzer = RouteRiskAnalyzer()

    def analyze_route(
        self,
        origin: str,
        destination: str,
        via: list[str] = None,
        month: int = None,
        cargo_type: str = "container",
    ) -> dict:
        """拡張ルートリスク分析を実行。

        Args:
            origin: 出発地
            destination: 目的地
            via: 経由地リスト
            month: 評価月 (1-12, None=現在月)
            cargo_type: 貨物タイプ

        Returns:
            EnhancedRouteResult.to_dict()
        """
        try:
            if month is None:
                month = datetime.utcnow().month

            # 1. ベース分析
            base_result = self._base_analyzer.analyze_route(origin, destination)

            if "error" in base_result:
                return {
                    "error": base_result["error"],
                    "source": "EnhancedRouteAnalyzer",
                    "timestamp": datetime.utcnow().isoformat(),
                }

            # 2. 経由地のリスク評価
            via_risks = []
            if via:
                for v in via:
                    # チョークポイントIDとして検索
                    for cp_id, cp_data in CHOKEPOINTS.items():
                        if (v.lower() in cp_data["name"].lower()
                                or cp_data["name"].lower() in v.lower()
                                or v.lower() == cp_id):
                            cp_risk = self._base_analyzer.get_chokepoint_risk(cp_id)
                            via_risks.append(cp_risk)
                            break

            # 3. 通過チョークポイントのルート名を推定
            route_names = self._infer_route_names(base_result)

            # 4. 季節性リスク
            seasonal_result = None
            max_seasonal_delta = 0
            for route_name in route_names:
                sr = self.get_seasonal_risk(route_name, month)
                if sr.get("seasonal_delta", 0) > max_seasonal_delta:
                    max_seasonal_delta = sr.get("seasonal_delta", 0)
                    seasonal_result = SeasonalRiskResult(
                        route=route_name,
                        month=month,
                        base_risk=sr.get("base_risk", 0),
                        seasonal_delta=sr.get("seasonal_delta", 0),
                        adjusted_risk=sr.get("adjusted_risk", 0),
                        active_adjustments=sr.get("active_adjustments", []),
                        timestamp=datetime.utcnow().isoformat(),
                    )

            # 5. 代替ルート提案
            alternative_results = []
            chokepoints_passed = base_result.get("chokepoints_passed", [])
            for cp in chokepoints_passed:
                cp_name = cp.get("name", "")
                if cp_name in ALTERNATIVE_ROUTES:
                    alts = self.calculate_alternative_routes(cp_name)
                    for alt in alts:
                        cost_info = self.estimate_rerouting_cost(
                            cp_name, cargo_type
                        )
                        alternative_results.append(AlternativeRouteResult(
                            blocked_chokepoint=cp_name,
                            alternative_route=alt.get("alternative_route", ""),
                            extra_days=alt.get("extra_days", 0),
                            extra_cost_usd=cost_info.get("total_rerouting_cost_usd", 0),
                            total_estimated_cost_usd=cost_info.get(
                                "total_rerouting_cost_usd", 0
                            ),
                            risk_comparison=alt.get("risk_comparison", {}),
                            description=alt.get("description", ""),
                            timestamp=datetime.utcnow().isoformat(),
                        ))

            # 6. 総合リスクスコア算出
            base_risk = base_result.get("route_risk", 0)
            via_risk_max = max(
                (r.get("risk_score", 0) for r in via_risks), default=0
            )
            seasonal_delta = seasonal_result.seasonal_delta if seasonal_result else 0

            total_risk = min(100, max(
                base_risk + seasonal_delta,
                via_risk_max + seasonal_delta,
            ))

            # リスクレベル判定
            risk_level = self._get_risk_level(total_risk)

            # 7. 推奨事項
            recommendations = self._generate_recommendations(
                base_result, seasonal_result, alternative_results, total_risk
            )

            result = EnhancedRouteResult(
                origin=origin,
                destination=destination,
                via_points=via or [],
                base_analysis=base_result,
                seasonal_risk=seasonal_result,
                alternative_routes=alternative_results,
                total_risk_score=total_risk,
                risk_level=risk_level,
                recommendations=recommendations,
                timestamp=datetime.utcnow().isoformat(),
            )
            return result.to_dict()

        except Exception as e:
            return {
                "error": str(e),
                "source": "EnhancedRouteAnalyzer",
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_seasonal_risk(self, route: str, month: int = None) -> dict:
        """季節性リスク調整を算出。

        Args:
            route: ルート名 ("Pacific", "Indian Ocean", "Suez", "Arctic", "Baltic")
            month: 評価月 (1-12, None=現在月)

        Returns:
            {"base_risk": float, "seasonal_delta": float, "adjusted_risk": float,
             "active_adjustments": list[dict]}
        """
        try:
            if month is None:
                month = datetime.utcnow().month

            if month < 1 or month > 12:
                return {
                    "error": f"Invalid month: {month}",
                    "base_risk": 0,
                    "seasonal_delta": 0,
                    "adjusted_risk": 0,
                    "active_adjustments": [],
                }

            # ルートに対応するチョークポイントのベースリスクを取得
            base_risk = 0
            cp_ids = _ROUTE_CHOKEPOINT_MAP.get(route, [])
            for cp_id in cp_ids:
                cp_risk = self._base_analyzer.get_chokepoint_risk(cp_id)
                base_risk = max(base_risk, cp_risk.get("risk_score", 0))

            if base_risk == 0:
                base_risk = 20  # ルートにチョークポイントがない場合の基本リスク

            # 季節性調整
            total_delta = 0
            active_adjustments = []

            for adj_name, adj_config in SEASONAL_ADJUSTMENTS.items():
                if month in adj_config["months"]:
                    # ルート名がマッチするか確認
                    for adj_route in adj_config["routes"]:
                        if (adj_route.lower() in route.lower()
                                or route.lower() in adj_route.lower()):
                            total_delta += adj_config["risk_delta"]
                            active_adjustments.append({
                                "adjustment": adj_name,
                                "delta": adj_config["risk_delta"],
                                "description": adj_config["description"],
                            })

            adjusted_risk = min(100, max(0, base_risk + total_delta))

            return {
                "route": route,
                "month": month,
                "base_risk": base_risk,
                "seasonal_delta": total_delta,
                "adjusted_risk": adjusted_risk,
                "active_adjustments": active_adjustments,
            }

        except Exception as e:
            return {
                "error": str(e),
                "base_risk": 0,
                "seasonal_delta": 0,
                "adjusted_risk": 0,
                "active_adjustments": [],
            }

    def calculate_alternative_routes(
        self,
        blocked_chokepoint: str,
    ) -> list[dict]:
        """チョークポイント封鎖時の代替ルートを提案。

        Args:
            blocked_chokepoint: 封鎖されたチョークポイント名

        Returns:
            代替ルートリスト [{"alternative_route": str, "extra_days": int, ...}]
        """
        try:
            alt_info = ALTERNATIVE_ROUTES.get(blocked_chokepoint)
            if not alt_info:
                # 部分一致で検索
                for key, val in ALTERNATIVE_ROUTES.items():
                    if (blocked_chokepoint.lower() in key.lower()
                            or key.lower() in blocked_chokepoint.lower()):
                        alt_info = val
                        blocked_chokepoint = key
                        break

            if not alt_info:
                return [{
                    "alternative_route": "No known alternative",
                    "extra_days": 0,
                    "extra_cost_usd": 0,
                    "risk_comparison": {},
                    "description": f"代替ルート情報なし: {blocked_chokepoint}",
                }]

            # 代替ルートのリスク評価（代替ルートはチョークポイント回避のため基本低リスク）
            alt_risk = 15  # ベースライン: オープンウォーター
            original_risk = 0

            # 元のチョークポイントリスク取得
            for cp_id, cp_data in CHOKEPOINTS.items():
                if (blocked_chokepoint.lower() in cp_data["name"].lower()
                        or cp_data["name"].lower() in blocked_chokepoint.lower()):
                    cp_risk = self._base_analyzer.get_chokepoint_risk(cp_id)
                    original_risk = cp_risk.get("risk_score", 0)
                    break

            return [{
                "alternative_route": alt_info["alt"],
                "extra_days": alt_info["extra_days"],
                "extra_cost_usd": alt_info["extra_cost_usd"],
                "risk_comparison": {
                    "original_route_risk": original_risk,
                    "alternative_route_risk": alt_risk,
                    "risk_reduction": max(0, original_risk - alt_risk),
                },
                "description": alt_info["description"],
            }]

        except Exception as e:
            return [{
                "error": str(e),
                "alternative_route": "Error",
                "extra_days": 0,
                "extra_cost_usd": 0,
            }]

    def estimate_rerouting_cost(
        self,
        blocked: str,
        cargo_type: str = "container",
    ) -> dict:
        """迂回コストを試算。

        Args:
            blocked: 封鎖されたチョークポイント名
            cargo_type: 貨物タイプ ("container", "bulk", "tanker", etc.)

        Returns:
            {"base_extra_cost_usd": float, "cargo_multiplier": float,
             "total_rerouting_cost_usd": float, ...}
        """
        try:
            alt_info = ALTERNATIVE_ROUTES.get(blocked)
            if not alt_info:
                for key, val in ALTERNATIVE_ROUTES.items():
                    if (blocked.lower() in key.lower()
                            or key.lower() in blocked.lower()):
                        alt_info = val
                        blocked = key
                        break

            if not alt_info:
                return {
                    "blocked_chokepoint": blocked,
                    "error": "No alternative route data available",
                    "total_rerouting_cost_usd": 0,
                }

            base_cost = alt_info["extra_cost_usd"]
            cargo_mult = CARGO_TYPE_MULTIPLIERS.get(cargo_type.lower(), 1.0)
            extra_days = alt_info["extra_days"]

            # 日次運行コスト（業界平均）
            daily_vessel_cost = 25_000  # USD/day (中型コンテナ船平均)
            daily_fuel_cost = 15_000    # USD/day (燃料費平均)
            daily_operating_cost = (daily_vessel_cost + daily_fuel_cost) * cargo_mult

            # 追加日数分の運行コスト
            time_based_cost = daily_operating_cost * extra_days

            # 保険追加料（迂回時は海上保険が割増）
            insurance_surcharge = base_cost * 0.05

            # 合計
            total_cost = (base_cost * cargo_mult) + time_based_cost + insurance_surcharge

            return {
                "blocked_chokepoint": blocked,
                "alternative_route": alt_info["alt"],
                "cargo_type": cargo_type,
                "extra_days": extra_days,
                "cost_breakdown": {
                    "base_rerouting_cost_usd": round(base_cost * cargo_mult, 2),
                    "time_based_cost_usd": round(time_based_cost, 2),
                    "insurance_surcharge_usd": round(insurance_surcharge, 2),
                },
                "cargo_multiplier": cargo_mult,
                "total_rerouting_cost_usd": round(total_cost, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            return {
                "blocked_chokepoint": blocked,
                "error": str(e),
                "total_rerouting_cost_usd": 0,
            }

    def get_all_seasonal_risks(self, month: int = None) -> dict:
        """全ルートの季節性リスクを一括取得。

        Args:
            month: 評価月 (1-12, None=現在月)

        Returns:
            ルート別の季節性リスク
        """
        if month is None:
            month = datetime.utcnow().month

        routes = list(_ROUTE_CHOKEPOINT_MAP.keys())
        results = {}

        for route in routes:
            results[route] = self.get_seasonal_risk(route, month)

        return {
            "month": month,
            "route_risks": results,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _infer_route_names(self, base_result: dict) -> list[str]:
        """ベース分析結果からルート名を推定"""
        route_names = []
        chokepoints = base_result.get("chokepoints_passed", [])

        cp_names = [cp.get("name", "").lower() for cp in chokepoints]

        if any("malacca" in n for n in cp_names):
            route_names.append("Indian Ocean")
        if any("suez" in n for n in cp_names):
            route_names.append("Suez")
        if any("panama" in n for n in cp_names):
            route_names.append("Pacific")
        if any("taiwan" in n for n in cp_names):
            route_names.append("Pacific")

        if not route_names:
            route_names.append("Pacific")

        return route_names

    def _get_risk_level(self, score: float) -> str:
        """リスクレベルを判定"""
        if score >= 80:
            return "CRITICAL"
        if score >= 60:
            return "HIGH"
        if score >= 40:
            return "MEDIUM"
        if score >= 20:
            return "LOW"
        return "MINIMAL"

    def _generate_recommendations(
        self,
        base_result: dict,
        seasonal_result: Optional[SeasonalRiskResult],
        alternatives: list[AlternativeRouteResult],
        total_risk: float,
    ) -> list[str]:
        """ルートリスクに基づき推奨事項を生成"""
        recs = []

        if total_risk >= 60:
            recs.append(
                "ルートリスクが高い: 代替ルートの事前確保と輸送保険の見直しを推奨。"
            )

        if seasonal_result and seasonal_result.seasonal_delta > 0:
            recs.append(
                f"季節性リスク (+{seasonal_result.seasonal_delta}pt): "
                f"{seasonal_result.active_adjustments[0]['description'] if seasonal_result.active_adjustments else '季節要因あり'}。"
                "出荷スケジュールの前倒しを検討してください。"
            )

        for alt in alternatives:
            if alt.extra_cost_usd > 0:
                recs.append(
                    f"{alt.blocked_chokepoint} 封鎖時: "
                    f"{alt.alternative_route} への迂回で +{alt.extra_days}日、"
                    f"+${alt.extra_cost_usd:,.0f} のコスト増。"
                    "緊急時の迂回計画を事前に策定してください。"
                )

        chokepoints = base_result.get("chokepoints_passed", [])
        if len(chokepoints) >= 3:
            recs.append(
                f"通過チョークポイントが{len(chokepoints)}箇所: "
                "複数の海峡リスクに晒されています。分散輸送を検討してください。"
            )

        if not recs:
            recs.append(
                "ルートリスクは許容範囲内です。定期的なモニタリングを継続してください。"
            )

        return recs
