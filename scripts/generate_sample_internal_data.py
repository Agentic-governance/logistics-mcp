#!/usr/bin/env python3
"""
サンプル内部ロジスティクスデータ生成スクリプト
==============================================
リアルな物流・製造シナリオを想定した6種類のCSVを生成し、
取込テストまで実行する。

出力:
  data/sample_inventory.csv         — 50部品×5拠点
  data/sample_purchase_orders.csv   — 30件発注残
  data/sample_production_plan.csv   — 3製品×30日間
  data/sample_locations.csv         — 工場3＋倉庫5＋港湾3
  data/sample_transport_routes.csv  — 主要ルート20本
  data/sample_procurement_costs.csv — 50部品×複数仕入先
"""

import os
import sys
import csv
import random
import datetime

# プロジェクトルートをパスに追加
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

random.seed(42)

TODAY = datetime.date(2026, 3, 28)

# ---------- 共通マスタ ----------

# 部品リスト（自動車部品風）
PARTS = [f"P{str(i).zfill(4)}" for i in range(1, 51)]

PART_NAMES = {
    "P0001": "リチウムイオンバッテリーセル",
    "P0002": "モーターコイル",
    "P0003": "インバーター基板",
    "P0004": "車載半導体(MCU)",
    "P0005": "レアアース磁石",
    "P0006": "アルミダイカスト筐体",
    "P0007": "銅線ハーネス",
    "P0008": "冷却用ラジエーター",
    "P0009": "高張力鋼板",
    "P0010": "CFRP構造材",
}

# 拠点ID
PLANTS = ["PLT-JP01", "PLT-CN01", "PLT-TH01"]
WAREHOUSES = ["WH-JP01", "WH-JP02", "WH-CN01", "WH-TH01", "WH-SG01"]
PORTS = ["PORT-TOKYO", "PORT-SHANGHAI", "PORT-LAEMCHABANG"]
ALL_LOCATIONS = PLANTS + WAREHOUSES + PORTS

# 仕入先
VENDORS = [
    ("V001", "JP", "パナソニックエナジー"),
    ("V002", "CN", "CATL"),
    ("V003", "KR", "Samsung SDI"),
    ("V004", "CN", "BYD Semiconductor"),
    ("V005", "JP", "日立金属"),
    ("V006", "TH", "Thai Summit Auto"),
    ("V007", "JP", "住友電工"),
    ("V008", "DE", "Bosch"),
    ("V009", "RU", "Norilsk Nickel"),   # 高リスク国
    ("V010", "MM", "Myanmar Metals"),    # 高リスク国
    ("V011", "JP", "JFEスチール"),
    ("V012", "CN", "Toray China"),
    ("V013", "TW", "TSMC"),
    ("V014", "US", "Texas Instruments"),
    ("V015", "IN", "Tata Steel"),
]


# ---------- 1. 在庫データ ----------

def gen_inventory():
    path = os.path.join(DATA_DIR, "sample_inventory.csv")
    rows = []
    for part in PARTS:
        # 各部品は5拠点のうちランダムに2〜5拠点に在庫
        locs = random.sample(ALL_LOCATIONS[:8], random.randint(2, 5))
        for loc in locs:
            stock = random.randint(0, 5000)
            # 一部を在庫薄にする（5日未満相当）
            if random.random() < 0.15:
                stock = random.randint(5, 50)
            ss_days = random.choice([3, 5, 7, 10, 14, None])
            rows.append({
                "品目番号": part,
                "プラント": loc,
                "在庫数量": stock,
                "安全在庫日数": ss_days if ss_days else "",
                "単位": random.choice(["PC", "KG", "M", "SET"]),
                "最終更新": (TODAY - datetime.timedelta(days=random.randint(0, 7))).isoformat(),
            })

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["品目番号", "プラント", "在庫数量", "安全在庫日数", "単位", "最終更新"])
        w.writeheader()
        w.writerows(rows)

    print(f"  inventory: {len(rows)} 行 → {path}")
    return path


# ---------- 2. 発注残 ----------

def gen_purchase_orders():
    path = os.path.join(DATA_DIR, "sample_purchase_orders.csv")
    rows = []
    for i in range(30):
        part = random.choice(PARTS[:20])
        vendor = random.choice(VENDORS)
        vid, country, _ = vendor
        delivery = TODAY + datetime.timedelta(days=random.randint(5, 90))
        lt = random.randint(7, 60)
        price = round(random.uniform(0.5, 500.0), 2)
        rows.append({
            "品目番号": part,
            "仕入先": vid,
            "仕入先国": country,
            "発注数量": random.randint(100, 10000),
            "納入日": delivery.isoformat(),
            "リードタイム": lt,
            "単価": price,
            "通貨": random.choice(["JPY", "USD", "CNY", "THB"]),
            "HSコード": f"{random.randint(7200, 8542)}.{random.randint(10, 99)}",
        })

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "品目番号", "仕入先", "仕入先国", "発注数量", "納入日",
            "リードタイム", "単価", "通貨", "HSコード"
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"  purchase_orders: {len(rows)} 行 → {path}")
    return path


# ---------- 3. 生産計画 ----------

def gen_production_plan():
    path = os.path.join(DATA_DIR, "sample_production_plan.csv")
    products = ["FG-EV100", "FG-HEV200", "FG-BEV300"]
    rows = []
    for prod in products:
        plant = random.choice(PLANTS)
        for day_offset in range(30):
            d = TODAY + datetime.timedelta(days=day_offset)
            # 週末は生産なし
            if d.weekday() >= 5:
                continue
            qty = random.randint(50, 300)
            rows.append({
                "製品番号": prod,
                "プラント": plant,
                "計画数量": qty,
                "計画日": d.isoformat(),
                "BOM番号": f"BOM-{prod[-5:]}",
                "作業区": random.choice(["WC-ASM01", "WC-ASM02", "WC-PAINT", "WC-TEST"]),
                "シフト": random.choice(["日勤", "夜勤", "2交代"]),
            })

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "製品番号", "プラント", "計画数量", "計画日", "BOM番号", "作業区", "シフト"
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"  production_plan: {len(rows)} 行 → {path}")
    return path


# ---------- 4. 拠点マスタ ----------

def gen_locations():
    path = os.path.join(DATA_DIR, "sample_locations.csv")
    rows = [
        # 工場
        {"拠点コード": "PLT-JP01", "拠点名": "愛知工場", "国": "JP",
         "緯度": 34.97, "経度": 137.17, "拠点種別": "factory", "面積(m2)": 45000, "機能": "組立,塗装"},
        {"拠点コード": "PLT-CN01", "拠点名": "蘇州工場", "国": "CN",
         "緯度": 31.30, "経度": 120.59, "拠点種別": "factory", "面積(m2)": 60000, "機能": "組立,加工"},
        {"拠点コード": "PLT-TH01", "拠点名": "ラヨーン工場", "国": "TH",
         "緯度": 12.68, "経度": 101.28, "拠点種別": "factory", "面積(m2)": 35000, "機能": "組立"},
        # 倉庫
        {"拠点コード": "WH-JP01", "拠点名": "名古屋DC", "国": "JP",
         "緯度": 35.18, "経度": 136.91, "拠点種別": "warehouse", "面積(m2)": 15000, "機能": "保管,仕分"},
        {"拠点コード": "WH-JP02", "拠点名": "横浜DC", "国": "JP",
         "緯度": 35.44, "経度": 139.64, "拠点種別": "warehouse", "面積(m2)": 12000, "機能": "保管,輸出"},
        {"拠点コード": "WH-CN01", "拠点名": "上海DC", "国": "CN",
         "緯度": 31.23, "経度": 121.47, "拠点種別": "warehouse", "面積(m2)": 20000, "機能": "保管,通関"},
        {"拠点コード": "WH-TH01", "拠点名": "バンコクDC", "国": "TH",
         "緯度": 13.76, "経度": 100.50, "拠点種別": "warehouse", "面積(m2)": 10000, "機能": "保管"},
        {"拠点コード": "WH-SG01", "拠点名": "シンガポールDC", "国": "SG",
         "緯度": 1.35, "経度": 103.82, "拠点種別": "warehouse", "面積(m2)": 8000, "機能": "ハブ,保管"},
        # 港湾
        {"拠点コード": "PORT-TOKYO", "拠点名": "東京港", "国": "JP",
         "緯度": 35.63, "経度": 139.77, "拠点種別": "port", "面積(m2)": "", "機能": "海上輸送"},
        {"拠点コード": "PORT-SHANGHAI", "拠点名": "上海港", "国": "CN",
         "緯度": 31.37, "経度": 121.61, "拠点種別": "port", "面積(m2)": "", "機能": "海上輸送"},
        {"拠点コード": "PORT-LAEMCHABANG", "拠点名": "レムチャバン港", "国": "TH",
         "緯度": 13.08, "経度": 100.88, "拠点種別": "port", "面積(m2)": "", "機能": "海上輸送"},
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "拠点コード", "拠点名", "国", "緯度", "経度", "拠点種別", "面積(m2)", "機能"
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"  locations: {len(rows)} 行 → {path}")
    return path


# ---------- 5. 輸送ルート ----------

def gen_transport_routes():
    path = os.path.join(DATA_DIR, "sample_transport_routes.csv")
    rows = [
        # 海上ルート
        {"出発地": "PORT-SHANGHAI", "目的地": "PORT-TOKYO", "輸送手段": "sea",
         "日数": 4, "単位コスト": 120, "通貨": "USD", "運送業者": "ONE", "週頻度": 5},
        {"出発地": "PORT-LAEMCHABANG", "目的地": "PORT-TOKYO", "輸送手段": "sea",
         "日数": 8, "単位コスト": 180, "通貨": "USD", "運送業者": "Evergreen", "週頻度": 3},
        {"出発地": "PORT-SHANGHAI", "目的地": "PORT-LAEMCHABANG", "輸送手段": "sea",
         "日数": 6, "単位コスト": 150, "通貨": "USD", "運送業者": "COSCO", "週頻度": 3},
        {"出発地": "PORT-LAEMCHABANG", "目的地": "PORT-SHANGHAI", "輸送手段": "sea",
         "日数": 6, "単位コスト": 150, "通貨": "USD", "運送業者": "COSCO", "週頻度": 3},
        {"出発地": "PORT-TOKYO", "目的地": "PORT-SHANGHAI", "輸送手段": "sea",
         "日数": 4, "単位コスト": 110, "通貨": "USD", "運送業者": "MOL", "週頻度": 5},
        # スエズ経由（チョークポイント）
        {"出発地": "PORT-SHANGHAI", "目的地": "PORT-HAMBURG", "輸送手段": "sea_suez",
         "日数": 30, "単位コスト": 450, "通貨": "USD", "運送業者": "Maersk", "週頻度": 2},
        {"出発地": "PORT-TOKYO", "目的地": "PORT-HAMBURG", "輸送手段": "sea_suez",
         "日数": 35, "単位コスト": 500, "通貨": "USD", "運送業者": "Hapag-Lloyd", "週頻度": 1},
        # 陸上ルート
        {"出発地": "PLT-JP01", "目的地": "WH-JP01", "輸送手段": "truck",
         "日数": 1, "単位コスト": 15, "通貨": "USD", "運送業者": "ヤマト運輸", "週頻度": 7},
        {"出発地": "WH-JP01", "目的地": "PORT-TOKYO", "輸送手段": "truck",
         "日数": 1, "単位コスト": 25, "通貨": "USD", "運送業者": "日本通運", "週頻度": 6},
        {"出発地": "PLT-CN01", "目的地": "WH-CN01", "輸送手段": "truck",
         "日数": 1, "単位コスト": 8, "通貨": "USD", "運送業者": "SF Express", "週頻度": 7},
        {"出発地": "WH-CN01", "目的地": "PORT-SHANGHAI", "輸送手段": "truck",
         "日数": 1, "単位コスト": 10, "通貨": "USD", "運送業者": "Sinotrans", "週頻度": 7},
        {"出発地": "PLT-TH01", "目的地": "WH-TH01", "輸送手段": "truck",
         "日数": 1, "単位コスト": 12, "通貨": "USD", "運送業者": "Kerry Logistics", "週頻度": 6},
        {"出発地": "WH-TH01", "目的地": "PORT-LAEMCHABANG", "輸送手段": "truck",
         "日数": 1, "単位コスト": 15, "通貨": "USD", "運送業者": "DHL Thailand", "週頻度": 6},
        # 航空
        {"出発地": "PLT-JP01", "目的地": "WH-SG01", "輸送手段": "air",
         "日数": 2, "単位コスト": 800, "通貨": "USD", "運送業者": "ANA Cargo", "週頻度": 5},
        {"出発地": "PLT-CN01", "目的地": "WH-SG01", "輸送手段": "air",
         "日数": 2, "単位コスト": 600, "通貨": "USD", "運送業者": "China Southern Cargo", "週頻度": 4},
        {"出発地": "PLT-JP01", "目的地": "PLT-TH01", "輸送手段": "air",
         "日数": 2, "単位コスト": 700, "通貨": "USD", "運送業者": "ANA Cargo", "週頻度": 3},
        # 鉄道（中国国内）
        {"出発地": "PLT-CN01", "目的地": "PORT-SHANGHAI", "輸送手段": "rail",
         "日数": 2, "単位コスト": 20, "通貨": "USD", "運送業者": "China Railway", "週頻度": 5},
        # ハブ経由
        {"出発地": "WH-SG01", "目的地": "WH-TH01", "輸送手段": "sea",
         "日数": 3, "単位コスト": 80, "通貨": "USD", "運送業者": "PIL", "週頻度": 4},
        {"出発地": "WH-SG01", "目的地": "WH-JP02", "輸送手段": "sea",
         "日数": 7, "単位コスト": 200, "通貨": "USD", "運送業者": "Yang Ming", "週頻度": 2},
        {"出発地": "WH-JP02", "目的地": "PLT-JP01", "輸送手段": "truck",
         "日数": 1, "単位コスト": 20, "通貨": "USD", "運送業者": "西濃運輸", "週頻度": 6},
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "出発地", "目的地", "輸送手段", "日数", "単位コスト", "通貨", "運送業者", "週頻度"
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"  transport_routes: {len(rows)} 行 → {path}")
    return path


# ---------- 6. 調達コスト ----------

def gen_procurement_costs():
    path = os.path.join(DATA_DIR, "sample_procurement_costs.csv")
    rows = []
    for part in PARTS:
        # 各部品に 1〜3 仕入先
        n_vendors = random.randint(1, 3)
        vendors = random.sample(VENDORS, n_vendors)
        for vid, country, name in vendors:
            price = round(random.uniform(1, 1000), 2)
            currency = {"JP": "JPY", "CN": "CNY", "TH": "THB", "KR": "KRW",
                         "DE": "EUR", "US": "USD", "RU": "USD", "MM": "USD",
                         "TW": "USD", "IN": "USD"}.get(country, "USD")
            # JPY は桁が大きいので調整
            if currency == "JPY":
                price = round(price * 100, 0)

            tariff = 0.0
            if country not in ("JP",):
                tariff = round(random.uniform(0, 15), 1)

            rows.append({
                "品目番号": part,
                "仕入先": vid,
                "単価": price,
                "通貨": currency,
                "最小発注数量": random.choice([1, 10, 50, 100, 500]),
                "有効開始": "2026-01-01",
                "有効終了": "2026-12-31",
                "関税率": tariff,
            })

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "品目番号", "仕入先", "単価", "通貨", "最小発注数量", "有効開始", "有効終了", "関税率"
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"  procurement_costs: {len(rows)} 行 → {path}")
    return path


# ---------- メイン ----------

def main():
    print("=" * 60)
    print("サンプル内部ロジスティクスデータ生成")
    print("=" * 60)

    # データ生成
    print("\n[1] CSVファイル生成...")
    paths = {
        "inventory": gen_inventory(),
        "purchase_orders": gen_purchase_orders(),
        "production_plan": gen_production_plan(),
        "locations": gen_locations(),
        "transport_routes": gen_transport_routes(),
        "procurement_costs": gen_procurement_costs(),
    }

    # 取込テスト
    print("\n[2] インポーター取込テスト...")
    from pipeline.internal.logistics_importer import LogisticsImporter
    importer = LogisticsImporter()

    all_ok = True
    imported = {}
    for dtype, fpath in paths.items():
        df = importer.auto_import(fpath, dtype)
        result = importer.validate(df, dtype)
        status = "OK" if result.ok else "NG"
        print(f"  {dtype:20s}: {status}  ({result.row_count} rows, {result.col_count} cols)")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
            all_ok = False
        imported[dtype] = df

    # DB格納テスト
    print("\n[3] データストア格納テスト...")
    from pipeline.internal.internal_data_store import InternalDataStore

    # テスト用に既存DBをクリア
    db_path = os.path.join(DATA_DIR, "internal_logistics.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    store = InternalDataStore(db_path)

    store.upsert_inventory(imported["inventory"].to_dict("records"))
    store.upsert_purchase_orders(imported["purchase_orders"].to_dict("records"))
    store.upsert_production_plan(imported["production_plan"].to_dict("records"))
    store.upsert_locations(imported["locations"].to_dict("records"))
    store.upsert_transport_routes(imported["transport_routes"].to_dict("records"))
    store.upsert_procurement_costs(imported["procurement_costs"].to_dict("records"))

    counts = store.get_table_counts()
    print("  テーブル別レコード数:")
    for table, cnt in counts.items():
        print(f"    {table:20s}: {cnt}")

    # 参照APIテスト
    print("\n[4] 参照APIテスト...")
    # 在庫日数
    sd = store.get_stock_days("P0001", "PLT-JP01")
    print(f"  get_stock_days('P0001', 'PLT-JP01'): {sd}")

    # 次回納入
    nd = store.get_next_delivery("P0001")
    if nd:
        print(f"  get_next_delivery('P0001'): vendor={nd['vendor_id']}, date={nd['delivery_date']}")
    else:
        print(f"  get_next_delivery('P0001'): (発注残なし)")

    # リードタイム
    lt = store.get_total_lead_time("PORT-SHANGHAI", "PORT-TOKYO", "sea")
    print(f"  get_total_lead_time('PORT-SHANGHAI', 'PORT-TOKYO', 'sea'): {lt} days")

    print("\n" + "=" * 60)
    if all_ok:
        print("全テスト完了: OK")
    else:
        print("一部エラーあり — 上記のログを確認してください")
    print("=" * 60)

    return all_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
