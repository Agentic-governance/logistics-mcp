#!/usr/bin/env python3
"""Generate docs/MCP_TOOLS_CATALOG.md by parsing mcp_server/server.py.

Reads all @mcp.tool() decorated functions, extracts name, docstring,
parameters, return type, and generates a comprehensive catalog with
3 example prompts per tool.
"""

import ast
import os
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Example prompts for each tool (3 per tool)
TOOL_EXAMPLES = {
    "screen_sanctions": [
        'Screen "Huawei Technologies" against all sanctions lists',
        "Is Rusal on any sanctions list? Check with country Russia",
        "この企業は制裁リストに載っていますか？ 企業名: 三菱商事",
    ],
    "monitor_supplier": [
        "Register supplier SUP-001 (Foxconn, Taiwan) for real-time monitoring",
        "Start monitoring Samsung Electronics in South Korea with ID KR-SAM-01",
        "このサプライヤーをリアルタイム監視に登録してください: ID=JP-101, 名前=村田製作所, 所在地=日本",
    ],
    "get_risk_score": [
        "Get the full 24-dimension risk score for TSMC in Taiwan",
        "What is the risk profile of Bosch in Germany?",
        "サプライヤーID: VN-01, ベトナムのVingroup社のリスクスコアを教えてください",
    ],
    "get_location_risk": [
        "Evaluate all risks for Vietnam",
        "What is the overall risk level of Myanmar?",
        "インドネシアのリスクを一括評価してください",
    ],
    "get_global_risk_dashboard": [
        "Show me the global risk dashboard",
        "What disasters and disruptions are happening right now worldwide?",
        "グローバルリスクダッシュボードを見せてください",
    ],
    "get_supply_chain_graph": [
        "Show Toyota's Tier-2 supply chain graph in Japan",
        "Build a supply network graph for Apple with depth 2",
        "トヨタ自動車のTier-2までのサプライチェーングラフを表示してください",
    ],
    "get_risk_alerts": [
        "Show me risk alerts from the last 24 hours with score above 60",
        "Any critical alerts in the past 12 hours?",
        "直近24時間のリスクアラートを見せてください",
    ],
    "bulk_screen": [
        "Screen this CSV of suppliers against sanctions: company_name,country\\nAcme,Iran\\nGlobal Corp,Russia",
        "Bulk screen my supplier list for sanctions matches",
        "CSVファイルのサプライヤーを一括スクリーニングしてください",
    ],
    "compare_locations": [
        "Compare risk between China, Vietnam, and Thailand",
        "Which is safer for sourcing: Indonesia, Philippines, or Malaysia?",
        "中国、ベトナム、タイのリスクを比較してください",
    ],
    "analyze_route_risk": [
        "Analyze the shipping route risk from Shanghai to Rotterdam",
        "What chokepoints does the route from Yokohama to Hamburg pass through?",
        "上海から横浜までの輸送ルートリスクを分析してください",
    ],
    "get_concentration_risk": [
        "Analyze concentration risk for my semiconductor suppliers (CSV with name, country, share)",
        "Is my supplier base too concentrated in one region?",
        "サプライヤー集中リスクを分析してください",
    ],
    "simulate_disruption": [
        "Simulate a Taiwan Strait blockade scenario",
        "What happens if the Suez Canal closes? Run the suez_closure scenario",
        "台湾海峡封鎖シナリオをシミュレーションしてください",
    ],
    "generate_dd_report": [
        "Generate a due diligence report for Alibaba Group in China",
        "Create a KYS DD report for a new supplier in Myanmar",
        "この企業のデューデリジェンスレポートを作成してください: 企業名=ZTE, 国=China",
    ],
    "get_commodity_exposure": [
        "What is the commodity exposure for the semiconductor sector?",
        "Analyze raw material risks for battery materials",
        "半導体セクターのコモディティ・エクスポージャーを分析してください",
    ],
    "bulk_assess_suppliers": [
        "Bulk assess this supplier CSV with full 24-dimension depth",
        "Quick-assess my supplier list: name,country\\nFoxconn,Taiwan\\nSamsung,South Korea",
        "サプライヤーリストを一括アセスメントしてください（フルモード）",
    ],
    "get_data_quality_report": [
        "Show me the data quality report",
        "Which data sources are currently unavailable?",
        "データ品質レポートを表示してください",
    ],
    "analyze_portfolio": [
        'Analyze my supplier portfolio: [{"name":"TSMC","country":"Taiwan","share":0.4},{"name":"Samsung","country":"South Korea","share":0.3},{"name":"Intel","country":"US","share":0.3}]',
        "Cluster my suppliers by risk profile (include clustering)",
        "サプライヤーポートフォリオを分析してクラスタリングしてください",
    ],
    "analyze_risk_correlations": [
        "Show the correlation matrix for Japan, China, Vietnam, and Thailand",
        "Which risk dimensions are highly correlated across ASEAN countries?",
        "リスク次元間の相関を分析してください（日本、中国、ベトナム）",
    ],
    "find_leading_risk_indicators": [
        "What dimensions are leading indicators for conflict risk?",
        "Find predictors of economic risk across Southeast Asian countries",
        "紛争リスクの先行指標を特定してください",
    ],
    "benchmark_risk_profile": [
        "Benchmark Vietnam against the automotive industry average",
        "Compare Taiwan's risk to semiconductor industry peers (South Korea, Japan, US)",
        "自動車業界のベンチマークと比較してください（ベトナム）",
    ],
    "analyze_score_sensitivity": [
        "Which dimensions most influence Vietnam's overall risk score?",
        "Run a weight sensitivity analysis for China with +/- 5% perturbation",
        "どの次元が最もスコアに影響するか分析してください（タイ）",
    ],
    "simulate_what_if": [
        'What if conflict in Taiwan rises to 90? Simulate with {"conflict": 90}',
        'How would Vietnam\'s score change if disaster goes to 70 and cyber to 60?',
        "紛争スコアが90になったら全体スコアはどう変わるか？（台湾）",
    ],
}


@dataclass
class ToolParam:
    name: str
    annotation: str
    default: Optional[str]
    required: bool


@dataclass
class ToolInfo:
    name: str
    docstring: str
    params: list[ToolParam] = field(default_factory=list)
    return_type: str = "dict"


def parse_mcp_tools(filepath: str) -> list[ToolInfo]:
    """Parse mcp_server/server.py and extract all @mcp.tool() decorated functions."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    tools: list[ToolInfo] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        # Check for @mcp.tool() decorator
        is_mcp_tool = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute):
                    if (
                        decorator.func.attr == "tool"
                        and isinstance(decorator.func.value, ast.Name)
                        and decorator.func.value.id == "mcp"
                    ):
                        is_mcp_tool = True
            elif isinstance(decorator, ast.Attribute):
                if (
                    decorator.attr == "tool"
                    and isinstance(decorator.value, ast.Name)
                    and decorator.value.id == "mcp"
                ):
                    is_mcp_tool = True

        if not is_mcp_tool:
            continue

        # Extract function info
        func_name = node.name
        docstring = ast.get_docstring(node) or ""

        # Extract return type
        return_type = "dict"
        if node.returns:
            return_type = ast.unparse(node.returns) if hasattr(ast, "unparse") else "dict"

        # Extract parameters
        params: list[ToolParam] = []
        args = node.args

        # Calculate defaults offset
        num_args = len(args.args)
        num_defaults = len(args.defaults)
        first_default_idx = num_args - num_defaults

        for i, arg in enumerate(args.args):
            if arg.arg == "self":
                continue

            # Type annotation
            annotation = "Any"
            if arg.annotation:
                annotation = ast.unparse(arg.annotation) if hasattr(ast, "unparse") else str(arg.annotation)

            # Default value
            default = None
            required = True
            default_idx = i - first_default_idx
            if default_idx >= 0 and default_idx < len(args.defaults):
                default_node = args.defaults[default_idx]
                default = ast.unparse(default_node) if hasattr(ast, "unparse") else str(default_node)
                required = False

            params.append(ToolParam(
                name=arg.arg,
                annotation=annotation,
                default=default,
                required=required,
            ))

        tools.append(ToolInfo(
            name=func_name,
            docstring=docstring,
            params=params,
            return_type=return_type,
        ))

    return tools


def generate_catalog(tools: list[ToolInfo]) -> str:
    """Generate the MCP_TOOLS_CATALOG.md content."""
    lines: list[str] = []

    lines.append("# SCRI Platform -- MCP Tools Catalog")
    lines.append("")
    lines.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Tools**: {len(tools)}")
    lines.append(f"**Server**: `FastMCP(\"Supply Chain Risk Intelligence\")` on SSE transport (port 8001)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")
    for i, tool in enumerate(tools, 1):
        lines.append(f"{i}. [{tool.name}](#{tool.name})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Category mapping
    categories = {
        "Sanctions & Screening": ["screen_sanctions", "bulk_screen"],
        "Risk Scoring": ["get_risk_score", "get_location_risk", "compare_locations"],
        "Monitoring & Alerts": ["monitor_supplier", "get_risk_alerts", "get_data_quality_report"],
        "Dashboard": ["get_global_risk_dashboard"],
        "Supply Chain Mapping": ["get_supply_chain_graph"],
        "Route & Transport": ["analyze_route_risk", "get_concentration_risk"],
        "Simulation": ["simulate_disruption"],
        "Reports": ["generate_dd_report"],
        "Commodity": ["get_commodity_exposure"],
        "Bulk Operations": ["bulk_assess_suppliers"],
        "Analytics -- Portfolio": ["analyze_portfolio"],
        "Analytics -- Correlation": ["analyze_risk_correlations", "find_leading_risk_indicators"],
        "Analytics -- Benchmark": ["benchmark_risk_profile"],
        "Analytics -- Sensitivity": ["analyze_score_sensitivity", "simulate_what_if"],
    }

    # Summary table
    lines.append("## Summary by Category")
    lines.append("")
    lines.append("| Category | Tools | Count |")
    lines.append("|---|---|---|")
    total = 0
    for cat, tool_names in categories.items():
        tool_list = ", ".join(f"`{t}`" for t in tool_names)
        lines.append(f"| {cat} | {tool_list} | {len(tool_names)} |")
        total += len(tool_names)
    lines.append(f"| **Total** | | **{total}** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed tool documentation
    for i, tool in enumerate(tools, 1):
        lines.append(f"## {i}. {tool.name}")
        lines.append("")

        # Extract purpose from docstring (first line or paragraph)
        doc_lines = tool.docstring.strip().split("\n")
        purpose_lines = []
        for dl in doc_lines:
            stripped = dl.strip()
            if stripped.startswith("Args:") or stripped.startswith("Returns:"):
                break
            if stripped:
                purpose_lines.append(stripped)
        purpose = " ".join(purpose_lines) if purpose_lines else "No description available."
        lines.append(f"**Purpose**: {purpose}")
        lines.append("")

        # Parameters table
        if tool.params:
            lines.append("### Parameters")
            lines.append("")
            lines.append("| Parameter | Type | Required | Default | Description |")
            lines.append("|---|---|---|---|---|")
            for p in tool.params:
                req = "Yes" if p.required else "No"
                default = p.default if p.default is not None else "--"
                # Try to extract parameter description from docstring Args section
                desc = _extract_param_desc(tool.docstring, p.name)
                lines.append(f"| `{p.name}` | `{p.annotation}` | {req} | {default} | {desc} |")
            lines.append("")
        else:
            lines.append("_No parameters required._")
            lines.append("")

        # Return type
        lines.append(f"**Returns**: `{tool.return_type}`")
        lines.append("")

        # Example prompts
        examples = TOOL_EXAMPLES.get(tool.name, [])
        if examples:
            lines.append("### Example Prompts")
            lines.append("")
            for j, ex in enumerate(examples, 1):
                lines.append(f"{j}. \"{ex}\"")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _extract_param_desc(docstring: str, param_name: str) -> str:
    """Extract parameter description from docstring Args section."""
    in_args = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Args:"):
            in_args = True
            continue
        if in_args:
            if stripped.startswith("Returns:") or (stripped and not stripped[0].isspace() and ":" not in stripped):
                break
            if stripped.startswith(f"{param_name}:"):
                return stripped.split(":", 1)[1].strip()
            if stripped.startswith(f"{param_name} :"):
                return stripped.split(":", 1)[1].strip()
    return "--"


def main():
    # Determine paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    server_path = os.path.join(project_root, "mcp_server", "server.py")
    output_path = os.path.join(project_root, "docs", "MCP_TOOLS_CATALOG.md")

    if not os.path.exists(server_path):
        print(f"ERROR: {server_path} not found")
        sys.exit(1)

    # Parse tools
    tools = parse_mcp_tools(server_path)
    print(f"Parsed {len(tools)} MCP tools from {server_path}")

    for tool in tools:
        print(f"  - {tool.name}({', '.join(p.name for p in tool.params)}) -> {tool.return_type}")

    # Generate catalog
    catalog = generate_catalog(tools)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Write catalog
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(catalog)

    print(f"\nCatalog written to {output_path}")
    print(f"Total tools documented: {len(tools)}")


if __name__ == "__main__":
    main()
