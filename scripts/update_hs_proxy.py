#!/usr/bin/env python3
"""HS_PROXY_DATA 自動更新スクリプト (C-2)

UN Comtrade APIから主要製造国の輸入データを取得し、
品目別輸入元シェアを計算して data/hs_proxy_auto.json に保存する。

実行: .venv311/bin/python scripts/update_hs_proxy.py
"""
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    print("requests が必要です: pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
COMTRADE_BASE = "https://comtradeapi.un.org/public/v1/preview"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "hs_proxy_auto.json")

# 対象HSコード（tier_inference.py の HS_MATERIAL_MAP 準拠）
TARGET_HS_CODES = [
    "8507",  # 電池
    "8542",  # 集積回路
    "2604",  # ニッケル鉱
    "2836",  # リチウム
    "8105",  # コバルト
    "2846",  # 希土類
    "2601",  # 鉄鉱石
    "8541",  # 半導体デバイス
    "8534",  # PCB
    "8501",  # 電動モーター
    "7403",  # 精製銅
    "8708",  # 自動車部品
    "8703",  # 乗用車
]

# 主要輸入国（reporter）の UN Comtrade コード
REPORTER_CODES = {
    "Japan": "392",
    "South Korea": "410",
    "China": "156",
    "United States": "842",
    "Germany": "276",
    "India": "356",
    "Vietnam": "704",
    "Thailand": "764",
    "Mexico": "484",
    "Poland": "616",
}

HEADERS = {
    "User-Agent": "SCRI-Platform/1.0 (supply-chain-risk-intelligence)",
}

# レート制限: 1リクエストあたり1.5秒の間隔
RATE_LIMIT = 1.5


# ---------------------------------------------------------------------------
# Comtrade API 呼び出し
# ---------------------------------------------------------------------------
def fetch_comtrade_imports(reporter_code: str, hs_code: str,
                          year: int = 2023) -> Optional[list]:
    """UN Comtrade APIから特定の輸入国×HSコードの貿易データを取得する。

    Args:
        reporter_code: 輸入国のUN Comtradeコード
        hs_code: 4桁HSコード
        year: 対象年（デフォルト2023）

    Returns:
        パートナー国別の貿易データリスト。失敗時は None。
    """
    params = {
        "reporterCode": reporter_code,
        "period": str(year),
        "cmdCode": hs_code,
        "flowCode": "M",  # Import
        "partnerCode": "",  # 全パートナー
        "partner2Code": "",
    }

    try:
        url = f"{COMTRADE_BASE}/getTarifflineData"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])

        # フォールバック: 通常の HS レベル（tariffline でなく commodity）
        url2 = f"{COMTRADE_BASE}/getDAData"
        params2 = {
            "reporterCode": reporter_code,
            "period": str(year),
            "cmdCode": hs_code,
            "flowCode": "M",
        }
        resp2 = requests.get(url2, params=params2, headers=HEADERS, timeout=30)
        if resp2.status_code == 200:
            data2 = resp2.json()
            return data2.get("data", [])

    except requests.RequestException as exc:
        print(f"  [WARN] Comtrade API エラー ({reporter_code}/{hs_code}): {exc}")
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"  [WARN] Comtrade レスポンス解析エラー: {exc}")

    return None


def compute_shares(records: list) -> list:
    """貿易レコードからパートナー国別シェアを計算する。

    Args:
        records: Comtrade APIのレスポンスデータ

    Returns:
        [{"country": str, "share": float, "value_usd": int}, ...] 降順
    """
    # パートナー国別の貿易額を集計
    partner_values = {}
    for rec in records:
        partner = rec.get("partnerDesc") or rec.get("partner") or "Unknown"
        # "World" は全体合計なのでスキップ
        if partner.lower() in ("world", "all", ""):
            continue
        value = rec.get("primaryValue") or rec.get("TradeValue") or 0
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = 0
        partner_values[partner] = partner_values.get(partner, 0) + value

    if not partner_values:
        return []

    total = sum(partner_values.values())
    if total <= 0:
        return []

    # シェア計算 & 上位ソート
    results = []
    for partner, value in sorted(partner_values.items(), key=lambda x: x[1], reverse=True):
        share = value / total
        if share < 0.01:  # 1%未満は除外
            continue
        results.append({
            "country": partner,
            "share": round(share, 4),
            "value_usd": int(value),
        })

    return results[:10]  # 上位10カ国


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------
def main():
    """全HSコード × 全輸入国の組合せでComtradeデータを取得し、
    HS_PROXY_DATA 互換のJSONを生成する。
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 60)
    print("HS_PROXY_DATA 自動更新スクリプト")
    print(f"対象HSコード: {len(TARGET_HS_CODES)}件")
    print(f"対象輸入国: {len(REPORTER_CODES)}カ国")
    print(f"出力先: {OUTPUT_PATH}")
    print("=" * 60)

    result: dict = {}
    success_count = 0
    fail_count = 0
    total = len(TARGET_HS_CODES) * len(REPORTER_CODES)

    for hs_code in TARGET_HS_CODES:
        result[hs_code] = {}
        print(f"\n[HS {hs_code}]")

        for country_name, reporter_code in REPORTER_CODES.items():
            print(f"  {country_name} ({reporter_code})...", end=" ", flush=True)

            records = fetch_comtrade_imports(reporter_code, hs_code)
            time.sleep(RATE_LIMIT)

            if records is None or len(records) == 0:
                print("データなし")
                fail_count += 1
                continue

            shares = compute_shares(records)
            if shares:
                result[hs_code][country_name] = shares
                print(f"OK ({len(shares)}カ国)")
                success_count += 1
            else:
                print("シェア計算不可")
                fail_count += 1

    # 結果保存
    output = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "source": "UN Comtrade API (preview)",
            "hs_codes": len(TARGET_HS_CODES),
            "reporters": len(REPORTER_CODES),
            "success": success_count,
            "failed": fail_count,
            "total_queries": total,
        },
        "hs_proxy_data": result,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"完了: {success_count}/{total} 成功, {fail_count} 失敗")
    print(f"保存先: {OUTPUT_PATH}")
    print(f"{'=' * 60}")

    return output


if __name__ == "__main__":
    main()
