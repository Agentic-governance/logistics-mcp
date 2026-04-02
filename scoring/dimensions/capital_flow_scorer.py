"""資金フローリスク スコアラー（第27次元）
資本規制・SWIFT除外・送金制限に基づくリスク評価。

スコアリングロジック:
  - Chinn-Ito Index: 資本勘定開放度 → 0-100基礎スコア
  - IMF AREAER: 規制フラグごとに+10点（最大+40点）
  - SWIFT除外: +50点
  - 最終スコア: min(100, 上記合計)
"""

import logging

logger = logging.getLogger(__name__)


class CapitalFlowScorer:
    """資本フローリスク スコアラー"""

    def score(self, country_iso3: str) -> int:
        """0-100のリスクスコアを返す

        Args:
            country_iso3: ISO3国コード（例: "JPN"）またはロケーション名

        Returns:
            0（リスクなし）〜100（最大リスク）
        """
        try:
            from pipeline.financial.capital_flow_client import get_capital_flow_risk
            result = get_capital_flow_risk(country_iso3)
            return min(100, max(0, result.get("score", 0)))
        except Exception as e:
            logger.warning(f"資本フローリスク算出失敗: {country_iso3} - {e}")
            return 0


def get_capital_flow_score(location: str) -> dict:
    """エンジン統合用: ロケーション文字列からスコアとエビデンスを返す

    Returns:
        {"score": int, "evidence": list[str]}
    """
    try:
        from pipeline.financial.capital_flow_client import get_capital_flow_risk
        result = get_capital_flow_risk(location)
        return {
            "score": min(100, max(0, result.get("score", 0))),
            "evidence": result.get("evidence", []),
        }
    except Exception as e:
        logger.warning(f"資本フローリスク算出失敗: {location} - {e}")
        return {"score": 0, "evidence": []}
