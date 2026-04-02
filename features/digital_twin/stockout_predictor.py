"""在庫枯渇予測エンジン (B-1)
部品在庫の枯渇日を予測し、リスク調整リードタイムとのギャップを算出。
ROLE-AのInternalDataStoreが未作成の場合はサンプルデータでフォールバック。
"""
from datetime import datetime, timedelta
from typing import Optional

# --- InternalDataStore フォールバック ---
try:
    from pipeline.internal.internal_data_store import InternalDataStore
    _store = InternalDataStore()
except Exception:
    _store = None

# --- SCRIエンジン (ネットワーク依存、try/except必須) ---
def _get_risk_score(country: str, location: str = "") -> int:
    """SCRIリスクスコアを取得（失敗時はデフォルト30）"""
    try:
        from scoring.engine import calculate_risk_score
        result = calculate_risk_score(
            supplier_id=f"dt_{country.lower()}",
            company_name=f"DT: {country}",
            country=country,
            location=location or country,
        )
        return result.overall_score
    except Exception:
        return 30  # デフォルト中程度リスク


# ========================================================================
# サンプルデータ（InternalDataStore不在時のフォールバック）
# ========================================================================
SAMPLE_PARTS = {
    "P-001": {
        "part_id": "P-001", "part_name": "MCU STM32F4",
        "supplier_name": "STMicro", "supplier_country": "France",
        "stock_qty": 5000, "daily_consumption": 200,
        "lead_time_days": 45, "unit_cost_jpy": 850,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": True,
        "alternative_suppliers": ["TI (US)", "NXP (Netherlands)"],
    },
    "P-002": {
        "part_id": "P-002", "part_name": "MLCC 0402 10uF",
        "supplier_name": "Murata", "supplier_country": "Japan",
        "stock_qty": 120000, "daily_consumption": 5000,
        "lead_time_days": 14, "unit_cost_jpy": 5,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": False,
        "alternative_suppliers": ["TDK (Japan)", "Samsung EM (South Korea)"],
    },
    "P-003": {
        "part_id": "P-003", "part_name": "コネクタ USB-C",
        "supplier_name": "Foxconn", "supplier_country": "Taiwan",
        "stock_qty": 800, "daily_consumption": 150,
        "lead_time_days": 30, "unit_cost_jpy": 120,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": True,
        "alternative_suppliers": ["JAE (Japan)"],
    },
    "P-004": {
        "part_id": "P-004", "part_name": "パワーMOSFET",
        "supplier_name": "Infineon", "supplier_country": "Germany",
        "stock_qty": 2000, "daily_consumption": 100,
        "lead_time_days": 60, "unit_cost_jpy": 450,
        "location_id": "PLANT-JP-OSAKA",
        "is_critical": True,
        "alternative_suppliers": ["Rohm (Japan)", "ON Semi (US)"],
    },
    "P-005": {
        "part_id": "P-005", "part_name": "アルミ電解コンデンサ",
        "supplier_name": "Nichicon", "supplier_country": "Japan",
        "stock_qty": 50000, "daily_consumption": 3000,
        "lead_time_days": 10, "unit_cost_jpy": 15,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": False,
        "alternative_suppliers": ["Rubycon (Japan)", "Panasonic (Japan)"],
    },
    "P-006": {
        "part_id": "P-006", "part_name": "リチウム電池セル",
        "supplier_name": "CATL", "supplier_country": "China",
        "stock_qty": 300, "daily_consumption": 50,
        "lead_time_days": 40, "unit_cost_jpy": 12000,
        "location_id": "PLANT-JP-OSAKA",
        "is_critical": True,
        "alternative_suppliers": ["Samsung SDI (South Korea)", "Panasonic (Japan)"],
    },
    "P-007": {
        "part_id": "P-007", "part_name": "車載CAN トランシーバ",
        "supplier_name": "NXP", "supplier_country": "Netherlands",
        "stock_qty": 10000, "daily_consumption": 300,
        "lead_time_days": 35, "unit_cost_jpy": 280,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": True,
        "alternative_suppliers": ["TI (US)", "Microchip (US)"],
    },
    "P-008": {
        "part_id": "P-008", "part_name": "高精度抵抗器 0.1%",
        "supplier_name": "Vishay", "supplier_country": "United States",
        "stock_qty": 200000, "daily_consumption": 8000,
        "lead_time_days": 20, "unit_cost_jpy": 3,
        "location_id": "PLANT-JP-NAGOYA",
        "is_critical": False,
        "alternative_suppliers": ["KOA (Japan)", "Yageo (Taiwan)"],
    },
}

# 拠点マスタ（フォールバック用）
SAMPLE_LOCATIONS = {
    "PLANT-JP-NAGOYA": {"name": "名古屋工場", "country": "Japan", "city": "Nagoya"},
    "PLANT-JP-OSAKA": {"name": "大阪工場", "country": "Japan", "city": "Osaka"},
    "PLANT-TH-BANGKOK": {"name": "バンコク工場", "country": "Thailand", "city": "Bangkok"},
    "PLANT-CN-SHENZHEN": {"name": "深圳工場", "country": "China", "city": "Shenzhen"},
    "WH-JP-YOKOHAMA": {"name": "横浜倉庫", "country": "Japan", "city": "Yokohama"},
}


def _get_parts_data(location_id: str = "") -> list:
    """InternalDataStoreまたはサンプルから部品データを取得"""
    if _store is not None:
        try:
            parts = _store.get_parts(location_id=location_id)
            if parts:
                return parts
        except Exception:
            pass
    # フォールバック: サンプルデータ
    if location_id:
        return [p for p in SAMPLE_PARTS.values() if p.get("location_id") == location_id]
    return list(SAMPLE_PARTS.values())


def _get_part_by_id(part_id: str) -> Optional[dict]:
    """部品IDから部品データを取得"""
    if _store is not None:
        try:
            part = _store.get_part(part_id)
            if part:
                return part
        except Exception:
            pass
    return SAMPLE_PARTS.get(part_id)


class StockoutPredictor:
    """在庫枯渇予測エンジン

    部品ごとにリスク調整リードタイムと現在庫日数を比較し、
    枯渇リスクの有無・枯渇予測日・深刻度を算出する。
    """

    def __init__(self, risk_cache: Optional[dict] = None):
        """
        Args:
            risk_cache: {country: score} の事前取得キャッシュ（ネットワーク抑制用）
        """
        self._risk_cache = risk_cache or {}

    def _country_risk(self, country: str) -> int:
        """国リスクスコア取得（キャッシュ優先）"""
        if country in self._risk_cache:
            return self._risk_cache[country]
        score = _get_risk_score(country)
        self._risk_cache[country] = score
        return score

    def predict_stockout(
        self,
        part_id: str,
        location_id: str = "",
        risk_context: Optional[dict] = None,
    ) -> dict:
        """単一部品の在庫枯渇予測

        Args:
            part_id: 部品ID
            location_id: 拠点ID（フィルタ用）
            risk_context: 追加リスクコンテキスト
                - extra_lead_time_days: リードタイム加算日数
                - demand_multiplier: 需要倍率（例: 1.5 = 50%増）
                - override_risk_score: リスクスコア上書き

        Returns:
            dict: 枯渇予測結果
        """
        # --- 入力バリデーション ---
        if not part_id or not isinstance(part_id, str):
            raise ValueError("part_id は空でない文字列で指定してください")

        risk_context = risk_context or {}

        # --- risk_context の型・範囲検証 ---
        if "demand_multiplier" in risk_context:
            try:
                dm = float(risk_context["demand_multiplier"])
            except (TypeError, ValueError):
                dm = 1.0
            if dm <= 0:
                dm = 1.0
            risk_context["demand_multiplier"] = dm

        if "override_risk_score" in risk_context:
            try:
                ors = int(risk_context["override_risk_score"])
            except (TypeError, ValueError):
                ors = 30  # デフォルト中程度
            risk_context["override_risk_score"] = max(0, min(100, ors))

        if "extra_lead_time_days" in risk_context:
            try:
                elt = int(risk_context["extra_lead_time_days"])
            except (TypeError, ValueError):
                elt = 0
            risk_context["extra_lead_time_days"] = max(0, elt)

        part = _get_part_by_id(part_id)
        if not part:
            return {"error": f"部品 {part_id} が見つかりません", "part_id": part_id}

        stock_qty = part.get("stock_qty", 0)
        daily_consumption = part.get("daily_consumption", 0)
        lead_time_days = part.get("lead_time_days", 30)
        supplier_country = part.get("supplier_country", "Unknown")
        unit_cost_jpy = part.get("unit_cost_jpy", 0)

        # 需要倍率の適用
        demand_multiplier = risk_context.get("demand_multiplier", 1.0)
        adjusted_consumption = daily_consumption * demand_multiplier

        # 現在庫日数 = 在庫数量 / 日次消費量
        # daily_consumption <= 0 の場合は需要なしとみなし、枯渇しない
        if adjusted_consumption <= 0:
            current_stock_days = 9999
        else:
            current_stock_days = stock_qty / adjusted_consumption

        # リスクスコア取得
        risk_score = risk_context.get(
            "override_risk_score",
            self._country_risk(supplier_country),
        )

        # リスク調整リードタイム = 基本LT × (1 + リスクスコア/200)
        # リスク100→1.5倍、リスク50→1.25倍
        risk_adjusted_lead_time = lead_time_days * (1 + risk_score / 200)

        # 追加リードタイム（シナリオ分析用）
        extra_lt = risk_context.get("extra_lead_time_days", 0)
        risk_adjusted_lead_time += extra_lt

        # ギャップ日数 = リスク調整LT - 現在庫日数
        gap_days = risk_adjusted_lead_time - current_stock_days

        # 枯渇予測日
        today = datetime.utcnow().date()
        stockout_date = None
        if gap_days > 0:
            stockout_date = today + timedelta(days=int(current_stock_days))

        # 深刻度判定
        if gap_days > 14:
            severity = "CRITICAL"
        elif gap_days > 7:
            severity = "HIGH"
        elif gap_days > 0:
            severity = "MEDIUM"
        else:
            severity = "OK"

        # リスク要因の列挙
        risk_factors = []
        if risk_score >= 60:
            risk_factors.append(f"高リスク調達国: {supplier_country} (スコア={risk_score})")
        if lead_time_days >= 45:
            risk_factors.append(f"長リードタイム: {lead_time_days}日")
        if current_stock_days < 7:
            risk_factors.append(f"在庫残日数危険水準: {current_stock_days:.1f}日")
        if part.get("is_critical"):
            risk_factors.append("クリティカル部品")
        if len(part.get("alternative_suppliers", [])) == 0:
            risk_factors.append("代替サプライヤーなし（単一調達源）")
        elif len(part.get("alternative_suppliers", [])) == 1:
            risk_factors.append("代替サプライヤー1社のみ")
        if demand_multiplier > 1.0:
            risk_factors.append(f"需要増加: {demand_multiplier:.1f}倍")

        # 財務影響額（在庫金額ベース）
        inventory_value_jpy = stock_qty * unit_cost_jpy
        daily_consumption_value_jpy = adjusted_consumption * unit_cost_jpy

        return {
            "part_id": part_id,
            "part_name": part.get("part_name", ""),
            "supplier_name": part.get("supplier_name", ""),
            "supplier_country": supplier_country,
            "location_id": part.get("location_id", location_id),
            "current_stock_qty": stock_qty,
            "daily_consumption": daily_consumption,
            "adjusted_daily_consumption": round(adjusted_consumption, 1),
            "current_stock_days": round(current_stock_days, 1),
            "lead_time_days": lead_time_days,
            "risk_score": risk_score,
            "risk_adjusted_lead_time": round(risk_adjusted_lead_time, 1),
            "gap_days": round(gap_days, 1),
            "stockout_date": stockout_date.isoformat() if stockout_date else None,
            "severity": severity,
            "is_critical": part.get("is_critical", False),
            "risk_factors": risk_factors,
            "inventory_value_jpy": inventory_value_jpy,
            "daily_consumption_value_jpy": round(daily_consumption_value_jpy, 1),
            "alternative_suppliers": part.get("alternative_suppliers", []),
            "calculated_at": datetime.utcnow().isoformat(),
        }

    def scan_all_parts(
        self,
        location_id: str = "",
        risk_threshold: int = 50,
    ) -> list:
        """全部品一括スキャン、枯渇リスク順でソート

        Args:
            location_id: 拠点ID（空=全拠点）
            risk_threshold: このリスクスコア以上の調達国の部品のみ詳細分析

        Returns:
            list: 枯渇リスク順にソートされた予測結果リスト
        """
        parts = _get_parts_data(location_id)
        results = []

        for part in parts:
            pid = part.get("part_id", "")
            if not pid:
                continue
            prediction = self.predict_stockout(pid, location_id)
            if isinstance(prediction, dict) and "error" not in prediction:
                results.append(prediction)

        # gap_days降順（最も危険な部品が先頭）
        results.sort(key=lambda x: x.get("gap_days", -999), reverse=True)

        # サマリ統計
        critical_count = sum(1 for r in results if r["severity"] == "CRITICAL")
        high_count = sum(1 for r in results if r["severity"] == "HIGH")
        medium_count = sum(1 for r in results if r["severity"] == "MEDIUM")
        ok_count = sum(1 for r in results if r["severity"] == "OK")
        total_exposure_jpy = sum(
            r["daily_consumption_value_jpy"] * max(r["gap_days"], 0)
            for r in results
        )

        return {
            "scan_timestamp": datetime.utcnow().isoformat(),
            "location_id": location_id or "ALL",
            "total_parts_scanned": len(results),
            "summary": {
                "CRITICAL": critical_count,
                "HIGH": high_count,
                "MEDIUM": medium_count,
                "OK": ok_count,
            },
            "total_risk_exposure_jpy": round(total_exposure_jpy),
            "parts": results,
        }

    def simulate_risk_event(
        self,
        scenario: str,
        affected_countries: list,
        duration_days: int = 30,
        risk_score_override: int = 80,
    ) -> dict:
        """シナリオ別影響シミュレーション

        指定国からの調達リードタイムが延長される想定で再計算。

        Args:
            scenario: シナリオ名（例: "taiwan_blockade", "pandemic"）
            affected_countries: 影響を受ける国リスト
            duration_days: シナリオ持続日数
            risk_score_override: シナリオ中の調達国リスクスコア

        Returns:
            dict: シナリオ分析結果
        """
        all_parts = _get_parts_data()
        normal_results = []
        scenario_results = []

        for part in all_parts:
            pid = part.get("part_id", "")
            country = part.get("supplier_country", "")
            if not pid:
                continue

            # 通常状態
            normal = self.predict_stockout(pid)
            normal_results.append(normal)

            # シナリオ適用: 対象国の場合リスクスコアとリードタイムを増加
            if country in affected_countries:
                ctx = {
                    "override_risk_score": risk_score_override,
                    "extra_lead_time_days": duration_days * 0.5,  # 持続日数の半分をLT加算
                }
                scenario_pred = self.predict_stockout(pid, risk_context=ctx)
                scenario_pred["scenario_applied"] = True
                scenario_pred["scenario_name"] = scenario
                scenario_results.append(scenario_pred)
            else:
                scenario_pred = normal.copy()
                scenario_pred["scenario_applied"] = False
                scenario_results.append(scenario_pred)

        # 影響比較
        affected_parts = [r for r in scenario_results if r.get("scenario_applied")]
        newly_critical = []
        for sc, nm in zip(scenario_results, normal_results):
            if (sc.get("scenario_applied")
                    and sc.get("severity") in ("CRITICAL", "HIGH")
                    and nm.get("severity") == "OK"):
                newly_critical.append({
                    "part_id": sc.get("part_id", ""),
                    "part_name": sc.get("part_name", ""),
                    "normal_severity": nm.get("severity", ""),
                    "scenario_severity": sc.get("severity", ""),
                    "normal_gap_days": nm.get("gap_days", 0),
                    "scenario_gap_days": sc.get("gap_days", 0),
                    "supplier_country": sc.get("supplier_country", ""),
                })

        total_scenario_exposure = sum(
            r.get("daily_consumption_value_jpy", 0) * max(r.get("gap_days", 0), 0)
            for r in scenario_results
        )
        total_normal_exposure = sum(
            r.get("daily_consumption_value_jpy", 0) * max(r.get("gap_days", 0), 0)
            for r in normal_results
        )

        return {
            "scenario": scenario,
            "affected_countries": affected_countries,
            "duration_days": duration_days,
            "risk_score_override": risk_score_override,
            "total_parts_analyzed": len(all_parts),
            "directly_affected_parts": len(affected_parts),
            "newly_critical_parts": newly_critical,
            "exposure_comparison": {
                "normal_exposure_jpy": round(total_normal_exposure),
                "scenario_exposure_jpy": round(total_scenario_exposure),
                "incremental_exposure_jpy": round(total_scenario_exposure - total_normal_exposure),
            },
            "scenario_results": scenario_results,
            "calculated_at": datetime.utcnow().isoformat(),
        }


# === 単独動作テスト ===
if __name__ == "__main__":
    import json
    predictor = StockoutPredictor(risk_cache={
        "France": 25, "Japan": 10, "Taiwan": 55, "Germany": 20,
        "China": 45, "Netherlands": 18, "United States": 22,
    })

    print("=" * 60)
    print("【単一部品予測: P-003 (USB-Cコネクタ, Taiwan)】")
    result = predictor.predict_stockout("P-003")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    print("\n" + "=" * 60)
    print("【全部品スキャン】")
    scan = predictor.scan_all_parts()
    print(f"スキャン部品数: {scan['total_parts_scanned']}")
    print(f"サマリ: {scan['summary']}")
    print(f"リスク曝露額合計: ¥{scan['total_risk_exposure_jpy']:,.0f}")
    for p in scan["parts"][:3]:
        print(f"  {p['part_id']} {p['part_name']}: gap={p['gap_days']}日 [{p['severity']}]")

    print("\n" + "=" * 60)
    print("【シナリオ: 台湾海峡封鎖】")
    sim = predictor.simulate_risk_event(
        scenario="taiwan_blockade",
        affected_countries=["Taiwan", "China"],
        duration_days=90,
    )
    print(f"影響部品数: {sim['directly_affected_parts']}")
    print(f"新規CRITICAL: {len(sim['newly_critical_parts'])}件")
    print(f"追加曝露額: ¥{sim['exposure_comparison']['incremental_exposure_jpy']:,.0f}")
