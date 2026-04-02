#!/usr/bin/env python3
"""BACI代替データ構築スクリプト (C-5)

UN Comtradeから主要製造国 × 主要HSコードの輸入元シェアを自動取得し、
HS_PROXY_DATA を自動更新するデータを生成する。

BACIデータ（有償/アカデミック限定）の代替として、
UN Comtrade パブリックAPIのみで同等のデータを構築する。

実行: .venv311/bin/python scripts/build_hs_proxy_from_comtrade.py
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
COMTRADE_PREVIEW = "https://comtradeapi.un.org/public/v1/preview"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "hs_proxy_baci_alt.json")
EXISTING_PROXY_PATH = os.path.join(DATA_DIR, "hs_proxy_auto.json")

HEADERS = {
    "User-Agent": "SCRI-Platform/1.0 (supply-chain-risk-intelligence)",
    "Accept": "application/json",
}

RATE_LIMIT = 2.0  # 秒

# 主要製造国と UN Comtrade レポーターコード
MAJOR_MANUFACTURERS = {
    "China": "156",
    "Japan": "392",
    "South Korea": "410",
    "Taiwan": "490",  # 「その他のアジア」として登録されることがある
    "Germany": "276",
    "United States": "842",
    "India": "356",
    "Vietnam": "704",
    "Thailand": "764",
    "Indonesia": "360",
    "Malaysia": "458",
    "Mexico": "484",
    "Brazil": "076",
    "Poland": "616",
    "Turkey": "792",
}

# 主要HSコード（完成品 + 中間財 + 原材料）
HS_CODES = {
    # 原材料
    "2601": "鉄鉱石",
    "2603": "銅鉱石",
    "2604": "ニッケル鉱",
    "2606": "アルミニウム鉱(ボーキサイト)",
    "2804": "ケイ素(シリコン)",
    "2836": "炭酸リチウム",
    "2846": "希土類化合物",
    "4001": "天然ゴム",
    # 中間財
    "7207": "鉄鋼半製品",
    "7403": "精製銅",
    "7502": "ニッケル地金",
    "7601": "アルミニウム地金",
    "8105": "コバルト",
    "8534": "プリント基板(PCB)",
    # 完成品・電子部品
    "8501": "電動モーター",
    "8507": "蓄電池(バッテリー)",
    "8541": "半導体デバイス",
    "8542": "集積回路(IC)",
    "8544": "電線・ケーブル",
    "8703": "乗用自動車",
    "8708": "自動車部品",
    "3920": "プラスチックフィルム",
}

# UN Comtrade パートナーコード → 国名（主要国のみ）
PARTNER_CODE_MAP = {
    "156": "China", "392": "Japan", "410": "South Korea",
    "490": "Taiwan", "158": "Taiwan",
    "276": "Germany", "842": "United States",
    "356": "India", "704": "Vietnam", "764": "Thailand",
    "360": "Indonesia", "458": "Malaysia", "484": "Mexico",
    "076": "Brazil", "616": "Poland", "792": "Turkey",
    "036": "Australia", "152": "Chile", "032": "Argentina",
    "608": "Philippines", "826": "United Kingdom",
    "250": "France", "380": "Italy", "528": "Netherlands",
    "056": "Belgium", "344": "Hong Kong", "702": "Singapore",
    "124": "Canada", "643": "Russia", "682": "Saudi Arabia",
    "784": "UAE",
}


# ---------------------------------------------------------------------------
# Comtrade API
# ---------------------------------------------------------------------------
def fetch_import_data(reporter_code: str, hs_code: str,
                      years: list = None) -> Optional[list]:
    """UN Comtrade から輸入データを取得する。

    Args:
        reporter_code: 輸入国コード
        hs_code: 4桁HSコード
        years: 対象年リスト（デフォルト [2022, 2023]）

    Returns:
        パートナー国別の集計データ。失敗時は None。
    """
    if years is None:
        years = [2022, 2023]

    all_records = []

    for year in years:
        try:
            # getTarifflineData を試行
            params = {
                "reporterCode": reporter_code,
                "period": str(year),
                "cmdCode": hs_code,
                "flowCode": "M",
            }

            resp = requests.get(
                f"{COMTRADE_PREVIEW}/getTarifflineData",
                params=params, headers=HEADERS, timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                records = data.get("data", [])
                if records:
                    all_records.extend(records)
                    continue

            # フォールバック: getDAData
            resp2 = requests.get(
                f"{COMTRADE_PREVIEW}/getDAData",
                params=params, headers=HEADERS, timeout=30,
            )

            if resp2.status_code == 200:
                data2 = resp2.json()
                records2 = data2.get("data", [])
                all_records.extend(records2)

        except requests.RequestException as exc:
            print(f"    [WARN] API エラー ({year}): {exc}")
        except (json.JSONDecodeError, KeyError):
            pass

        time.sleep(RATE_LIMIT)

    return all_records if all_records else None


def aggregate_partners(records: list) -> list:
    """パートナー国別の貿易額を集計し、シェアを計算する。

    Returns:
        [{"country": str, "share": float, "value_usd": int, "partner_code": str}, ...]
    """
    partner_totals = {}

    for rec in records:
        partner_code = str(rec.get("partnerCode", rec.get("partner_code", "")))
        partner_name = rec.get("partnerDesc", rec.get("partner", ""))

        # "World" / "All" は合計行なのでスキップ
        if partner_name and partner_name.lower() in ("world", "all", ""):
            continue
        if partner_code in ("0", ""):
            continue

        # パートナー名の解決
        if not partner_name or partner_name == "N/A":
            partner_name = PARTNER_CODE_MAP.get(partner_code, f"Code_{partner_code}")

        value = rec.get("primaryValue") or rec.get("TradeValue") or 0
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = 0

        key = partner_name
        if key not in partner_totals:
            partner_totals[key] = {"value": 0, "code": partner_code}
        partner_totals[key]["value"] += value

    if not partner_totals:
        return []

    total_value = sum(v["value"] for v in partner_totals.values())
    if total_value <= 0:
        return []

    results = []
    for partner, data in sorted(partner_totals.items(), key=lambda x: x[1]["value"], reverse=True):
        share = data["value"] / total_value
        if share < 0.005:  # 0.5%未満は除外
            continue
        results.append({
            "country": partner,
            "share": round(share, 4),
            "value_usd": int(data["value"]),
            "partner_code": data["code"],
        })

    return results[:15]  # 上位15カ国


def merge_with_existing(new_data: dict) -> dict:
    """既存の hs_proxy_auto.json とマージする。

    新データがある品目×国はそちらを優先し、
    ないものは既存データを保持する。
    """
    if os.path.exists(EXISTING_PROXY_PATH):
        try:
            with open(EXISTING_PROXY_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_hs = existing.get("hs_proxy_data", {})

            for hs_code, countries in existing_hs.items():
                if hs_code not in new_data:
                    new_data[hs_code] = countries
                else:
                    for country, shares in countries.items():
                        if country not in new_data[hs_code]:
                            new_data[hs_code][country] = shares

            print(f"既存データとマージ完了（{EXISTING_PROXY_PATH}）")
        except Exception as exc:
            print(f"既存データ読込失敗（新規データのみ使用）: {exc}")

    return new_data


def generate_python_snippet(data: dict) -> str:
    """tier_inference.py に直接貼り付け可能な Python コードスニペットを生成する。"""
    lines = ["# Auto-generated HS_PROXY_DATA from UN Comtrade"]
    lines.append(f"# Generated: {datetime.utcnow().isoformat()}")
    lines.append("HS_PROXY_DATA_AUTO = {")

    for hs_code in sorted(data.keys()):
        countries = data[hs_code]
        if not countries:
            continue
        lines.append(f'    "{hs_code}": {{')
        for country_name in sorted(countries.keys()):
            shares = countries[country_name]
            if not shares:
                continue
            lines.append(f'        "{country_name}": [')
            for item in shares:
                c = item["country"]
                s = item["share"]
                v = item["value_usd"]
                lines.append(f'            {{"country": "{c}", "share": {s}, "value_usd": {v:_}}},')
            lines.append("        ],")
        lines.append("    },")

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    """全HSコード × 全製造国からComtradeデータを取得し、
    HS_PROXY_DATA 互換のJSONを生成する。
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 70)
    print("BACI代替データ構築（UN Comtrade パブリックAPI）")
    print(f"対象HSコード: {len(HS_CODES)}件")
    print(f"対象製造国: {len(MAJOR_MANUFACTURERS)}カ国")
    print(f"出力先: {OUTPUT_PATH}")
    print("=" * 70)

    result_data = {}
    stats = {"success": 0, "empty": 0, "failed": 0, "total": 0}

    for hs_code, hs_name in HS_CODES.items():
        result_data[hs_code] = {}
        print(f"\n[HS {hs_code}: {hs_name}]")

        for country_name, reporter_code in MAJOR_MANUFACTURERS.items():
            stats["total"] += 1
            print(f"  {country_name}...", end=" ", flush=True)

            records = fetch_import_data(reporter_code, hs_code)
            time.sleep(RATE_LIMIT)

            if records is None:
                print("取得失敗")
                stats["failed"] += 1
                continue

            partners = aggregate_partners(records)
            if partners:
                result_data[hs_code][country_name] = partners
                top3 = ", ".join(f"{p['country']}({p['share']:.0%})" for p in partners[:3])
                print(f"OK ({len(partners)}カ国: {top3})")
                stats["success"] += 1
            else:
                print("データ空")
                stats["empty"] += 1

    # 既存データとマージ
    result_data = merge_with_existing(result_data)

    # JSON保存
    output = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "source": "UN Comtrade Public API (BACI alternative)",
            "hs_codes_queried": len(HS_CODES),
            "manufacturers_queried": len(MAJOR_MANUFACTURERS),
            "stats": stats,
            "description": "BACIデータの代替。UN ComtradeパブリックAPIから自動構築した"
                          "品目別輸入元シェアデータ。tier_inference.py の HS_PROXY_DATA に統合可能。",
        },
        "hs_proxy_data": result_data,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Python コードスニペットも出力
    snippet_path = os.path.join(DATA_DIR, "hs_proxy_snippet.py")
    with open(snippet_path, "w", encoding="utf-8") as f:
        f.write(generate_python_snippet(result_data))

    print(f"\n{'=' * 70}")
    print(f"結果: 成功 {stats['success']}, 空 {stats['empty']}, "
          f"失敗 {stats['failed']} / 合計 {stats['total']}")
    print(f"JSON: {OUTPUT_PATH}")
    print(f"Python snippet: {snippet_path}")
    print(f"{'=' * 70}")

    return output


if __name__ == "__main__":
    main()
