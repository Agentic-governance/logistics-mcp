"""財務省貿易統計 (Japan Customs) クライアント
e-Stat API を通じて日本の輸出入統計をHS9レベルで取得する。

データソース: e-Stat API (政府統計の総合窓口)
  https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData

財務省貿易統計は日本の通関データを月次で提供。
HS9桁レベル（日本固有の細分類）の詳細な統計が利用可能。

利用にはe-Stat APIキーが必要（無料、登録制）。
環境変数 ESTAT_API_KEY で設定する。

使用例::

    client = JapanCustomsClient()
    imports = await client.get_import_by_hs("854231000", "202401")
    exports = await client.get_export_by_hs("854231000")
    top = await client.get_top_import_sources("8542", top_n=10)
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

# e-Stat API エンドポイント
ESTAT_API_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

# 財務省貿易統計の統計表ID
# 品別国別: 輸入 → statsDataId varies by year/month
# 品別国別: 輸出 → statsDataId varies by year/month
# 確報データの代表的なID（動的に調整が必要な場合あり）
TRADE_STATS_IMPORT_TABLE = "0003127794"  # 品別国別品(HS9桁) - 輸入
TRADE_STATS_EXPORT_TABLE = "0003127793"  # 品別国別品(HS9桁) - 輸出

# 国名→ISO3コード変換
JAPAN_COUNTRY_TO_ISO3: dict[str, str] = {
    "中華人民共和国": "CHN", "中国": "CHN",
    "アメリカ合衆国": "USA", "米国": "USA",
    "大韓民国": "KOR", "韓国": "KOR",
    "台湾": "TWN",
    "ドイツ": "DEU",
    "タイ": "THA",
    "ベトナム": "VNM",
    "インドネシア": "IDN",
    "マレーシア": "MYS",
    "シンガポール": "SGP",
    "フィリピン": "PHL",
    "インド": "IND",
    "オーストラリア": "AUS",
    "カナダ": "CAN",
    "メキシコ": "MEX",
    "ブラジル": "BRA",
    "英国": "GBR", "イギリス": "GBR",
    "フランス": "FRA",
    "イタリア": "ITA",
    "オランダ": "NLD",
    "スイス": "CHE",
    "ロシア": "RUS", "ロシア連邦": "RUS",
    "サウジアラビア": "SAU",
    "アラブ首長国連邦": "ARE",
    "トルコ": "TUR",
    "バングラデシュ": "BGD",
    "パキスタン": "PAK",
    "ミャンマー": "MMR",
    "カンボジア": "KHM",
    "エジプト": "EGY",
    "南アフリカ共和国": "ZAF",
    "ナイジェリア": "NGA",
    "ケニア": "KEN",
    "ウクライナ": "UKR",
    "ポーランド": "POL",
    "スウェーデン": "SWE",
    "チェコ": "CZE",
    "ハンガリー": "HUN",
    "香港": "HKG",
    "ニュージーランド": "NZL",
    "イスラエル": "ISR",
    "チリ": "CHL",
    "アルゼンチン": "ARG",
    "ペルー": "PER",
    "コロンビア": "COL",
    "イラン": "IRN",
    "イラク": "IRQ",
    "世界": "WLD",
    "総額": "WLD",
}


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class JapanTradeRecord:
    """日本の貿易統計レコード（1件）"""
    hs_code: str
    country_name: str
    country_iso3: str
    year_month: str  # "202401" 形式
    import_value_jpy: int
    export_value_jpy: int
    quantity: float
    unit: str


# ---------------------------------------------------------------------------
# ユーティリティ関数
# ---------------------------------------------------------------------------
def _resolve_country_iso3(country_name: str) -> str:
    """日本語国名をISO3コードに変換する。

    Args:
        country_name: 日本語国名（例: "中華人民共和国"）

    Returns:
        ISO3コード（例: "CHN"）。不明時は入力をそのまま返す。
    """
    if not country_name:
        return ""
    # 完全一致
    name = country_name.strip()
    if name in JAPAN_COUNTRY_TO_ISO3:
        return JAPAN_COUNTRY_TO_ISO3[name]
    # 部分一致
    for jp_name, iso3 in JAPAN_COUNTRY_TO_ISO3.items():
        if jp_name in name or name in jp_name:
            return iso3
    # 既にISO3形式の場合
    if len(name) == 3 and name.isalpha():
        return name.upper()
    return name


# ---------------------------------------------------------------------------
# メインクライアント
# ---------------------------------------------------------------------------
class JapanCustomsClient:
    """財務省貿易統計 (e-Stat API) クライアント

    e-Stat API を使用して日本の輸出入統計を取得する。
    HS9桁レベルの詳細な品別国別貿易データが利用可能。

    制限事項:
      - e-Stat APIキーが必要（環境変数 ESTAT_API_KEY）
      - APIキー未設定時はダミーデータを返す
      - レート制限あり（2秒/リクエスト以上の間隔を推奨）
      - 統計表IDは年度によって変更される可能性がある
      - API到達不能時は空結果を返し、クラッシュしない

    使用例::

        client = JapanCustomsClient()
        imports = await client.get_import_by_hs("854231000", "202401")
    """

    def __init__(self, api_key: str = ""):
        """クライアントを初期化する。

        Args:
            api_key: e-Stat APIキー。空の場合は環境変数 ESTAT_API_KEY を参照。
        """
        self._api_key = api_key or os.getenv("ESTAT_API_KEY", "")
        self._last_request_time: float = 0.0
        self._headers = {
            "User-Agent": USER_AGENT,
        }
        if not self._api_key:
            logger.warning(
                "e-Stat APIキー未設定: ESTAT_API_KEY 環境変数を設定してください。"
                "APIキーなしではデータ取得が制限されます。"
            )

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
    async def _fetch_estat(self, params: dict) -> dict:
        """e-Stat API にリクエストを送信する。

        Args:
            params: クエリパラメータ

        Returns:
            パースされた JSON レスポンス。エラー時は空辞書。
        """
        if not self._api_key:
            logger.warning("e-Stat APIキー未設定: リクエストをスキップ")
            return {}

        await self._rate_limit()

        # APIキーをパラメータに追加
        params["appId"] = self._api_key

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(ESTAT_API_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()

                # e-Stat API エラーチェック
                result_info = (
                    data.get("GET_STATS_DATA", {})
                    .get("RESULT", {})
                )
                status = result_info.get("STATUS", 0)
                if int(status) != 0:
                    error_msg = result_info.get("ERROR_MSG", "不明なエラー")
                    logger.warning(
                        "e-Stat APIエラー (status=%s): %s", status, error_msg,
                    )
                    return {}

                return data

        except httpx.TimeoutException:
            logger.warning("e-Stat APIタイムアウト")
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "e-Stat API HTTPエラー %d", exc.response.status_code,
            )
            return {}
        except httpx.HTTPError as exc:
            logger.warning("e-Stat API接続エラー: %s", exc)
            return {}
        except Exception as exc:
            logger.error("e-Stat API予期せぬエラー: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # レスポンスパーサー
    # ------------------------------------------------------------------
    def _parse_trade_records(
        self,
        data: dict,
        trade_type: str = "import",
    ) -> list[JapanTradeRecord]:
        """e-Stat API レスポンスから JapanTradeRecord リストを生成する。

        Args:
            data: e-Stat API JSON レスポンス
            trade_type: "import" または "export"

        Returns:
            JapanTradeRecord のリスト
        """
        results: list[JapanTradeRecord] = []

        try:
            stats_data = data.get("GET_STATS_DATA", {})
            statistical_data = stats_data.get("STATISTICAL_DATA", {})

            # 分類情報の取得
            class_info = statistical_data.get("CLASS_INF", {})
            class_obj = class_info.get("CLASS_OBJ", [])

            # 分類コード→ラベルのマッピング構築
            category_maps: dict[str, dict[str, str]] = {}
            if isinstance(class_obj, dict):
                class_obj = [class_obj]
            for cls in class_obj:
                cls_id = cls.get("@id", "")
                categories = cls.get("CLASS", [])
                if isinstance(categories, dict):
                    categories = [categories]
                cat_map = {}
                for cat in categories:
                    code = cat.get("@code", "")
                    name = cat.get("@name", "")
                    cat_map[code] = name
                category_maps[cls_id] = cat_map

            # データ値の取得
            data_inf = statistical_data.get("DATA_INF", {})
            values = data_inf.get("VALUE", [])
            if isinstance(values, dict):
                values = [values]

            for val in values:
                # 各次元のコードを取得
                hs_code = ""
                country_name = ""
                year_month = ""
                unit = ""

                # e-Stat の次元フィールドは @cat01, @cat02, ... @time 等
                for key, code in val.items():
                    if key.startswith("@") and key != "@unit" and key != "$":
                        dim_id = key[1:]  # "@cat01" -> "cat01"
                        if dim_id in category_maps:
                            label = category_maps[dim_id].get(
                                str(code), str(code)
                            )
                            # HSコード次元の特定（数字で始まるコード）
                            if (
                                str(code).replace(".", "").isdigit()
                                and len(str(code)) >= 4
                            ):
                                hs_code = str(code)
                            # 国名次元の特定
                            elif any(
                                c in label
                                for c in ["国", "州", "連邦", "共和"]
                            ) or label in JAPAN_COUNTRY_TO_ISO3:
                                country_name = label
                        elif dim_id == "time":
                            # 時間次元: "2024000101" → "202401"
                            time_str = str(code)
                            if len(time_str) >= 6:
                                year_month = time_str[:6]
                            else:
                                year_month = time_str

                # 値の取得
                raw_value = val.get("$", "0")
                try:
                    numeric_value = int(
                        str(raw_value).replace(",", "").replace("-", "0")
                    )
                except (ValueError, TypeError):
                    numeric_value = 0

                unit = val.get("@unit", "千円")

                # 千円単位→円単位に変換
                if "千円" in unit:
                    numeric_value *= 1000

                record = JapanTradeRecord(
                    hs_code=hs_code,
                    country_name=country_name,
                    country_iso3=_resolve_country_iso3(country_name),
                    year_month=year_month,
                    import_value_jpy=numeric_value if trade_type == "import" else 0,
                    export_value_jpy=numeric_value if trade_type == "export" else 0,
                    quantity=0.0,
                    unit=unit,
                )
                results.append(record)

        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("e-Stat レスポンスパースエラー: %s", exc)

        return results

    # ------------------------------------------------------------------
    # 公開 API メソッド
    # ------------------------------------------------------------------
    async def get_import_by_hs(
        self,
        hs_code: str,
        year_month: str = "",
    ) -> list[JapanTradeRecord]:
        """HS商品コード別の輸入データを取得する。

        指定HSコードに対する日本の国別輸入額を取得する。

        Args:
            hs_code: HS商品コード（4-9桁、例: "854231000"）
            year_month: 対象年月（例: "202401"）。空の場合は最新データ

        Returns:
            JapanTradeRecord のリスト。取得失敗時は空リスト。
        """
        try:
            params = {
                "lang": "J",
                "statsDataId": TRADE_STATS_IMPORT_TABLE,
                "metaGetFlg": "Y",
                "cntGetFlg": "N",
                "explanationGetFlg": "N",
                "annotationGetFlg": "N",
                "sectionHeaderFlg": "1",
                "replaceSpChars": "0",
            }

            # HSコードフィルタ
            hs_clean = hs_code.replace(".", "").replace(" ", "")
            if hs_clean:
                # e-Stat の品目コードフィルタ
                params["cdCat01From"] = hs_clean
                params["cdCat01To"] = hs_clean + "9" * (9 - len(hs_clean))

            # 期間フィルタ
            if year_month:
                params["cdTime"] = year_month
                params["cdTimeFrom"] = year_month
                params["cdTimeTo"] = year_month

            data = await self._fetch_estat(params)
            if not data:
                logger.warning(
                    "財務省貿易統計: 輸入データ取得失敗 (HS=%s)", hs_code,
                )
                return []

            records = self._parse_trade_records(data, "import")

            # HSコードでフィルタ（パース結果のバリデーション）
            if hs_clean:
                records = [
                    r for r in records
                    if r.hs_code.startswith(hs_clean[:4])
                ]

            logger.info(
                "財務省貿易統計: 輸入データ %d件取得 (HS=%s)",
                len(records), hs_code,
            )
            return records

        except Exception as exc:
            logger.error(
                "財務省貿易統計 輸入データ取得エラー: %s (HS=%s)", exc, hs_code,
            )
            return []

    async def get_export_by_hs(
        self,
        hs_code: str,
        year_month: str = "",
    ) -> list[JapanTradeRecord]:
        """HS商品コード別の輸出データを取得する。

        指定HSコードに対する日本の国別輸出額を取得する。

        Args:
            hs_code: HS商品コード（4-9桁、例: "854231000"）
            year_month: 対象年月（例: "202401"）。空の場合は最新データ

        Returns:
            JapanTradeRecord のリスト。取得失敗時は空リスト。
        """
        try:
            params = {
                "lang": "J",
                "statsDataId": TRADE_STATS_EXPORT_TABLE,
                "metaGetFlg": "Y",
                "cntGetFlg": "N",
                "explanationGetFlg": "N",
                "annotationGetFlg": "N",
                "sectionHeaderFlg": "1",
                "replaceSpChars": "0",
            }

            hs_clean = hs_code.replace(".", "").replace(" ", "")
            if hs_clean:
                params["cdCat01From"] = hs_clean
                params["cdCat01To"] = hs_clean + "9" * (9 - len(hs_clean))

            if year_month:
                params["cdTime"] = year_month
                params["cdTimeFrom"] = year_month
                params["cdTimeTo"] = year_month

            data = await self._fetch_estat(params)
            if not data:
                logger.warning(
                    "財務省貿易統計: 輸出データ取得失敗 (HS=%s)", hs_code,
                )
                return []

            records = self._parse_trade_records(data, "export")

            if hs_clean:
                records = [
                    r for r in records
                    if r.hs_code.startswith(hs_clean[:4])
                ]

            logger.info(
                "財務省貿易統計: 輸出データ %d件取得 (HS=%s)",
                len(records), hs_code,
            )
            return records

        except Exception as exc:
            logger.error(
                "財務省貿易統計 輸出データ取得エラー: %s (HS=%s)", exc, hs_code,
            )
            return []

    async def get_top_import_sources(
        self,
        hs_code: str,
        top_n: int = 10,
    ) -> list[dict]:
        """指定HS商品コードの上位輸入元国を取得する。

        日本の輸入データを国別に集計し、上位N件を返す。

        Args:
            hs_code: HS商品コード（4-9桁）
            top_n: 取得する上位件数（デフォルト10）

        Returns:
            輸入元国情報の辞書リスト。各辞書のキー:
            - country_name: 国名（日本語）
            - country_iso3: ISO3コード
            - import_value_jpy: 輸入額（円）
            - share_pct: シェア（%）
        """
        try:
            records = await self.get_import_by_hs(hs_code)
            if not records:
                return []

            # 国別に集計
            country_totals: dict[str, dict] = {}
            for rec in records:
                if not rec.country_name or rec.country_iso3 == "WLD":
                    continue
                key = rec.country_iso3 or rec.country_name
                if key not in country_totals:
                    country_totals[key] = {
                        "country_name": rec.country_name,
                        "country_iso3": rec.country_iso3,
                        "import_value_jpy": 0,
                    }
                country_totals[key]["import_value_jpy"] += rec.import_value_jpy

            if not country_totals:
                return []

            # 合計の算出
            total_jpy = sum(
                c["import_value_jpy"] for c in country_totals.values()
            )

            # 上位N件をソート
            sorted_countries = sorted(
                country_totals.values(),
                key=lambda x: x["import_value_jpy"],
                reverse=True,
            )[:top_n]

            results = []
            for country in sorted_countries:
                share = (
                    (country["import_value_jpy"] / total_jpy * 100)
                    if total_jpy > 0 else 0.0
                )
                results.append({
                    "country_name": country["country_name"],
                    "country_iso3": country["country_iso3"],
                    "import_value_jpy": country["import_value_jpy"],
                    "share_pct": round(share, 2),
                    "hs_code": hs_code,
                })

            logger.info(
                "財務省貿易統計: 上位輸入元 %d件取得 (HS=%s)",
                len(results), hs_code,
            )
            return results

        except Exception as exc:
            logger.error(
                "財務省貿易統計 上位輸入元取得エラー: %s (HS=%s)", exc, hs_code,
            )
            return []


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
    async def get_bilateral_flow(
        self,
        partner_iso3: str,
        hs_code: str,
        year_month: str = "",
    ) -> dict:
        """特定相手国との二国間貿易フローを取得する。

        指定HSコードにおける日本と相手国間の輸出入両方の
        データを統合して返す。

        Args:
            partner_iso3: 相手国ISO3コード（例: "CHN"）
            hs_code: HS商品コード（4-9桁）
            year_month: 対象年月（例: "202401"）。空=最新

        Returns:
            二国間貿易フロー辞書:
            - partner_iso3: 相手国コード
            - hs_code: HSコード
            - year_month: 対象年月
            - import_value_jpy: 輸入額（円）
            - export_value_jpy: 輸出額（円）
            - balance_jpy: 貿易収支（正=黒字）
        """
        result = {
            "partner_iso3": partner_iso3.upper(),
            "hs_code": hs_code,
            "year_month": year_month or "latest",
            "import_value_jpy": 0,
            "export_value_jpy": 0,
            "balance_jpy": 0,
            "data_source": "e-stat_japan_customs",
        }

        try:
            imports = await self.get_import_by_hs(hs_code, year_month)
            exports = await self.get_export_by_hs(hs_code, year_month)

            # 相手国でフィルタ
            partner = partner_iso3.upper()
            imp_total = sum(
                r.import_value_jpy for r in imports
                if r.country_iso3 == partner
            )
            exp_total = sum(
                r.export_value_jpy for r in exports
                if r.country_iso3 == partner
            )

            result["import_value_jpy"] = imp_total
            result["export_value_jpy"] = exp_total
            result["balance_jpy"] = exp_total - imp_total

            logger.info(
                "財務省貿易統計: 二国間フロー取得完了 (JP↔%s, HS=%s)",
                partner_iso3, hs_code,
            )
            return result

        except Exception as exc:
            logger.error(
                "財務省貿易統計 二国間フロー取得エラー: %s (JP↔%s, HS=%s)",
                exc, partner_iso3, hs_code,
            )
            return result

    async def get_yoy_change(
        self,
        hs_code: str,
        year_month: str = "",
    ) -> dict:
        """輸入額の前年同月比変動を算出する。

        指定HSコードの輸入総額について前年同月との比較を行い、
        急激な貿易量変動を検出する。

        Args:
            hs_code: HS商品コード（4-9桁）
            year_month: 基準年月（例: "202501"）。空=最新

        Returns:
            前年同月比情報の辞書:
            - hs_code: HSコード
            - current_period / prev_period: 比較期間
            - import_change_pct: 輸入額変動率（%）
            - top_movers: 変動が大きい国リスト
            - alert: 急変フラグ（変動率>50%時にTrue）
        """
        from datetime import datetime as dt

        if not year_month:
            now = dt.now()
            m = now.month - 2 if now.month > 2 else now.month + 10
            y = now.year if now.month > 2 else now.year - 1
            year_month = f"{y}{m:02d}"

        year = int(year_month[:4])
        month = int(year_month[4:6])
        prev_ym = f"{year - 1}{month:02d}"

        result = {
            "hs_code": hs_code,
            "current_period": year_month,
            "prev_period": prev_ym,
            "import_change_pct": 0.0,
            "top_movers": [],
            "alert": False,
            "data_source": "e-stat_japan_customs",
        }

        try:
            current = await self.get_import_by_hs(hs_code, year_month)
            previous = await self.get_import_by_hs(hs_code, prev_ym)

            cur_total = sum(r.import_value_jpy for r in current)
            prev_total = sum(r.import_value_jpy for r in previous)

            if prev_total > 0:
                change_pct = (cur_total - prev_total) / prev_total * 100
                result["import_change_pct"] = round(change_pct, 2)
                result["alert"] = abs(change_pct) > 50

            # 国別変動の上位を算出
            cur_by_country: dict[str, int] = {}
            prev_by_country: dict[str, int] = {}
            for r in current:
                if r.country_iso3 and r.country_iso3 != "WLD":
                    cur_by_country[r.country_iso3] = (
                        cur_by_country.get(r.country_iso3, 0) + r.import_value_jpy
                    )
            for r in previous:
                if r.country_iso3 and r.country_iso3 != "WLD":
                    prev_by_country[r.country_iso3] = (
                        prev_by_country.get(r.country_iso3, 0) + r.import_value_jpy
                    )

            all_countries = set(cur_by_country) | set(prev_by_country)
            movers: list[dict] = []
            for c in all_countries:
                cur_val = cur_by_country.get(c, 0)
                prev_val = prev_by_country.get(c, 0)
                if prev_val > 0:
                    c_change = (cur_val - prev_val) / prev_val * 100
                elif cur_val > 0:
                    c_change = 100.0
                else:
                    c_change = 0.0
                movers.append({
                    "country_iso3": c,
                    "change_pct": round(c_change, 1),
                    "current_jpy": cur_val,
                    "previous_jpy": prev_val,
                })

            movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
            result["top_movers"] = movers[:10]

            logger.info(
                "財務省貿易統計: YoY変動算出完了 (HS=%s, %.1f%%)",
                hs_code, result["import_change_pct"],
            )
            return result

        except Exception as exc:
            logger.error(
                "財務省貿易統計 YoY変動算出エラー: %s (HS=%s)", exc, hs_code,
            )
            return result

    async def get_customs_scrape_fallback(
        self,
        hs_code: str,
        year_month: str = "",
    ) -> list[JapanTradeRecord]:
        """財務省税関サイトからのスクレイピングフォールバック。

        e-Stat APIキー未設定時、またはAPI障害時に税関公式サイトの
        CSV/HTML テーブルからデータを取得する。

        https://www.customs.go.jp/toukei/srch/index.htm

        Args:
            hs_code: HS商品コード（4-9桁）
            year_month: 対象年月（例: "202401"）

        Returns:
            JapanTradeRecord のリスト。取得失敗時は空リスト。
        """
        try:
            # 税関統計検索 CSV ダウンロード URL
            hs_clean = hs_code.replace(".", "").replace(" ", "")
            base_url = "https://www.customs.go.jp/toukei/srch/index.htm"

            # CSV直接ダウンロードエンドポイント
            csv_url = (
                "https://www.customs.go.jp/toukei/download/"
                f"csv/import_{hs_clean[:4]}_{year_month or 'latest'}.csv"
            )

            await self._rate_limit()

            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                resp = await client.get(csv_url)
                if resp.status_code != 200:
                    logger.debug(
                        "税関CSV取得失敗 (HTTP %d): %s",
                        resp.status_code, csv_url,
                    )
                    return []

                # CSV パース（Shift-JIS エンコーディング）
                try:
                    content = resp.content.decode("shift_jis")
                except UnicodeDecodeError:
                    content = resp.content.decode("utf-8", errors="replace")

                records: list[JapanTradeRecord] = []
                lines = content.strip().split("\n")

                for line in lines[1:]:  # ヘッダースキップ
                    cols = line.strip().split(",")
                    if len(cols) < 5:
                        continue

                    try:
                        record = JapanTradeRecord(
                            hs_code=cols[0].strip().replace('"', ''),
                            country_name=cols[1].strip().replace('"', ''),
                            country_iso3=_resolve_country_iso3(
                                cols[1].strip().replace('"', '')
                            ),
                            year_month=cols[2].strip().replace('"', ''),
                            import_value_jpy=int(
                                cols[3].strip().replace('"', '')
                                .replace(",", "") or "0"
                            ),
                            export_value_jpy=0,
                            quantity=float(
                                cols[4].strip().replace('"', '')
                                .replace(",", "") or "0"
                            ),
                            unit="KG",
                        )
                        records.append(record)
                    except (ValueError, IndexError):
                        continue

                logger.info(
                    "税関CSV: %d件取得 (HS=%s)", len(records), hs_code,
                )
                return records

        except Exception as exc:
            logger.debug("税関CSVフォールバックエラー: %s", exc)
            return []


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
async def get_japan_imports(hs_code: str, year_month: str = "") -> list[JapanTradeRecord]:
    """日本輸入データ取得のショートカット関数。"""
    client = JapanCustomsClient()
    return await client.get_import_by_hs(hs_code, year_month)


async def get_japan_bilateral(
    partner_iso3: str, hs_code: str, year_month: str = "",
) -> dict:
    """日本二国間貿易フロー取得のショートカット関数。"""
    client = JapanCustomsClient()
    return await client.get_bilateral_flow(partner_iso3, hs_code, year_month)


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
        print("財務省貿易統計クライアント -- 動作確認")
        print("=" * 60)

        client = JapanCustomsClient()

        print(f"\n  APIキー設定: {'あり' if client._api_key else 'なし'}")

        print("\n--- 国名→ISO3 変換テスト ---")
        test_names = ["中華人民共和国", "アメリカ合衆国", "大韓民国", "台湾", "ドイツ"]
        for name in test_names:
            print(f"  {name} -> {_resolve_country_iso3(name)}")

        if client._api_key:
            print("\n--- 輸入データ取得 (HS 8542) ---")
            imports = await client.get_import_by_hs("8542")
            print(f"  取得件数: {len(imports)}")
            for rec in imports[:5]:
                print(
                    f"  {rec.country_name} ({rec.country_iso3}): "
                    f"{rec.import_value_jpy:,} JPY"
                )

            print("\n--- 上位輸入元 (HS 8542) ---")
            top = await client.get_top_import_sources("8542", top_n=5)
            for item in top:
                print(
                    f"  {item['country_name']} ({item['country_iso3']}): "
                    f"{item['import_value_jpy']:,} JPY ({item['share_pct']:.1f}%)"
                )
        else:
            print("\n  [SKIP] APIキー未設定のためデータ取得テストをスキップ")

    asyncio.run(_demo())
