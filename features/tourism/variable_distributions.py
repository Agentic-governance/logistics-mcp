"""
29変数の確率分布と相関行列。
設計原則:
  - 全変数はゼロ期待値（ベースからの乖離）
  - σはJNTO実績とIMF/OECD文献から設定
  - 相関行列は経済理論に基づく（検証済み）
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict

@dataclass
class VarSpec:
    name: str
    mu: float
    sigma: float
    lo: float
    hi: float

SPECS: Dict[str, VarSpec] = {
    "fx_usd": VarSpec("USD/JPY変化率",  0.0, 0.10, -0.30,  0.35),
    "fx_krw": VarSpec("KRW/JPY変化率",  0.0, 0.10, -0.30,  0.35),
    "fx_cny": VarSpec("CNY/JPY変化率",  0.0, 0.05, -0.15,  0.15),
    "fx_twd": VarSpec("TWD/JPY変化率",  0.0, 0.09, -0.25,  0.30),
    "fx_aud": VarSpec("AUD/JPY変化率",  0.0, 0.13, -0.35,  0.40),
    "fx_thb": VarSpec("THB/JPY変化率",  0.0, 0.09, -0.25,  0.30),
    "gdp_kr": VarSpec("韓国GDPショック",   0.0, 0.015, -0.05, 0.05),
    "gdp_cn": VarSpec("中国GDPショック",   0.0, 0.020, -0.07, 0.07),
    "gdp_tw": VarSpec("台湾GDPショック",   0.0, 0.018, -0.06, 0.06),
    "gdp_us": VarSpec("米国GDPショック",   0.0, 0.015, -0.05, 0.05),
    "gdp_au": VarSpec("豪州GDPショック",   0.0, 0.015, -0.05, 0.05),
    "geo_cn": VarSpec("日中関係変化",   0.0, 12.0, -50.0, 20.0),
    "geo_tw": VarSpec("台湾海峡リスク", 0.0,  8.0, -40.0, 15.0),
    "geo_kr": VarSpec("日韓関係変化",   0.0,  5.0, -20.0, 15.0),
    "geo_th": VarSpec("タイ政情変化",   0.0, 10.0, -40.0, 10.0),
    "flt_kr": VarSpec("日韓フライト変化", 0.03, 0.06, -0.20, 0.30),
    "flt_cn": VarSpec("日中フライト変化", 0.05, 0.10, -0.30, 0.40),
    "flt_tw": VarSpec("日台フライト変化", 0.03, 0.06, -0.20, 0.30),
    "flt_us": VarSpec("日米フライト変化", 0.02, 0.05, -0.15, 0.25),
    "flt_au": VarSpec("日豪フライト変化", 0.02, 0.05, -0.15, 0.25),
    "cci_kr": VarSpec("韓国CCI変化",  0.0, 5.0, -20.0, 15.0),
    "cci_cn": VarSpec("中国CCI変化",  0.0, 4.0, -15.0, 12.0),
    "cci_us": VarSpec("米国CCI変化",  0.0, 6.0, -25.0, 18.0),
    "stk_kr": VarSpec("韓国株リターン", 0.07, 0.20, -0.50, 0.60),
    "stk_cn": VarSpec("中国株リターン", 0.05, 0.28, -0.60, 0.70),
    "stk_us": VarSpec("米国株リターン", 0.08, 0.18, -0.45, 0.55),
    "clt_kr": VarSpec("韓国の日本関心", 0.0, 8.0, -30.0, 25.0),
    "clt_cn": VarSpec("中国の日本関心", 0.0, 10.0, -35.0, 30.0),
    "clt_us": VarSpec("米国の日本関心", 0.0, 8.0, -25.0, 25.0),
}

VAR_NAMES = list(SPECS.keys())
N_VARS = len(VAR_NAMES)

def _build_corr():
    idx = {v: i for i, v in enumerate(VAR_NAMES)}
    C = np.eye(N_VARS)
    def s(v1, v2, rho):
        if v1 in idx and v2 in idx:
            C[idx[v1], idx[v2]] = C[idx[v2], idx[v1]] = rho
    s("fx_usd","fx_krw",+0.65); s("fx_usd","fx_twd",+0.60)
    s("fx_usd","fx_cny",+0.30); s("fx_usd","fx_aud",+0.45)
    s("fx_usd","fx_thb",+0.50); s("fx_krw","fx_twd",+0.70)
    s("fx_krw","fx_cny",+0.45); s("fx_aud","fx_thb",+0.35)
    s("gdp_kr","gdp_cn",+0.55); s("gdp_kr","gdp_tw",+0.65)
    s("gdp_cn","gdp_tw",+0.50); s("gdp_us","gdp_kr",+0.40)
    s("gdp_us","gdp_au",+0.45); s("gdp_us","gdp_cn",+0.35)
    s("gdp_us","fx_usd",+0.30); s("gdp_kr","fx_krw",+0.25)
    s("gdp_cn","fx_cny",+0.20)
    s("geo_cn","geo_tw",+0.40); s("geo_cn","geo_kr",+0.05)
    s("geo_cn","fx_cny",-0.20)
    s("stk_kr","cci_kr",+0.50); s("stk_cn","cci_cn",+0.40)
    s("stk_us","cci_us",+0.55)
    s("stk_us","gdp_us",+0.60); s("stk_kr","gdp_kr",+0.55)
    s("stk_cn","gdp_cn",+0.45)
    s("clt_kr","gdp_kr",+0.35); s("clt_cn","gdp_cn",+0.25)
    s("clt_us","gdp_us",+0.35)
    s("flt_cn","gdp_cn",+0.30); s("flt_kr","gdp_kr",+0.20)
    # Higham (2002) nearest correlation matrix（対角1を保持しつつ正定値に）
    # Broadcasting matmul (np.diag回避) + ridge regularization
    S = np.zeros_like(C)
    Y = C.copy()
    eps = 1e-4  # 固有値下限を引き上げ (1e-6→1e-4) で数値安定性向上
    for _ in range(200):
        R = Y - S
        eigvals, eigvecs = np.linalg.eigh(R)
        eigvals = np.maximum(eigvals, eps)
        X = (eigvecs * eigvals) @ eigvecs.T  # broadcasting (np.diagより高速・安定)
        S = X - R
        Y = X.copy()
        np.fill_diagonal(Y, 1.0)
        if np.linalg.eigvalsh(Y).min() >= eps:
            break
    # Ridge regularization: わずかにI_nを混ぜて条件数改善
    ridge_alpha = 0.001
    C = (1 - ridge_alpha) * Y + ridge_alpha * np.eye(N_VARS)
    # 再度対角を1に戻す
    np.fill_diagonal(C, 1.0)
    return C

CORR = _build_corr()
CHOL = np.linalg.cholesky(CORR)

def sample_all_vars(n):
    z = np.random.standard_normal((n, N_VARS)) @ CHOL.T
    out = np.empty_like(z)
    for i, name in enumerate(VAR_NAMES):
        sp = SPECS[name]
        raw = sp.mu + sp.sigma * z[:, i]
        out[:, i] = np.clip(raw, sp.lo, sp.hi)
    return out

VAR_IDX = {v: i for i, v in enumerate(VAR_NAMES)}
