"""Tier-2+ サプライチェーン推定エンジン
UN Comtrade 二国間貿易データを使って、Tier-1 サプライヤーの仕入先
（Tier-2/3）を確率的に推定する。

原理:
  - Tier-1 サプライヤーが国A に所在し、材料 X を使用していると判明した場合
  - 国A が HS コード X を輸入している相手国 B, C, D を Comtrade で取得
  - 貿易シェアに基づいて各国が Tier-2 候補となる確率(confidence)を算出
  - Tier-3 は Tier-2 候補国に対して同じ再帰を 1 段階追加
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
#  HS コード ⇔ 材料 マッピング
# ---------------------------------------------------------------------------
HS_MATERIAL_MAP: dict[str, list[str]] = {
    "lithium": ["2836", "2825"],         # lithium carbonate, lithium oxide
    "cobalt": ["8105", "2605"],          # cobalt articles, cobalt ores
    "nickel": ["2604", "7502"],          # nickel ores, unwrought nickel
    "copper": ["2603", "7403"],          # copper ores, refined copper
    "aluminum": ["2606", "7601"],        # aluminum ores, unwrought aluminum
    "rare_earth": ["2846"],              # rare-earth compounds
    "silicon": ["2804"],                 # silicon
    "iron_ore": ["2601"],               # iron ores
    "graphite": ["2504"],               # natural graphite
    "rubber": ["4001"],                 # natural rubber
    "platinum": ["7110"],               # platinum
    "semiconductor": ["8541", "8542"],   # diodes/transistors, ICs
    "battery": ["8507"],                # electric accumulators (batteries)
    "display": ["9013", "8524"],        # LCD/OLED modules
    "motor": ["8501"],                  # electric motors
    "pcb": ["8534"],                    # printed circuits
    "sensor": ["9031"],                 # measuring instruments
    "steel": ["7206", "7207"],          # iron/steel semi-finished
    "glass": ["7005", "7007"],          # float glass, safety glass
    "plastic": ["3901", "3907"],        # polyethylene, polyesters
    # --- v0.9.0: New HS code mappings ---
    "vehicle": ["8703"],                # passenger vehicles
    "auto_parts": ["8708"],             # auto parts & accessories
    "wire": ["8544"],                   # electric wire/cable
    "lens": ["9013"],                   # optical lenses (shares code with display)
    "silicon_raw": ["2804"],            # silicon (semiconductor material)
    "refined_copper": ["7403"],         # refined copper
    "plastic_film": ["3920"],           # plastic film / sheets
}

# 材料名 → 代表 HS コード（推定用）
MATERIAL_TO_HS: dict[str, str] = {}
for mat, codes in HS_MATERIAL_MAP.items():
    MATERIAL_TO_HS[mat] = codes[0]

# 製品 HS コード → 原材料 HS コード（Tier-3 推定用）
# 完成品を作るのに必要な原材料を逆引きで特定
HS_RAW_MATERIAL_CHAIN: dict[str, list[str]] = {
    "8507": ["8105", "2846", "7501"],    # バッテリー → コバルト/希土類/ニッケル
    "8501": ["2846", "7202"],            # モーター → 希土類/フェロアロイ
    "8542": ["2804", "2818", "2825"],    # 半導体 → ケイ素/アルミナ/希土類
    "8534": ["8542", "7410"],            # PCB → 半導体/銅箔
    "7207": ["2601"],                    # 鉄鋼 → 鉄鉱石
    "7601": ["2606"],                    # アルミ → ボーキサイト
    # v0.9.0: New raw material chains
    "8703": ["8708", "7207", "3920"],    # 乗用車 → 自動車部品/鉄鋼/プラスチック
    "8708": ["7207", "7403", "3920"],    # 自動車部品 → 鉄鋼/銅/プラスチック
    "8544": ["7403", "3920"],            # 電線 → 精製銅/プラスチック
    "9013": ["7005", "2804"],            # 光学レンズ → ガラス/ケイ素
    "3920": ["3901", "3907"],            # プラスチックフィルム → PE/ポリエステル
}

# ---------------------------------------------------------------------------
#  Comtrade 未接続時のフォールバック: 静的近似データ
#  HS コード × 輸入国 → 上位輸出国と貿易シェア
# ---------------------------------------------------------------------------
HS_PROXY_DATA: dict[str, dict[str, list[dict]]] = {
    # =========================================================================
    #  HS 8507 (電池 / Batteries)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8507": {
        "South Korea": [
            {"country": "China", "share": 0.72, "value_usd": 8_200_000_000},
            {"country": "Japan", "share": 0.14, "value_usd": 1_600_000_000},
            {"country": "Belgium", "share": 0.04, "value_usd": 460_000_000},
            {"country": "Germany", "share": 0.03, "value_usd": 340_000_000},
            {"country": "United States", "share": 0.02, "value_usd": 230_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.68, "value_usd": 5_400_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 960_000_000},
            {"country": "Vietnam", "share": 0.06, "value_usd": 480_000_000},
            {"country": "Taiwan", "share": 0.05, "value_usd": 400_000_000},
        ],
        "United States": [
            {"country": "China", "share": 0.42, "value_usd": 6_300_000_000},
            {"country": "South Korea", "share": 0.28, "value_usd": 4_200_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 1_800_000_000},
            {"country": "Germany", "share": 0.06, "value_usd": 900_000_000},
        ],
        "Germany": [
            {"country": "China", "share": 0.38, "value_usd": 3_200_000_000},
            {"country": "Poland", "share": 0.18, "value_usd": 1_500_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 1_260_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 672_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "China", "share": 0.65, "value_usd": 2_600_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 480_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 400_000_000},
            {"country": "Hong Kong", "share": 0.05, "value_usd": 200_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.55, "value_usd": 1_100_000_000},
            {"country": "South Korea", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Taiwan", "share": 0.06, "value_usd": 120_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.58, "value_usd": 1_740_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 540_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 300_000_000},
            {"country": "Germany", "share": 0.05, "value_usd": 150_000_000},
        ],
        "Mexico": [
            {"country": "China", "share": 0.48, "value_usd": 1_440_000_000},
            {"country": "United States", "share": 0.22, "value_usd": 660_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 450_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Poland": [
            {"country": "China", "share": 0.35, "value_usd": 700_000_000},
            {"country": "Germany", "share": 0.25, "value_usd": 500_000_000},
            {"country": "South Korea", "share": 0.20, "value_usd": 400_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Hungary": [
            {"country": "China", "share": 0.40, "value_usd": 1_200_000_000},
            {"country": "South Korea", "share": 0.30, "value_usd": 900_000_000},
            {"country": "Germany", "share": 0.15, "value_usd": 450_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Czech Republic": [
            {"country": "China", "share": 0.38, "value_usd": 380_000_000},
            {"country": "Germany", "share": 0.28, "value_usd": 280_000_000},
            {"country": "Poland", "share": 0.15, "value_usd": 150_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 100_000_000},
        ],
    },
    # =========================================================================
    #  HS 8542 (集積回路 / Integrated circuits)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8542": {
        "South Korea": [
            {"country": "Taiwan", "share": 0.35, "value_usd": 12_000_000_000},
            {"country": "China", "share": 0.25, "value_usd": 8_500_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 5_100_000_000},
            {"country": "United States", "share": 0.10, "value_usd": 3_400_000_000},
        ],
        "Japan": [
            {"country": "Taiwan", "share": 0.40, "value_usd": 14_000_000_000},
            {"country": "China", "share": 0.22, "value_usd": 7_700_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 4_200_000_000},
            {"country": "United States", "share": 0.10, "value_usd": 3_500_000_000},
        ],
        "China": [
            {"country": "Taiwan", "share": 0.32, "value_usd": 48_000_000_000},
            {"country": "South Korea", "share": 0.25, "value_usd": 37_500_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 18_000_000_000},
            {"country": "Malaysia", "share": 0.08, "value_usd": 12_000_000_000},
        ],
        "United States": [
            {"country": "Taiwan", "share": 0.30, "value_usd": 21_000_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 12_600_000_000},
            {"country": "Malaysia", "share": 0.12, "value_usd": 8_400_000_000},
            {"country": "China", "share": 0.10, "value_usd": 7_000_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "China", "share": 0.35, "value_usd": 7_000_000_000},
            {"country": "Taiwan", "share": 0.22, "value_usd": 4_400_000_000},
            {"country": "Singapore", "share": 0.15, "value_usd": 3_000_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 2_000_000_000},
        ],
        "Vietnam": [
            {"country": "South Korea", "share": 0.32, "value_usd": 6_400_000_000},
            {"country": "Taiwan", "share": 0.25, "value_usd": 5_000_000_000},
            {"country": "China", "share": 0.20, "value_usd": 4_000_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 2_000_000_000},
        ],
        "Thailand": [
            {"country": "Taiwan", "share": 0.28, "value_usd": 2_800_000_000},
            {"country": "China", "share": 0.25, "value_usd": 2_500_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 1_200_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.30, "value_usd": 3_000_000_000},
            {"country": "Taiwan", "share": 0.22, "value_usd": 2_200_000_000},
            {"country": "China", "share": 0.20, "value_usd": 2_000_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 1_200_000_000},
        ],
        "Poland": [
            {"country": "China", "share": 0.28, "value_usd": 840_000_000},
            {"country": "Germany", "share": 0.22, "value_usd": 660_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 540_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 360_000_000},
        ],
        "Hungary": [
            {"country": "China", "share": 0.30, "value_usd": 600_000_000},
            {"country": "Germany", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 360_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 240_000_000},
        ],
        "Czech Republic": [
            {"country": "China", "share": 0.30, "value_usd": 450_000_000},
            {"country": "Germany", "share": 0.25, "value_usd": 375_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 270_000_000},
            {"country": "Malaysia", "share": 0.10, "value_usd": 150_000_000},
        ],
    },
    # =========================================================================
    #  HS 2604 (ニッケル鉱 / Nickel ores)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "2604": {
        "China": [
            {"country": "Philippines", "share": 0.40, "value_usd": 3_200_000_000},
            {"country": "Indonesia", "share": 0.30, "value_usd": 2_400_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 960_000_000},
        ],
        "Japan": [
            {"country": "Indonesia", "share": 0.35, "value_usd": 1_400_000_000},
            {"country": "Philippines", "share": 0.25, "value_usd": 1_000_000_000},
            {"country": "Australia", "share": 0.20, "value_usd": 800_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "Indonesia", "share": 0.40, "value_usd": 800_000_000},
            {"country": "Philippines", "share": 0.25, "value_usd": 500_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 300_000_000},
        ],
        "Vietnam": [
            {"country": "Indonesia", "share": 0.45, "value_usd": 270_000_000},
            {"country": "Philippines", "share": 0.30, "value_usd": 180_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 60_000_000},
        ],
        "Thailand": [
            {"country": "Indonesia", "share": 0.38, "value_usd": 190_000_000},
            {"country": "Philippines", "share": 0.28, "value_usd": 140_000_000},
            {"country": "Australia", "share": 0.18, "value_usd": 90_000_000},
        ],
    },
    # =========================================================================
    #  HS 2836 (リチウム / Lithium carbonate)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "2836": {
        "South Korea": [
            {"country": "Chile", "share": 0.40, "value_usd": 2_800_000_000},
            {"country": "Australia", "share": 0.30, "value_usd": 2_100_000_000},
            {"country": "China", "share": 0.15, "value_usd": 1_050_000_000},
            {"country": "Argentina", "share": 0.08, "value_usd": 560_000_000},
        ],
        "China": [
            {"country": "Chile", "share": 0.45, "value_usd": 5_400_000_000},
            {"country": "Australia", "share": 0.35, "value_usd": 4_200_000_000},
            {"country": "Argentina", "share": 0.10, "value_usd": 1_200_000_000},
        ],
        "Japan": [
            {"country": "Chile", "share": 0.38, "value_usd": 1_900_000_000},
            {"country": "Australia", "share": 0.32, "value_usd": 1_600_000_000},
            {"country": "China", "share": 0.18, "value_usd": 900_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "China", "share": 0.45, "value_usd": 450_000_000},
            {"country": "Chile", "share": 0.25, "value_usd": 250_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 150_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.55, "value_usd": 110_000_000},
            {"country": "Chile", "share": 0.20, "value_usd": 40_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 24_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.50, "value_usd": 100_000_000},
            {"country": "Chile", "share": 0.22, "value_usd": 44_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 30_000_000},
        ],
    },
    # =========================================================================
    #  HS 2846 (レアアース / Rare-earth compounds)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "2846": {
        "Japan": [
            {"country": "China", "share": 0.60, "value_usd": 1_200_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Myanmar", "share": 0.10, "value_usd": 200_000_000},
        ],
        "United States": [
            {"country": "China", "share": 0.55, "value_usd": 880_000_000},
            {"country": "Malaysia", "share": 0.12, "value_usd": 192_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 160_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "China", "share": 0.65, "value_usd": 260_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 48_000_000},
            {"country": "Myanmar", "share": 0.10, "value_usd": 40_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.70, "value_usd": 70_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 10_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 8_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.62, "value_usd": 62_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 15_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 10_000_000},
        ],
    },
    # =========================================================================
    #  HS 8105 (コバルト / Cobalt)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8105": {
        "China": [
            {"country": "Congo", "share": 0.72, "value_usd": 4_800_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 1_000_000_000},
            {"country": "Philippines", "share": 0.08, "value_usd": 533_000_000},
        ],
        "Japan": [
            {"country": "Congo", "share": 0.50, "value_usd": 600_000_000},
            {"country": "Australia", "share": 0.25, "value_usd": 300_000_000},
            {"country": "Philippines", "share": 0.15, "value_usd": 180_000_000},
        ],
        "South Korea": [
            {"country": "Congo", "share": 0.55, "value_usd": 880_000_000},
            {"country": "Australia", "share": 0.20, "value_usd": 320_000_000},
            {"country": "Philippines", "share": 0.12, "value_usd": 192_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "Congo", "share": 0.48, "value_usd": 240_000_000},
            {"country": "Australia", "share": 0.20, "value_usd": 100_000_000},
            {"country": "Philippines", "share": 0.15, "value_usd": 75_000_000},
        ],
    },
    # =========================================================================
    #  HS 8501 (電動機 / Electric motors)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8501": {
        "South Korea": [
            {"country": "China", "share": 0.55, "value_usd": 2_200_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 720_000_000},
            {"country": "Germany", "share": 0.08, "value_usd": 320_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.50, "value_usd": 1_800_000_000},
            {"country": "Thailand", "share": 0.15, "value_usd": 540_000_000},
            {"country": "Vietnam", "share": 0.10, "value_usd": 360_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "China", "share": 0.52, "value_usd": 1_560_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 450_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 300_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.48, "value_usd": 960_000_000},
            {"country": "Japan", "share": 0.20, "value_usd": 400_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Taiwan", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.42, "value_usd": 840_000_000},
            {"country": "Japan", "share": 0.28, "value_usd": 560_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 200_000_000},
            {"country": "Taiwan", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Mexico": [
            {"country": "China", "share": 0.38, "value_usd": 760_000_000},
            {"country": "United States", "share": 0.25, "value_usd": 500_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Poland": [
            {"country": "Germany", "share": 0.35, "value_usd": 350_000_000},
            {"country": "China", "share": 0.28, "value_usd": 280_000_000},
            {"country": "Italy", "share": 0.12, "value_usd": 120_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 80_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.32, "value_usd": 192_000_000},
            {"country": "China", "share": 0.28, "value_usd": 168_000_000},
            {"country": "Italy", "share": 0.15, "value_usd": 90_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 60_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.35, "value_usd": 175_000_000},
            {"country": "China", "share": 0.25, "value_usd": 125_000_000},
            {"country": "Italy", "share": 0.12, "value_usd": 60_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 50_000_000},
        ],
    },
    # =========================================================================
    #  HS 2603 (銅鉱 / Copper ores)
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "2603": {
        "China": [
            {"country": "Chile", "share": 0.30, "value_usd": 9_000_000_000},
            {"country": "Peru", "share": 0.20, "value_usd": 6_000_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 3_600_000_000},
        ],
        "Japan": [
            {"country": "Chile", "share": 0.35, "value_usd": 3_500_000_000},
            {"country": "Indonesia", "share": 0.20, "value_usd": 2_000_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 1_500_000_000},
        ],
        # v0.9.0: New country importers (estimates)
        "India": [
            {"country": "Chile", "share": 0.28, "value_usd": 1_400_000_000},
            {"country": "Peru", "share": 0.22, "value_usd": 1_100_000_000},
            {"country": "Indonesia", "share": 0.18, "value_usd": 900_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 600_000_000},
        ],
    },
    # =========================================================================
    #  HS 8703 (乗用車 / Passenger vehicles)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8703": {
        "United States": [
            {"country": "Mexico", "share": 0.28, "value_usd": 56_000_000_000},
            {"country": "Japan", "share": 0.22, "value_usd": 44_000_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 30_000_000_000},
            {"country": "Germany", "share": 0.12, "value_usd": 24_000_000_000},
            {"country": "Canada", "share": 0.10, "value_usd": 20_000_000_000},
        ],
        "Germany": [
            {"country": "Czech Republic", "share": 0.15, "value_usd": 6_000_000_000},
            {"country": "Spain", "share": 0.12, "value_usd": 4_800_000_000},
            {"country": "United Kingdom", "share": 0.10, "value_usd": 4_000_000_000},
            {"country": "France", "share": 0.10, "value_usd": 4_000_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 3_200_000_000},
        ],
        "China": [
            {"country": "Germany", "share": 0.35, "value_usd": 28_000_000_000},
            {"country": "Japan", "share": 0.25, "value_usd": 20_000_000_000},
            {"country": "United States", "share": 0.12, "value_usd": 9_600_000_000},
            {"country": "United Kingdom", "share": 0.08, "value_usd": 6_400_000_000},
        ],
        "Japan": [
            {"country": "Germany", "share": 0.30, "value_usd": 6_000_000_000},
            {"country": "United Kingdom", "share": 0.15, "value_usd": 3_000_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 2_400_000_000},
            {"country": "Italy", "share": 0.10, "value_usd": 2_000_000_000},
        ],
        "India": [
            {"country": "South Korea", "share": 0.25, "value_usd": 2_500_000_000},
            {"country": "Japan", "share": 0.22, "value_usd": 2_200_000_000},
            {"country": "Germany", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "China", "share": 0.15, "value_usd": 1_500_000_000},
        ],
        "Vietnam": [
            {"country": "Thailand", "share": 0.28, "value_usd": 1_400_000_000},
            {"country": "Indonesia", "share": 0.22, "value_usd": 1_100_000_000},
            {"country": "China", "share": 0.18, "value_usd": 900_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 750_000_000},
        ],
        "Thailand": [
            {"country": "Japan", "share": 0.35, "value_usd": 3_500_000_000},
            {"country": "Indonesia", "share": 0.15, "value_usd": 1_500_000_000},
            {"country": "Germany", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "China", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.40, "value_usd": 8_000_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 3_600_000_000},
            {"country": "Germany", "share": 0.12, "value_usd": 2_400_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 2_000_000_000},
        ],
        "Poland": [
            {"country": "Germany", "share": 0.35, "value_usd": 7_000_000_000},
            {"country": "France", "share": 0.12, "value_usd": 2_400_000_000},
            {"country": "Czech Republic", "share": 0.10, "value_usd": 2_000_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 1_600_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.35, "value_usd": 3_500_000_000},
            {"country": "Czech Republic", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "Slovakia", "share": 0.10, "value_usd": 1_000_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 800_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.32, "value_usd": 3_200_000_000},
            {"country": "Slovakia", "share": 0.15, "value_usd": 1_500_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "France", "share": 0.10, "value_usd": 1_000_000_000},
        ],
    },
    # =========================================================================
    #  HS 8708 (自動車部品 / Auto parts)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8708": {
        "United States": [
            {"country": "Mexico", "share": 0.35, "value_usd": 28_000_000_000},
            {"country": "China", "share": 0.18, "value_usd": 14_400_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 9_600_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 8_000_000_000},
            {"country": "Canada", "share": 0.08, "value_usd": 6_400_000_000},
        ],
        "Germany": [
            {"country": "Czech Republic", "share": 0.18, "value_usd": 5_400_000_000},
            {"country": "Poland", "share": 0.15, "value_usd": 4_500_000_000},
            {"country": "China", "share": 0.12, "value_usd": 3_600_000_000},
            {"country": "France", "share": 0.10, "value_usd": 3_000_000_000},
            {"country": "Italy", "share": 0.08, "value_usd": 2_400_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.42, "value_usd": 8_400_000_000},
            {"country": "Thailand", "share": 0.18, "value_usd": 3_600_000_000},
            {"country": "Vietnam", "share": 0.10, "value_usd": 2_000_000_000},
            {"country": "Indonesia", "share": 0.08, "value_usd": 1_600_000_000},
        ],
        "China": [
            {"country": "Japan", "share": 0.28, "value_usd": 8_400_000_000},
            {"country": "Germany", "share": 0.22, "value_usd": 6_600_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 4_500_000_000},
            {"country": "Thailand", "share": 0.08, "value_usd": 2_400_000_000},
        ],
        "India": [
            {"country": "China", "share": 0.30, "value_usd": 3_000_000_000},
            {"country": "Germany", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 1_500_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 1_200_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.32, "value_usd": 1_600_000_000},
            {"country": "Japan", "share": 0.25, "value_usd": 1_250_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 900_000_000},
            {"country": "Thailand", "share": 0.10, "value_usd": 500_000_000},
        ],
        "Thailand": [
            {"country": "Japan", "share": 0.35, "value_usd": 5_250_000_000},
            {"country": "China", "share": 0.22, "value_usd": 3_300_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 1_500_000_000},
            {"country": "Indonesia", "share": 0.08, "value_usd": 1_200_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.40, "value_usd": 12_000_000_000},
            {"country": "China", "share": 0.18, "value_usd": 5_400_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 3_600_000_000},
            {"country": "Germany", "share": 0.08, "value_usd": 2_400_000_000},
        ],
        "Poland": [
            {"country": "Germany", "share": 0.38, "value_usd": 5_700_000_000},
            {"country": "Czech Republic", "share": 0.15, "value_usd": 2_250_000_000},
            {"country": "Italy", "share": 0.10, "value_usd": 1_500_000_000},
            {"country": "France", "share": 0.08, "value_usd": 1_200_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.38, "value_usd": 3_040_000_000},
            {"country": "Czech Republic", "share": 0.12, "value_usd": 960_000_000},
            {"country": "Poland", "share": 0.10, "value_usd": 800_000_000},
            {"country": "Austria", "share": 0.08, "value_usd": 640_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.40, "value_usd": 4_000_000_000},
            {"country": "Poland", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "Slovakia", "share": 0.10, "value_usd": 1_000_000_000},
            {"country": "Italy", "share": 0.08, "value_usd": 800_000_000},
        ],
    },
    # =========================================================================
    #  HS 8544 (電線・ケーブル / Electric wire & cable)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "8544": {
        "United States": [
            {"country": "Mexico", "share": 0.32, "value_usd": 9_600_000_000},
            {"country": "China", "share": 0.28, "value_usd": 8_400_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 2_400_000_000},
            {"country": "Germany", "share": 0.06, "value_usd": 1_800_000_000},
        ],
        "Germany": [
            {"country": "China", "share": 0.22, "value_usd": 2_200_000_000},
            {"country": "Poland", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Czech Republic", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "Romania", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.45, "value_usd": 2_700_000_000},
            {"country": "Vietnam", "share": 0.15, "value_usd": 900_000_000},
            {"country": "Philippines", "share": 0.10, "value_usd": 600_000_000},
            {"country": "Thailand", "share": 0.08, "value_usd": 480_000_000},
        ],
        "China": [
            {"country": "Japan", "share": 0.22, "value_usd": 1_320_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 1_080_000_000},
            {"country": "Germany", "share": 0.15, "value_usd": 900_000_000},
            {"country": "Taiwan", "share": 0.12, "value_usd": 720_000_000},
        ],
        "India": [
            {"country": "China", "share": 0.52, "value_usd": 2_600_000_000},
            {"country": "Vietnam", "share": 0.10, "value_usd": 500_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 400_000_000},
            {"country": "Japan", "share": 0.06, "value_usd": 300_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.38, "value_usd": 760_000_000},
            {"country": "South Korea", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Taiwan", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.35, "value_usd": 700_000_000},
            {"country": "Japan", "share": 0.25, "value_usd": 500_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Taiwan", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.30, "value_usd": 1_500_000_000},
            {"country": "China", "share": 0.28, "value_usd": 1_400_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 500_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 400_000_000},
        ],
        "Poland": [
            {"country": "Germany", "share": 0.32, "value_usd": 960_000_000},
            {"country": "China", "share": 0.22, "value_usd": 660_000_000},
            {"country": "Romania", "share": 0.12, "value_usd": 360_000_000},
            {"country": "Czech Republic", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.30, "value_usd": 450_000_000},
            {"country": "China", "share": 0.22, "value_usd": 330_000_000},
            {"country": "Romania", "share": 0.15, "value_usd": 225_000_000},
            {"country": "Czech Republic", "share": 0.10, "value_usd": 150_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.35, "value_usd": 525_000_000},
            {"country": "China", "share": 0.20, "value_usd": 300_000_000},
            {"country": "Poland", "share": 0.12, "value_usd": 180_000_000},
            {"country": "Romania", "share": 0.10, "value_usd": 150_000_000},
        ],
    },
    # =========================================================================
    #  HS 9013 (光学レンズ / Optical lenses & devices)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "9013": {
        "United States": [
            {"country": "China", "share": 0.32, "value_usd": 3_200_000_000},
            {"country": "Japan", "share": 0.22, "value_usd": 2_200_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Taiwan", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.35, "value_usd": 1_750_000_000},
            {"country": "South Korea", "share": 0.22, "value_usd": 1_100_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 900_000_000},
            {"country": "Germany", "share": 0.08, "value_usd": 400_000_000},
        ],
        "China": [
            {"country": "Japan", "share": 0.30, "value_usd": 3_000_000_000},
            {"country": "South Korea", "share": 0.28, "value_usd": 2_800_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Germany", "share": 0.08, "value_usd": 800_000_000},
        ],
        "Germany": [
            {"country": "China", "share": 0.28, "value_usd": 840_000_000},
            {"country": "Japan", "share": 0.22, "value_usd": 660_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 540_000_000},
            {"country": "Taiwan", "share": 0.12, "value_usd": 360_000_000},
        ],
        "India": [
            {"country": "China", "share": 0.48, "value_usd": 960_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 300_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Taiwan", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Vietnam": [
            {"country": "South Korea", "share": 0.35, "value_usd": 700_000_000},
            {"country": "China", "share": 0.28, "value_usd": 560_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Taiwan", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Thailand": [
            {"country": "Japan", "share": 0.30, "value_usd": 300_000_000},
            {"country": "China", "share": 0.28, "value_usd": 280_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 150_000_000},
            {"country": "Taiwan", "share": 0.10, "value_usd": 100_000_000},
        ],
        "Mexico": [
            {"country": "China", "share": 0.35, "value_usd": 350_000_000},
            {"country": "United States", "share": 0.25, "value_usd": 250_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 150_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 100_000_000},
        ],
    },
    # =========================================================================
    #  HS 2804 (ケイ素 / Silicon)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "2804": {
        "Japan": [
            {"country": "China", "share": 0.40, "value_usd": 800_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Brazil", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Norway", "share": 0.10, "value_usd": 200_000_000},
        ],
        "United States": [
            {"country": "China", "share": 0.35, "value_usd": 700_000_000},
            {"country": "Brazil", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Norway", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 200_000_000},
        ],
        "South Korea": [
            {"country": "China", "share": 0.45, "value_usd": 900_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Australia", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Norway", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Germany": [
            {"country": "China", "share": 0.28, "value_usd": 280_000_000},
            {"country": "Norway", "share": 0.22, "value_usd": 220_000_000},
            {"country": "Brazil", "share": 0.18, "value_usd": 180_000_000},
            {"country": "France", "share": 0.10, "value_usd": 100_000_000},
        ],
        "India": [
            {"country": "China", "share": 0.55, "value_usd": 550_000_000},
            {"country": "Malaysia", "share": 0.12, "value_usd": 120_000_000},
            {"country": "Norway", "share": 0.08, "value_usd": 80_000_000},
            {"country": "Brazil", "share": 0.08, "value_usd": 80_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.60, "value_usd": 120_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 30_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 20_000_000},
        ],
        "Thailand": [
            {"country": "China", "share": 0.50, "value_usd": 100_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 36_000_000},
            {"country": "Australia", "share": 0.10, "value_usd": 20_000_000},
        ],
    },
    # =========================================================================
    #  HS 7403 (精製銅 / Refined copper)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "7403": {
        "China": [
            {"country": "Chile", "share": 0.25, "value_usd": 7_500_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 4_500_000_000},
            {"country": "Congo", "share": 0.12, "value_usd": 3_600_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 3_000_000_000},
        ],
        "United States": [
            {"country": "Chile", "share": 0.30, "value_usd": 4_500_000_000},
            {"country": "Canada", "share": 0.22, "value_usd": 3_300_000_000},
            {"country": "Mexico", "share": 0.12, "value_usd": 1_800_000_000},
            {"country": "Peru", "share": 0.10, "value_usd": 1_500_000_000},
        ],
        "Japan": [
            {"country": "Chile", "share": 0.32, "value_usd": 3_200_000_000},
            {"country": "Indonesia", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 1_500_000_000},
            {"country": "Peru", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "Germany": [
            {"country": "Chile", "share": 0.22, "value_usd": 1_320_000_000},
            {"country": "Poland", "share": 0.18, "value_usd": 1_080_000_000},
            {"country": "Russia", "share": 0.12, "value_usd": 720_000_000},
            {"country": "Belgium", "share": 0.10, "value_usd": 600_000_000},
        ],
        "India": [
            {"country": "Chile", "share": 0.25, "value_usd": 1_250_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 900_000_000},
            {"country": "Indonesia", "share": 0.15, "value_usd": 750_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 600_000_000},
        ],
        "Vietnam": [
            {"country": "Japan", "share": 0.28, "value_usd": 560_000_000},
            {"country": "South Korea", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Chile", "share": 0.18, "value_usd": 360_000_000},
            {"country": "China", "share": 0.12, "value_usd": 240_000_000},
        ],
        "Thailand": [
            {"country": "Japan", "share": 0.30, "value_usd": 600_000_000},
            {"country": "Chile", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Australia", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Indonesia", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.35, "value_usd": 1_050_000_000},
            {"country": "Chile", "share": 0.25, "value_usd": 750_000_000},
            {"country": "Peru", "share": 0.15, "value_usd": 450_000_000},
            {"country": "Japan", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Poland": [
            {"country": "Chile", "share": 0.22, "value_usd": 440_000_000},
            {"country": "Germany", "share": 0.20, "value_usd": 400_000_000},
            {"country": "Belgium", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Sweden", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.28, "value_usd": 168_000_000},
            {"country": "Poland", "share": 0.22, "value_usd": 132_000_000},
            {"country": "Chile", "share": 0.18, "value_usd": 108_000_000},
            {"country": "Austria", "share": 0.12, "value_usd": 72_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.30, "value_usd": 180_000_000},
            {"country": "Poland", "share": 0.22, "value_usd": 132_000_000},
            {"country": "Belgium", "share": 0.15, "value_usd": 90_000_000},
            {"country": "Chile", "share": 0.12, "value_usd": 72_000_000},
        ],
    },
    # =========================================================================
    #  HS 3920 (プラスチックフィルム / Plastic film & sheets)   [v0.9.0 NEW]
    #  Note: Shares are estimates based on known global trade patterns.
    # =========================================================================
    "3920": {
        "United States": [
            {"country": "China", "share": 0.30, "value_usd": 3_000_000_000},
            {"country": "Japan", "share": 0.15, "value_usd": 1_500_000_000},
            {"country": "South Korea", "share": 0.12, "value_usd": 1_200_000_000},
            {"country": "Germany", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "Germany": [
            {"country": "China", "share": 0.18, "value_usd": 720_000_000},
            {"country": "Italy", "share": 0.15, "value_usd": 600_000_000},
            {"country": "Netherlands", "share": 0.12, "value_usd": 480_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 400_000_000},
        ],
        "Japan": [
            {"country": "China", "share": 0.35, "value_usd": 1_050_000_000},
            {"country": "South Korea", "share": 0.18, "value_usd": 540_000_000},
            {"country": "Taiwan", "share": 0.15, "value_usd": 450_000_000},
            {"country": "Thailand", "share": 0.10, "value_usd": 300_000_000},
        ],
        "China": [
            {"country": "Japan", "share": 0.28, "value_usd": 2_800_000_000},
            {"country": "South Korea", "share": 0.22, "value_usd": 2_200_000_000},
            {"country": "Taiwan", "share": 0.18, "value_usd": 1_800_000_000},
            {"country": "Saudi Arabia", "share": 0.10, "value_usd": 1_000_000_000},
        ],
        "India": [
            {"country": "China", "share": 0.42, "value_usd": 1_260_000_000},
            {"country": "Japan", "share": 0.12, "value_usd": 360_000_000},
            {"country": "South Korea", "share": 0.10, "value_usd": 300_000_000},
            {"country": "Thailand", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Vietnam": [
            {"country": "China", "share": 0.38, "value_usd": 760_000_000},
            {"country": "South Korea", "share": 0.20, "value_usd": 400_000_000},
            {"country": "Japan", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Taiwan", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Thailand": [
            {"country": "Japan", "share": 0.28, "value_usd": 560_000_000},
            {"country": "China", "share": 0.25, "value_usd": 500_000_000},
            {"country": "South Korea", "share": 0.15, "value_usd": 300_000_000},
            {"country": "Taiwan", "share": 0.10, "value_usd": 200_000_000},
        ],
        "Mexico": [
            {"country": "United States", "share": 0.35, "value_usd": 1_050_000_000},
            {"country": "China", "share": 0.25, "value_usd": 750_000_000},
            {"country": "Japan", "share": 0.10, "value_usd": 300_000_000},
            {"country": "South Korea", "share": 0.08, "value_usd": 240_000_000},
        ],
        "Poland": [
            {"country": "Germany", "share": 0.32, "value_usd": 640_000_000},
            {"country": "China", "share": 0.18, "value_usd": 360_000_000},
            {"country": "Italy", "share": 0.12, "value_usd": 240_000_000},
            {"country": "Czech Republic", "share": 0.08, "value_usd": 160_000_000},
        ],
        "Hungary": [
            {"country": "Germany", "share": 0.30, "value_usd": 300_000_000},
            {"country": "China", "share": 0.18, "value_usd": 180_000_000},
            {"country": "Austria", "share": 0.15, "value_usd": 150_000_000},
            {"country": "Italy", "share": 0.12, "value_usd": 120_000_000},
        ],
        "Czech Republic": [
            {"country": "Germany", "share": 0.35, "value_usd": 350_000_000},
            {"country": "Poland", "share": 0.15, "value_usd": 150_000_000},
            {"country": "China", "share": 0.15, "value_usd": 150_000_000},
            {"country": "Italy", "share": 0.10, "value_usd": 100_000_000},
        ],
    },
}


@dataclass
class InferredSupplier:
    """推定されたサプライヤー情報"""
    country: str
    tier: int                        # 2 or 3
    hs_code: str
    material: str
    trade_share: float               # 0.0-1.0
    trade_value_usd: float
    confidence: float                # 0.0-1.0
    source: str = "comtrade"         # "comtrade" or "proxy"
    risk_score: Optional[int] = None # 後で付与


@dataclass
class SupplyTreeNode:
    """供給ツリーのノード"""
    country: str
    tier: int
    material: str
    hs_code: str
    trade_share: float
    confidence: float
    risk_score: Optional[int] = None
    children: list["SupplyTreeNode"] = field(default_factory=list)
    is_inferred: bool = True

    def to_dict(self) -> dict:
        return {
            "country": self.country,
            "tier": self.tier,
            "material": self.material,
            "hs_code": self.hs_code,
            "trade_share": round(self.trade_share, 4),
            "confidence": round(self.confidence, 3),
            "risk_score": self.risk_score,
            "is_inferred": self.is_inferred,
            "children": [c.to_dict() for c in self.children],
        }


class TierInferenceEngine:
    """Tier-2/3 サプライチェーン推定エンジン"""

    def __init__(self, cache_dir: str = None):
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.cache_dir = cache_dir or os.path.join(project_root, "data", "comtrade_cache")
        self._cache: dict[str, dict] = {}
        self._load_cache()

    def _load_cache(self):
        """ディスクキャッシュを読み込み"""
        if not os.path.isdir(self.cache_dir):
            return
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self.cache_dir, fname), "r") as f:
                        data = json.load(f)
                    key = fname.replace(".json", "")
                    self._cache[key] = data
                except Exception:
                    pass

    def _cache_key(self, importer: str, hs_code: str) -> str:
        return f"{importer.lower().replace(' ', '_')}_{hs_code}"

    def _get_import_sources(self, importer: str, hs_code: str) -> list[dict]:
        """国 importer が HS コード hs_code を輸入している相手国リストを返す。

        優先順位:
        1. ディスクキャッシュ (Comtrade API で事前取得)
        2. ライブ Comtrade API
        3. HS_PROXY_DATA (フォールバック)
        """
        # 1. キャッシュ
        key = self._cache_key(importer, hs_code)
        if key in self._cache:
            return self._cache[key].get("sources", [])

        # 2. ライブ API
        live = self._fetch_comtrade_live(importer, hs_code)
        if live:
            return live

        # 3. フォールバック
        proxy = HS_PROXY_DATA.get(hs_code, {})
        # Try exact match first, then fuzzy
        for name in [importer, importer.title()]:
            if name in proxy:
                return proxy[name]

        # Try substring match
        importer_lower = importer.lower()
        for country_name, sources in proxy.items():
            if importer_lower in country_name.lower() or country_name.lower() in importer_lower:
                return sources

        return []

    def _fetch_comtrade_live(self, importer: str, hs_code: str) -> list[dict]:
        """Comtrade API からライブデータを取得"""
        try:
            from pipeline.trade.comtrade_client import (
                _resolve_code, COMTRADE_PREVIEW, COMTRADE_FULL, COMTRADE_KEY,
            )
            import requests

            reporter_code = _resolve_code(importer)
            if not reporter_code:
                return []

            params = {
                "reporterCode": reporter_code,
                "partnerCode": "0",  # World (all partners)
                "period": "2023",
                "cmdCode": hs_code,
                "flowCode": "M",  # Imports only
            }

            url = COMTRADE_FULL if COMTRADE_KEY else COMTRADE_PREVIEW
            headers = {"Ocp-Apim-Subscription-Key": COMTRADE_KEY} if COMTRADE_KEY else {}

            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            records = data.get("data", [])
            if not records:
                return []

            # Calculate total import value
            total_value = sum(
                r.get("primaryValue") or r.get("cifvalue") or 0
                for r in records
                if r.get("partnerCode", 0) != 0  # exclude "World"
            )

            if total_value == 0:
                return []

            sources = []
            for r in records:
                partner_code = r.get("partnerCode", 0)
                if partner_code == 0:
                    continue
                value = r.get("primaryValue") or r.get("cifvalue") or 0
                if value <= 0:
                    continue
                partner_name = r.get("partnerDesc", f"Code:{partner_code}")
                sources.append({
                    "country": partner_name,
                    "share": round(value / total_value, 4),
                    "value_usd": value,
                })

            sources.sort(key=lambda x: -x["share"])

            # Cache result
            self._save_to_cache(importer, hs_code, sources)

            return sources[:10]

        except Exception:
            return []

    def _save_to_cache(self, importer: str, hs_code: str, sources: list[dict]):
        """結果をディスクキャッシュに保存"""
        os.makedirs(self.cache_dir, exist_ok=True)
        key = self._cache_key(importer, hs_code)
        data = {
            "importer": importer,
            "hs_code": hs_code,
            "sources": sources,
            "fetched_at": datetime.utcnow().isoformat(),
        }
        self._cache[key] = data
        try:
            with open(os.path.join(self.cache_dir, f"{key}.json"), "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def infer_tier2(
        self,
        tier1_country: str,
        hs_code: str,
        material: str = "",
        min_share: float = 0.02,
    ) -> list[InferredSupplier]:
        """Tier-1 国の輸入データから Tier-2 候補を推定する。

        Args:
            tier1_country: Tier-1 サプライヤーの所在国
            hs_code: 対象材料の HS コード
            material: 材料名（表示用）
            min_share: 最小貿易シェア閾値（これ以下の国は除外）

        Returns:
            InferredSupplier のリスト（confidence 降順）
        """
        sources = self._get_import_sources(tier1_country, hs_code)
        if not sources:
            return []

        results = []
        for src in sources:
            share = src.get("share", 0)
            if share < min_share:
                continue

            # Confidence = trade_share * data_freshness_factor
            # Proxy data gets 0.7x, cached Comtrade gets 0.9x, live gets 1.0x
            key = self._cache_key(tier1_country, hs_code)
            if key in self._cache:
                source_type = "comtrade"
                freshness = 0.9
            else:
                source_type = "proxy"
                freshness = 0.7

            confidence = min(1.0, share * freshness)

            results.append(InferredSupplier(
                country=src["country"],
                tier=2,
                hs_code=hs_code,
                material=material or hs_code,
                trade_share=share,
                trade_value_usd=src.get("value_usd", 0),
                confidence=round(confidence, 3),
                source=source_type,
            ))

        results.sort(key=lambda x: -x.confidence)
        return results

    def infer_tier3(
        self,
        tier2_countries: list[InferredSupplier],
        raw_material_hs: str = None,
        min_share: float = 0.05,
    ) -> list[InferredSupplier]:
        """Tier-2 候補群の各国が原材料を輸入している Tier-3 国を推定。

        Args:
            tier2_countries: Tier-2 の推定結果
            raw_material_hs: 原材料の HS コード（None の場合は HS_RAW_MATERIAL_CHAIN で自動推定）
            min_share: 最小貿易シェア閾値

        Returns:
            InferredSupplier のリスト（Tier-3）
        """
        results = []
        seen = set()

        for t2 in tier2_countries:
            # Determine raw material HS codes for Tier-3
            if raw_material_hs:
                hs_list = [raw_material_hs]
            else:
                # Auto-detect from raw material chain
                hs_list = HS_RAW_MATERIAL_CHAIN.get(t2.hs_code, [t2.hs_code])

            for hs in hs_list:
                t3_candidates = self._get_import_sources(t2.country, hs)

                for src in t3_candidates:
                    share = src.get("share", 0)
                    if share < min_share:
                        continue

                    country = src["country"]
                    dedupe_key = f"{country}|{hs}"
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    # Tier-3 confidence = tier2_confidence * tier3_share * 0.6
                    confidence = min(1.0, t2.confidence * share * 0.6)

                    results.append(InferredSupplier(
                        country=country,
                        tier=3,
                        hs_code=hs,
                        material=t2.material,
                        trade_share=share,
                        trade_value_usd=src.get("value_usd", 0),
                        confidence=round(confidence, 3),
                        source=t2.source,
                    ))

        results.sort(key=lambda x: -x.confidence)
        return results

    def build_full_supply_tree(
        self,
        tier1_country: str,
        materials: list[dict],
        max_depth: int = 3,
    ) -> list[SupplyTreeNode]:
        """材料リストから完全な供給ツリーを構築。

        Args:
            tier1_country: Tier-1 サプライヤーの所在国
            materials: [{"material": "battery", "hs_code": "8507"}, ...]
            max_depth: 最大推定深度 (2=Tier-2 まで, 3=Tier-3 まで)

        Returns:
            SupplyTreeNode のルートリスト
        """
        tree: list[SupplyTreeNode] = []

        for mat_info in materials:
            material = mat_info.get("material", "")
            hs_code = mat_info.get("hs_code", "")

            if not hs_code and material:
                hs_code = MATERIAL_TO_HS.get(material.lower(), "")
            if not hs_code:
                continue

            # Tier-2
            tier2 = self.infer_tier2(tier1_country, hs_code, material)

            for t2 in tier2:
                node = SupplyTreeNode(
                    country=t2.country,
                    tier=2,
                    material=material,
                    hs_code=hs_code,
                    trade_share=t2.trade_share,
                    confidence=t2.confidence,
                )

                # Tier-3
                if max_depth >= 3:
                    tier3 = self.infer_tier3([t2], min_share=0.05)
                    for t3 in tier3:
                        child = SupplyTreeNode(
                            country=t3.country,
                            tier=3,
                            material=material,
                            hs_code=t3.hs_code,
                            trade_share=t3.trade_share,
                            confidence=t3.confidence,
                        )
                        node.children.append(child)

                tree.append(node)

        return tree

    def estimate_risk_exposure(
        self,
        tier1_country: str,
        hs_code: str,
        material: str = "",
    ) -> dict:
        """特定材料の隠れたリスク・エクスポージャーを推定。

        Tier-1 の国リスクだけでは見えない、Tier-2/3 由来のリスクを算出。

        Returns:
            {
                "tier1_risk": int,
                "weighted_tier2_risk": float,
                "weighted_tier3_risk": float,
                "full_risk": float,
                "hidden_risk_delta": float,
                "tier2_suppliers": [...],
                "tier3_suppliers": [...],
                "highest_risk_path": str,
            }
        """
        from scoring.engine import calculate_risk_score

        # Tier-1 risk
        t1_score = calculate_risk_score(
            f"tier1_{tier1_country}", f"Tier1: {tier1_country}",
            country=tier1_country, location=tier1_country,
        )
        tier1_risk = t1_score.overall_score

        # Tier-2 inference
        tier2 = self.infer_tier2(tier1_country, hs_code, material)

        # Score each Tier-2 country
        tier2_weighted = 0.0
        tier2_results = []
        for t2 in tier2:
            try:
                t2_score = calculate_risk_score(
                    f"tier2_{t2.country}", f"Tier2: {t2.country}",
                    country=t2.country, location=t2.country,
                )
                t2.risk_score = t2_score.overall_score
            except Exception:
                t2.risk_score = 0

            weighted = t2.risk_score * t2.trade_share * t2.confidence
            tier2_weighted += weighted
            tier2_results.append({
                "country": t2.country,
                "trade_share": round(t2.trade_share, 4),
                "confidence": t2.confidence,
                "risk_score": t2.risk_score,
                "weighted_contribution": round(weighted, 2),
                "source": t2.source,
            })

        # Tier-3 inference
        tier3 = self.infer_tier3(tier2)
        tier3_weighted = 0.0
        tier3_results = []
        for t3 in tier3:
            try:
                t3_score = calculate_risk_score(
                    f"tier3_{t3.country}", f"Tier3: {t3.country}",
                    country=t3.country, location=t3.country,
                )
                t3.risk_score = t3_score.overall_score
            except Exception:
                t3.risk_score = 0

            weighted = t3.risk_score * t3.trade_share * t3.confidence
            tier3_weighted += weighted
            tier3_results.append({
                "country": t3.country,
                "trade_share": round(t3.trade_share, 4),
                "confidence": t3.confidence,
                "risk_score": t3.risk_score,
                "weighted_contribution": round(weighted, 2),
                "source": t3.source,
            })

        # Full risk = Tier-1 + weighted Tier-2 + weighted Tier-3
        full_risk = min(100, tier1_risk + tier2_weighted * 0.4 + tier3_weighted * 0.2)
        hidden_delta = round(full_risk - tier1_risk, 1)

        # Find highest risk path
        all_inferred = tier2_results + tier3_results
        if all_inferred:
            worst = max(all_inferred, key=lambda x: x["risk_score"])
            highest_path = f"{tier1_country} → {worst['country']} (Tier-{2 if worst in tier2_results else 3}, risk={worst['risk_score']})"
        else:
            highest_path = f"{tier1_country} (Tier-1 only)"

        return {
            "material": material or hs_code,
            "hs_code": hs_code,
            "tier1_country": tier1_country,
            "tier1_risk": tier1_risk,
            "weighted_tier2_risk": round(tier2_weighted, 2),
            "weighted_tier3_risk": round(tier3_weighted, 2),
            "full_risk": round(full_risk, 1),
            "hidden_risk_delta": hidden_delta,
            "tier2_suppliers": tier2_results,
            "tier3_suppliers": tier3_results,
            "highest_risk_path": highest_path,
            "timestamp": datetime.utcnow().isoformat(),
        }
