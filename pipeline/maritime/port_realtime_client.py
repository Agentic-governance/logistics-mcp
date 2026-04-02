"""港湾リアルタイム混雑状況モニタリングクライアント
主要港湾のリアルタイム混雑状況を公開データソースから取得し、
サプライチェーンの海上物流リスクを評価する。

対象港湾: Shanghai, Singapore, Rotterdam, Los Angeles/Long Beach,
         Yokohama, Busan, Hamburg

データソース（優先順）:
  1. MarineTraffic 無料ティア（港湾エリアの船舶数）
  2. AISHub API（公開AISデータ）
  3. IMF PortWatch（港湾活動指数）
  4. 静的ベースライン（フォールバック）

使用例::

    client = PortRealtimeClient()
    status = await client.get_port_congestion_live("CNSHA")
    all_ports = await client.get_all_ports_status()
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 15  # 秒
RATE_LIMIT_INTERVAL = 2.0  # 秒
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-intelligence)"

# AISHub API（公開AISデータ）
AISHUB_API_URL = "http://data.aishub.net/ws.php"

# IMF PortWatch ArcGIS Feature Service
PORTWATCH_BASE = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
PORTWATCH_ACTIVITY_URL = (
    f"{PORTWATCH_BASE}/PortWatch_Portal_Daily_Port_Data/FeatureServer/0/query"
)


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class PortCongestionStatus:
    """港湾混雑状況レコード"""
    port_name: str
    port_code: str
    vessels_waiting: int
    avg_wait_hours: float
    berth_utilization_pct: float
    congestion_level: str  # "LOW", "MODERATE", "HIGH", "CRITICAL"
    data_source: str
    timestamp: str  # ISO 8601 形式


# ---------------------------------------------------------------------------
# 主要港湾定義
# ---------------------------------------------------------------------------
# UN/LOCODE ベースのポートコード → 港湾情報マッピング
MAJOR_PORTS: dict[str, dict] = {
    "CNSHA": {
        "name": "Shanghai",
        "lat": 31.23,
        "lon": 121.47,
        "baseline_wait": 24,
        "baseline_vessels": 150,
        "baseline_utilization": 85.0,
        "area_radius_deg": 0.5,  # AIS検索用の半径（度）
    },
    "SGSIN": {
        "name": "Singapore",
        "lat": 1.26,
        "lon": 103.84,
        "baseline_wait": 12,
        "baseline_vessels": 200,
        "baseline_utilization": 80.0,
        "area_radius_deg": 0.3,
    },
    "NLRTM": {
        "name": "Rotterdam",
        "lat": 51.95,
        "lon": 4.13,
        "baseline_wait": 8,
        "baseline_vessels": 80,
        "baseline_utilization": 70.0,
        "area_radius_deg": 0.3,
    },
    "USLAX": {
        "name": "Los Angeles",
        "lat": 33.74,
        "lon": -118.26,
        "baseline_wait": 18,
        "baseline_vessels": 60,
        "baseline_utilization": 75.0,
        "area_radius_deg": 0.3,
    },
    "JPYOK": {
        "name": "Yokohama",
        "lat": 35.44,
        "lon": 139.64,
        "baseline_wait": 6,
        "baseline_vessels": 40,
        "baseline_utilization": 65.0,
        "area_radius_deg": 0.2,
    },
    "KRPUS": {
        "name": "Busan",
        "lat": 35.10,
        "lon": 129.04,
        "baseline_wait": 10,
        "baseline_vessels": 70,
        "baseline_utilization": 72.0,
        "area_radius_deg": 0.3,
    },
    "DEHAM": {
        "name": "Hamburg",
        "lat": 53.54,
        "lon": 9.97,
        "baseline_wait": 8,
        "baseline_vessels": 50,
        "baseline_utilization": 68.0,
        "area_radius_deg": 0.2,
    },
}


# ---------------------------------------------------------------------------
# メインクライアント
# ---------------------------------------------------------------------------
class PortRealtimeClient:
    """港湾リアルタイム混雑状況モニタリングクライアント

    複数のデータソースを統合して主要港湾の混雑状況を推定する。
    利用可能なソースに応じて最適なデータを選択し、
    すべてのソースが利用不可の場合は静的ベースラインにフォールバック。

    混雑レベル判定基準:
      - LOW:      待機時間 < ベースラインの 80%
      - MODERATE: 待機時間 ベースラインの 80-120%
      - HIGH:     待機時間 ベースラインの 120-200%
      - CRITICAL: 待機時間 > ベースラインの 200%

    使用例::

        client = PortRealtimeClient()
        status = await client.get_port_congestion_live("CNSHA")
    """

    MAJOR_PORTS = MAJOR_PORTS

    def __init__(self):
        """クライアントを初期化する。"""
        self._last_request_time: float = 0.0
        self._aishub_api_key = os.getenv("AISHUB_API_KEY", "")
        self._headers = {
            "User-Agent": USER_AGENT,
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
    # データソース: AISHub
    # ------------------------------------------------------------------
    async def _fetch_aishub_vessels(
        self,
        port_info: dict,
    ) -> Optional[int]:
        """AISHub API で港湾エリアの船舶数を取得する。

        Args:
            port_info: 港湾情報辞書（lat, lon, area_radius_deg含む）

        Returns:
            船舶数。取得失敗時は None。
        """
        if not self._aishub_api_key:
            return None

        await self._rate_limit()

        lat = port_info["lat"]
        lon = port_info["lon"]
        radius = port_info.get("area_radius_deg", 0.3)

        params = {
            "username": self._aishub_api_key,
            "format": "1",
            "output": "json",
            "compress": "0",
            "latmin": lat - radius,
            "latmax": lat + radius,
            "lonmin": lon - radius,
            "lonmax": lon + radius,
        }

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(AISHUB_API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                # AISHub レスポンス: list or {"vessels": []}
                if isinstance(data, list):
                    vessels = data
                else:
                    vessels = data.get("vessels", data.get("data", []))

                # カーゴ船のみカウント（ship type 70-79）
                cargo_vessels = [
                    v for v in vessels
                    if isinstance(v, dict)
                    and v.get("TYPE", v.get("type", 0)) in range(70, 90)
                ]

                return len(cargo_vessels) if cargo_vessels else len(vessels)

        except httpx.TimeoutException:
            logger.debug("AISHub APIタイムアウト")
            return None
        except httpx.HTTPError as exc:
            logger.debug("AISHub API接続エラー: %s", exc)
            return None
        except Exception as exc:
            logger.debug("AISHub API予期せぬエラー: %s", exc)
            return None

    # ------------------------------------------------------------------
    # データソース: IMF PortWatch
    # ------------------------------------------------------------------
    async def _fetch_portwatch_activity(
        self,
        port_name: str,
    ) -> Optional[dict]:
        """IMF PortWatch から港湾活動データを取得する。

        Args:
            port_name: 港湾名（例: "Shanghai"）

        Returns:
            港湾活動データの辞書。取得失敗時は None。
        """
        await self._rate_limit()

        since = datetime.utcnow() - timedelta(days=7)
        since_epoch = int(since.timestamp() * 1000)

        params = {
            "where": f"port_name LIKE '%{port_name}%' AND date >= {since_epoch}",
            "outFields": "port_name,date,import_volume,export_volume,vessel_count",
            "f": "json",
            "resultRecordCount": 7,
            "orderByFields": "date DESC",
        }

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(PORTWATCH_ACTIVITY_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                features = data.get("features", [])
                if not features:
                    return None

                # 最新データを使用
                latest = features[0].get("attributes", {})
                vessel_count = latest.get("vessel_count", 0)
                import_vol = latest.get("import_volume", 0)
                export_vol = latest.get("export_volume", 0)

                return {
                    "vessel_count": vessel_count or 0,
                    "import_volume": import_vol or 0,
                    "export_volume": export_vol or 0,
                    "data_points": len(features),
                }

        except httpx.TimeoutException:
            logger.debug("PortWatch APIタイムアウト: %s", port_name)
            return None
        except httpx.HTTPError as exc:
            logger.debug("PortWatch API接続エラー: %s", exc)
            return None
        except Exception as exc:
            logger.debug("PortWatch API予期せぬエラー: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 混雑レベル判定
    # ------------------------------------------------------------------
    def _determine_congestion_level(
        self,
        wait_hours: float,
        baseline_wait: float,
    ) -> str:
        """混雑レベルを判定する。

        Args:
            wait_hours: 推定待機時間（時間）
            baseline_wait: ベースライン待機時間（時間）

        Returns:
            混雑レベル文字列
        """
        if baseline_wait <= 0:
            return "UNKNOWN"

        ratio = wait_hours / baseline_wait

        if ratio < 0.8:
            return "LOW"
        elif ratio < 1.2:
            return "MODERATE"
        elif ratio < 2.0:
            return "HIGH"
        else:
            return "CRITICAL"

    def _estimate_wait_and_utilization(
        self,
        vessel_count: int,
        port_info: dict,
    ) -> tuple[float, float]:
        """船舶数から待機時間とバース利用率を推定する。

        Args:
            vessel_count: 検出された船舶数
            port_info: 港湾情報辞書

        Returns:
            (推定待機時間, 推定バース利用率) のタプル
        """
        baseline_vessels = port_info.get("baseline_vessels", 100)
        baseline_wait = port_info.get("baseline_wait", 12)
        baseline_util = port_info.get("baseline_utilization", 75.0)

        if baseline_vessels <= 0:
            return baseline_wait, baseline_util

        # 船舶数の比率から待機時間とバース利用率を推定
        vessel_ratio = vessel_count / baseline_vessels

        estimated_wait = baseline_wait * vessel_ratio
        estimated_util = min(100.0, baseline_util * vessel_ratio)

        return round(estimated_wait, 1), round(estimated_util, 1)

    # ------------------------------------------------------------------
    # データソース: VesselFinder スクレイピング
    # ------------------------------------------------------------------
    async def _fetch_vesselfinder_congestion(
        self,
        port_name: str,
        port_code: str,
    ) -> Optional[dict]:
        """VesselFinder の港湾ページからスクレイピングする（フォールバック）。

        VesselFinder の公開港湾ページから待機船舶数の概算を取得する。
        正確なAPIアクセスには有料プランが必要だが、公開ページの
        テキストから概算値を抽出可能。

        Args:
            port_name: 港湾名（例: "Shanghai"）
            port_code: UN/LOCODEポートコード

        Returns:
            船舶データ辞書。取得失敗時は None。
        """
        await self._rate_limit()

        # VesselFinder の港湾コード形式への変換
        vf_port_map = {
            "CNSHA": "CNSHA",
            "SGSIN": "SGSIN",
            "NLRTM": "NLRTM",
            "USLAX": "USLAX",
            "JPYOK": "JPYOK",
            "KRPUS": "KRPUS",
            "DEHAM": "DEHAM",
        }

        vf_code = vf_port_map.get(port_code, port_code)
        url = f"https://www.vesselfinder.com/ports/{vf_code}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; SCRI/1.0)"
                    ),
                },
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                text = resp.text

                # HTMLテキストから船舶数を抽出（概算）
                import re
                # "XX vessels in port" パターン
                vessel_match = re.search(
                    r'(\d+)\s*(?:vessels?\s*(?:in|at)\s*port)',
                    text, re.IGNORECASE,
                )
                # "XX ships" パターン
                if not vessel_match:
                    vessel_match = re.search(
                        r'(\d+)\s*(?:ships?\s*(?:in|at))',
                        text, re.IGNORECASE,
                    )
                # "Expected Arrivals: XX" パターン
                arrival_match = re.search(
                    r'(?:expected|arriving)[:\s]*(\d+)',
                    text, re.IGNORECASE,
                )

                if vessel_match:
                    vessel_count = int(vessel_match.group(1))
                    arrivals = (
                        int(arrival_match.group(1))
                        if arrival_match else 0
                    )

                    return {
                        "vessel_count": vessel_count,
                        "expected_arrivals": arrivals,
                        "source": "vesselfinder_scrape",
                    }

                return None

        except Exception as exc:
            logger.debug("VesselFinder スクレイピングエラー: %s", exc)
            return None

    async def get_port_congestion_live(
        self,
        port_code: str,
    ) -> PortCongestionStatus:
        """指定港湾のリアルタイム混雑状況を取得する。

        複数のデータソースを試行し、利用可能な最良のデータで
        混雑状況を推定する。

        データソース優先順:
          1. AISHub（リアルタイムAIS）
          2. IMF PortWatch（準リアルタイム）
          3. VesselFinder（スクレイピング）
          4. 静的ベースライン（フォールバック）

        Args:
            port_code: UN/LOCODEベースのポートコード（例: "CNSHA"）

        Returns:
            PortCongestionStatus データクラス。
        """
        port_code = port_code.upper()
        port_info = self.MAJOR_PORTS.get(port_code)

        if not port_info:
            logger.warning("未対応のポートコード: %s", port_code)
            return PortCongestionStatus(
                port_name=f"Unknown ({port_code})",
                port_code=port_code,
                vessels_waiting=0,
                avg_wait_hours=0.0,
                berth_utilization_pct=0.0,
                congestion_level="UNKNOWN",
                data_source="none",
                timestamp=datetime.utcnow().isoformat(),
            )

        port_name = port_info["name"]
        baseline_wait = port_info["baseline_wait"]
        now_iso = datetime.utcnow().isoformat()

        # --- ソース1: AISHub ---
        ais_vessels = await self._fetch_aishub_vessels(port_info)
        if ais_vessels is not None and ais_vessels > 0:
            wait_hours, utilization = self._estimate_wait_and_utilization(
                ais_vessels, port_info,
            )
            congestion = self._determine_congestion_level(
                wait_hours, baseline_wait,
            )
            logger.info(
                "ポート混雑状況[AIS]: %s (%s) - 船舶=%d, 待機=%.1fh, %s",
                port_name, port_code, ais_vessels, wait_hours, congestion,
            )
            return PortCongestionStatus(
                port_name=port_name,
                port_code=port_code,
                vessels_waiting=ais_vessels,
                avg_wait_hours=wait_hours,
                berth_utilization_pct=utilization,
                congestion_level=congestion,
                data_source="aishub_ais",
                timestamp=now_iso,
            )

        # --- ソース2: IMF PortWatch ---
        portwatch_data = await self._fetch_portwatch_activity(port_name)
        if portwatch_data is not None:
            pw_vessels = portwatch_data.get("vessel_count", 0)
            if pw_vessels > 0:
                wait_hours, utilization = self._estimate_wait_and_utilization(
                    pw_vessels, port_info,
                )
                congestion = self._determine_congestion_level(
                    wait_hours, baseline_wait,
                )
                logger.info(
                    "ポート混雑状況[PortWatch]: %s (%s) - 船舶=%d, 待機=%.1fh, %s",
                    port_name, port_code, pw_vessels, wait_hours, congestion,
                )
                return PortCongestionStatus(
                    port_name=port_name,
                    port_code=port_code,
                    vessels_waiting=pw_vessels,
                    avg_wait_hours=wait_hours,
                    berth_utilization_pct=utilization,
                    congestion_level=congestion,
                    data_source="imf_portwatch",
                    timestamp=now_iso,
                )

        # --- ソース3: VesselFinder スクレイピング ---
        vf_data = await self._fetch_vesselfinder_congestion(port_name, port_code)
        if vf_data is not None:
            vf_vessels = vf_data.get("vessel_count", 0)
            if vf_vessels > 0:
                wait_hours, utilization = self._estimate_wait_and_utilization(
                    vf_vessels, port_info,
                )
                congestion = self._determine_congestion_level(
                    wait_hours, baseline_wait,
                )
                logger.info(
                    "ポート混雑状況[VesselFinder]: %s (%s) - 船舶=%d, 待機=%.1fh, %s",
                    port_name, port_code, vf_vessels, wait_hours, congestion,
                )
                return PortCongestionStatus(
                    port_name=port_name,
                    port_code=port_code,
                    vessels_waiting=vf_vessels,
                    avg_wait_hours=wait_hours,
                    berth_utilization_pct=utilization,
                    congestion_level=congestion,
                    data_source="vesselfinder_scrape",
                    timestamp=now_iso,
                )

        # --- ソース4: 静的ベースライン（フォールバック） ---
        logger.info(
            "ポート混雑状況[ベースライン]: %s (%s) - ライブデータ取得不可",
            port_name, port_code,
        )
        return PortCongestionStatus(
            port_name=port_name,
            port_code=port_code,
            vessels_waiting=port_info.get("baseline_vessels", 0),
            avg_wait_hours=float(baseline_wait),
            berth_utilization_pct=port_info.get("baseline_utilization", 0.0),
            congestion_level="MODERATE",
            data_source="static_baseline",
            timestamp=now_iso,
        )

    async def get_congestion_trend(
        self,
        port_code: str,
        days: int = 7,
    ) -> dict:
        """港湾混雑のトレンドを推定する。

        PortWatchの過去データから混雑トレンド（改善/悪化/安定）を判定。
        直近days日間のデータを分析する。

        Args:
            port_code: UN/LOCODEポートコード
            days: 分析期間（日数、デフォルト7）

        Returns:
            トレンド情報辞書:
            - port_code: ポートコード
            - trend: "IMPROVING" / "WORSENING" / "STABLE"
            - avg_vessels_early: 前半平均船舶数
            - avg_vessels_late: 後半平均船舶数
            - data_points: データポイント数
        """
        port_info = self.MAJOR_PORTS.get(port_code.upper())
        if not port_info:
            return {
                "port_code": port_code,
                "trend": "UNKNOWN",
                "data_points": 0,
            }

        result = {
            "port_code": port_code.upper(),
            "port_name": port_info["name"],
            "trend": "STABLE",
            "avg_vessels_early": 0,
            "avg_vessels_late": 0,
            "change_pct": 0.0,
            "data_points": 0,
            "data_source": "imf_portwatch",
        }

        try:
            # PortWatch で過去数日分のデータを取得
            since = datetime.utcnow() - timedelta(days=days)
            since_epoch = int(since.timestamp() * 1000)

            params = {
                "where": (
                    f"port_name LIKE '%{port_info['name']}%' "
                    f"AND date >= {since_epoch}"
                ),
                "outFields": "port_name,date,vessel_count",
                "f": "json",
                "resultRecordCount": days,
                "orderByFields": "date ASC",
            }

            await self._rate_limit()

            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(PORTWATCH_ACTIVITY_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            features = data.get("features", [])
            if len(features) < 2:
                return result

            vessel_counts = [
                f.get("attributes", {}).get("vessel_count", 0) or 0
                for f in features
            ]
            result["data_points"] = len(vessel_counts)

            # 前半 vs 後半の比較
            mid = len(vessel_counts) // 2
            early = vessel_counts[:mid] or [0]
            late = vessel_counts[mid:] or [0]

            avg_early = sum(early) / len(early)
            avg_late = sum(late) / len(late)

            result["avg_vessels_early"] = round(avg_early, 1)
            result["avg_vessels_late"] = round(avg_late, 1)

            if avg_early > 0:
                change_pct = (avg_late - avg_early) / avg_early * 100
                result["change_pct"] = round(change_pct, 1)

                if change_pct > 15:
                    result["trend"] = "WORSENING"
                elif change_pct < -15:
                    result["trend"] = "IMPROVING"

            logger.info(
                "ポート混雑トレンド: %s (%s) - %s (変動%.1f%%)",
                port_info["name"], port_code,
                result["trend"], result["change_pct"],
            )
            return result

        except Exception as exc:
            logger.debug("PortWatch トレンド取得エラー: %s", exc)
            return result

    async def get_delay_forecast(
        self,
        port_code: str,
    ) -> dict:
        """港湾遅延の短期予測を行う。

        現在の混雑状況とトレンドに基づいて、今後24-72時間の
        遅延予測を行う。季節性・曜日効果も考慮する。

        Args:
            port_code: UN/LOCODEポートコード

        Returns:
            遅延予測辞書:
            - port_code: ポートコード
            - current_wait_hours: 現在の待機時間
            - forecast_24h: 24時間後の予測待機時間
            - forecast_72h: 72時間後の予測待機時間
            - confidence: 予測信頼度（LOW/MEDIUM/HIGH）
            - factors: 予測に影響する要因リスト
        """
        port_code = port_code.upper()
        port_info = self.MAJOR_PORTS.get(port_code)

        if not port_info:
            return {
                "port_code": port_code,
                "current_wait_hours": 0.0,
                "forecast_24h": 0.0,
                "forecast_72h": 0.0,
                "confidence": "LOW",
                "factors": [],
            }

        result = {
            "port_code": port_code,
            "port_name": port_info["name"],
            "current_wait_hours": 0.0,
            "forecast_24h": 0.0,
            "forecast_72h": 0.0,
            "confidence": "LOW",
            "factors": [],
        }

        try:
            # 現在の混雑状況を取得
            current = await self.get_port_congestion_live(port_code)
            result["current_wait_hours"] = current.avg_wait_hours

            # トレンドを取得
            trend = await self.get_congestion_trend(port_code, days=7)

            # 予測モデル（簡易線形外挿+季節性補正）
            current_wait = current.avg_wait_hours
            baseline_wait = port_info["baseline_wait"]

            # トレンドの日次変化率
            daily_change_rate = 0.0
            if trend.get("change_pct", 0) != 0 and trend.get("data_points", 0) > 1:
                daily_change_rate = trend["change_pct"] / 100.0 / max(
                    1, trend["data_points"]
                )

            # 季節性補正（曜日効果）
            weekday = datetime.utcnow().weekday()
            # 月曜=混雑増、金曜=やや増、土日=減少
            weekday_factors = {
                0: 1.05,  # 月曜
                1: 1.02,  # 火曜
                2: 1.00,  # 水曜
                3: 0.98,  # 木曜
                4: 1.03,  # 金曜
                5: 0.90,  # 土曜
                6: 0.88,  # 日曜
            }
            wd_factor_24 = weekday_factors.get((weekday + 1) % 7, 1.0)
            wd_factor_72 = weekday_factors.get((weekday + 3) % 7, 1.0)

            # 24時間後の予測
            forecast_24 = current_wait * (1 + daily_change_rate) * wd_factor_24
            # 72時間後の予測
            forecast_72 = current_wait * (1 + daily_change_rate * 3) * wd_factor_72

            # ベースラインへの回帰（平均回帰効果）
            reversion_rate = 0.1  # 10%/日でベースラインに回帰
            forecast_24 = (
                forecast_24 * (1 - reversion_rate)
                + baseline_wait * reversion_rate
            )
            forecast_72 = (
                forecast_72 * (1 - reversion_rate * 3)
                + baseline_wait * reversion_rate * 3
            )

            result["forecast_24h"] = round(max(0, forecast_24), 1)
            result["forecast_72h"] = round(max(0, forecast_72), 1)

            # 信頼度の判定
            data_source = current.data_source
            if data_source in ("aishub_ais", "imf_portwatch"):
                result["confidence"] = "HIGH" if trend["data_points"] >= 5 else "MEDIUM"
            elif data_source == "vesselfinder_scrape":
                result["confidence"] = "MEDIUM"
            else:
                result["confidence"] = "LOW"

            # 影響要因の記録
            if trend.get("trend") == "WORSENING":
                result["factors"].append("混雑悪化トレンド継続中")
            elif trend.get("trend") == "IMPROVING":
                result["factors"].append("混雑改善トレンド")

            if wd_factor_24 > 1.0:
                result["factors"].append("翌日は曜日効果で混雑増加傾向")

            if current.congestion_level == "CRITICAL":
                result["factors"].append("現在CRITICALレベル: 大幅遅延リスク")

            logger.info(
                "ポート遅延予測: %s (%s) - 現在=%.1fh, 24h=%.1fh, 72h=%.1fh",
                port_info["name"], port_code,
                current_wait, result["forecast_24h"], result["forecast_72h"],
            )
            return result

        except Exception as exc:
            logger.error(
                "ポート遅延予測エラー: %s (%s)", exc, port_code,
            )
            return result

    async def get_all_ports_status(self) -> list[PortCongestionStatus]:
        """全主要港湾の混雑状況を一括取得する。

        7つの主要港湾の混雑状況を順次取得する。
        レート制限を遵守するため、各リクエスト間に最低2秒の
        間隔を確保する。

        Returns:
            PortCongestionStatus のリスト（7港分）。
        """
        results: list[PortCongestionStatus] = []

        for port_code in self.MAJOR_PORTS:
            try:
                status = await self.get_port_congestion_live(port_code)
                results.append(status)
            except Exception as exc:
                logger.error(
                    "ポート状況取得エラー: %s (%s)", exc, port_code,
                )
                # エラー時はベースラインで記録
                port_info = self.MAJOR_PORTS[port_code]
                results.append(PortCongestionStatus(
                    port_name=port_info["name"],
                    port_code=port_code,
                    vessels_waiting=0,
                    avg_wait_hours=float(port_info["baseline_wait"]),
                    berth_utilization_pct=port_info.get(
                        "baseline_utilization", 0.0
                    ),
                    congestion_level="UNKNOWN",
                    data_source="error_fallback",
                    timestamp=datetime.utcnow().isoformat(),
                ))

        logger.info(
            "全港湾混雑状況取得完了: %d/%d港",
            len(results), len(self.MAJOR_PORTS),
        )
        return results

    async def get_global_congestion_summary(self) -> dict:
        """全主要港湾の混雑サマリーを生成する。

        全港湾の混雑状況を取得し、グローバルな海上物流リスクの
        概要を返す。

        Returns:
            グローバル混雑サマリー辞書:
            - global_risk_level: 全体リスクレベル
            - avg_wait_hours: 全港平均待機時間
            - critical_ports: CRITICAL状態の港湾リスト
            - congestion_by_region: 地域別の混雑概要
            - ports: 全港湾の状況リスト
        """
        all_status = await self.get_all_ports_status()

        # 地域分類
        REGION_MAP = {
            "CNSHA": "Asia", "SGSIN": "Asia", "JPYOK": "Asia",
            "KRPUS": "Asia",
            "NLRTM": "Europe", "DEHAM": "Europe",
            "USLAX": "Americas",
        }

        result = {
            "global_risk_level": "LOW",
            "avg_wait_hours": 0.0,
            "critical_ports": [],
            "high_ports": [],
            "congestion_by_region": {},
            "ports": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            wait_hours_list: list[float] = []
            region_waits: dict[str, list[float]] = {}

            for status in all_status:
                wait_hours_list.append(status.avg_wait_hours)
                region = REGION_MAP.get(status.port_code, "Other")

                if region not in region_waits:
                    region_waits[region] = []
                region_waits[region].append(status.avg_wait_hours)

                port_entry = {
                    "port_name": status.port_name,
                    "port_code": status.port_code,
                    "wait_hours": status.avg_wait_hours,
                    "vessels": status.vessels_waiting,
                    "congestion": status.congestion_level,
                    "source": status.data_source,
                }
                result["ports"].append(port_entry)

                if status.congestion_level == "CRITICAL":
                    result["critical_ports"].append(port_entry)
                elif status.congestion_level == "HIGH":
                    result["high_ports"].append(port_entry)

            if wait_hours_list:
                result["avg_wait_hours"] = round(
                    sum(wait_hours_list) / len(wait_hours_list), 1,
                )

            # 地域別サマリー
            for region, waits in region_waits.items():
                avg = sum(waits) / len(waits) if waits else 0
                result["congestion_by_region"][region] = {
                    "avg_wait_hours": round(avg, 1),
                    "port_count": len(waits),
                }

            # グローバルリスクレベル判定
            critical_count = len(result["critical_ports"])
            high_count = len(result["high_ports"])
            if critical_count >= 2:
                result["global_risk_level"] = "CRITICAL"
            elif critical_count >= 1 or high_count >= 3:
                result["global_risk_level"] = "HIGH"
            elif high_count >= 1:
                result["global_risk_level"] = "MEDIUM"

            logger.info(
                "グローバル混雑サマリー: risk=%s, avg_wait=%.1fh, critical=%d",
                result["global_risk_level"],
                result["avg_wait_hours"],
                critical_count,
            )
            return result

        except Exception as exc:
            logger.error("グローバル混雑サマリーエラー: %s", exc)
            return result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
async def get_port_status(port_code: str) -> PortCongestionStatus:
    """港湾混雑状況取得のショートカット関数。"""
    client = PortRealtimeClient()
    return await client.get_port_congestion_live(port_code)


async def get_global_port_summary() -> dict:
    """グローバル港湾混雑サマリー取得のショートカット関数。"""
    client = PortRealtimeClient()
    return await client.get_global_congestion_summary()


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
        print("港湾リアルタイム混雑状況モニタリング -- 動作確認")
        print("=" * 60)

        client = PortRealtimeClient()

        print(f"\n  AISHub APIキー: {'設定済' if client._aishub_api_key else '未設定'}")
        print(f"  対象港湾: {len(client.MAJOR_PORTS)}港")

        print("\n--- 全港湾ステータス ---")
        all_status = await client.get_all_ports_status()
        for status in all_status:
            print(
                f"  {status.port_name:12s} ({status.port_code}): "
                f"待機={status.avg_wait_hours:5.1f}h, "
                f"船舶={status.vessels_waiting:4d}, "
                f"稼働率={status.berth_utilization_pct:5.1f}%, "
                f"混雑={status.congestion_level:9s} "
                f"[{status.data_source}]"
            )

        print("\n--- 個別港湾: Shanghai ---")
        sha = await client.get_port_congestion_live("CNSHA")
        print(f"  港名: {sha.port_name}")
        print(f"  ポートコード: {sha.port_code}")
        print(f"  待機船舶: {sha.vessels_waiting}")
        print(f"  平均待機時間: {sha.avg_wait_hours}h")
        print(f"  バース稼働率: {sha.berth_utilization_pct}%")
        print(f"  混雑レベル: {sha.congestion_level}")
        print(f"  データソース: {sha.data_source}")

    asyncio.run(_demo())
