"""緊急調達最適化エンジン (B-3)
scipy.optimizeでコスト最小×リスク最小の最適サプライヤー選定。
リスク顕在化の総コスト vs 予防コストのROI計算。
"""
from datetime import datetime, timedelta
from typing import Optional

try:
    from scipy.optimize import linprog
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# --- InternalDataStore フォールバック ---
try:
    from pipeline.internal.internal_data_store import InternalDataStore
    _store = InternalDataStore()
except Exception:
    _store = None

# --- SCRIエンジン ---
def _get_risk_score(country: str) -> int:
    try:
        from scoring.engine import calculate_risk_score
        result = calculate_risk_score(
            supplier_id=f"ep_{country.lower()}",
            company_name=f"EP: {country}",
            country=country,
            location=country,
        )
        return result.overall_score
    except Exception:
        return 30


# ========================================================================
# サンプル緊急調達候補データ（フォールバック）
# ========================================================================
SAMPLE_VENDOR_CATALOG = {
    "P-001": [  # MCU STM32F4
        {"vendor_id": "V-STM", "vendor_name": "STMicro", "country": "France",
         "unit_price_jpy": 850, "min_order_qty": 500, "lead_time_days": 45,
         "emergency_lead_time_days": 21, "emergency_price_premium_pct": 25,
         "quality_rating": 0.95, "on_time_delivery_rate": 0.92, "relationship": "primary"},
        {"vendor_id": "V-TI", "vendor_name": "Texas Instruments", "country": "United States",
         "unit_price_jpy": 920, "min_order_qty": 1000, "lead_time_days": 35,
         "emergency_lead_time_days": 18, "emergency_price_premium_pct": 30,
         "quality_rating": 0.93, "on_time_delivery_rate": 0.90, "relationship": "secondary"},
        {"vendor_id": "V-NXP", "vendor_name": "NXP Semiconductors", "country": "Netherlands",
         "unit_price_jpy": 900, "min_order_qty": 500, "lead_time_days": 40,
         "emergency_lead_time_days": 20, "emergency_price_premium_pct": 28,
         "quality_rating": 0.94, "on_time_delivery_rate": 0.91, "relationship": "approved"},
    ],
    "P-003": [  # コネクタ USB-C
        {"vendor_id": "V-FOX", "vendor_name": "Foxconn", "country": "Taiwan",
         "unit_price_jpy": 120, "min_order_qty": 2000, "lead_time_days": 30,
         "emergency_lead_time_days": 15, "emergency_price_premium_pct": 20,
         "quality_rating": 0.90, "on_time_delivery_rate": 0.88, "relationship": "primary"},
        {"vendor_id": "V-JAE", "vendor_name": "JAE Electronics", "country": "Japan",
         "unit_price_jpy": 150, "min_order_qty": 1000, "lead_time_days": 14,
         "emergency_lead_time_days": 7, "emergency_price_premium_pct": 15,
         "quality_rating": 0.97, "on_time_delivery_rate": 0.96, "relationship": "approved"},
    ],
    "P-004": [  # パワーMOSFET
        {"vendor_id": "V-INF", "vendor_name": "Infineon", "country": "Germany",
         "unit_price_jpy": 450, "min_order_qty": 500, "lead_time_days": 60,
         "emergency_lead_time_days": 30, "emergency_price_premium_pct": 35,
         "quality_rating": 0.96, "on_time_delivery_rate": 0.89, "relationship": "primary"},
        {"vendor_id": "V-ROHM", "vendor_name": "Rohm", "country": "Japan",
         "unit_price_jpy": 480, "min_order_qty": 500, "lead_time_days": 21,
         "emergency_lead_time_days": 10, "emergency_price_premium_pct": 20,
         "quality_rating": 0.94, "on_time_delivery_rate": 0.95, "relationship": "secondary"},
        {"vendor_id": "V-ONSE", "vendor_name": "ON Semiconductor", "country": "United States",
         "unit_price_jpy": 430, "min_order_qty": 1000, "lead_time_days": 50,
         "emergency_lead_time_days": 25, "emergency_price_premium_pct": 30,
         "quality_rating": 0.92, "on_time_delivery_rate": 0.87, "relationship": "approved"},
    ],
    "P-006": [  # リチウム電池セル
        {"vendor_id": "V-CATL", "vendor_name": "CATL", "country": "China",
         "unit_price_jpy": 12000, "min_order_qty": 100, "lead_time_days": 40,
         "emergency_lead_time_days": 20, "emergency_price_premium_pct": 25,
         "quality_rating": 0.91, "on_time_delivery_rate": 0.85, "relationship": "primary"},
        {"vendor_id": "V-SSDI", "vendor_name": "Samsung SDI", "country": "South Korea",
         "unit_price_jpy": 13500, "min_order_qty": 100, "lead_time_days": 35,
         "emergency_lead_time_days": 18, "emergency_price_premium_pct": 20,
         "quality_rating": 0.94, "on_time_delivery_rate": 0.92, "relationship": "secondary"},
        {"vendor_id": "V-PANA", "vendor_name": "Panasonic Energy", "country": "Japan",
         "unit_price_jpy": 14000, "min_order_qty": 50, "lead_time_days": 21,
         "emergency_lead_time_days": 10, "emergency_price_premium_pct": 15,
         "quality_rating": 0.97, "on_time_delivery_rate": 0.96, "relationship": "approved"},
    ],
    "P-007": [  # CANトランシーバ
        {"vendor_id": "V-NXP2", "vendor_name": "NXP Semiconductors", "country": "Netherlands",
         "unit_price_jpy": 280, "min_order_qty": 500, "lead_time_days": 35,
         "emergency_lead_time_days": 17, "emergency_price_premium_pct": 25,
         "quality_rating": 0.95, "on_time_delivery_rate": 0.91, "relationship": "primary"},
        {"vendor_id": "V-TI2", "vendor_name": "Texas Instruments", "country": "United States",
         "unit_price_jpy": 300, "min_order_qty": 1000, "lead_time_days": 30,
         "emergency_lead_time_days": 15, "emergency_price_premium_pct": 28,
         "quality_rating": 0.93, "on_time_delivery_rate": 0.90, "relationship": "secondary"},
        {"vendor_id": "V-MCHP", "vendor_name": "Microchip", "country": "United States",
         "unit_price_jpy": 310, "min_order_qty": 500, "lead_time_days": 28,
         "emergency_lead_time_days": 14, "emergency_price_premium_pct": 22,
         "quality_rating": 0.92, "on_time_delivery_rate": 0.89, "relationship": "approved"},
    ],
}

# 部品カタログが無い部品用のデフォルト候補
DEFAULT_VENDOR_CATALOG = {
    "P-002": [
        {"vendor_id": "V-MUR", "vendor_name": "Murata", "country": "Japan",
         "unit_price_jpy": 5, "min_order_qty": 10000, "lead_time_days": 14,
         "emergency_lead_time_days": 7, "emergency_price_premium_pct": 15,
         "quality_rating": 0.98, "on_time_delivery_rate": 0.97, "relationship": "primary"},
    ],
    "P-005": [
        {"vendor_id": "V-NICH", "vendor_name": "Nichicon", "country": "Japan",
         "unit_price_jpy": 15, "min_order_qty": 5000, "lead_time_days": 10,
         "emergency_lead_time_days": 5, "emergency_price_premium_pct": 10,
         "quality_rating": 0.96, "on_time_delivery_rate": 0.95, "relationship": "primary"},
    ],
    "P-008": [
        {"vendor_id": "V-VISH", "vendor_name": "Vishay", "country": "United States",
         "unit_price_jpy": 3, "min_order_qty": 10000, "lead_time_days": 20,
         "emergency_lead_time_days": 10, "emergency_price_premium_pct": 20,
         "quality_rating": 0.95, "on_time_delivery_rate": 0.93, "relationship": "primary"},
    ],
}


def _get_vendor_catalog(part_id: str) -> list:
    """部品IDのサプライヤー候補リストを取得"""
    if _store:
        try:
            vendors = _store.get_vendors(part_id)
            if vendors:
                return vendors
        except Exception:
            pass
    catalog = SAMPLE_VENDOR_CATALOG.get(part_id, DEFAULT_VENDOR_CATALOG.get(part_id, []))
    return catalog


class EmergencyProcurementOptimizer:
    """緊急調達最適化エンジン

    候補サプライヤーを評価し、コスト最小×リスク最小の最適解を算出。
    scipy.optimize (linprog) が利用可能な場合は線形計画法で最適化。
    """

    def __init__(self, risk_cache: Optional[dict] = None):
        self._risk_cache = risk_cache or {}

    def _country_risk(self, country: str) -> int:
        if country in self._risk_cache:
            return self._risk_cache[country]
        score = _get_risk_score(country)
        self._risk_cache[country] = score
        return score

    def optimize_emergency_order(
        self,
        part_id: str,
        required_qty: int,
        deadline_date: str,
        budget_limit_jpy: Optional[int] = None,
    ) -> dict:
        """緊急発注の最適化

        Args:
            part_id: 部品ID
            required_qty: 必要数量
            deadline_date: 納入期限 (ISO format)
            budget_limit_jpy: 予算上限（円）

        Returns:
            dict: 最適調達プラン
        """
        # --- 入力バリデーション ---
        if not part_id or not isinstance(part_id, str):
            raise ValueError("part_id は空でない文字列で指定してください")
        if required_qty <= 0:
            raise ValueError("required_qty は正の整数で指定してください")
        if budget_limit_jpy is not None and budget_limit_jpy <= 0:
            raise ValueError("budget_limit_jpy は正の整数で指定してください")

        deadline = datetime.fromisoformat(deadline_date).date()
        today = datetime.utcnow().date()
        remaining_days = (deadline - today).days

        vendors = _get_vendor_catalog(part_id)
        if not vendors:
            return {
                "error": f"部品 {part_id} の調達候補が見つかりません",
                "part_id": part_id,
            }

        # 各候補の評価
        evaluated = []
        for v in vendors:
            risk_score = self._country_risk(v["country"])
            emergency_lt = v.get("emergency_lead_time_days", v["lead_time_days"])
            emergency_price = v["unit_price_jpy"] * (1 + v.get("emergency_price_premium_pct", 30) / 100)
            total_cost = emergency_price * max(required_qty, v.get("min_order_qty", 1))
            actual_qty = max(required_qty, v.get("min_order_qty", 1))
            will_meet_deadline = emergency_lt <= remaining_days
            normal_total = v["unit_price_jpy"] * actual_qty
            cost_premium = total_cost - normal_total

            # 総合スコア: コスト正規化(40%) + リスク逆数(30%) + 品質(15%) + 納期遵守(15%)
            # 低いほど良い
            max_cost = max(
                vv["unit_price_jpy"] * (1 + vv.get("emergency_price_premium_pct", 30) / 100)
                for vv in vendors
            ) or 1
            cost_norm = emergency_price / max_cost
            risk_norm = risk_score / 100
            quality_norm = 1 - v.get("quality_rating", 0.9)
            delivery_norm = 1 - v.get("on_time_delivery_rate", 0.9)

            composite_score = (
                cost_norm * 0.40 +
                risk_norm * 0.30 +
                quality_norm * 0.15 +
                delivery_norm * 0.15
            )

            # 期限超過ペナルティ
            if not will_meet_deadline:
                composite_score += 0.5

            evaluated.append({
                "vendor_id": v["vendor_id"],
                "vendor_name": v["vendor_name"],
                "country": v["country"],
                "unit_price_jpy": v["unit_price_jpy"],
                "emergency_unit_price_jpy": round(emergency_price),
                "emergency_lead_time_days": emergency_lt,
                "normal_lead_time_days": v["lead_time_days"],
                "min_order_qty": v.get("min_order_qty", 1),
                "actual_order_qty": actual_qty,
                "total_cost_jpy": round(total_cost),
                "cost_vs_normal_jpy": round(cost_premium),
                "cost_premium_pct": v.get("emergency_price_premium_pct", 30),
                "will_meet_deadline": will_meet_deadline,
                "risk_score": risk_score,
                "quality_rating": v.get("quality_rating", 0.9),
                "on_time_delivery_rate": v.get("on_time_delivery_rate", 0.9),
                "relationship": v.get("relationship", "unknown"),
                "composite_score": round(composite_score, 4),
            })

        # スコア順ソート（低いほど良い）
        evaluated.sort(key=lambda x: x["composite_score"])

        # 予算フィルタ
        if budget_limit_jpy:
            within_budget = [e for e in evaluated if e["total_cost_jpy"] <= budget_limit_jpy]
            if within_budget:
                evaluated = within_budget + [
                    e for e in evaluated if e["total_cost_jpy"] > budget_limit_jpy
                ]

        # scipy最適化: 複数サプライヤー分割発注
        split_plan = None
        if HAS_SCIPY and len(evaluated) >= 2:
            split_plan = self._optimize_split_order(evaluated, required_qty, remaining_days, budget_limit_jpy)

        recommended = evaluated[0] if evaluated else None

        # 予算超過チェック: 推奨候補が予算を超えている場合フラグを付与
        budget_exceeded = False
        if (budget_limit_jpy is not None
                and recommended is not None
                and recommended["total_cost_jpy"] > budget_limit_jpy):
            budget_exceeded = True

        result = {
            "part_id": part_id,
            "required_qty": required_qty,
            "deadline_date": deadline_date,
            "remaining_days": remaining_days,
            "budget_limit_jpy": budget_limit_jpy,
            "recommended_vendor": recommended,
            "alternatives": evaluated[1:],
            "split_order_plan": split_plan,
            "total_candidates_evaluated": len(evaluated),
            "calculated_at": datetime.utcnow().isoformat(),
        }
        if budget_exceeded:
            result["budget_exceeded"] = True
            result["warning"] = "予算制約を満たす候補なし。予算の見直しまたは数量削減を検討してください。"
        return result

    def _optimize_split_order(
        self,
        vendors: list,
        required_qty: int,
        remaining_days: int,
        budget_limit_jpy: Optional[int],
    ) -> Optional[dict]:
        """scipy線形計画法による分割発注最適化

        目的関数: コスト×リスク複合スコアの最小化
        制約: 総数量 >= required_qty, 各サプライヤーのMOQ, 納期, 予算上限
        """
        n = len(vendors)
        if n == 0:
            return None

        # 目的関数係数: 単価×(1 + risk/100) を最小化
        c = [
            v["emergency_unit_price_jpy"] * (1 + v["risk_score"] / 100)
            for v in vendors
        ]

        # 等式制約: 総発注量 = required_qty
        A_eq = [[1] * n]
        b_eq = [required_qty]

        # 不等式制約リスト (A_ub @ x <= b_ub)
        A_ub = []
        b_ub = []

        # 予算制約: Σ(単価_i × x_i) <= budget_limit_jpy
        if budget_limit_jpy is not None:
            A_ub.append([v["emergency_unit_price_jpy"] for v in vendors])
            b_ub.append(budget_limit_jpy)

        # 変数の上下限
        bounds = []
        for v in vendors:
            # 納期に間に合わないサプライヤーは発注量0に固定
            if v["emergency_lead_time_days"] > remaining_days:
                bounds.append((0, 0))
            else:
                bounds.append((0, required_qty))

        try:
            result = linprog(
                c,
                A_ub=A_ub if A_ub else None,
                b_ub=b_ub if b_ub else None,
                A_eq=A_eq,
                b_eq=b_eq,
                bounds=bounds,
                method="highs",
            )
            if result.success:
                allocations = []
                total_cost = 0
                for i, qty in enumerate(result.x):
                    if qty < 0.5:
                        continue
                    moq = vendors[i].get("min_order_qty", 1)
                    alloc_qty = int(round(qty))
                    # MOQ制約: 割当量がMOQ未満かつ0でなければMOQに切り上げ
                    if 0 < alloc_qty < moq:
                        alloc_qty = moq
                    alloc_cost = alloc_qty * vendors[i]["emergency_unit_price_jpy"]
                    total_cost += alloc_cost
                    allocations.append({
                        "vendor_id": vendors[i]["vendor_id"],
                        "vendor_name": vendors[i]["vendor_name"],
                        "allocated_qty": alloc_qty,
                        "min_order_qty": moq,
                        "cost_jpy": round(alloc_cost),
                        "lead_time_days": vendors[i]["emergency_lead_time_days"],
                        "risk_score": vendors[i]["risk_score"],
                    })

                # 予算超過チェック: 超過の場合は予算内の代替案を付記
                budget_exceeded = (
                    budget_limit_jpy is not None and total_cost > budget_limit_jpy
                )
                plan = {
                    "optimization_method": "scipy.linprog (HiGHS)",
                    "allocations": allocations,
                    "total_cost_jpy": round(total_cost),
                    "meets_quantity": sum(a["allocated_qty"] for a in allocations) >= required_qty,
                    "optimization_successful": True,
                }
                if budget_exceeded:
                    plan["budget_exceeded"] = True
                    plan["budget_limit_jpy"] = budget_limit_jpy
                    plan["warning"] = (
                        f"MOQ切り上げにより予算 ¥{budget_limit_jpy:,} を"
                        f" ¥{total_cost - budget_limit_jpy:,.0f} 超過しています。"
                        "発注先の絞り込みを検討してください。"
                    )
                return plan
        except Exception as e:
            # 内部エラー詳細はログのみ、外部には汎用メッセージを返す
            import logging
            logging.getLogger(__name__).error(
                "linprog最適化エラー: %s", e, exc_info=True
            )
            return {
                "optimization_method": "scipy.linprog",
                "optimization_successful": False,
                "error": "分割発注の最適化計算で内部エラーが発生しました",
            }

        return None

    def calculate_total_cost_of_risk(
        self,
        part_id: str,
        scenario: str,
        duration_days: int,
        annual_production_units: int = 50000,
    ) -> dict:
        """リスク顕在化の総コスト vs 予防コストのROI

        Args:
            part_id: 部品ID
            scenario: シナリオ名
            duration_days: シナリオ持続日数
            annual_production_units: 年間生産台数

        Returns:
            dict: コスト分析結果
        """
        vendors = _get_vendor_catalog(part_id)
        if not vendors:
            return {"error": f"部品 {part_id} の調達候補が見つかりません"}

        primary = vendors[0]
        normal_unit_price = primary["unit_price_jpy"]
        daily_units = annual_production_units / 365

        # === リスク顕在化コスト ===
        # 1. 緊急調達コスト増（プレミアム分）
        emergency_premium_pct = primary.get("emergency_price_premium_pct", 30)
        emergency_unit_price = normal_unit_price * (1 + emergency_premium_pct / 100)
        emergency_procurement_extra = (emergency_unit_price - normal_unit_price) * daily_units * duration_days

        # 2. 生産停止損失（安全在庫枯渇後）
        # 仮に1製品あたり売上=部品単価の20倍と推定
        revenue_per_unit = normal_unit_price * 20
        safety_stock_days = 14  # 標準安全在庫
        actual_stop_days = max(0, duration_days - safety_stock_days - primary.get("emergency_lead_time_days", 21))
        production_loss = revenue_per_unit * daily_units * actual_stop_days

        # 3. 代替開発コスト（認定費用等）
        alternative_development_cost = normal_unit_price * 5000  # 概算: 単価の5000倍

        total_risk_cost = emergency_procurement_extra + production_loss + alternative_development_cost

        # === 予防コスト ===
        # 1. 安全在庫積増コスト（現行14日→30日）
        additional_safety_days = 16
        safety_stock_cost = normal_unit_price * daily_units * additional_safety_days

        # 2. デュアルソース維持コスト（年間認定・維持費）
        dual_source_annual = normal_unit_price * 2000  # 概算

        total_prevention_cost = safety_stock_cost + dual_source_annual

        # === ROI計算 ===
        # リスク発生確率を考慮した期待損失
        risk_probability = 0.10  # 10%/年（仮定）
        expected_annual_loss = total_risk_cost * risk_probability
        roi = expected_annual_loss / max(total_prevention_cost, 1)

        return {
            "part_id": part_id,
            "scenario": scenario,
            "duration_days": duration_days,
            "annual_production_units": annual_production_units,
            "risk_materialization_cost": {
                "emergency_procurement_extra_jpy": round(emergency_procurement_extra),
                "production_stop_loss_jpy": round(production_loss),
                "alternative_development_cost_jpy": round(alternative_development_cost),
                "total_jpy": round(total_risk_cost),
            },
            "prevention_cost": {
                "safety_stock_increase_jpy": round(safety_stock_cost),
                "dual_source_maintenance_annual_jpy": round(dual_source_annual),
                "total_jpy": round(total_prevention_cost),
            },
            "roi_analysis": {
                "risk_probability_pct": risk_probability * 100,
                "expected_annual_loss_jpy": round(expected_annual_loss),
                "prevention_cost_annual_jpy": round(total_prevention_cost),
                "roi": round(roi, 2),
                "recommendation": (
                    "予防投資を強く推奨（ROI > 2.0）" if roi > 2.0 else
                    "予防投資を推奨（ROI > 1.0）" if roi > 1.0 else
                    "現状のリスク受容も選択肢（ROI < 1.0）"
                ),
                "payback_scenario": f"リスク顕在化1回で予防コスト{round(total_risk_cost/max(total_prevention_cost,1),1)}年分を回収",
            },
            "calculated_at": datetime.utcnow().isoformat(),
        }


# === 単独動作テスト ===
if __name__ == "__main__":
    import json
    opt = EmergencyProcurementOptimizer(risk_cache={
        "France": 25, "United States": 22, "Netherlands": 18,
        "Taiwan": 55, "Japan": 10, "Germany": 20,
        "China": 45, "South Korea": 15,
    })

    print("=" * 60)
    print("【緊急調達最適化: P-001 MCU 3000個, 期限30日後】")
    deadline = (datetime.utcnow().date() + timedelta(days=30)).isoformat()
    result = opt.optimize_emergency_order("P-001", 3000, deadline)
    rec = result["recommended_vendor"]
    print(f"推奨: {rec['vendor_name']} ({rec['country']})")
    print(f"  緊急単価: ¥{rec['emergency_unit_price_jpy']:,}")
    print(f"  総コスト: ¥{rec['total_cost_jpy']:,}")
    print(f"  期限内納品: {'○' if rec['will_meet_deadline'] else '×'}")
    print(f"  リスクスコア: {rec['risk_score']}")
    if result.get("split_order_plan"):
        sp = result["split_order_plan"]
        print(f"  分割発注案: {len(sp.get('allocations', []))}社 → ¥{sp.get('total_cost_jpy', 0):,}")

    print("\n" + "=" * 60)
    print("【リスクコストROI: P-006 バッテリーセル 中国制裁90日】")
    roi = opt.calculate_total_cost_of_risk("P-006", "china_sanctions", 90, 50000)
    print(f"リスク顕在化コスト: ¥{roi['risk_materialization_cost']['total_jpy']:,}")
    print(f"予防コスト: ¥{roi['prevention_cost']['total_jpy']:,}")
    print(f"ROI: {roi['roi_analysis']['roi']}")
    print(f"推奨: {roi['roi_analysis']['recommendation']}")
