#!/usr/bin/env python3
"""データソースリファレンス自動生成スクリプト

pipeline/ 配下の全クライアントモジュールをスキャンし、
docs/DATA_SOURCES.md を自動生成する。

Usage:
    python scripts/generate_data_source_reference.py
"""
import os
import sys
import re
import ast
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "docs", "DATA_SOURCES.md")

# カテゴリマッピング
CATEGORY_MAP = {
    "sanctions": "Sanctions & Compliance",
    "compliance": "Sanctions & Compliance",
    "gdelt": "Geopolitical & Conflict",
    "conflict": "Geopolitical & Conflict",
    "disaster": "Disaster & Weather",
    "weather": "Disaster & Weather",
    "economic": "Economic & Trade",
    "trade": "Economic & Trade",
    "energy": "Economic & Trade",
    "maritime": "Maritime & Transport",
    "aviation": "Maritime & Transport",
    "transport": "Maritime & Transport",
    "health": "Health & Humanitarian",
    "food": "Health & Humanitarian",
    "infrastructure": "Infrastructure & Cyber",
    "cyber": "Infrastructure & Cyber",
    "climate": "Climate & Environment",
    "japan": "Japan-Specific",
    "regional": "Regional Statistics",
    "corporate": "Corporate & ERP",
    "erp": "Corporate & ERP",
    "opensanctions": "Sanctions & Compliance",
}


def scan_pipeline_modules():
    """pipeline/ 配下の全 .py ファイルをスキャンし、モジュール情報を収集"""
    modules = []

    for root, dirs, files in os.walk(PIPELINE_DIR):
        # __pycache__ をスキップ
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        for fname in sorted(files):
            if not fname.endswith(".py") or fname == "__init__.py":
                continue

            filepath = os.path.join(root, fname)
            relpath = os.path.relpath(filepath, PROJECT_ROOT)

            # カテゴリを決定
            subdir = os.path.relpath(root, PIPELINE_DIR).split(os.sep)[0]
            category = CATEGORY_MAP.get(subdir, "Other")

            # ファイル内容を読んでdocstringとクラス名を抽出
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                # モジュールdocstring
                tree = ast.parse(content)
                docstring = ast.get_docstring(tree) or ""

                # クラス名
                classes = [
                    node.name for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef)
                ]

                # 関数名（外部API呼び出しの手がかり）
                functions = [
                    node.name for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef)
                    and not node.name.startswith("_")
                ]

                # URL検出（データソースの手がかり）
                urls = re.findall(r'https?://[^\s\'"]+', content)

                # API キー検出
                has_api_key = bool(re.search(r'API_KEY|api_key|apikey', content))

                modules.append({
                    "path": relpath,
                    "category": category,
                    "subdir": subdir,
                    "filename": fname,
                    "docstring": docstring.split("\n")[0] if docstring else "",
                    "classes": classes,
                    "functions": functions[:10],  # 上位10個
                    "urls": urls[:5],  # 上位5個
                    "has_api_key": has_api_key,
                    "line_count": content.count("\n") + 1,
                })

            except Exception as e:
                print(f"Warning: could not parse {relpath}: {e}")

    return modules


def generate_markdown(modules):
    """スキャン結果からMarkdownを生成"""
    lines = [
        "# Data Sources Reference -- SCRI Platform (Auto-Generated)",
        "",
        f"> Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"> Scanned {len(modules)} pipeline modules from `pipeline/`",
        "",
        "---",
        "",
        "## Pipeline Module Inventory",
        "",
    ]

    # カテゴリ別にグループ化
    by_category = {}
    for m in modules:
        cat = m["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(m)

    for cat in sorted(by_category.keys()):
        cat_modules = by_category[cat]
        lines.append(f"### {cat} ({len(cat_modules)} modules)")
        lines.append("")
        lines.append("| Module | Classes | Public Functions | LOC | API Key |")
        lines.append("|---|---|---|---|---|")
        for m in cat_modules:
            classes_str = ", ".join(m["classes"][:3]) or "-"
            funcs_str = ", ".join(m["functions"][:3]) or "-"
            api_key = "Yes" if m["has_api_key"] else "No"
            lines.append(
                f"| `{m['path']}` | {classes_str} | {funcs_str} | {m['line_count']} | {api_key} |"
            )
        lines.append("")

    # サマリー
    total_loc = sum(m["line_count"] for m in modules)
    total_classes = sum(len(m["classes"]) for m in modules)
    total_functions = sum(len(m["functions"]) for m in modules)
    api_key_modules = sum(1 for m in modules if m["has_api_key"])

    lines.extend([
        "---",
        "",
        "## Summary Statistics",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total pipeline modules | {len(modules)} |",
        f"| Total lines of code | {total_loc:,} |",
        f"| Total classes | {total_classes} |",
        f"| Total public functions | {total_functions} |",
        f"| Modules requiring API key | {api_key_modules} |",
        f"| Categories | {len(by_category)} |",
        "",
    ])

    return "\n".join(lines)


def main():
    print(f"Scanning pipeline directory: {PIPELINE_DIR}")
    modules = scan_pipeline_modules()
    print(f"Found {len(modules)} pipeline modules")

    markdown = generate_markdown(modules)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"Written to {OUTPUT_PATH}")
    print(f"  Modules: {len(modules)}")
    print(f"  Categories: {len(set(m['category'] for m in modules))}")


if __name__ == "__main__":
    main()
