"""
全予測変数の確率分布と相関行列。
変数間の相関がコレスキー分解で注入される。
"""
import numpy as np
from dataclasses import dataclass

@dataclass
class VariableSpec:
    name: str
    unit: str
    mu: float
    sigma: float
    distribution: str = "normal"
    min_val: float = -np.inf
    max_val: float = np.inf

VARIABLE_SPECS = {
    # 為替 (年率変化率)
    "fx_usd_jpy": VariableSpec("USD/JPY変化率", "%", 0.0, 0.10, min_val=-0.30, max_val=0.30),
    "fx_krw_jpy": VariableSpec("KRW/JPY変化率", "%", 0.0, 0.10, min_val=-0.30, max_val=0.30),
    "fx_cny_jpy": VariableSpec("CNY/JPY変化率", "%", 0.0, 0.05, min_val=-0.15, max_val=0.15),
    "fx_twd_jpy": VariableSpec("TWD/JPY変化率", "%", 0.0, 0.09, min_val=-0.25, max_val=0.25),
    "fx_aud_jpy": VariableSpec("AUD/JPY変化率", "%", 0.0, 0.13, min_val=-0.35, max_val=0.35),
    "fx_thb_jpy": VariableSpec("THB/JPY変化率", "%", 0.0, 0.09, min_val=-0.25, max_val=0.25),
    # GDP成長率ショック
    "gdp_shock_kr": VariableSpec("韓国GDPショック", "%pt", 0.0, 0.015, min_val=-0.05, max_val=0.05),
    "gdp_shock_cn": VariableSpec("中国GDPショック", "%pt", 0.0, 0.020, min_val=-0.07, max_val=0.07),
    "gdp_shock_tw": VariableSpec("台湾GDPショック", "%pt", 0.0, 0.018),
    "gdp_shock_us": VariableSpec("米国GDPショック", "%pt", 0.0, 0.015),
    "gdp_shock_au": VariableSpec("豪州GDPショック", "%pt", 0.0, 0.015),
    # 地政学リスク
    "geo_cn": VariableSpec("日中関係変化", "点", 0.0, 12.0, min_val=-50, max_val=20),
    "geo_tw": VariableSpec("台湾海峡リスク", "点", 0.0, 8.0, min_val=-40, max_val=15),
    "geo_kr": VariableSpec("日韓関係変化", "点", 0.0, 5.0, min_val=-20, max_val=15),
    "geo_th": VariableSpec("タイ政情変化", "点", 0.0, 10.0, min_val=-40, max_val=10),
    # フライト供給
    "flight_kr": VariableSpec("日韓フライト変化", "%", 0.03, 0.06, min_val=-0.20, max_val=0.30),
    "flight_cn": VariableSpec("日中フライト変化", "%", 0.05, 0.10, min_val=-0.30, max_val=0.40),
    "flight_tw": VariableSpec("日台フライト変化", "%", 0.03, 0.06, min_val=-0.20, max_val=0.30),
    "flight_us": VariableSpec("日米フライト変化", "%", 0.02, 0.05),
    "flight_au": VariableSpec("日豪フライト変化", "%", 0.02, 0.05),
    # 消費者信頼感
    "consumer_confidence_kr": VariableSpec("韓国消費者信頼感", "pt", 0.0, 5.0),
    "consumer_confidence_cn": VariableSpec("中国消費者信頼感", "pt", 0.0, 4.0),
    "consumer_confidence_us": VariableSpec("米国消費者信頼感", "pt", 0.0, 6.0),
    # 株価
    "stock_return_kr": VariableSpec("韓国株式リターン", "%", 0.07, 0.20),
    "stock_return_cn": VariableSpec("中国株式リターン", "%", 0.05, 0.28),
    "stock_return_us": VariableSpec("米国株式リターン", "%", 0.08, 0.18),
    # 文化的関心
    "japan_interest_kr": VariableSpec("韓国の日本関心", "pt", 0.0, 8.0),
    "japan_interest_cn": VariableSpec("中国の日本関心", "pt", 0.0, 10.0),
    "japan_interest_us": VariableSpec("米国の日本関心", "pt", 0.0, 8.0),
}

VAR_NAMES = list(VARIABLE_SPECS.keys())
N_VARS = len(VAR_NAMES)

def build_correlation_matrix():
    corr = np.eye(N_VARS)
    idx = {v: i for i, v in enumerate(VAR_NAMES)}

    def s(v1, v2, rho):
        if v1 in idx and v2 in idx:
            corr[idx[v1], idx[v2]] = corr[idx[v2], idx[v1]] = rho

    # 為替間
    s("fx_usd_jpy","fx_krw_jpy",0.65); s("fx_usd_jpy","fx_cny_jpy",0.30)
    s("fx_usd_jpy","fx_twd_jpy",0.60); s("fx_usd_jpy","fx_aud_jpy",0.45)
    s("fx_usd_jpy","fx_thb_jpy",0.50); s("fx_krw_jpy","fx_twd_jpy",0.70)
    s("fx_krw_jpy","fx_cny_jpy",0.45); s("fx_aud_jpy","fx_thb_jpy",0.35)
    # GDP間
    s("gdp_shock_kr","gdp_shock_cn",0.55); s("gdp_shock_kr","gdp_shock_tw",0.65)
    s("gdp_shock_cn","gdp_shock_tw",0.50); s("gdp_shock_us","gdp_shock_kr",0.40)
    s("gdp_shock_us","gdp_shock_cn",0.35); s("gdp_shock_us","gdp_shock_au",0.45)
    # GDP-為替
    s("gdp_shock_us","fx_usd_jpy",0.30); s("gdp_shock_kr","fx_krw_jpy",0.25)
    s("gdp_shock_cn","fx_cny_jpy",0.20)
    # 地政学
    s("geo_cn","geo_kr",0.05); s("geo_cn","geo_tw",0.40)
    s("geo_cn","fx_cny_jpy",-0.20)
    # 株-信頼感
    s("stock_return_kr","consumer_confidence_kr",0.50)
    s("stock_return_cn","consumer_confidence_cn",0.40)
    s("stock_return_us","consumer_confidence_us",0.55)
    # 株-GDP
    s("stock_return_us","gdp_shock_us",0.60)
    s("stock_return_kr","gdp_shock_kr",0.55)
    s("stock_return_cn","gdp_shock_cn",0.45)
    # 文化-GDP
    s("japan_interest_kr","gdp_shock_kr",0.35)
    s("japan_interest_cn","gdp_shock_cn",0.25)
    s("japan_interest_us","gdp_shock_us",0.35)

    # 正定値補正
    eigvals = np.linalg.eigvalsh(corr)
    if np.any(eigvals < 0):
        corr += (-eigvals.min() + 1e-6) * np.eye(N_VARS)
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)
    return corr

CORRELATION_MATRIX = build_correlation_matrix()
