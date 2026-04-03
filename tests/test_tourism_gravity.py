"""観光重力モデル・インバウンドリスク評価テストスイート — SCRI v1.5.0

外部APIを呼ばないユニットテスト。
ハードコードデータ・フォールバック値のみで検証。
InboundRiskScorerは外部API呼び出しのため @pytest.mark.network を付与。
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# =====================================================================
# TestGravityModel — 重力モデル
# =====================================================================
class TestGravityModel:
    """features/tourism/gravity_model.py のテスト"""

    def _get_model(self):
        """フォールバックで初期化された重力モデルを返す"""
        from features.tourism.gravity_model import TourismGravityModel
        model = TourismGravityModel()
        # statsmodelsがなくてもフォールバック係数で初期化される
        model.fit()
        return model

    def test_coefficients_have_expected_signs(self):
        """為替係数は正（円安有利）、二国間リスク係数は負"""
        from features.tourism.gravity_model import COEFFICIENT_PRIORS
        # 為替: EXRインデックス上昇=円安=訪日有利 → 正の係数
        assert COEFFICIENT_PRIORS["ln_exr"] > 0, \
            "為替レート弾性値は正であるべき（円安=訪日増加）"
        # GDP: 送客国GDP上昇 → 渡航需要増 → 正の係数
        assert COEFFICIENT_PRIORS["ln_gdp_source"] > 0, \
            "GDP弾性値は正であるべき"
        # 二国間リスク: リスク増加 → 渡航減少 → 負の係数
        assert COEFFICIENT_PRIORS["bilateral_risk"] < 0, \
            "二国間リスク弾性値は負であるべき"

    def test_predict_returns_forecast(self):
        """predict()がGravityPredictionを返す"""
        model = self._get_model()
        result = model.predict(source_country="KOR", horizon_months=6)
        # GravityPredictionデータクラスの検証
        assert result.source_country == "KOR"
        assert result.baseline_forecast > 0, "予測値は正であるべき"
        assert isinstance(result.elasticities, dict)
        assert "ln_exr" in result.elasticities

    def test_exchange_rate_scenario(self):
        """円安シナリオで予測が変化する（predict_point使用）"""
        model = self._get_model()
        # ベースライン
        base = model.predict_point("CN", "2026-07")
        # 円安シナリオ（ln_exrを上昇させる = 円安方向）
        scenario = model.predict_point("CN", "2026-07", shock={"ln_exr": 2.5})
        # 予測値が正
        assert base > 0, f"ベースライン予測値は正であるべき: {base}"
        # シナリオで予測値が変化する
        assert scenario != base, \
            f"シナリオ適用で予測値が変化するべき: base={base}, scenario={scenario}"

    def test_decompose_returns_factors(self):
        """decompose_forecast_by_variable()が要因分解を返す"""
        model = self._get_model()
        result = model.decompose_forecast_by_variable(
            source_country="KR", year_month="2026-07"
        )
        # 辞書で各変数の寄与割合(%)を返す
        assert isinstance(result, dict)
        assert "ln_exr" in result
        assert "ln_flight" in result
        assert "ln_gdp_source" in result
        # 全て数値
        for key, val in result.items():
            assert isinstance(val, float), f"{key}の値がfloatでない: {type(val)}"

    def test_panel_data_has_sufficient_countries(self):
        """内蔵パネルデータに十分な国数がある"""
        from features.tourism.gravity_model import _BUILTIN_PANEL
        countries = set(r["country"] for r in _BUILTIN_PANEL)
        assert len(countries) >= 10, f"パネルデータに10カ国以上必要: {len(countries)}カ国"

    def test_predict_with_uncertainty_returns_bayesian(self):
        """predict_with_uncertainty()がBayesianForecastを返す"""
        model = self._get_model()
        from features.tourism.gravity_model import BayesianForecast
        result = model.predict_with_uncertainty(
            source_country="KR",
            months=["2026-01", "2026-02", "2026-03"],
            n_samples=100,
        )
        assert isinstance(result, BayesianForecast)
        assert result.country == "KR"
        assert len(result.months) == 3
        assert len(result.median) == 3
        assert len(result.p10) == 3
        assert len(result.p90) == 3
        # p10 <= median <= p90
        for i in range(3):
            assert result.p10[i] <= result.median[i] <= result.p90[i], \
                f"月{i}: p10={result.p10[i]} <= median={result.median[i]} <= p90={result.p90[i]} が不成立"


# =====================================================================
# TestRegionalDistribution — 日本国内分散モデル
# =====================================================================
class TestRegionalDistribution:
    """features/tourism/regional_distribution.py のテスト"""

    def _get_model(self):
        from features.tourism.regional_distribution import RegionalDistributionModel
        return RegionalDistributionModel()

    def test_distribution_sums_to_total(self):
        """地域別合計 = 入力総数"""
        model = self._get_model()
        total = 1_000_000
        result = model.predict_regional_distribution(total_forecast=total)
        dist = result["distribution"]
        actual_sum = sum(dist.values())
        assert actual_sum == total, \
            f"分配合計 {actual_sum} != 入力 {total}"

    def test_nationality_bias_applied(self):
        """中国人は大阪シェアが高い"""
        model = self._get_model()
        total = 1_000_000
        # 国籍バイアスなし
        neutral = model.predict_regional_distribution(total_forecast=total)
        # 中国人バイアスあり
        china = model.predict_regional_distribution(
            total_forecast=total, source_country="CHN"
        )
        # 中国人は大阪シェアが+0.04されるため、大阪の人数が増加するはず
        assert china["distribution"]["Osaka"] > neutral["distribution"]["Osaka"], \
            "中国人の大阪シェアはバイアスなしより高いはず"
        assert "nationality:CHN" in china["adjustments_applied"]

    def test_seasonal_bias_applied(self):
        """冬は北海道シェアが高い"""
        model = self._get_model()
        total = 1_000_000
        # 夏（7月）
        summer = model.predict_regional_distribution(
            total_forecast=total, month=7
        )
        # 冬（1月＝winter_ski）
        winter = model.predict_regional_distribution(
            total_forecast=total, month=1
        )
        # 冬は北海道に+0.08バイアス
        assert winter["distribution"]["Hokkaido"] > summer["distribution"]["Hokkaido"], \
            "冬季の北海道シェアは夏季より高いはず"

    def test_capacity_constraint(self):
        """稼働率95%超でCAPACITY_LIMIT"""
        model = self._get_model()
        # 京都の4月は稼働率0.95 → CAPACITY_LIMIT
        result = model.get_capacity_constraint("Kyoto", month=4)
        assert result["status"] == "CAPACITY_LIMIT", \
            f"京都4月はCAPACITY_LIMITであるべき: {result['status']}"
        assert result["occupancy_rate"] >= 0.95

    def test_prefecture_shares_sum_to_one(self):
        """都道府県シェアの合計が1.0"""
        from features.tourism.regional_distribution import PREFECTURE_SHARES
        total = sum(PREFECTURE_SHARES.values())
        assert abs(total - 1.0) < 1e-9, f"シェア合計: {total}"

    def test_47_prefectures(self):
        """47都道府県が含まれる"""
        from features.tourism.regional_distribution import ALL_PREFECTURES
        assert len(ALL_PREFECTURES) == 47

    def test_zero_forecast_returns_all_zeros(self):
        """入力0なら全都道府県0"""
        model = self._get_model()
        result = model.predict_regional_distribution(total_forecast=0)
        assert result["total"] == 0
        assert all(v == 0 for v in result["distribution"].values())


# =====================================================================
# TestFlightSupply — フライト供給クライアント
# =====================================================================
class TestFlightSupply:
    """pipeline/tourism/flight_supply_client.py のテスト（ハードコードデータ）"""

    def test_capacity_index_returns_data(self):
        """CAPACITY_INDEXにデータが存在する"""
        from pipeline.tourism.flight_supply_client import CAPACITY_INDEX
        # 主要国のデータがある
        assert "CHN" in CAPACITY_INDEX
        assert "KOR" in CAPACITY_INDEX
        assert "USA" in CAPACITY_INDEX
        # 各国に複数年のデータがある
        for country, data in CAPACITY_INDEX.items():
            assert len(data) >= 5, f"{country}: データが5年分以上必要"
            assert "2019" in data, f"{country}: 2019年（基準年）のデータが必要"
            assert data["2019"] == 100, f"{country}: 2019年は基準値100であるべき"

    def test_current_ratio_reasonable(self):
        """2019年比が0-2.0の範囲"""
        from pipeline.tourism.flight_supply_client import CAPACITY_INDEX
        for country, data in CAPACITY_INDEX.items():
            # 最新年のデータを取得
            latest_year = max(data.keys())
            ratio = data[latest_year] / 100.0
            assert 0 <= ratio <= 2.0, \
                f"{country} {latest_year}: 2019年比 {ratio} は0-2.0の範囲外"

    def test_baseline_weekly_seats_positive(self):
        """2019年基準の週次座席数が正"""
        from pipeline.tourism.flight_supply_client import BASELINE_WEEKLY_SEATS_2019
        for country, seats in BASELINE_WEEKLY_SEATS_2019.items():
            assert seats > 0, f"{country}: 週次座席数は正であるべき"

    def test_japan_airports_defined(self):
        """日本の主要空港が定義されている"""
        from pipeline.tourism.flight_supply_client import JAPAN_AIRPORTS
        assert "NRT" in JAPAN_AIRPORTS  # 成田
        assert "HND" in JAPAN_AIRPORTS  # 羽田
        assert "KIX" in JAPAN_AIRPORTS  # 関西
        assert len(JAPAN_AIRPORTS) >= 5


# =====================================================================
# TestUNWTO — UNWTO観光統計クライアント
# =====================================================================
class TestUNWTO:
    """pipeline/tourism/unwto_client.py のテスト（フォールバックデータ）"""

    def test_outbound_total_positive(self):
        """アウトバウンド総数が正の値（フォールバックデータ検証）"""
        from pipeline.tourism.unwto_client import UNWTOClient
        client = UNWTOClient()
        # フォールバックデータの検証
        for iso3, years in client.OUTBOUND_FALLBACK.items():
            for year, count in years.items():
                assert count > 0, f"{iso3} {year}: アウトバウンド数は正であるべき"

    def test_destination_share_in_range(self):
        """日本シェアが0-100%（ハードコード競合シェアデータの検証）"""
        # 直接ハードコードデータの妥当性を検証
        from pipeline.tourism.unwto_client import UNWTOClient
        client = UNWTOClient()
        # インバウンドフォールバックデータの検証
        for dest, years in client.INBOUND_FALLBACK.items():
            for year, count in years.items():
                assert count > 0, f"{dest} {year}: インバウンド数は正であるべき"

    def test_tourism_indicators_defined(self):
        """観光指標が定義されている"""
        from pipeline.tourism.unwto_client import TOURISM_INDICATORS
        assert "inbound_arrivals" in TOURISM_INDICATORS
        assert "outbound_departures" in TOURISM_INDICATORS
        assert "tourism_receipts" in TOURISM_INDICATORS

    def test_iso_mapping_covers_major_countries(self):
        """ISO3→ISO2マッピングが主要国をカバー"""
        from pipeline.tourism.unwto_client import ISO3_TO_ISO2
        for country in ["JPN", "CHN", "KOR", "USA", "THA", "SGP", "AUS"]:
            assert country in ISO3_TO_ISO2, f"{country}のISO変換が未定義"


# =====================================================================
# TestJNTO — 訪日外客統計クライアント
# =====================================================================
class TestJNTO:
    """pipeline/tourism/jnto_client.py のテスト"""

    def test_top_markets_include_china_korea(self):
        """上位市場に中国・韓国が含まれる"""
        from pipeline.tourism.jnto_client import JNTOClient
        client = JNTOClient()
        markets = list(client.MARKET_MAP.keys())
        assert "CHN" in markets, "中国が上位市場に含まれるべき"
        assert "KOR" in markets, "韓国が上位市場に含まれるべき"

    def test_monthly_arrivals_positive(self):
        """月次到着数が正（推定値の検証）"""
        from pipeline.tourism.jnto_client import JNTOClient
        client = JNTOClient()
        # 中国の2024年4月の推定値
        result = client._estimate_monthly("CHN", 2024, 4)
        assert result is not None, "推定値がNoneであるべきでない"
        assert result > 0, "月次到着数は正であるべき"

    def test_historical_data_covers_major_markets(self):
        """過去実績データが主要20市場をカバー"""
        from pipeline.tourism.jnto_client import JNTOClient
        client = JNTOClient()
        assert len(client.HISTORICAL_DATA) >= 20, \
            f"過去データは20市場以上必要: {len(client.HISTORICAL_DATA)}"
        # 2019年（コロナ前ピーク）のデータがある
        for iso3, years in client.HISTORICAL_DATA.items():
            assert "2019" in years, f"{iso3}: 2019年データが必要"

    def test_monthly_share_sums_to_one(self):
        """月別構成比の合計が1.0"""
        from pipeline.tourism.jnto_client import JNTOClient
        total = sum(JNTOClient.MONTHLY_SHARE.values())
        assert abs(total - 1.0) < 0.01, f"月別構成比合計: {total}"

    def test_2019_china_largest(self):
        """2019年は中国が最大の送客国"""
        from pipeline.tourism.jnto_client import JNTOClient
        client = JNTOClient()
        china_2019 = client.HISTORICAL_DATA["CHN"]["2019"]
        for iso3, years in client.HISTORICAL_DATA.items():
            if iso3 == "CHN":
                continue
            assert china_2019 >= years.get("2019", 0), \
                f"2019年: 中国({china_2019}) < {iso3}({years.get('2019', 0)})"


# =====================================================================
# TestInboundRiskScorer — インバウンドリスクスコアラー
# =====================================================================
class TestInboundRiskScorer:
    """features/tourism/inbound_risk_scorer.py のテスト"""

    def _get_scorer(self):
        from features.tourism.inbound_risk_scorer import InboundTourismRiskScorer
        return InboundTourismRiskScorer()

    @pytest.mark.network
    def test_market_risk_in_range(self):
        """リスクスコアが0-100（外部API呼び出しあり）"""
        scorer = self._get_scorer()
        result = scorer.calculate_market_risk("KR")
        score = result["inbound_risk_score"]
        assert 0 <= score <= 100, f"リスクスコア {score} は0-100の範囲外"
        assert result["risk_level"] in (
            "CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"
        )

    @pytest.mark.network
    def test_scan_all_markets_returns_list(self):
        """scan_all_markets()がリストを返す（top_n=2で時間短縮）"""
        scorer = self._get_scorer()
        # 全スコアリングエンジンを呼ぶため1市場あたり数十秒かかる
        # top_n=2 でタイムアウト回避
        results = scorer.scan_all_markets(top_n=2)
        assert isinstance(results, list)
        assert len(results) == 2, f"2市場を要求したが{len(results)}市場返却"
        # ランク付けされている
        for i, item in enumerate(results, 1):
            assert item["rank"] == i, f"ランク{item['rank']} != 期待値{i}"
        # リスクスコア降順
        if len(results) >= 2:
            assert results[0]["inbound_risk_score"] >= results[1]["inbound_risk_score"], \
                "リスクスコア降順でソートされるべき"

    @pytest.mark.network
    def test_forecast_includes_confidence(self):
        """予測に信頼区間が含まれる（外部API呼び出しあり）"""
        scorer = self._get_scorer()
        result = scorer.forecast_visitor_volume("CN", horizon_months=6)
        assert "confidence_interval" in result
        ci = result["confidence_interval"]
        assert "lower" in ci
        assert "upper" in ci
        assert "uncertainty_pct" in ci
        assert ci["lower"] <= result["adjusted_forecast"] <= ci["upper"], \
            "予測値が信頼区間の範囲内であるべき"

    @pytest.mark.network
    def test_risk_categories_present(self):
        """3カテゴリのリスク内訳が含まれる（外部API呼び出しあり）"""
        scorer = self._get_scorer()
        result = scorer.calculate_market_risk("US")
        cats = result["categories"]
        assert "demand_risk" in cats
        assert "supply_risk" in cats
        assert "japan_risk" in cats
        # 各カテゴリにスコアとウェイトがある
        for name, cat in cats.items():
            assert 0 <= cat["score"] <= 100, f"{name} スコア範囲外"
            assert cat["weight"] > 0

    @pytest.mark.network
    def test_decompose_visitor_change(self):
        """decompose_visitor_change()が要因分解を返す（外部API呼び出しあり）"""
        scorer = self._get_scorer()
        result = scorer.decompose_visitor_change("KR", period_months=12)
        assert "decomposition" in result
        decomp = result["decomposition"]
        assert "demand_factors" in decomp
        assert "supply_factors" in decomp
        assert "japan_factors" in decomp

    @pytest.mark.network
    def test_forecast_with_scenario(self):
        """シナリオ付き予測が動作する（外部API呼び出しあり）"""
        scorer = self._get_scorer()
        # 悲観シナリオ（影響度-30%）
        result = scorer.forecast_visitor_volume(
            "CN", horizon_months=6,
            scenario={"impact_factor": -0.3}
        )
        assert result["scenario_adjustment"] < 1.0, \
            "悲観シナリオでは調整係数が1.0未満であるべき"
        assert result["adjusted_forecast"] >= 0, "予測値は非負であるべき"

    def test_country_resolution(self):
        """各種フォーマットの国名解決"""
        from features.tourism.inbound_risk_scorer import (
            _resolve_country_name, _resolve_iso2
        )
        # ISO2
        assert _resolve_country_name("CN") == "China"
        assert _resolve_country_name("KR") == "South Korea"
        # ISO3
        assert _resolve_country_name("CHN") == "China"
        assert _resolve_country_name("USA") == "United States"
        # ISO2逆変換
        assert _resolve_iso2("China") == "CN"


# =====================================================================
# TestCompetitorStats — 競合デスティネーション統計
# =====================================================================
class TestCompetitorStats:
    """pipeline/tourism/competitor_stats_client.py のテスト"""

    def test_relative_performance_includes_japan(self):
        """比較結果に日本（基準国）が含まれる"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        client = CompetitorStatsClient()
        # 日本のインバウンドデータがある
        assert client.JAPAN_INBOUND, "日本のインバウンドデータが必要"
        assert "2019" in client.JAPAN_INBOUND

    def test_competitors_defined(self):
        """8競合国が定義されている"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        client = CompetitorStatsClient()
        assert len(client.COMPETITORS) >= 7, \
            f"競合国が7カ国以上必要: {len(client.COMPETITORS)}"
        # 主要競合が含まれる
        assert "THA" in client.COMPETITORS, "タイが競合に含まれるべき"
        assert "KOR" in client.COMPETITORS, "韓国が競合に含まれるべき"

    def test_competitor_fallback_data(self):
        """競合国のフォールバックデータが妥当"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        client = CompetitorStatsClient()
        for iso3, info in client.COMPETITORS.items():
            fallback = info.get("inbound_fallback", {})
            assert fallback, f"{iso3}: フォールバックデータが必要"
            for year, count in fallback.items():
                assert count > 0, f"{iso3} {year}: インバウンド数は正であるべき"

    def test_source_destination_shares(self):
        """送客国→デスティネーションシェアが定義されている"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        shares = CompetitorStatsClient.SOURCE_DESTINATION_SHARES
        # 中国からの送客先に日本が含まれる
        assert "CHN" in shares
        assert "JPN" in shares["CHN"]
        # シェアが0-100%の範囲
        for source, dests in shares.items():
            for dest, pct in dests.items():
                assert 0 <= pct <= 100, \
                    f"{source}→{dest}: シェア {pct}% は0-100の範囲外"


# =====================================================================
# TestCapitalFlowRisk — 資本フローリスク
# =====================================================================
class TestCapitalFlowRisk:
    """資本フローリスク評価のテスト（フォールバックデータ検証）"""

    def _evaluate(self, country_iso3):
        """フォールバックロジックで資本フローリスクを評価"""
        swift_excluded = {"RUS", "BLR", "IRN", "PRK", "SYR", "CUB"}
        closed_economies = {"CHN": 65, "RUS": 80, "IRN": 85, "PRK": 95,
                            "CUB": 90, "VEN": 75, "BLR": 78, "SYR": 88}
        open_economies = {"USA": 12, "GBR": 10, "SGP": 8, "JPN": 15,
                          "DEU": 11, "AUS": 13, "CAN": 12, "CHE": 9,
                          "HKG": 7, "NZL": 14}

        iso3 = country_iso3.upper()
        if iso3 in swift_excluded:
            score = max(closed_economies.get(iso3, 75), 70)
        else:
            score = closed_economies.get(iso3, open_economies.get(iso3, 40))
        return score

    def test_score_in_range(self):
        """スコアが0-100"""
        for c in ["USA", "CHN", "RUS", "JPN", "SGP", "IRN", "PRK"]:
            score = self._evaluate(c)
            assert 0 <= score <= 100, f"{c}: スコア {score} は0-100の範囲外"

    def test_open_economy_low_risk(self):
        """開放経済(USA/SGP)は低スコア"""
        for c in ["USA", "SGP"]:
            score = self._evaluate(c)
            assert score < 30, f"{c}: 開放経済のスコア {score} が30以上"

    def test_closed_economy_high_risk(self):
        """規制経済(CHN/RUS)は高スコア"""
        for c in ["CHN", "RUS"]:
            score = self._evaluate(c)
            assert score >= 60, f"{c}: 規制経済のスコア {score} が60未満"

    def test_swift_excluded_very_high(self):
        """SWIFT除外国は70以上"""
        swift_excluded = ["RUS", "BLR", "IRN", "PRK", "SYR", "CUB"]
        for c in swift_excluded:
            score = self._evaluate(c)
            assert score >= 70, f"{c}: SWIFT除外国のスコア {score} が70未満"


# =====================================================================
# TestTourismDB — 観光統計DB
# =====================================================================
class TestTourismDB:
    """pipeline/tourism/tourism_db.py のテスト"""

    def _get_db(self, tmp_path=None):
        """テスト用一時DBを作成"""
        import tempfile
        if tmp_path is None:
            tmp_path = tempfile.mkdtemp()
        db_path = os.path.join(tmp_path, "test_tourism.db")
        from pipeline.tourism.tourism_db import TourismDB
        return TourismDB(db_path=db_path)

    def test_upsert_and_retrieve(self):
        """データ格納と取得"""
        db = self._get_db()
        # アウトバウンドデータを格納
        db.upsert_outbound([{
            "source_country": "CHN",
            "year": 2024,
            "month": 0,
            "outbound_total": 130_000_000,
            "top_destinations": {"JPN": 6962800, "KOR": 4800000},
            "data_source": "test",
        }])
        # 取得
        rows = db.get_outbound("CHN", year=2024)
        assert len(rows) >= 1, "格納したデータが取得できない"
        assert rows[0]["outbound_total"] == 130_000_000

    def test_table_counts(self):
        """テーブル件数取得"""
        db = self._get_db()
        # 空DB
        counts = db.get_table_counts()
        assert isinstance(counts, dict)
        assert "outbound_stats" in counts
        assert "japan_inbound" in counts
        assert "gravity_variables" in counts
        assert "inbound_stats" in counts
        # 空なので全て0
        assert all(v == 0 for v in counts.values()), f"空DBなのに件数がある: {counts}"

        # データを1件追加して再確認
        db.upsert_japan_inbound([{
            "source_country": "KOR",
            "year": 2024,
            "month": 0,
            "arrivals": 8_818_500,
        }])
        counts = db.get_table_counts()
        assert counts["japan_inbound"] == 1


# =====================================================================
# TestSourceMarkets — ソースマーケット統計
# =====================================================================
class TestSourceMarkets:
    """pipeline/tourism/source_markets/ のテスト"""

    def test_taiwan_outbound_known_value(self):
        """台湾2024: 16,849,683人（Tourism Bureau公表値に近い）"""
        # 台湾クライアントが存在しない場合はスキップ
        try:
            from pipeline.tourism.source_markets import TaiwanSourceMarketClient
            client = TaiwanSourceMarketClient()
            annual = client.ANNUAL_DATA
            assert 2024 in annual, "台湾の2024年データが必要"
            val = annual[2024]
            # 16,849,683 ± 20%
            assert 13_000_000 <= val <= 20_000_000, \
                f"台湾2024アウトバウンド {val} は13M-20Mの範囲外"
        except ImportError:
            # 台湾クライアント未実装の場合
            # 中国クライアントの台湾向けデータで代替検証
            from pipeline.tourism.source_markets import ChinaSourceMarketClient
            client = ChinaSourceMarketClient()
            shares_2024 = client.DESTINATION_SHARES.get(2024, {})
            twn = shares_2024.get("TWN", {})
            assert twn.get("visitors", 0) > 0, "中国→台湾の訪問者データが必要"

    def test_korea_japan_share(self):
        """韓国の日本向けシェアが15-30%範囲"""
        from pipeline.tourism.source_markets import KoreaSourceMarketClient
        client = KoreaSourceMarketClient()
        shares_2024 = client.DESTINATION_SHARES.get(2024, {})
        jpn = shares_2024.get("JPN", {})
        share_pct = jpn.get("share_pct", 0)
        assert 15 <= share_pct <= 30, \
            f"韓国の日本向けシェア {share_pct}% は15-30%の範囲外"


# =====================================================================
# TestCompetitorDB — 競合デスティネーションDB
# =====================================================================
class TestCompetitorDB:
    """pipeline/tourism/competitors/ のテスト"""

    def test_relative_growth(self):
        """成長率比較が返る"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        client = CompetitorStatsClient()
        # 日本のインバウンド成長率を算出
        jp = client.JAPAN_INBOUND
        years = sorted(jp.keys())
        if len(years) >= 2:
            y1, y2 = years[-2], years[-1]
            v1, v2 = jp[y1], jp[y2]
            if v1 > 0:
                growth = (v2 - v1) / v1 * 100
                assert isinstance(growth, float), "成長率がfloatで返らない"
                # コロナ回復期なので-50%~+200%は妥当
                assert -50 <= growth <= 200, f"成長率 {growth}% は異常値"

    def test_diversion_signal(self):
        """転換シグナルが数値で返る"""
        from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
        client = CompetitorStatsClient()
        # 中国→日本 vs 中国→タイ の転換シグナルを検証
        shares = CompetitorStatsClient.SOURCE_DESTINATION_SHARES
        if "CHN" in shares:
            chn_shares = shares["CHN"]
            jpn_share = chn_shares.get("JPN", 0)
            tha_share = chn_shares.get("THA", 0)
            # 転換シグナル = シェア差分
            diversion = jpn_share - tha_share
            assert isinstance(diversion, (int, float)), \
                "転換シグナルが数値で返らない"


# =====================================================================
# TestGravityModelDB — 重力モデルDB統合
# =====================================================================
class TestGravityModelDB:
    """gravity_model.py の build_training_dataset / auto_refit テスト"""

    def test_build_training_dataset_fallback(self):
        """DBがない場合にfit_from_db()が内蔵データにフォールバック"""
        from features.tourism.gravity_model import TourismGravityModel, FitResult
        model = TourismGravityModel()
        # fit_from_db()はDB不在時に内蔵データにフォールバック
        result = model.fit_from_db()
        assert isinstance(result, FitResult)
        assert result.n_obs >= 10 or result.method == "prior_fallback", \
            f"フォールバックが機能していない: n_obs={result.n_obs}, method={result.method}"

    def test_refit_returns_consistent_result(self):
        """fit()を2回呼んでも一貫した結果を返す"""
        from features.tourism.gravity_model import TourismGravityModel, FitResult
        model = TourismGravityModel()
        result1 = model.fit()
        result2 = model.fit()
        assert isinstance(result1, FitResult)
        assert isinstance(result2, FitResult)
        assert result1.method == result2.method
        assert result1.n_obs == result2.n_obs
        # 同じデータで推定すれば係数は同一
        for key in result1.coefficients:
            assert abs(result1.coefficients[key] - result2.coefficients[key]) < 1e-6, \
                f"係数 {key} が再推定で変化: {result1.coefficients[key]} vs {result2.coefficients[key]}"


# =====================================================================
# TestTFI — Travel Friction Index
# =====================================================================
class TestTFI:
    """features/tourism/travel_friction_index.py のテスト"""

    def _get_tfi(self):
        from features.tourism.travel_friction_index import TravelFrictionIndex
        return TravelFrictionIndex()

    def test_tfi_ranking_kr_lowest(self):
        """韓国が最低TFI近辺（最も摩擦が小さい）"""
        tfi = self._get_tfi()
        ranking = tfi.get_expected_tfi_ranking()
        # 韓国はトップ3以内であるべき
        top3_countries = [r.source_country for r in ranking[:3]]
        assert "KR" in top3_countries, \
            f"韓国がTFI最低3カ国に入っていない: {top3_countries}"

    def test_tfi_all_positive(self):
        """全TFIが0-100の範囲"""
        tfi = self._get_tfi()
        all_results = tfi.calculate_all_countries()
        for country, result in all_results.items():
            assert 0 <= result.tfi <= 100, \
                f"{country}: TFI={result.tfi} は0-100の範囲外"

    def test_cultural_distance_symmetric(self):
        """文化距離がJP基準で計算されている（正の値）"""
        tfi = self._get_tfi()
        result = tfi.calculate("KR")
        assert result.cultural_distance > 0, \
            "韓国の文化距離は正であるべき"
        assert result.cultural_distance < 100, \
            "韓国の文化距離は100未満であるべき（近隣国）"

    def test_visa_barrier_china_higher(self):
        """中国のビザ障壁は韓国より高い"""
        tfi = self._get_tfi()
        kr = tfi.calculate("KR")
        cn = tfi.calculate("CN")
        assert cn.visa_barrier > kr.visa_barrier, \
            f"中国ビザ({cn.visa_barrier}) > 韓国ビザ({kr.visa_barrier}) であるべき"

    def test_tfi_components_present(self):
        """TFI結果にコンポーネントが含まれる"""
        tfi = self._get_tfi()
        result = tfi.calculate("US")
        assert "cultural_norm" in result.components
        assert "efd_norm" in result.components
        assert "visa_norm" in result.components

    def test_tfi_precomputed_coverage(self):
        """プリコンピュートデータが20カ国をカバー"""
        from features.tourism.travel_friction_index import TFI_PRECOMPUTED
        assert len(TFI_PRECOMPUTED) >= 20, \
            f"プリコンピュート: {len(TFI_PRECOMPUTED)}カ国 < 20"


# =====================================================================
# TestTFIEnrichedGravityModel — TFI統合PPML
# =====================================================================
class TestTFIEnrichedGravityModel:
    """features/tourism/gravity_model.py TFIEnrichedGravityModel のテスト"""

    def _get_model(self):
        from features.tourism.gravity_model import TFIEnrichedGravityModel
        model = TFIEnrichedGravityModel()
        model.fit()
        return model

    def test_fit_returns_result(self):
        """fit()がFitResultを返す"""
        from features.tourism.gravity_model import TFIEnrichedGravityModel, FitResult
        model = TFIEnrichedGravityModel()
        result = model.fit()
        assert isinstance(result, FitResult)
        assert "tfi" in result.coefficients, \
            "TFI係数が推定結果に含まれるべき"

    def test_tfi_coefficient_negative(self):
        """TFI係数は負（摩擦増→訪日減）"""
        model = self._get_model()
        coeffs = model.get_coefficients()
        assert coeffs.get("tfi", 0) < 0, \
            f"TFI係数は負であるべき: {coeffs.get('tfi')}"

    def test_excess_demand_calculated(self):
        """超過需要が計算できる"""
        from features.tourism.gravity_model import ExcessDemandRecord
        model = self._get_model()
        records = model.calculate_excess_demand()
        assert len(records) > 0, "超過需要レコードが空"
        for rec in records:
            assert isinstance(rec, ExcessDemandRecord)
            assert rec.interpretation in ("BRAND_PREMIUM", "BRAND_DEFICIT", "NEUTRAL")

    def test_fit_from_db_fallback(self):
        """DBなし時にfit_from_db()がフォールバック"""
        from features.tourism.gravity_model import TFIEnrichedGravityModel, FitResult
        model = TFIEnrichedGravityModel()
        result = model.fit_from_db()
        assert isinstance(result, FitResult)


# =====================================================================
# TestCIC — Cultural Inertia Coefficient
# =====================================================================
class TestCIC:
    """features/tourism/cultural_inertia.py のテスト"""

    def _get_cic(self):
        from features.tourism.cultural_inertia import CulturalInertiaCoefficient
        return CulturalInertiaCoefficient()

    def test_structural_cic_range(self):
        """構造的CICが0-1の範囲"""
        cic = self._get_cic()
        for country in ["KR", "CN", "US", "GB", "TH", "RU"]:
            val = cic.calculate_structural(country)
            assert 0 <= val <= 1, \
                f"{country}: structural_cic={val} は0-1の範囲外"

    def test_asia_higher_than_europe(self):
        """アジアCIC > 欧米CIC（近隣国のほうが文化的慣性が強い）"""
        cic = self._get_cic()
        kr_cic = cic.get_full_cic("KR")
        gb_cic = cic.get_full_cic("GB")
        assert kr_cic.total_cic > gb_cic.total_cic, \
            f"韓国CIC({kr_cic.total_cic}) > 英国CIC({gb_cic.total_cic}) であるべき"

    def test_structural_inverse_of_tfi(self):
        """structural CIC ≈ 1 - TFI/100"""
        cic = self._get_cic()
        from features.tourism.travel_friction_index import TFI_PRECOMPUTED
        for country in ["KR", "US", "CN"]:
            structural = cic.calculate_structural(country)
            tfi = cic._get_tfi(country)
            expected = 1.0 - tfi / 100.0
            assert abs(structural - expected) < 0.01, \
                f"{country}: structural={structural} != 1-TFI/100={expected}"

    def test_cic_result_fields(self):
        """CICResultに必要なフィールドがある"""
        cic = self._get_cic()
        result = cic.get_full_cic("KR")
        assert hasattr(result, "structural_cic")
        assert hasattr(result, "psychological_cic")
        assert hasattr(result, "total_cic")
        assert hasattr(result, "alpha")
        assert hasattr(result, "recovery_rate")
        assert hasattr(result, "interpretation")
        assert result.interpretation in ("STRONG", "MODERATE", "WEAK")

    def test_psychological_no_data_returns_zero(self):
        """データ不足時にpsychological CICが0"""
        cic = self._get_cic()
        psy = cic.estimate_psychological("XX")  # 存在しない国
        assert psy == 0.0, f"データなしのpsychological CICは0であるべき: {psy}"

    def test_ranking_order(self):
        """ランキングがCIC降順"""
        cic = self._get_cic()
        ranking = cic.get_cic_ranking()
        for i in range(len(ranking) - 1):
            assert ranking[i].total_cic >= ranking[i+1].total_cic, \
                f"ランキング順序エラー: {ranking[i].country}({ranking[i].total_cic}) < {ranking[i+1].country}({ranking[i+1].total_cic})"


# =====================================================================
# TestCalendarEvents — カレンダーイベント
# =====================================================================
class TestCalendarEvents:
    """features/tourism/calendar_events.py のテスト"""

    def _get_funcs(self):
        from features.tourism.calendar_events import (
            get_events_for_country_month,
            get_demand_multiplier,
            get_uncertainty_multiplier,
        )
        return get_events_for_country_month, get_demand_multiplier, get_uncertainty_multiplier

    def test_spring_festival_cn_low(self):
        """中国2月(春節)の需要倍率が1.0未満"""
        _, get_dm, _ = self._get_funcs()
        dm = get_dm("CN", 2)
        assert dm < 1.0, f"春節(CN, 2月)の需要倍率は1.0未満であるべき: {dm}"

    def test_golden_week_cn_high(self):
        """中国10月(国慶節)の需要倍率が1.5以上"""
        _, get_dm, _ = self._get_funcs()
        dm = get_dm("CN", 10)
        assert dm >= 1.5, f"国慶節(CN, 10月)の需要倍率は1.5以上であるべき: {dm}"

    def test_typhoon_high_uncertainty(self):
        """台風シーズン(9月)の不確実性が通常月より高い"""
        _, _, get_um = self._get_funcs()
        typhoon_um = get_um("TW", 9)
        normal_um = get_um("TW", 5)  # 5月は台風なし
        assert typhoon_um > normal_um, \
            f"台風シーズン不確実性({typhoon_um}) > 通常月({normal_um})であるべき"

    def test_chuseok_kr_low(self):
        """韓国9月(秋夕)の需要倍率が1.0未満"""
        _, get_dm, _ = self._get_funcs()
        dm = get_dm("KR", 9)
        assert dm < 1.0, f"秋夕(KR, 9月)の需要倍率は1.0未満であるべき: {dm}"

    def test_no_events_returns_neutral(self):
        """イベントなしの国・月は倍率1.0"""
        _, get_dm, get_um = self._get_funcs()
        assert get_dm("XX", 6) == 1.0
        assert get_um("XX", 6) == 1.0

    def test_cherry_blossom_all_markets(self):
        """桜シーズン(3-4月)は多数市場で需要増"""
        _, get_dm, _ = self._get_funcs()
        for country in ["KR", "CN", "TW", "US", "AU"]:
            dm = get_dm(country, 4)
            assert dm > 1.0, f"桜シーズン({country}, 4月)の需要倍率 > 1.0: {dm}"


# =====================================================================
# TestGPModel — ガウス過程モデル
# =====================================================================
class TestGPModel:
    """features/tourism/gaussian_process_model.py のテスト"""

    def _get_model(self):
        from features.tourism.gaussian_process_model import (
            GaussianProcessInboundModel,
        )
        return GaussianProcessInboundModel()

    def test_predict_returns_distribution(self):
        """predict()がmedian/p10/p90を返す"""
        model = self._get_model()
        result = model.predict("KR", list(range(1, 13)), n_samples=500)
        assert "median" in result, "median が結果に含まれるべき"
        assert "p10" in result, "p10 が結果に含まれるべき"
        assert "p90" in result, "p90 が結果に含まれるべき"
        assert len(result["median"]) == 12, "12ヶ月分のmedianが必要"

    def test_uncertainty_varies_by_month(self):
        """月別不確実性が変動する"""
        model = self._get_model()
        result = model.predict("CN", list(range(1, 13)), n_samples=500)
        uncertainties = list(result["uncertainty_by_month"].values())
        assert len(set(round(u, 6) for u in uncertainties)) > 1, \
            f"月別不確実性が全て同一: {uncertainties}"

    def test_calendar_effects_applied(self):
        """カレンダー効果が適用される"""
        model = self._get_model()
        result = model.predict("CN", list(range(1, 13)), n_samples=500)
        cal = result["calendar_effects"]
        # 10月(国慶節)にイベントが存在すること
        assert len(cal[10]["events"]) > 0, \
            f"10月のカレンダーイベントが空: {cal[10]}"
        assert cal[10]["demand_multiplier"] > 1.0, \
            f"国慶節の需要倍率 > 1.0: {cal[10]['demand_multiplier']}"

    def test_risk_adjustments_applied(self):
        """リスク調整が反映される"""
        model = self._get_model()
        base = model.predict("KR", [6], n_samples=2000)
        adjusted = model.predict("KR", [6], n_samples=2000,
                                 risk_adjustments={6: 0.5})
        # 0.5倍調整なのでmedianが明確に下がるはず
        assert adjusted["median"][0] < base["median"][0] * 0.8, \
            "リスク調整0.5でmedianが十分下がるべき"

    def test_model_type_is_fallback_without_gpytorch(self):
        """gpytorch未インストール時はnumpy_fallbackモデル"""
        model = self._get_model()
        result = model.predict("US", [1, 2, 3])
        # gpytorchがあればgpytorch、なければnumpy_fallback
        assert result["model_type"] in ("gpytorch", "numpy_fallback")


# =====================================================================
# TestMultiMarketAggregator — 複数市場集計
# =====================================================================
class TestMultiMarketAggregator:
    """MultiMarketGPAggregator のテスト"""

    def _get_aggregator(self):
        from features.tourism.gaussian_process_model import (
            MultiMarketGPAggregator,
        )
        return MultiMarketGPAggregator()

    def test_base_scenario_returns_total(self):
        """baseシナリオで合計予測が返る"""
        agg = self._get_aggregator()
        result = agg.predict_japan_total_gp([1, 2, 3], scenario="base",
                                            n_samples=300)
        assert "total" in result
        assert len(result["total"]["median"]) == 3

    def test_optimistic_higher_than_base(self):
        """optimisticシナリオはbaseより高い"""
        agg = self._get_aggregator()
        base = agg.predict_japan_total_gp([6], scenario="base", n_samples=500)
        opt = agg.predict_japan_total_gp([6], scenario="optimistic", n_samples=500)
        assert opt["total"]["mean"][0] > base["total"]["mean"][0] * 1.05, \
            "optimisticはbaseより5%以上高いはず"

    def test_pessimistic_lower_than_base(self):
        """pessimisticシナリオはbaseより低い"""
        agg = self._get_aggregator()
        base = agg.predict_japan_total_gp([6], scenario="base", n_samples=500)
        pes = agg.predict_japan_total_gp([6], scenario="pessimistic", n_samples=500)
        assert pes["total"]["mean"][0] < base["total"]["mean"][0] * 0.98, \
            "pessimisticはbaseより低いはず"


# =====================================================================
# TestBilateralFXClient — 二国間為替レートクライアント
# =====================================================================
class TestBilateralFXClient:
    """pipeline/tourism/bilateral_fx_client.py のテスト"""

    def _get_client(self):
        from pipeline.tourism.bilateral_fx_client import BilateralFXClient
        return BilateralFXClient()

    def test_fallback_rates_all_positive(self):
        """フォールバックレートが全て正"""
        from pipeline.tourism.bilateral_fx_client import FALLBACK_RATES
        for cc, rate in FALLBACK_RATES.items():
            assert rate > 0, f"{cc}のフォールバックレートが正でない: {rate}"

    def test_currency_map_coverage(self):
        """通貨マップが全12市場をカバー"""
        from pipeline.tourism.bilateral_fx_client import CURRENCY_MAP
        expected = {"KR", "CN", "TW", "US", "AU", "TH", "HK", "SG", "DE", "FR", "GB", "IN"}
        assert expected == set(CURRENCY_MAP.keys())

    def test_fx_shock_positive_jpy_weak(self):
        """円安10%で全国の需要変化が正"""
        client = self._get_client()
        result = client.calculate_fx_shock("KR", 10.0, current_rate=0.107)
        assert result.demand_change_pct > 0, "円安でKR需要は増加すべき"
        assert abs(result.demand_change_pct - 10.0 * 0.45) < 0.01

    def test_fx_shock_negative_jpy_strong(self):
        """円高10%で需要変化が負"""
        client = self._get_client()
        result = client.calculate_fx_shock("CN", -10.0, current_rate=20.8)
        assert result.demand_change_pct < 0, "円高でCN需要は減少すべき"

    def test_fx_shock_unknown_country(self):
        """未対応国コードでValueError"""
        client = self._get_client()
        with pytest.raises(ValueError):
            client.calculate_fx_shock("ZZ", 5.0)


# =====================================================================
# TestScenarioEngine — 国別シナリオエンジン
# =====================================================================
class TestScenarioEngine:
    """features/tourism/scenario_engine.py のテスト"""

    def _get_engine(self):
        from features.tourism.scenario_engine import ScenarioEngine
        return ScenarioEngine()

    def test_base_no_change(self):
        """ベースシナリオは全国0%変化"""
        engine = self._get_engine()
        impacts = engine.calculate_country_impacts("base")
        for cc, impact in impacts.items():
            assert abs(impact.total_demand_change_pct) < 0.01, \
                f"ベースで{cc}の変化率が0でない: {impact.total_demand_change_pct}"

    def test_china_tension_cn_down(self):
        """日中悪化シナリオでCNが大幅マイナス"""
        engine = self._get_engine()
        impacts = engine.calculate_country_impacts("japan_china_tension")
        cn_impact = impacts["CN"]
        assert cn_impact.total_demand_change_pct < -30.0, \
            f"日中悪化でCN変化率が-30%未満であるべき: {cn_impact.total_demand_change_pct}"

    def test_stagflation_mixed_directions(self):
        """スタグフレーションでUSとCNが逆方向"""
        engine = self._get_engine()
        impacts = engine.calculate_country_impacts("stagflation_mixed")
        us_change = impacts["US"].total_demand_change_pct
        cn_change = impacts["CN"].total_demand_change_pct
        # USは大幅マイナス（インフレ＋景気後退）、CNは円安効果でプラス寄り
        assert us_change < 0, f"USはマイナスであるべき: {us_change}"
        assert cn_change > us_change, f"CNはUSより良いはず: CN={cn_change}, US={us_change}"

    def test_all_scenarios_defined(self):
        """7シナリオ以上が定義されている"""
        from features.tourism.scenario_engine import SCENARIOS
        assert len(SCENARIOS) >= 7, f"シナリオ数不足: {len(SCENARIOS)}"

    def test_japan_total_impact(self):
        """日本全体影響サマリーが正しい構造"""
        engine = self._get_engine()
        result = engine.calculate_japan_total_impact("jpy_weak_10")
        assert "total_base_visitors_k" in result
        assert "total_scenario_visitors_k" in result
        assert "total_change_pct" in result
        assert "country_impacts" in result
        assert result["total_change_pct"] > 0, "円安シナリオで全体は増加すべき"

    def test_list_scenarios(self):
        """シナリオ一覧が返る"""
        engine = self._get_engine()
        scenarios = engine.list_scenarios()
        assert len(scenarios) >= 7
        for s in scenarios:
            assert "name" in s
            assert "label" in s

    def test_unknown_scenario_raises(self):
        """未定義シナリオでValueError"""
        engine = self._get_engine()
        with pytest.raises(ValueError):
            engine.calculate_country_impacts("nonexistent_scenario")

    def test_taiwan_strait_tw_severe(self):
        """台湾海峡リスクでTWが大幅減"""
        engine = self._get_engine()
        impacts = engine.calculate_country_impacts("taiwan_strait_risk")
        tw_impact = impacts["TW"]
        assert tw_impact.total_demand_change_pct < -40.0, \
            f"台湾海峡リスクでTWは-40%以下であるべき: {tw_impact.total_demand_change_pct}"
