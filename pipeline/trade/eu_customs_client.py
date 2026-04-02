"""EU Comext (Eurostat) 詳細貿易統計クライアント
欧州域内・域外の二国間貿易フローをHS8レベルで取得。
ImportYetiは米国のみ対象のため、本モジュールで欧州貿易をカバーする。

データソース: Eurostat SDMX REST API
  https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/

月次更新。HS8桁レベルの詳細な輸出入統計を提供。
APIキー不要（レート制限あり）。

使用例::

    client = EUCustomsClient()
    flow = await client.get_bilateral_flow("DE", "CN", "85423100", "2024M01")
    top = await client.get_top_importers("8542", top_n=10)
    balance = await client.get_trade_balance("DE", "CN")
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 15  # 秒
RATE_LIMIT_INTERVAL = 2.0  # 秒（リクエスト間の最小待機時間）
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-intelligence)"

# Eurostat SDMX REST API エンドポイント
EUROSTAT_BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"

# Eurostat Comext データセット
# DS-045409: EU trade since 1988 by HS2-4-6 and CN8
COMEXT_DATASET = "DS-045409"

# EU加盟国 ISO2 → Eurostat reporter コード
EU_REPORTER_CODES: dict[str, str] = {
    "AT": "AT", "BE": "BE", "BG": "BG", "HR": "HR", "CY": "CY",
    "CZ": "CZ", "DK": "DK", "EE": "EE", "FI": "FI", "FR": "FR",
    "DE": "DE", "GR": "EL", "HU": "HU", "IE": "IE", "IT": "IT",
    "LV": "LV", "LT": "LT", "LU": "LU", "MT": "MT", "NL": "NL",
    "PL": "PL", "PT": "PT", "RO": "RO", "SK": "SK", "SI": "SI",
    "ES": "ES", "SE": "SE",
}

# 主要貿易相手国 ISO2 → Eurostat partner コード
PARTNER_CODES: dict[str, str] = {
    "CN": "CN", "US": "US", "JP": "JP", "KR": "KR", "IN": "IN",
    "GB": "GB", "CH": "CH", "RU": "RU", "TR": "TR", "BR": "BR",
    "TW": "TW", "VN": "VN", "TH": "TH", "MY": "MY", "ID": "ID",
    "SG": "SG", "AU": "AU", "CA": "CA", "MX": "MX", "SA": "SA",
    "AE": "AE", "EG": "EG", "ZA": "ZA", "NG": "NG", "BD": "BD",
    "PK": "PK", "PH": "PH", "MM": "MM", "KH": "KH", "UA": "UA",
    "NO": "NO", "IL": "IL", "AR": "AR", "CL": "CL", "PE": "PE",
}


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class EUTradeFlow:
    """EU Comext 二国間貿易フローレコード"""
    reporter_iso2: str
    partner_iso2: str
    hs8_code: str
    period: str  # "2024M01" 形式
    import_value_eur: float
    export_value_eur: float
    quantity_kg: float


# ---------------------------------------------------------------------------
# メインクライアント
# ---------------------------------------------------------------------------
class EUCustomsClient:
    """Eurostat Comext SDMX REST API クライアント

    EU加盟国の二国間貿易データをHS8レベルで取得する。
    SDMX 2.1 REST API を使用し、JSON形式でデータを受信する。

    制限事項:
      - EU加盟国のみレポーターとして利用可能
      - APIレート制限あり（2秒/リクエスト以上の間隔を推奨）
      - 大量データリクエストはタイムアウトの可能性あり
      - API到達不能時は空結果を返し、クラッシュしない

    使用例::

        client = EUCustomsClient()
        flow = await client.get_bilateral_flow("DE", "CN", "85423100")
    """

    BASE_URL = EUROSTAT_BASE_URL

    def __init__(self):
        """クライアントを初期化する。"""
        self._last_request_time: float = 0.0
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.sdmx.data+json;version=1.0.0",
        }

    # ------------------------------------------------------------------
    # レート制限
    # ------------------------------------------------------------------
    async def _rate_limit(self) -> None:
        """リクエスト間のレート制限を適用する。"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < RATE_LIMIT_INTERVAL:
            wait = RATE_LIMIT_INTERVAL - elapsed
            logger.debug("レート制限: %.1f秒待機", wait)
            await asyncio.sleep(wait)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # HTTP リクエスト
    # ------------------------------------------------------------------
    async def _fetch_sdmx(self, resource: str, params: dict | None = None) -> dict:
        """Eurostat SDMX REST API にリクエストを送信する。

        Args:
            resource: API リソースパス
            params: クエリパラメータ

        Returns:
            パースされた JSON レスポンス。エラー時は空辞書。
        """
        await self._rate_limit()
        url = f"{self.BASE_URL}/{resource}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, params=params or {})
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException:
            logger.warning("Eurostat APIタイムアウト: %s", url)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Eurostat API HTTPエラー %d: %s",
                exc.response.status_code, url,
            )
            return {}
        except httpx.HTTPError as exc:
            logger.warning("Eurostat API接続エラー: %s (%s)", exc, url)
            return {}
        except Exception as exc:
            logger.error("Eurostat API予期せぬエラー: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Eurostat JSON-stat / SDMX-JSON パーサー
    # ------------------------------------------------------------------
    def _parse_sdmx_trade_data(
        self,
        data: dict,
        reporter_iso2: str,
        partner_iso2: str,
        hs_code: str,
    ) -> list[EUTradeFlow]:
        """SDMX-JSON レスポンスから EUTradeFlow リストを生成する。

        Eurostat SDMX-JSON のデータ構造に基づいてパースする。
        構造変更時はここを修正する。

        Args:
            data: SDMX-JSON レスポンス辞書
            reporter_iso2: レポーター国ISO2コード
            partner_iso2: パートナー国ISO2コード
            hs_code: HSコード

        Returns:
            EUTradeFlow のリスト
        """
        results: list[EUTradeFlow] = []

        try:
            # SDMX-JSON 構造: dataSets[0].series
            datasets = data.get("dataSets", [])
            if not datasets:
                # Eurostat JSON-stat 形式を試行
                return self._parse_jsonstat_trade_data(
                    data, reporter_iso2, partner_iso2, hs_code
                )

            structure = data.get("structure", {})
            dimensions = structure.get("dimensions", {})
            series_dims = dimensions.get("series", [])
            obs_dims = dimensions.get("observation", [])

            # 期間次元の値を取得
            time_values = []
            for dim in obs_dims:
                if dim.get("id") in ("TIME_PERIOD", "TIME"):
                    time_values = [
                        v.get("id", v.get("name", ""))
                        for v in dim.get("values", [])
                    ]
                    break

            series_data = datasets[0].get("series", {})

            for series_key, series_val in series_data.items():
                observations = series_val.get("observations", {})
                for obs_key, obs_values in observations.items():
                    obs_idx = int(obs_key)
                    period = time_values[obs_idx] if obs_idx < len(time_values) else ""
                    value = obs_values[0] if obs_values else 0.0

                    # フロー方向の判定（シリーズキーから推測）
                    # Comext: FLOW=1 (import), FLOW=2 (export)
                    is_import = "0:" in series_key or series_key.startswith("0")

                    flow = EUTradeFlow(
                        reporter_iso2=reporter_iso2,
                        partner_iso2=partner_iso2,
                        hs8_code=hs_code,
                        period=period,
                        import_value_eur=value if is_import else 0.0,
                        export_value_eur=0.0 if is_import else value,
                        quantity_kg=0.0,
                    )
                    results.append(flow)

        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("SDMX-JSONパースエラー: %s", exc)

        return results

    def _parse_jsonstat_trade_data(
        self,
        data: dict,
        reporter_iso2: str,
        partner_iso2: str,
        hs_code: str,
    ) -> list[EUTradeFlow]:
        """JSON-stat 形式のレスポンスをパースする（フォールバック）。"""
        results: list[EUTradeFlow] = []

        try:
            # JSON-stat 形式: value[], dimension.time.category.index
            values = data.get("value", [])
            if not values:
                return results

            time_dim = data.get("dimension", {}).get("time", {})
            time_index = time_dim.get("category", {}).get("index", {})

            # 期間とインデックスの逆引きマップ
            idx_to_period = {v: k for k, v in time_index.items()}

            for idx, val in enumerate(values):
                if val is None:
                    continue
                period = idx_to_period.get(idx, "")
                flow = EUTradeFlow(
                    reporter_iso2=reporter_iso2,
                    partner_iso2=partner_iso2,
                    hs8_code=hs_code,
                    period=period,
                    import_value_eur=float(val),
                    export_value_eur=0.0,
                    quantity_kg=0.0,
                )
                results.append(flow)

        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("JSON-statパースエラー: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Eurostat Comext REST API クエリ構築
    # ------------------------------------------------------------------
    def _build_comext_query(
        self,
        reporter: str,
        partner: str,
        hs_code: str,
        period: str = "",
        flow: str = "",
    ) -> str:
        """Comext データセットのSDMXクエリパスを構築する。

        Eurostat SDMX REST API のデータフロークエリ形式:
        data/{flowRef}/{key}?{params}

        Key structure for Comext (DS-045409):
        REPORTER.PARTNER.PRODUCT.FLOW.INDICATORS

        Args:
            reporter: レポーター国コード
            partner: パートナー国コード
            hs_code: HS商品コード
            period: 期間フィルタ（例: "2024M01"）
            flow: フロー方向（"1"=import, "2"=export, ""=both）

        Returns:
            SDMX REST API クエリ文字列
        """
        # Eurostat レポーターコードに変換
        reporter_code = EU_REPORTER_CODES.get(
            reporter.upper(), reporter.upper()
        )
        partner_code = PARTNER_CODES.get(
            partner.upper(), partner.upper()
        )

        # HS コード正規化（ドット除去）
        hs_clean = hs_code.replace(".", "").replace(" ", "")

        # SDMX key: REPORTER.PARTNER.PRODUCT.FLOW.INDICATORS
        flow_code = flow if flow else "1+2"  # 1=import, 2=export
        key = f"{reporter_code}.{partner_code}.{hs_clean}.{flow_code}.VALUE_IN_EUROS"

        resource = f"data/{COMEXT_DATASET}/{key}"

        return resource

    # ------------------------------------------------------------------
    # 公開 API メソッド
    # ------------------------------------------------------------------
    async def get_bilateral_flow(
        self,
        reporter: str,
        partner: str,
        hs8: str,
        period: str = "",
    ) -> EUTradeFlow:
        """二国間貿易フローを取得する。

        指定されたレポーター国とパートナー国間の、特定のHS8商品コードに
        おける貿易フロー（輸入・輸出額）を取得する。

        Args:
            reporter: レポーター国ISO2コード（EU加盟国、例: "DE"）
            partner: パートナー国ISO2コード（例: "CN"）
            hs8: HS8桁商品コード（例: "85423100"）
            period: 期間（例: "2024M01"）。空の場合は最新データ

        Returns:
            EUTradeFlow データクラス。API取得失敗時は空のレコードを返す。
        """
        empty_flow = EUTradeFlow(
            reporter_iso2=reporter.upper(),
            partner_iso2=partner.upper(),
            hs8_code=hs8,
            period=period or "unknown",
            import_value_eur=0.0,
            export_value_eur=0.0,
            quantity_kg=0.0,
        )

        try:
            resource = self._build_comext_query(reporter, partner, hs8)
            params = {}
            if period:
                params["startPeriod"] = period
                params["endPeriod"] = period

            data = await self._fetch_sdmx(resource, params)
            if not data:
                logger.warning(
                    "Eurostat Comext: データ取得失敗 (%s→%s, HS=%s)",
                    reporter, partner, hs8,
                )
                return empty_flow

            flows = self._parse_sdmx_trade_data(
                data, reporter.upper(), partner.upper(), hs8
            )

            if not flows:
                logger.info(
                    "Eurostat Comext: 該当データなし (%s→%s, HS=%s)",
                    reporter, partner, hs8,
                )
                return empty_flow

            # 同一期間のimport/exportを統合
            combined_import = sum(f.import_value_eur for f in flows)
            combined_export = sum(f.export_value_eur for f in flows)
            combined_qty = sum(f.quantity_kg for f in flows)
            result_period = flows[0].period or period or "latest"

            return EUTradeFlow(
                reporter_iso2=reporter.upper(),
                partner_iso2=partner.upper(),
                hs8_code=hs8,
                period=result_period,
                import_value_eur=combined_import,
                export_value_eur=combined_export,
                quantity_kg=combined_qty,
            )

        except Exception as exc:
            logger.error(
                "Eurostat Comext 二国間貿易取得エラー: %s (%s→%s, HS=%s)",
                exc, reporter, partner, hs8,
            )
            return empty_flow

    async def get_top_importers(
        self,
        hs_code: str,
        top_n: int = 10,
    ) -> list[dict]:
        """指定HS商品コードの上位輸入国を取得する。

        EU全体としての主要輸入元を特定する。
        全EU加盟国のデータを集約し、上位N件を返す。

        Args:
            hs_code: HS商品コード（4-8桁、例: "8542"）
            top_n: 取得する上位件数（デフォルト10）

        Returns:
            輸入国情報の辞書リスト。各辞書は以下のキーを含む:
            - partner_iso2: パートナー国ISO2コード
            - total_import_eur: 輸入総額（EUR）
            - reporter_count: データを報告したEU加盟国数
        """
        try:
            # EU全体（EU27_2020）をレポーターとして使用
            hs_clean = hs_code.replace(".", "").replace(" ", "")
            resource = f"data/{COMEXT_DATASET}/EU27_2020..{hs_clean}.1.VALUE_IN_EUROS"

            data = await self._fetch_sdmx(resource)
            if not data:
                logger.warning(
                    "Eurostat Comext: 上位輸入元データ取得失敗 (HS=%s)", hs_code,
                )
                return []

            # パートナー国別に集計
            partner_totals: dict[str, float] = {}
            try:
                datasets = data.get("dataSets", [])
                if datasets:
                    series_data = datasets[0].get("series", {})
                    structure = data.get("structure", {})
                    dimensions = structure.get("dimensions", {})
                    series_dims = dimensions.get("series", [])

                    # パートナー次元の値を特定
                    partner_values = []
                    partner_dim_idx = -1
                    for idx, dim in enumerate(series_dims):
                        if dim.get("id") in ("PARTNER", "partner"):
                            partner_values = [
                                v.get("id", "") for v in dim.get("values", [])
                            ]
                            partner_dim_idx = idx
                            break

                    for series_key, series_val in series_data.items():
                        # シリーズキーからパートナーインデックスを抽出
                        key_parts = series_key.split(":")
                        if partner_dim_idx >= 0 and partner_dim_idx < len(key_parts):
                            p_idx = int(key_parts[partner_dim_idx])
                            if p_idx < len(partner_values):
                                partner = partner_values[p_idx]
                            else:
                                partner = f"UNKNOWN_{p_idx}"
                        else:
                            partner = "UNKNOWN"

                        # 観測値を合計
                        observations = series_val.get("observations", {})
                        total_val = sum(
                            obs[0] for obs in observations.values()
                            if obs and obs[0] is not None
                        )
                        partner_totals[partner] = (
                            partner_totals.get(partner, 0.0) + total_val
                        )

            except (KeyError, IndexError, TypeError) as exc:
                logger.debug("上位輸入元パースエラー: %s", exc)

            if not partner_totals:
                return []

            # 上位N件をソート
            sorted_partners = sorted(
                partner_totals.items(), key=lambda x: x[1], reverse=True
            )[:top_n]

            results = []
            for partner_code, total_eur in sorted_partners:
                results.append({
                    "partner_iso2": partner_code,
                    "total_import_eur": total_eur,
                    "hs_code": hs_code,
                    "reporter": "EU27",
                })

            logger.info(
                "Eurostat Comext: 上位輸入元 %d件取得 (HS=%s)",
                len(results), hs_code,
            )
            return results

        except Exception as exc:
            logger.error(
                "Eurostat Comext 上位輸入元取得エラー: %s (HS=%s)", exc, hs_code,
            )
            return []

    async def get_trade_balance(
        self,
        reporter: str,
        partner: str,
    ) -> dict:
        """二国間の貿易収支を取得する。

        レポーター国とパートナー国間の全品目合計の
        輸出入額と貿易収支を算出する。

        Args:
            reporter: レポーター国ISO2コード（EU加盟国）
            partner: パートナー国ISO2コード

        Returns:
            貿易収支情報の辞書:
            - reporter: レポーター国
            - partner: パートナー国
            - total_import_eur: 輸入総額（EUR）
            - total_export_eur: 輸出総額（EUR）
            - balance_eur: 貿易収支（EUR, 正=黒字）
            - data_source: データソース
        """
        default_result = {
            "reporter": reporter.upper(),
            "partner": partner.upper(),
            "total_import_eur": 0.0,
            "total_export_eur": 0.0,
            "balance_eur": 0.0,
            "data_source": "eurostat_comext",
        }

        try:
            reporter_code = EU_REPORTER_CODES.get(
                reporter.upper(), reporter.upper()
            )
            partner_code = PARTNER_CODES.get(
                partner.upper(), partner.upper()
            )

            # 全品目（TOTAL）の輸入・輸出を取得
            resource = (
                f"data/{COMEXT_DATASET}/"
                f"{reporter_code}.{partner_code}.TOTAL.1+2.VALUE_IN_EUROS"
            )

            data = await self._fetch_sdmx(resource)
            if not data:
                logger.warning(
                    "Eurostat Comext: 貿易収支データ取得失敗 (%s→%s)",
                    reporter, partner,
                )
                return default_result

            # インポート/エクスポート値を抽出
            total_import = 0.0
            total_export = 0.0

            try:
                datasets = data.get("dataSets", [])
                if datasets:
                    series_data = datasets[0].get("series", {})
                    for series_key, series_val in series_data.items():
                        observations = series_val.get("observations", {})
                        total_val = sum(
                            obs[0] for obs in observations.values()
                            if obs and obs[0] is not None
                        )
                        # フロー方向: シリーズキーの位置でインポート/エクスポートを判定
                        key_parts = series_key.split(":")
                        # フロー=1はimport、フロー=2はexport
                        if "0" in key_parts[-2:]:
                            total_import += total_val
                        else:
                            total_export += total_val

            except (KeyError, IndexError, TypeError) as exc:
                logger.debug("貿易収支パースエラー: %s", exc)

            balance = total_export - total_import

            result = {
                "reporter": reporter.upper(),
                "partner": partner.upper(),
                "total_import_eur": total_import,
                "total_export_eur": total_export,
                "balance_eur": balance,
                "data_source": "eurostat_comext",
            }

            logger.info(
                "Eurostat Comext: 貿易収支取得完了 (%s→%s: 収支=%.0f EUR)",
                reporter, partner, balance,
            )
            return result

        except Exception as exc:
            logger.error(
                "Eurostat Comext 貿易収支取得エラー: %s (%s→%s)",
                exc, reporter, partner,
            )
            return default_result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
    async def get_time_series(
        self,
        reporter: str,
        partner: str,
        hs_code: str,
        start_period: str = "",
        end_period: str = "",
    ) -> list[EUTradeFlow]:
        """二国間貿易フローの月次時系列を取得する。

        指定期間のHS商品コードにおける貿易フロー月次データを返す。
        前年同月比の変動把握やトレンド分析に使用する。

        Args:
            reporter: レポーター国ISO2コード（EU加盟国、例: "DE"）
            partner: パートナー国ISO2コード（例: "CN"）
            hs_code: HS商品コード（4-8桁）
            start_period: 開始期間（例: "2023M01"）。空=最新12ヶ月
            end_period: 終了期間（例: "2024M12"）。空=最新月

        Returns:
            EUTradeFlow のリスト（期間昇順）。取得失敗時は空リスト。
        """
        try:
            resource = self._build_comext_query(reporter, partner, hs_code)
            params: dict[str, str] = {}
            if start_period:
                params["startPeriod"] = start_period
            if end_period:
                params["endPeriod"] = end_period

            data = await self._fetch_sdmx(resource, params)
            if not data:
                logger.warning(
                    "Eurostat Comext: 時系列データ取得失敗 (%s→%s, HS=%s)",
                    reporter, partner, hs_code,
                )
                return []

            flows = self._parse_sdmx_trade_data(
                data, reporter.upper(), partner.upper(), hs_code,
            )

            # 同一期間の import/export を統合
            period_map: dict[str, dict] = {}
            for f in flows:
                key = f.period
                if key not in period_map:
                    period_map[key] = {
                        "import": 0.0, "export": 0.0, "qty": 0.0,
                    }
                period_map[key]["import"] += f.import_value_eur
                period_map[key]["export"] += f.export_value_eur
                period_map[key]["qty"] += f.quantity_kg

            results: list[EUTradeFlow] = []
            for period, vals in sorted(period_map.items()):
                results.append(EUTradeFlow(
                    reporter_iso2=reporter.upper(),
                    partner_iso2=partner.upper(),
                    hs8_code=hs_code,
                    period=period,
                    import_value_eur=vals["import"],
                    export_value_eur=vals["export"],
                    quantity_kg=vals["qty"],
                ))

            logger.info(
                "Eurostat Comext: 時系列 %d期間取得 (%s→%s, HS=%s)",
                len(results), reporter, partner, hs_code,
            )
            return results

        except Exception as exc:
            logger.error(
                "Eurostat Comext 時系列取得エラー: %s (%s→%s, HS=%s)",
                exc, reporter, partner, hs_code,
            )
            return []

    async def get_yoy_change(
        self,
        reporter: str,
        partner: str,
        hs_code: str,
        period: str = "",
    ) -> dict:
        """二国間貿易の前年同月比を算出する。

        輸入・輸出それぞれの前年同月比変動率を返す。
        急激な貿易量変動の検出に使用する。

        Args:
            reporter: レポーター国ISO2コード
            partner: パートナー国ISO2コード
            hs_code: HS商品コード（4-8桁）
            period: 基準期間（例: "2025M01"）。空=最新

        Returns:
            前年同月比情報の辞書:
            - period: 基準期間
            - prev_period: 前年同月
            - import_change_pct: 輸入額変動率（%）
            - export_change_pct: 輸出額変動率（%）
            - alert: 急変フラグ（変動率>50%時にTrue）
        """
        default_result = {
            "reporter": reporter.upper(),
            "partner": partner.upper(),
            "hs_code": hs_code,
            "period": period or "latest",
            "prev_period": "",
            "import_change_pct": 0.0,
            "export_change_pct": 0.0,
            "alert": False,
            "data_source": "eurostat_comext",
        }

        try:
            # 基準期間と前年同月の計算
            if period and "M" in period:
                year = int(period.split("M")[0])
                month = int(period.split("M")[1])
                prev_period = f"{year - 1}M{month:02d}"
            else:
                # 最新月=2か月前と仮定、前年同月はその12か月前
                from datetime import datetime as dt
                now = dt.now()
                base_month = now.month - 2 if now.month > 2 else now.month + 10
                base_year = now.year if now.month > 2 else now.year - 1
                period = f"{base_year}M{base_month:02d}"
                prev_period = f"{base_year - 1}M{base_month:02d}"

            default_result["period"] = period
            default_result["prev_period"] = prev_period

            current = await self.get_bilateral_flow(
                reporter, partner, hs_code, period,
            )
            previous = await self.get_bilateral_flow(
                reporter, partner, hs_code, prev_period,
            )

            # 変動率の計算
            imp_change = 0.0
            if previous.import_value_eur > 0:
                imp_change = (
                    (current.import_value_eur - previous.import_value_eur)
                    / previous.import_value_eur * 100
                )
            exp_change = 0.0
            if previous.export_value_eur > 0:
                exp_change = (
                    (current.export_value_eur - previous.export_value_eur)
                    / previous.export_value_eur * 100
                )

            default_result["import_change_pct"] = round(imp_change, 2)
            default_result["export_change_pct"] = round(exp_change, 2)
            default_result["alert"] = (
                abs(imp_change) > 50 or abs(exp_change) > 50
            )

            logger.info(
                "Eurostat Comext: YoY変動算出完了 (%s→%s, HS=%s, imp=%.1f%%, exp=%.1f%%)",
                reporter, partner, hs_code, imp_change, exp_change,
            )
            return default_result

        except Exception as exc:
            logger.error(
                "Eurostat Comext YoY変動算出エラー: %s (%s→%s, HS=%s)",
                exc, reporter, partner, hs_code,
            )
            return default_result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
async def get_eu_trade_flow(
    reporter: str, partner: str, hs8: str, period: str = "",
) -> EUTradeFlow:
    """EU二国間貿易フロー取得のショートカット関数。"""
    client = EUCustomsClient()
    return await client.get_bilateral_flow(reporter, partner, hs8, period)


async def get_eu_trade_yoy(
    reporter: str, partner: str, hs_code: str, period: str = "",
) -> dict:
    """EU貿易 前年同月比取得のショートカット関数。"""
    client = EUCustomsClient()
    return await client.get_yoy_change(reporter, partner, hs_code, period)


# ---------------------------------------------------------------------------
# メイン（動作確認用）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def _demo():
        print("=" * 60)
        print("EU Comext (Eurostat) 貿易統計クライアント -- 動作確認")
        print("=" * 60)

        client = EUCustomsClient()

        print("\n--- 二国間貿易フロー (DE->CN, HS 85423100) ---")
        flow = await client.get_bilateral_flow("DE", "CN", "85423100")
        print(f"  輸入額: {flow.import_value_eur:,.0f} EUR")
        print(f"  輸出額: {flow.export_value_eur:,.0f} EUR")
        print(f"  期間: {flow.period}")

        print("\n--- 上位輸入元 (HS 8542) ---")
        top = await client.get_top_importers("8542", top_n=5)
        for item in top:
            print(f"  {item['partner_iso2']}: {item['total_import_eur']:,.0f} EUR")

        print("\n--- 貿易収支 (DE <-> CN) ---")
        balance = await client.get_trade_balance("DE", "CN")
        print(f"  輸入: {balance['total_import_eur']:,.0f} EUR")
        print(f"  輸出: {balance['total_export_eur']:,.0f} EUR")
        print(f"  収支: {balance['balance_eur']:,.0f} EUR")

    asyncio.run(_demo())
