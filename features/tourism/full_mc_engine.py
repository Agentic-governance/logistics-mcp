"""
Full Monte Carlo Engine — 29変数相関サンプリングで来訪者数を生成。
p10=悲観, p50=ベース, p90=楽観（分布から自然生成、人間が設定しない）
"""
import numpy as np
import sqlite3
from .variable_distributions import sample_all_vars, VAR_IDX, SPECS

FX_ELA = {"KR":-1.05,"CN":-0.95,"TW":-1.08,"US":-1.18,"AU":-1.22,"TH":-1.10,"HK":-1.00,"SG":-1.08}
GDP_ELA  = 1.24
FLT_ELA  = 0.60
GEO_COEF = -0.038  # 地政学1pt悪化→需要3.8%減（日中関係12ptσで46%の変動幅）
CCI_COEF = 0.012
STK_COEF = 0.08
CLT_COEF = 0.010

PARAMS = {
    "KR": dict(base=716000,fx="fx_krw",gdp="gdp_kr",geo="geo_kr",flt="flt_kr",cci="cci_kr",stk="stk_kr",clt="clt_kr",
               idio=0.08,peaks={7:1.35,8:1.40,4:1.15,3:1.10,10:1.10},troughs={2:0.75,9:0.80}),
    "CN": dict(base=580000,fx="fx_cny",gdp="gdp_cn",geo="geo_cn",flt="flt_cn",cci="cci_cn",stk="stk_cn",clt="clt_cn",
               idio=0.22,peaks={10:1.55,5:1.45,9:1.15},troughs={2:0.45,1:0.55}),  # base 433K→580K: 2024実績に合わせ
    "TW": dict(base=400000,fx="fx_twd",gdp="gdp_tw",geo="geo_tw",flt="flt_tw",cci=None,stk=None,clt=None,
               idio=0.12,peaks={4:1.20,7:1.15,8:1.10},troughs={2:0.55}),
    "US": dict(base=272000,fx="fx_usd",gdp="gdp_us",geo=None,flt="flt_us",cci="cci_us",stk="stk_us",clt="clt_us",
               idio=0.20,peaks={7:1.45,8:1.50,4:1.15},troughs={11:0.75,12:0.80}),  # base 300K→272K: 2024実績反映
    "AU": dict(base=53000,fx="fx_aud",gdp="gdp_au",geo=None,flt="flt_au",cci=None,stk=None,clt=None,
               idio=0.18,peaks={7:1.60,8:1.70,1:1.30,2:1.25},troughs={5:0.85,6:0.90}),  # 8月2.80→1.70: 月単位で過大だった
    "TH": dict(base=98000,fx="fx_thb",gdp=None,geo="geo_th",flt=None,cci=None,stk=None,clt=None,
               idio=0.20,peaks={4:1.20,10:1.15},troughs={}),  # base 35K→98K: 2024実績に合わせ
    "HK": dict(base=109000,fx="fx_usd",gdp=None,geo="geo_cn",flt=None,cci=None,stk=None,clt=None,
               idio=0.18,peaks={4:1.15,10:1.20},troughs={2:0.50}),
    "SG": dict(base=45000,fx="fx_usd",gdp=None,geo=None,flt=None,cci=None,stk=None,clt=None,
               idio=0.12,peaks={4:1.15,12:1.20},troughs={}),
}
ALL_COUNTRIES = list(PARAMS.keys())

# ISO2→ISO3マッピング (japan_inboundテーブルはISO3)
ISO2_TO_ISO3 = {"KR":"KOR","CN":"CHN","TW":"TWN","US":"USA","AU":"AUS","TH":"THA","HK":"HKG","SG":"SGP"}
ISO3_TO_ISO2 = {v:k for k,v in ISO2_TO_ISO3.items()}

def _load_db_actuals():
    cache = {}
    try:
        conn = sqlite3.connect('data/tourism_stats.db')
        for r in conn.execute("SELECT source_country,year,month,fx_rate_jpy,stock_return,consumer_confidence,japan_travel_trend FROM monthly_indicators").fetchall():
            cache[(r[0],r[1],r[2])] = {'fx':r[3],'stock':r[4],'cci':r[5],'trend':r[6]}
        for r in conn.execute("SELECT source_country,year,gdp_growth_rate,leave_utilization_rate,remote_work_rate,unemployment_rate,travel_momentum_index,exchange_rate FROM gravity_variables_v2 WHERE month=0").fetchall():
            cache[(r[0],r[1],'a')] = {'gdp_growth':r[2],'leave_util':r[3],'remote_work':r[4],'unemployment':r[5],'tmi':r[6],'fx_annual':r[7]}
        conn.close()
    except:
        pass
    return cache


class FullMCEngine:
    def __init__(self, n_samples=3000):
        self.n_samples = n_samples
        self._db = _load_db_actuals()

    def _get_db_fx_shock(self, iso2, year, month):
        current = self._db.get((iso2,year,month),{}).get('fx')
        if current is None: return 0.0
        prev = [self._db.get((iso2,year if month-dy>0 else year-1,(month-dy-1)%12+1),{}).get('fx') for dy in range(1,13)]
        prev = [p for p in prev if p]
        if not prev: return 0.0
        base = np.mean(prev)
        return (current - base) / base if base > 0 else 0.0

    def _compute_country(self, iso2, month, year, all_vars):
        p = PARAMS[iso2]
        base = p['base']
        cal = p['peaks'].get(month, p['troughs'].get(month, 1.0))

        def get(var_name):
            if var_name is None or var_name not in VAR_IDX:
                return np.zeros(self.n_samples)
            return all_vars[:, VAR_IDX[var_name]]

        fx  = get(p['fx']) + self._get_db_fx_shock(iso2, year, month)
        gdp = get(p['gdp'])
        geo = get(p['geo'])
        flt = get(p['flt'])
        cci = get(p['cci'])
        stk = get(p['stk'])
        clt = get(p['clt'])

        fx_ela = FX_ELA.get(iso2, -1.12)
        log_impact = (
            -fx_ela * np.log1p(np.clip(fx, -0.5, 1.0))
            + GDP_ELA * np.log1p(np.clip(gdp, -0.1, 0.1))
            + FLT_ELA * np.log1p(np.clip(flt, -0.5, 1.0))
            + GEO_COEF * geo
            + CCI_COEF * cci
            + STK_COEF * stk
            + CLT_COEF * clt
        )
        log_impact += np.random.normal(0, p['idio']/np.sqrt(12), self.n_samples)
        return np.maximum(base * cal * np.exp(log_impact), 0)

    def driver_sensitivity(self, iso2, month=4, year=2026):
        """変数別の感度分析: 各変数を±1σ動かした時の来訪者変化率"""
        from .variable_distributions import VAR_NAMES, SPECS
        p = PARAMS[iso2]
        sens_n = min(self.n_samples, 500)
        orig_n = self.n_samples
        self.n_samples = sens_n
        base_vars = sample_all_vars(sens_n)
        base_visitors = np.median(self._compute_country(iso2, month, year, base_vars))
        results = {}
        for vi, vname in enumerate(VAR_NAMES):
            # 関連する変数のみ計算
            relevant = [p['fx'], p['gdp'], p['geo'], p['flt'], p['cci'], p['stk'], p['clt']]
            if vname not in relevant:
                continue
            sp = SPECS[vname]
            shocked = base_vars.copy()
            shocked[:, vi] = sp.mu + sp.sigma  # +1σ
            up = np.median(self._compute_country(iso2, month, year, shocked))
            shocked[:, vi] = sp.mu - sp.sigma  # -1σ
            down = np.median(self._compute_country(iso2, month, year, shocked))
            results[vname] = {
                "label": sp.name,
                "up_pct": round(float((up - base_visitors) / max(base_visitors, 1) * 100), 2),
                "down_pct": round(float((down - base_visitors) / max(base_visitors, 1) * 100), 2),
                "total_range_pct": round(float(abs(up - down) / max(base_visitors, 1) * 100), 2),
            }
        self.n_samples = orig_n
        return {"iso2": iso2, "base_visitors": int(base_visitors), "sensitivities": results}

    def market_opportunity_score(self, month=4, year=2026):
        """各市場の投資機会スコア (0-100)"""
        months = [f"{year}/{month:02d}"]
        result = self.run(months, "ALL")
        scores = {}
        for iso2 in ALL_COUNTRIES:
            bc = result["by_country"][iso2]
            median = bc["median"][0]
            p10 = bc["p10"][0]
            p90 = bc["p90"][0]
            bandwidth = (p90 - p10) / max(median, 1)
            upside = p90 - median
            downside = median - p10
            asym = upside / max(downside, 1)

            # Composite score (0-100)
            size_score = min(median / 800000 * 30, 30)  # max 30 for largest markets
            efficiency_score = min((1 / max(bandwidth, 0.1)) * 15, 30)  # lower bandwidth = better
            asym_score = min(asym * 20, 20)  # higher asymmetry = better
            growth_score = 20  # placeholder for YoY

            total = size_score + efficiency_score + asym_score + growth_score
            scores[iso2] = {
                "score": round(total, 1),
                "median": median,
                "bandwidth_pct": round(bandwidth * 100, 1),
                "asymmetry": round(asym, 2),
                "components": {
                    "size": round(size_score, 1),
                    "efficiency": round(efficiency_score, 1),
                    "asymmetry": round(asym_score, 1),
                    "growth": round(growth_score, 1)
                }
            }
        return {"month": f"{year}/{month:02d}", "scores": scores}

    # 国通貨マッピング (訪日客の支払通貨ベース)
    CURRENCY_MAP = {
        "KR":"KRW","CN":"CNY","TW":"TWD","US":"USD","AU":"AUD",
        "TH":"THB","HK":"HKD","SG":"SGD",
    }
    # 為替レート前提 (JPY per 1 unit of currency, as of 2026/04)
    FX_RATES = {
        "USD":155.0,"KRW":0.115,"CNY":21.3,"TWD":4.85,"AUD":100.5,
        "THB":4.25,"HKD":19.8,"SGD":115.2,
    }

    def fx_exposure(self, month=4, year=2026):
        """通貨別FXエクスポージャー台帳 (IFRS 9ヘッジ会計対応)"""
        spending = self.spending_forecast(month, year)
        exposures = {}
        currencies = {}
        for iso2, data in spending["by_country"].items():
            ccy = self.CURRENCY_MAP.get(iso2)
            if not ccy: continue
            fx_rate = self.FX_RATES.get(ccy, 1.0)
            # 円建て消費額 → 現地通貨換算 (観光客の支払は基本JPYだが、サプライチェーン・仕入は現地通貨)
            # 営業CF受取は円建て、仕入CF支払は50%が現地通貨と仮定
            revenue_jpy = data["monthly_spending_p50"]
            revenue_p10 = data["monthly_spending_p10"]
            revenue_p90 = data["monthly_spending_p90"]
            notional_ccy = revenue_jpy / fx_rate
            currencies.setdefault(ccy, {"notional_ccy":0,"notional_jpy":0,"p10_jpy":0,"p90_jpy":0,"countries":[]})
            currencies[ccy]["notional_ccy"] += notional_ccy
            currencies[ccy]["notional_jpy"] += revenue_jpy
            currencies[ccy]["p10_jpy"] += revenue_p10
            currencies[ccy]["p90_jpy"] += revenue_p90
            currencies[ccy]["countries"].append(iso2)
            exposures[iso2] = {
                "currency": ccy, "fx_rate": fx_rate,
                "notional_ccy": round(notional_ccy),
                "notional_jpy": revenue_jpy,
                "p10_jpy": revenue_p10, "p90_jpy": revenue_p90,
            }
        # 通貨別サマリー
        for ccy, c in currencies.items():
            c["notional_ccy"] = round(c["notional_ccy"])
            c["var_at_risk_pct"] = round((c["notional_jpy"] - c["p10_jpy"]) / max(c["notional_jpy"], 1) * 100, 1)
        return {
            "month": f"{year}/{month:02d}",
            "by_country": exposures,
            "by_currency": currencies,
        }

    def compute_var_cvar(self, month=4, year=2026, confidence=0.99):
        """VaR/CVaRをモンテカルロシミュレーションから算出"""
        months_list = [f"{year}/{month:02d}"]
        # FXショック込みのMCサンプル生成
        n = min(self.n_samples, 3000)
        # 通貨別サンプル生成 (各通貨の消費額分布)
        from .variable_distributions import sample_all_vars, VAR_IDX
        all_vars = sample_all_vars(n)

        # 全通貨合算の消費額サンプル
        total_samples_jpy = np.zeros(n)
        currency_samples = {}
        for iso2 in ALL_COUNTRIES:
            ccy = self.CURRENCY_MAP.get(iso2)
            if not ccy: continue
            # 訪問者数サンプル (MCから)
            visitor_samples = self._compute_country(iso2, month, year, all_vars)
            # 消費単価サンプル (対数正規)
            mean_spv, cv = self.SPENDING_PARAMS.get(iso2, (120000, 0.35))
            sigma_ln = np.sqrt(np.log(1 + cv**2))
            mu_ln = np.log(mean_spv) - 0.5 * sigma_ln**2
            spv_samples = np.random.lognormal(mu_ln, sigma_ln, n)
            # 為替変動サンプル
            fx_var = f"fx_{ccy.lower()}"
            if fx_var in VAR_IDX:
                fx_shock = all_vars[:, VAR_IDX[fx_var]]
            else:
                fx_shock = np.zeros(n)
            # 円建て消費額 (為替影響込み)
            fx_base = self.FX_RATES.get(ccy, 1.0)
            jpy_samples = visitor_samples * spv_samples * (1 + fx_shock * 0.5)  # 為替感応0.5
            total_samples_jpy += jpy_samples
            currency_samples[ccy] = jpy_samples

        # 全体VaR/CVaR (日本円ベース、期待値からの下方乖離)
        expected = float(np.mean(total_samples_jpy))
        loss_distribution = expected - total_samples_jpy  # 期待値からの損失
        alpha = 1 - confidence  # 0.01 for 99%
        var_threshold = float(np.percentile(loss_distribution, 100 * confidence))
        cvar_tail = loss_distribution[loss_distribution >= var_threshold]
        cvar = float(np.mean(cvar_tail)) if len(cvar_tail) > 0 else var_threshold

        # 通貨別VaR
        ccy_var = {}
        for ccy, samples in currency_samples.items():
            c_exp = float(np.mean(samples))
            c_loss = c_exp - samples
            c_var = float(np.percentile(c_loss, 100 * confidence))
            ccy_var[ccy] = {
                "notional_jpy": int(c_exp),
                "var_jpy": int(c_var),
                "var_pct": round(c_var / max(c_exp, 1) * 100, 2),
            }

        return {
            "month": f"{year}/{month:02d}",
            "confidence_level": confidence,
            "n_samples": n,
            "expected_revenue_jpy": int(expected),
            "var_jpy": int(var_threshold),
            "cvar_jpy": int(cvar),
            "var_pct": round(var_threshold / max(expected, 1) * 100, 2),
            "cvar_pct": round(cvar / max(expected, 1) * 100, 2),
            "by_currency": ccy_var,
        }

    # 国別1人1回あたり消費額 (mean, CV) — 観光庁2024年調査
    SPENDING_PARAMS = {
        "KR": (72000, 0.35), "CN": (210000, 0.45), "TW": (125000, 0.30),
        "US": (230000, 0.40), "AU": (280000, 0.35), "TH": (105000, 0.40),
        "HK": (155000, 0.35), "SG": (165000, 0.30),
    }

    def spending_forecast(self, month=4, year=2026):
        """国別消費額予測（月次）— 消費単価の不確実性も伝播"""
        months = [f"{year}/{month:02d}"]
        result = self.run(months, "ALL")
        n = min(self.n_samples, 1000)
        spending = {}
        all_totals = np.zeros(n)
        for iso2 in ALL_COUNTRIES:
            bc = result["by_country"][iso2]
            mean_spv, cv = self.SPENDING_PARAMS.get(iso2, (120000, 0.35))
            # 対数正規分布で消費単価をサンプリング
            sigma_ln = np.sqrt(np.log(1 + cv**2))
            mu_ln = np.log(mean_spv) - 0.5 * sigma_ln**2
            spv_samples = np.random.lognormal(mu_ln, sigma_ln, n)
            # 来訪者数のp10/p50/p90からサンプル生成（簡易正規近似）
            v_med = bc["median"][0]
            v_std = (bc["p90"][0] - bc["p10"][0]) / 2.56  # 80%区間→σ
            v_samples = np.maximum(np.random.normal(v_med, v_std, n), 0)
            # 消費額 = 来訪者 × 単価
            spend_samples = v_samples * spv_samples
            all_totals += spend_samples
            spending[iso2] = {
                "visitors_p50": bc["median"][0],
                "spending_per_visitor_mean": int(mean_spv),
                "spending_per_visitor_cv": cv,
                "monthly_spending_p10": int(np.percentile(spend_samples, 10)),
                "monthly_spending_p50": int(np.percentile(spend_samples, 50)),
                "monthly_spending_p90": int(np.percentile(spend_samples, 90)),
            }
        return {
            "month": f"{year}/{month:02d}",
            "by_country": spending,
            "total_p10_oku": round(float(np.percentile(all_totals, 10)) / 1e8, 1),
            "total_p50_oku": round(float(np.percentile(all_totals, 50)) / 1e8, 1),
            "total_p90_oku": round(float(np.percentile(all_totals, 90)) / 1e8, 1),
        }

    def correlation_health(self):
        """相関行列の健全性チェック"""
        from .variable_distributions import CORR, VAR_NAMES
        eigvals = np.linalg.eigvalsh(CORR)
        return {
            "n_vars": len(VAR_NAMES),
            "min_eigenvalue": round(float(eigvals.min()), 6),
            "max_eigenvalue": round(float(eigvals.max()), 3),
            "condition_number": round(float(eigvals.max() / max(eigvals.min(), 1e-10)), 1),
            "is_positive_definite": bool(eigvals.min() > 0),
            "near_singular": bool(eigvals.min() < 1e-4),
        }

    def create_hedge_documentation(self, hedged_item, hedging_instrument, hedge_ratio,
                                    risk_objective, effectiveness_method="dollar_offset",
                                    designated_by="treasury@company.com"):
        """IFRS 9ヘッジ指定文書データモデル (監査対応)"""
        import hashlib, datetime
        timestamp = datetime.datetime.now().isoformat()
        # 監査証跡: 不変ハッシュ生成
        doc_content = f"{hedged_item}|{hedging_instrument}|{hedge_ratio}|{risk_objective}|{timestamp}"
        doc_hash = hashlib.sha256(doc_content.encode()).hexdigest()[:16]
        return {
            "document_id": f"HEDGE-{timestamp[:10]}-{doc_hash}",
            "designation_date": timestamp,
            "hedged_item": hedged_item,
            "hedging_instrument": hedging_instrument,
            "hedge_ratio": hedge_ratio,
            "risk_management_objective": risk_objective,
            "effectiveness_method": effectiveness_method,
            "effectiveness_thresholds": {"lower_bound_pct": 80, "upper_bound_pct": 125, "r_squared_min": 0.8},
            "designated_by": designated_by,
            "document_hash": doc_hash,
            "model_version": "full_mc_29vars_v1.6.0",
            "applicable_standards": ["IFRS 9", "J-GAAP金融商品会計基準"],
            "retest_frequency": "quarterly",
            "discontinuation_triggers": [
                "effectiveness_ratio < 80% or > 125%",
                "R² < 0.8",
                "correlation changes sign",
                "hedged item no longer expected",
                "hedging instrument terminated",
            ],
        }

    def audit_trail(self, action, params, user="system", result_summary=""):
        """監査証跡 (immutable log)"""
        import hashlib, datetime, json
        timestamp = datetime.datetime.now().isoformat()
        entry = {
            "timestamp": timestamp, "action": action, "user": user,
            "params": params, "result_summary": result_summary,
            "model_version": "full_mc_29vars_v1.6.0",
        }
        # SHA-256ハッシュで改ざん検知
        entry_hash = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        entry["entry_hash"] = entry_hash[:16]
        return entry

    def optimal_hedge_ratio(self, month=4, year=2026, target="cvar_min"):
        """ヘッジ比率最適化 (制約: 30-70%, 目的: CVaR最小化)"""
        var_result = self.compute_var_cvar(month, year, confidence=0.95)
        # ヘッジ比率を0.0-1.0で変化させたときのCVaR評価
        # ヘッジ済み部分は為替リスク完全除去、未ヘッジ部分はMC分散維持
        unhedged_cvar = var_result["cvar_jpy"]
        unhedged_var = var_result["var_jpy"]

        best_ratio = 0.5
        best_metric = float('inf')
        candidates = []
        for r in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            # ヘッジ後残存リスク = (1-r) × unhedged + r × 0 + ヘッジコスト
            residual_cvar = (1 - r) * unhedged_cvar
            # ヘッジコスト: フォワードプレミアム年率2% + オプション時間価値
            hedge_cost_rate = 0.02 * (r / 12)  # 月割り
            notional = var_result["expected_revenue_jpy"]
            hedge_cost_jpy = notional * hedge_cost_rate
            total_loss = residual_cvar + hedge_cost_jpy
            candidates.append({
                "hedge_ratio": r, "residual_cvar": int(residual_cvar),
                "hedge_cost_jpy": int(hedge_cost_jpy), "total_loss": int(total_loss),
                "within_policy": 0.3 <= r <= 0.7,
            })
            if 0.3 <= r <= 0.7 and total_loss < best_metric:
                best_metric = total_loss
                best_ratio = r

        return {
            "month": f"{year}/{month:02d}",
            "optimal_ratio": best_ratio,
            "policy_range": [0.3, 0.7],
            "unhedged_cvar_jpy": int(unhedged_cvar),
            "unhedged_var_jpy": int(unhedged_var),
            "optimal_total_loss": int(best_metric),
            "candidates": candidates,
            "note": "ヘッジコスト: フォワードプレミアム年率2% + オプション時間価値",
        }

    def hedge_effectiveness_test(self, months, hedge_notional_jpy, hedged_item_pct=1.0, fx_sensitivity=0.8, seed=42):
        """IFRS 9ヘッジ有効性テスト (80-125%ルール)
        ヘッジ対象: 外貨建て売上の為替感応部分
        ヘッジ手段: 為替フォワード (売りヘッジ)
        監査対応: seed固定で再現性確保
        """
        actual = self._load_actual_arrivals(months, "ALL")
        y = np.array(actual, dtype=float)
        if not any(y > 0):
            return {"status": "no_data", "note": "実績データ不足"}

        # FXショック: 実績DBから抽出（再現性のため乱数依存を排除）
        try:
            import sqlite3, datetime
            conn = sqlite3.connect('data/tourism_stats.db')
            fx_values = []
            for ms in months:
                y_, m_ = int(ms.split('/')[0]), int(ms.split('/')[1])
                # USD/JPY変化率を実績から取得
                cur = conn.execute(
                    "SELECT fx_rate_jpy FROM monthly_indicators WHERE source_country='US' AND year=? AND month=?",
                    (y_, m_)
                ).fetchone()
                fx_values.append(cur[0] if cur and cur[0] else None)
            conn.close()
            # 月次変化率計算
            fx_changes = []
            prev = None
            for v in fx_values:
                if v is not None and prev is not None and prev > 0:
                    fx_changes.append((v - prev) / prev)
                else:
                    fx_changes.append(0.0)
                prev = v
            fx_changes = np.array(fx_changes)
            # フォールバック: 実績が取れない場合はseed固定乱数
            if np.all(fx_changes == 0):
                rng = np.random.RandomState(seed)
                fx_changes = rng.normal(0, 0.04, len(months))
        except Exception:
            rng = np.random.RandomState(seed)
            fx_changes = rng.normal(0, 0.04, len(months))

        # ヘッジ対象: 外貨建て売上の為替変動影響
        # 売上 × 為替感応度 × FXショック
        avg_spv = 150000
        base_revenue = y * avg_spv * hedged_item_pct
        hedged_item_values = base_revenue * (1 + fx_changes * fx_sensitivity)  # 為替感応

        # ヘッジ手段: 為替フォワード売りヘッジ
        # PnL = -Notional × FXショック (円安→損失をフォワード売りで相殺)
        hedging_instrument_values = -hedge_notional_jpy * fx_changes

        # 80-125%ルール判定: Δヘッジ手段 / Δヘッジ対象 (為替影響部分のみ)
        # 為替影響部分 = hedged_item - base_revenue
        fx_impact_on_hedged = hedged_item_values - base_revenue
        dY = np.diff(fx_impact_on_hedged)
        dH = np.diff(hedging_instrument_values)
        if len(dY) < 2 or np.sum(np.abs(dY)) == 0:
            return {"status": "insufficient_data"}

        # 最小二乗回帰: dH = slope × dY + intercept
        mean_dY = np.mean(dY); mean_dH = np.mean(dH)
        num = np.sum((dY - mean_dY) * (dH - mean_dH))
        den = np.sum((dY - mean_dY) ** 2)
        slope = float(num / den) if den > 0 else 0
        # 有効性比率 = |slope| × 100 (-1.0 = 完全ヘッジ)
        # ヘッジ対象変動1単位に対するヘッジ手段変動を%で表現
        avg_effectiveness = abs(slope) * 100
        # 相関係数 (R)
        if np.std(dY) > 0 and np.std(dH) > 0:
            correlation = float(np.corrcoef(dY, dH)[0, 1])
            r_squared = correlation ** 2
        else:
            correlation = 0; r_squared = 0

        # IFRS 9: 80-125%ルール + R²>0.8 + 相関が負 (売りヘッジ)
        is_highly_effective = 80 <= avg_effectiveness <= 125 and r_squared >= 0.8 and correlation < 0

        return {
            "months": months,
            "hedge_notional_jpy": hedge_notional_jpy,
            "hedged_item_pct": hedged_item_pct,
            "effectiveness_ratio": round(avg_effectiveness, 1),
            "slope": round(slope, 4),
            "correlation": round(correlation, 4),
            "r_squared": round(r_squared, 4),
            "is_highly_effective": is_highly_effective,
            "ifrs9_compliant": is_highly_effective,
            "judgement": "高度に有効 (80-125%ルール適合)" if is_highly_effective else
                         f"無効 (比率={avg_effectiveness:.0f}%, R²={r_squared:.2f})",
        }

    def stress_test_scenarios(self, month=4, year=2026):
        """ストレステスト (リーマン級/COVID級/尖閣級/金融危機級)"""
        base = self.run([f"{year}/{month:02d}"], "ALL")["median"][0]
        scenarios = {
            "2008_lehman": {"fx_shock": -0.25, "geo_shock": -15, "gdp_shock": -0.04, "name": "2008年リーマン危機"},
            "2020_covid": {"fx_shock": -0.10, "geo_shock": -5, "gdp_shock": -0.08, "demand_shock": -0.90, "name": "2020年COVID-19"},
            "2012_senkaku": {"fx_shock": 0.05, "geo_shock": -45, "gdp_shock": 0.00, "name": "2012年尖閣危機(CN特化)"},
            "2022_russia": {"fx_shock": -0.15, "geo_shock": -10, "gdp_shock": -0.03, "name": "2022年ロシア侵攻"},
            "flash_crash": {"fx_shock": -0.35, "geo_shock": 0, "gdp_shock": -0.02, "name": "フラッシュクラッシュ"},
        }
        results = []
        for key, s in scenarios.items():
            # 各ショックを適用したストレス値
            fx_impact = 1 + s["fx_shock"] * 1.1  # FX: 円安(+)で需要増、円高(-)で需要減
            gdp_impact = 1 + s.get("gdp_shock", 0) * 1.24
            demand_impact = 1 + s.get("demand_shock", 0)
            geo_impact = float(np.exp(-0.038 * (-s["geo_shock"])))  # geo_shock<0で需要減
            stressed_value = base * fx_impact * gdp_impact * demand_impact * geo_impact
            loss_jpy = max(0, (base - stressed_value) * 150000)  # 消費額換算
            results.append({
                "scenario": s["name"], "key": key,
                "base_visitors": int(base),
                "stressed_visitors": int(max(stressed_value, 0)),
                "visitor_decline_pct": round((stressed_value - base) / base * 100, 1),
                "estimated_loss_jpy": int(loss_jpy),
                "estimated_loss_oku": round(loss_jpy / 1e8, 1),
                "shocks": s,
            })
        worst = min(results, key=lambda x: x["visitor_decline_pct"])
        return {
            "month": f"{year}/{month:02d}",
            "scenarios": results,
            "worst_case": worst["scenario"],
            "worst_case_loss_oku": worst["estimated_loss_oku"],
            "average_loss_oku": round(sum(r["estimated_loss_oku"] for r in results) / len(results), 1),
        }

    def counterparty_credit_risk(self, counterparty_ratings=None):
        """カウンターパーティ信用リスク (CVA/PFE/EE)"""
        if counterparty_ratings is None:
            counterparty_ratings = {
                "MUFG": {"rating": "A+", "cds_bp": 35, "exposure_jpy": 800e8, "utilization_pct": 60},
                "SMBC": {"rating": "A+", "cds_bp": 32, "exposure_jpy": 600e8, "utilization_pct": 45},
                "MS_JP": {"rating": "A", "cds_bp": 48, "exposure_jpy": 400e8, "utilization_pct": 70},
                "Citi_JP": {"rating": "A", "cds_bp": 52, "exposure_jpy": 300e8, "utilization_pct": 80},
            }
        results = []
        total_cva = 0
        for cp_name, cp in counterparty_ratings.items():
            # CVA = EAD × PD × LGD (simplified)
            # PD from CDS: CDS bp / (1-recovery 40%) / 10000 / year
            pd_annual = cp["cds_bp"] / 6000  # CDS spread / LGD / bps
            pd_tenor = pd_annual * 0.25  # 3M tenor
            lgd = 0.60  # 40% recovery assumption
            ead = cp["exposure_jpy"]  # Expected Exposure
            pfe = ead * 1.65  # 95th percentile future exposure (simplified)
            cva = ead * pd_tenor * lgd
            total_cva += cva
            # WWR (Wrong-Way Risk): 観光業とFXリスクの相関が高い場合
            wwr_flag = cp["utilization_pct"] > 75
            results.append({
                "counterparty": cp_name, "rating": cp["rating"],
                "cds_bp": cp["cds_bp"],
                "exposure_jpy": int(ead), "pfe_jpy": int(pfe),
                "pd_annual_pct": round(pd_annual * 100, 3),
                "cva_jpy": int(cva), "cva_bp": round(cva / ead * 10000, 1),
                "utilization_pct": cp["utilization_pct"],
                "wwr_flag": wwr_flag,
                "credit_limit_breach": cp["utilization_pct"] > 95,
            })
        return {
            "total_exposure_jpy": int(sum(r["exposure_jpy"] for r in results)),
            "total_cva_jpy": int(total_cva),
            "total_cva_oku": round(total_cva / 1e8, 2),
            "counterparties": results,
            "portfolio_health": "GOOD" if total_cva / sum(r["exposure_jpy"] for r in results) < 0.01 else "REVIEW",
        }

    def dynamic_hedge_rebalance(self, current_hedge_ratio, current_effectiveness, recent_fx_change):
        """動的ヘッジリバランス推奨 (ルールベース)"""
        adjustments = []
        new_ratio = current_hedge_ratio
        # Rule 1: 有効性劣化対応
        if current_effectiveness < 85:
            new_ratio = min(current_hedge_ratio + 0.05, 0.70)
            adjustments.append({
                "trigger": "効率低下", "old": current_hedge_ratio, "new": new_ratio,
                "reason": f"有効性{current_effectiveness}% → ヘッジ比率+5%で補正",
            })
        elif current_effectiveness > 120:
            new_ratio = max(current_hedge_ratio - 0.05, 0.30)
            adjustments.append({
                "trigger": "過剰ヘッジ", "old": current_hedge_ratio, "new": new_ratio,
                "reason": f"有効性{current_effectiveness}% → ヘッジ比率-5%で調整",
            })
        # Rule 2: 大幅FX変動対応
        if abs(recent_fx_change) > 0.05:
            if recent_fx_change < 0:  # 円高
                new_ratio = min(new_ratio + 0.10, 0.70)
                adjustments.append({
                    "trigger": "円高加速", "old": current_hedge_ratio, "new": new_ratio,
                    "reason": f"為替{recent_fx_change*100:.1f}% → ヘッジ比率+10%で防御",
                })
            else:  # 円安
                new_ratio = max(new_ratio - 0.05, 0.30)
                adjustments.append({
                    "trigger": "円安進行", "old": current_hedge_ratio, "new": new_ratio,
                    "reason": f"為替+{recent_fx_change*100:.1f}% → ヘッジ比率-5%で機会活用",
                })
        return {
            "current_ratio": current_hedge_ratio,
            "recommended_ratio": round(new_ratio, 2),
            "change": round(new_ratio - current_hedge_ratio, 2),
            "rebalance_required": abs(new_ratio - current_hedge_ratio) >= 0.05,
            "adjustments": adjustments,
            "within_policy": 0.30 <= new_ratio <= 0.70,
        }

    def detect_discontinuation(self, effectiveness_history, r_squared_history, correlation_sign_history):
        """ヘッジ会計中止条件検出 (IFRS 9 6.5.6)"""
        triggers = []
        latest_eff = effectiveness_history[-1] if effectiveness_history else None
        latest_r2 = r_squared_history[-1] if r_squared_history else None
        latest_corr_sign = correlation_sign_history[-1] if correlation_sign_history else None
        # Trigger 1: 80-125%範囲逸脱
        if latest_eff is not None and (latest_eff < 80 or latest_eff > 125):
            triggers.append({
                "trigger": "effectiveness_out_of_range",
                "value": latest_eff, "threshold": "80-125%",
                "action_required": "ヘッジ会計中止、以降は時価評価",
            })
        # Trigger 2: R²<0.8
        if latest_r2 is not None and latest_r2 < 0.8:
            triggers.append({
                "trigger": "r_squared_below_threshold",
                "value": latest_r2, "threshold": 0.8,
                "action_required": "再テスト実施、改善しなければ中止",
            })
        # Trigger 3: 相関符号反転
        if latest_corr_sign is not None and latest_corr_sign > 0:
            triggers.append({
                "trigger": "correlation_sign_reversal",
                "value": latest_corr_sign, "threshold": "<0 (売りヘッジ)",
                "action_required": "即時ヘッジ会計中止、ineffectiveness全額P/L",
            })
        # Trigger 4: 連続2期間の劣化傾向
        if len(effectiveness_history) >= 3:
            recent = effectiveness_history[-3:]
            if all(e < 80 or e > 125 for e in recent[-2:]):
                triggers.append({
                    "trigger": "consecutive_deterioration",
                    "value": recent, "threshold": "2期間連続逸脱",
                    "action_required": "ヘッジ会計中止確定",
                })
        return {
            "discontinuation_required": len(triggers) > 0,
            "triggers": triggers,
            "recommendation": "ヘッジ会計中止手続き開始" if triggers else "ヘッジ会計継続",
        }

    def generate_journal_entries(self, hedge_type, effective_amount_jpy, ineffective_amount_jpy, standard="IFRS"):
        """ヘッジ会計仕訳自動生成 (IFRS 9 / J-GAAP両対応)"""
        entries = []
        if standard == "IFRS":
            # IFRS 9: Cash Flow Hedge
            if hedge_type == "cash_flow":
                entries.append({
                    "date": "月末",
                    "debit": "デリバティブ資産/負債 (時価変動)",
                    "credit": "OCI (その他包括利益) — Effective Portion",
                    "amount": abs(effective_amount_jpy),
                    "description": f"CFヘッジ有効部分のOCI振替 ({effective_amount_jpy:+,}円)",
                })
                if abs(ineffective_amount_jpy) > 0:
                    entries.append({
                        "date": "月末",
                        "debit": "為替差損 (P/L)" if ineffective_amount_jpy < 0 else "デリバティブ資産",
                        "credit": "デリバティブ負債" if ineffective_amount_jpy < 0 else "為替差益 (P/L)",
                        "amount": abs(ineffective_amount_jpy),
                        "description": f"ヘッジ非有効部分のP/L計上 ({ineffective_amount_jpy:+,}円)",
                    })
            elif hedge_type == "fair_value":
                entries.append({
                    "date": "月末",
                    "debit": "ヘッジ対象 (時価変動)",
                    "credit": "為替差益 (P/L)",
                    "amount": abs(effective_amount_jpy),
                    "description": "FVヘッジ対象の時価評価",
                })
        elif standard == "JGAAP":
            # J-GAAP金融商品会計基準: 繰延ヘッジが原則
            entries.append({
                "date": "月末",
                "debit": "デリバティブ資産/負債",
                "credit": "繰延ヘッジ損益 (純資産直入)",
                "amount": abs(effective_amount_jpy),
                "description": f"繰延ヘッジ処理 ({effective_amount_jpy:+,}円)",
            })
        return {
            "standard": standard,
            "hedge_type": hedge_type,
            "total_entries": len(entries),
            "entries": entries,
            "disclosure_notes": [
                "有価証券報告書: ヘッジ手段の公正価値、ヘッジ対象、有効性評価結果を開示",
                "注記: 80-125%ルール適合判定、回帰R²、ineffectiveness金額を明示",
            ],
        }

    def dollar_offset_test(self, hedged_item_pnl, hedging_instrument_pnl):
        """Dollar Offset method (IFRS 9 B6.4.4.b 事後有効性テスト)
        累積相殺比率 = -ΣΔHI / ΣΔHedgedItem
        80-125%適合判定
        """
        sum_hi = float(np.sum(hedging_instrument_pnl))
        sum_hedged = float(np.sum(hedged_item_pnl))
        if abs(sum_hedged) < 1:
            return {"status": "insufficient_movement", "cumulative_ratio": None}
        ratio = -sum_hi / sum_hedged * 100
        is_effective = 80 <= ratio <= 125
        # Ineffectiveness = 超過部分 (P/L計上)
        perfect_hedge = -sum_hedged
        ineffectiveness_jpy = sum_hi - perfect_hedge
        return {
            "sum_hedged_item_pnl": int(sum_hedged),
            "sum_hedging_instrument_pnl": int(sum_hi),
            "cumulative_ratio_pct": round(ratio, 1),
            "is_highly_effective": is_effective,
            "ineffectiveness_jpy": int(ineffectiveness_jpy),
            "ineffectiveness_treatment": "P/L (ineffective portion)" if not is_effective else "OCI (effective portion)",
        }

    def compute_ineffectiveness(self, hedged_item_pnl_series, hedging_instrument_pnl_series):
        """非有効部分の測定 (OCI/PL配分)"""
        hedged = np.array(hedged_item_pnl_series, dtype=float)
        hi = np.array(hedging_instrument_pnl_series, dtype=float)
        n = min(len(hedged), len(hi))
        hedged = hedged[:n]; hi = hi[:n]
        # 完全ヘッジ: hi + hedged = 0
        # Lesser of test (IFRS 9 6.5.11): min(|ΣΔHI|, |ΣΔHypoDerivative|)
        cumulative_hi = float(np.sum(hi))
        cumulative_hedged = float(np.sum(hedged))
        # Effective portion = min(|cumulative_hi|, |cumulative_hedged|) with same sign as hedging instrument
        effective = min(abs(cumulative_hi), abs(cumulative_hedged))
        if cumulative_hi < 0: effective = -effective
        ineffective = cumulative_hi - effective
        return {
            "periods": n,
            "cumulative_hedging_instrument_pnl": int(cumulative_hi),
            "cumulative_hedged_item_pnl": int(cumulative_hedged),
            "effective_portion_oci": int(effective),
            "ineffective_portion_pl": int(ineffective),
            "ineffectiveness_pct": round(abs(ineffective) / max(abs(cumulative_hi), 1) * 100, 1),
        }

    def pair_trading_signal(self, country_a="KR", country_b="TW", window=24):
        """ペアトレード信号 (z-score, half-life, spread分析)"""
        # Get actual arrivals for both countries (24 months)
        import datetime
        months = []
        year, month = 2023, 1
        for _ in range(window):
            months.append(f"{year}/{month:02d}")
            month += 1
            if month > 12: month = 1; year += 1
        a_data = self._load_actual_arrivals(months, country_a)
        b_data = self._load_actual_arrivals(months, country_b)
        a = np.array(a_data, dtype=float)
        b = np.array(b_data, dtype=float)
        mask = (a > 0) & (b > 0)
        if mask.sum() < 12:
            return {"status": "insufficient_data"}
        a, b = a[mask], b[mask]
        # log ratio spread
        log_a = np.log(a); log_b = np.log(b)
        spread = log_a - log_b
        mean_spread = float(np.mean(spread))
        std_spread = float(np.std(spread))
        current_spread = float(spread[-1])
        z_score = (current_spread - mean_spread) / max(std_spread, 1e-9)
        # Half-life (OU process estimation): dX_t = -theta*(X_t - mu)*dt
        # Using OLS: d_spread = -theta * (spread_{t-1} - mu) + e
        if len(spread) > 3:
            d_spread = np.diff(spread)
            lag_spread = spread[:-1] - mean_spread
            if np.var(lag_spread) > 0:
                theta = -float(np.cov(d_spread, lag_spread)[0,1] / np.var(lag_spread))
                half_life = float(np.log(2) / theta) if theta > 0 else float('inf')
            else:
                half_life = float('inf')
        else:
            half_life = float('inf')
        # Signal
        if z_score > 2:
            signal = "SHORT_A_LONG_B"  # A is rich, B is cheap
        elif z_score < -2:
            signal = "LONG_A_SHORT_B"
        else:
            signal = "NEUTRAL"
        return {
            "pair": f"{country_a}/{country_b}",
            "current_spread": round(current_spread, 4),
            "mean_spread": round(mean_spread, 4),
            "std_spread": round(std_spread, 4),
            "z_score": round(z_score, 2),
            "half_life_months": round(half_life, 1) if half_life != float('inf') else None,
            "signal": signal,
            "window_months": window,
            "statistical_significance": "HIGH" if abs(z_score) > 2 else ("MEDIUM" if abs(z_score) > 1 else "LOW"),
        }

    def rolling_correlation(self, country_a="KR", country_b="TW", window=12):
        """時変相関 (Rolling correlation) — レジーム変化検出"""
        months = []
        year, month = 2022, 1
        for _ in range(36):
            months.append(f"{year}/{month:02d}")
            month += 1
            if month > 12: month = 1; year += 1
        a_data = self._load_actual_arrivals(months, country_a)
        b_data = self._load_actual_arrivals(months, country_b)
        a = np.array(a_data, dtype=float); b = np.array(b_data, dtype=float)
        mask = (a > 0) & (b > 0)
        a, b = a[mask], b[mask]
        if len(a) < window + 1:
            return {"status": "insufficient_data"}
        # Log returns
        ret_a = np.diff(np.log(a)); ret_b = np.diff(np.log(b))
        rolling_corrs = []
        for i in range(window, len(ret_a)):
            window_a = ret_a[i-window:i]; window_b = ret_b[i-window:i]
            if np.std(window_a) > 0 and np.std(window_b) > 0:
                rolling_corrs.append(float(np.corrcoef(window_a, window_b)[0,1]))
        if not rolling_corrs: return {"status": "insufficient_data"}
        current_corr = rolling_corrs[-1]
        mean_corr = float(np.mean(rolling_corrs))
        std_corr = float(np.std(rolling_corrs))
        # Regime change detection (2-sigma deviation)
        regime_change = abs(current_corr - mean_corr) > 2 * std_corr
        return {
            "pair": f"{country_a}/{country_b}",
            "window_months": window,
            "current_correlation": round(current_corr, 3),
            "mean_correlation": round(mean_corr, 3),
            "std_correlation": round(std_corr, 3),
            "min_correlation": round(min(rolling_corrs), 3),
            "max_correlation": round(max(rolling_corrs), 3),
            "regime_change_detected": bool(regime_change),
            "series": [round(c, 3) for c in rolling_corrs],
        }

    # 金利前提 (年率, 2026/04時点)
    INTEREST_RATES = {
        "JPY": 0.005, "USD": 0.0475, "KRW": 0.0325, "CNY": 0.0285,
        "TWD": 0.0175, "AUD": 0.0435, "THB": 0.0225, "HKD": 0.0475, "SGD": 0.0345,
    }

    def fx_forward_price(self, currency="USD", tenor_months=3):
        """FXフォワード理論価格 (Interest Rate Parity)"""
        spot = self.FX_RATES.get(currency, 100.0)
        r_jpy = self.INTEREST_RATES.get("JPY", 0.005)
        r_foreign = self.INTEREST_RATES.get(currency, 0.02)
        T = tenor_months / 12.0
        # F = S * (1 + r_JPY*T) / (1 + r_foreign*T)
        forward = spot * (1 + r_jpy * T) / (1 + r_foreign * T)
        forward_premium_pct = (forward - spot) / spot * 100
        annualized_premium = forward_premium_pct / T
        return {
            "currency": currency,
            "tenor_months": tenor_months,
            "spot_rate": round(spot, 4),
            "forward_rate": round(forward, 4),
            "forward_points": round((forward - spot) * 10000, 1),
            "forward_premium_pct": round(forward_premium_pct, 3),
            "annualized_premium_pct": round(annualized_premium, 3),
            "r_domestic_jpy": r_jpy,
            "r_foreign": r_foreign,
        }

    def fx_option_price_bs(self, currency="USD", tenor_months=3, strike_pct=1.0, is_call=False, iv=0.10):
        """Black-Scholes Garman-Kohlhagen FXオプション価格"""
        from math import log, sqrt, exp, erf
        spot = self.FX_RATES.get(currency, 100.0)
        strike = spot * strike_pct
        r_jpy = self.INTEREST_RATES.get("JPY", 0.005)
        r_foreign = self.INTEREST_RATES.get(currency, 0.02)
        T = tenor_months / 12.0
        if T <= 0 or iv <= 0:
            return {"error": "invalid_params"}
        def N(x): return 0.5 * (1 + erf(x / sqrt(2)))
        d1 = (log(spot/strike) + (r_jpy - r_foreign + 0.5*iv**2)*T) / (iv*sqrt(T))
        d2 = d1 - iv*sqrt(T)
        if is_call:
            price = spot * exp(-r_foreign*T) * N(d1) - strike * exp(-r_jpy*T) * N(d2)
            delta = exp(-r_foreign*T) * N(d1)
        else:
            price = strike * exp(-r_jpy*T) * N(-d2) - spot * exp(-r_foreign*T) * N(-d1)
            delta = -exp(-r_foreign*T) * N(-d1)
        premium_pct = price / spot * 100
        return {
            "currency": currency, "option_type": "CALL" if is_call else "PUT",
            "tenor_months": tenor_months, "strike": round(strike, 4),
            "strike_pct_of_spot": strike_pct,
            "spot": round(spot, 4), "iv_annual": iv,
            "premium_per_unit": round(price, 4),
            "premium_pct_of_spot": round(premium_pct, 3),
            "delta": round(delta, 4),
        }

    def fx_vol_analysis(self, currency="USD"):
        """FXボラティリティ分析 (Implied vs Realized)"""
        # Realized vol from sigma of FX shock spec
        from .variable_distributions import SPECS
        fx_var = f"fx_{currency.lower()}"
        if fx_var in SPECS:
            # SPECS.sigmaは年次変化率の標準偏差
            realized_vol_annual = float(SPECS[fx_var].sigma)
        else:
            realized_vol_annual = 0.10
        # Implied vol approximation (market typically ~10-15%)
        implied_vol_annual = {
            "USD": 0.095, "KRW": 0.115, "CNY": 0.065, "TWD": 0.075,
            "AUD": 0.125, "THB": 0.095, "HKD": 0.020, "SGD": 0.080,
        }.get(currency, 0.10)
        iv_rv_spread = implied_vol_annual - realized_vol_annual
        return {
            "currency": currency,
            "realized_vol_annual": round(realized_vol_annual, 4),
            "implied_vol_annual": round(implied_vol_annual, 4),
            "iv_rv_spread": round(iv_rv_spread, 4),
            "iv_rv_ratio": round(implied_vol_annual / max(realized_vol_annual, 0.01), 2),
            "signal": "SELL_VOL" if iv_rv_spread > 0.02 else ("BUY_VOL" if iv_rv_spread < -0.02 else "NEUTRAL"),
        }

    def basis_risk_analysis(self, company_revenue_monthly=None, months=None):
        """ベーシスリスク定量化 (JNTO見込み vs 自社実績)"""
        if months is None:
            months = [f"2024/{m:02d}" for m in range(1, 13)]
        jnto_actuals = np.array(self._load_actual_arrivals(months, "ALL"), dtype=float)
        if company_revenue_monthly is None:
            company_revenue_monthly = jnto_actuals * 150000 * 0.01
        company_revenue = np.array(company_revenue_monthly, dtype=float)
        mask = (jnto_actuals > 0) & (company_revenue > 0)
        if mask.sum() < 3: return {"status": "insufficient_data"}
        jnto_growth = np.diff(np.log(jnto_actuals[mask]))
        rev_growth = np.diff(np.log(company_revenue[mask]))
        if len(jnto_growth) < 2: return {"status": "insufficient_data"}
        correlation = float(np.corrcoef(jnto_growth, rev_growth)[0, 1])
        slope = float(np.cov(jnto_growth, rev_growth)[0, 1] / max(np.var(jnto_growth), 1e-9))
        r_squared = correlation ** 2
        residuals = rev_growth - slope * jnto_growth
        basis_vol = float(np.std(residuals))
        return {
            "months": months,
            "correlation": round(correlation, 3),
            "r_squared": round(r_squared, 3),
            "beta_to_jnto": round(slope, 3),
            "basis_volatility_monthly": round(basis_vol, 4),
            "tracking_error_annual": round(basis_vol * np.sqrt(12), 4),
            "hedge_quality": "HIGH" if r_squared > 0.7 else ("MEDIUM" if r_squared > 0.4 else "LOW"),
        }

    def customer_hedge_recommendation(self, revenue_ccy_breakdown):
        """顧客別ヘッジ推奨 (地銀RM向け)"""
        total_revenue = sum(revenue_ccy_breakdown.values())
        recommendations = []
        high_vol_currencies = ["KRW", "CNY", "TWD", "THB", "AUD"]
        for ccy, notional in revenue_ccy_breakdown.items():
            if notional < 1e7: continue
            is_high_vol = ccy in high_vol_currencies
            if notional >= 1e9:
                product = "通貨スワップ (長期) + 為替予約 (短期)"
                hedge_ratio = 0.60
                reason = "大口・長期: 金利リスクも考慮しスワップ併用"
            elif is_high_vol and notional >= 1e8:
                product = "通貨オプション (プット買い)"
                hedge_ratio = 0.50
                reason = "高ボラ通貨: 下落保険でアップサイド維持"
            elif notional >= 1e8:
                product = "為替予約 (3-6ヶ月ロール)"
                hedge_ratio = 0.70
                reason = "中規模・安定通貨: シンプルな為替予約"
            else:
                product = "為替予約 (3ヶ月)"
                hedge_ratio = 0.50
                reason = "小口: 短期予約で柔軟性確保"
            recommendations.append({
                "currency": ccy, "notional_jpy": int(notional),
                "pct_of_total": round(notional / total_revenue * 100, 1),
                "recommended_product": product,
                "recommended_hedge_ratio": hedge_ratio,
                "annual_hedge_cost_jpy": int(notional * hedge_ratio * 0.015),
                "risk_category": "HIGH_VOL" if is_high_vol else "STABLE",
                "rationale": reason,
            })
        weighted_hr = sum(r["recommended_hedge_ratio"] * r["notional_jpy"] for r in recommendations) / max(total_revenue, 1)
        total_cost = sum(r["annual_hedge_cost_jpy"] for r in recommendations)
        return {
            "total_fx_exposure_jpy": int(total_revenue),
            "portfolio_hedge_ratio": round(weighted_hr, 3),
            "total_annual_hedge_cost_jpy": int(total_cost),
            "cost_as_pct_of_revenue": round(total_cost / max(total_revenue, 1) * 100, 3),
            "recommendations": recommendations,
            "suitability_check": {
                "within_30_70_policy": 0.3 <= weighted_hr <= 0.7,
                "cost_reasonable": total_cost / max(total_revenue, 1) < 0.02,
                "currency_diversified": len(recommendations) >= 2,
            },
        }

    def auto_calibrate(self):
        """バックテスト結果に基づくidioパラメータ自動校正"""
        months_2024 = [f"2024/{m:02d}" for m in range(1, 13)]
        adjustments = {}
        for iso2 in ALL_COUNTRIES:
            bt = self.backtest(months_2024, iso2)
            if bt['mape'] is None:
                continue
            cov = bt['coverage_p10_p90']
            current_idio = PARAMS[iso2]['idio']
            if cov < 70:
                new_idio = min(current_idio * 1.3, 0.40)  # +30%, cap at 0.40
                PARAMS[iso2]['idio'] = new_idio
                adjustments[iso2] = {"old": current_idio, "new": round(new_idio, 3), "coverage": cov, "action": "increased"}
            elif cov < 80:
                new_idio = min(current_idio * 1.15, 0.35)  # +15%
                PARAMS[iso2]['idio'] = new_idio
                adjustments[iso2] = {"old": current_idio, "new": round(new_idio, 3), "coverage": cov, "action": "increased"}
            elif cov > 95:
                new_idio = max(current_idio * 0.90, 0.05)  # -10%, floor 0.05
                PARAMS[iso2]['idio'] = new_idio
                adjustments[iso2] = {"old": current_idio, "new": round(new_idio, 3), "coverage": cov, "action": "decreased"}
        return adjustments

    def _load_actual_arrivals(self, months, source_country="ALL"):
        """DBから実績来訪者数を取得 (ISO3→ISO2変換付き)"""
        countries = ALL_COUNTRIES if source_country == "ALL" else [source_country]
        try:
            conn = sqlite3.connect('data/tourism_stats.db')
            totals = []
            for ms in months:
                year, month = int(ms.split('/')[0]), int(ms.split('/')[1])
                total = 0
                for iso2 in countries:
                    iso3 = ISO2_TO_ISO3.get(iso2, iso2)
                    row = conn.execute(
                        "SELECT arrivals FROM japan_inbound WHERE source_country=? AND year=? AND month=?",
                        (iso3, year, month)
                    ).fetchone()
                    if row and row[0]: total += row[0]
                totals.append(total)
            conn.close()
            return totals
        except Exception:
            return [0] * len(months)

    def backtest(self, months, source_country="ALL"):
        """バックテスト: 過去予測のMAPE + p10-p90カバー率"""
        pred = self.run(months, source_country)
        actual = self._load_actual_arrivals(months, source_country)
        yhat = np.array(pred["median"], dtype=float)
        y = np.array(actual, dtype=float)
        p10 = np.array(pred["p10"], dtype=float)
        p90 = np.array(pred["p90"], dtype=float)

        mask = y > 0
        if not mask.any():
            return {"months": months, "mape": None, "wmape": None, "coverage_p10_p90": None,
                    "note": "実績データなし"}

        errors = np.abs(yhat[mask] - y[mask])
        mape = float(np.mean(errors / y[mask]) * 100)
        wmape = float(np.sum(errors) / np.sum(y[mask]) * 100)
        coverage = float(np.mean((y[mask] >= p10[mask]) & (y[mask] <= p90[mask])))

        by_month = []
        for i, ms in enumerate(months):
            if y[i] > 0:
                by_month.append({
                    "month": ms, "actual": int(y[i]), "predicted": int(yhat[i]),
                    "p10": int(p10[i]), "p90": int(p90[i]),
                    "error_pct": round(abs(yhat[i]-y[i])/y[i]*100, 1),
                    "in_band": bool(y[i] >= p10[i] and y[i] <= p90[i])
                })

        return {
            "months": months, "source_country": source_country,
            "mape": round(mape, 1), "wmape": round(wmape, 1),
            "coverage_p10_p90": round(coverage * 100, 1),
            "target_coverage": 80.0,
            "n_months_with_data": int(mask.sum()),
            "by_month": by_month,
        }

    def _compute_bias_correction(self, source_country="ALL"):
        """過去12ヶ月の予測バイアスを推定して補正係数を返す"""
        try:
            months_2024 = [f"2024/{m:02d}" for m in range(1, 13)]
            actual = self._load_actual_arrivals(months_2024, source_country)
            if not any(a > 0 for a in actual):
                return 1.0
            # 簡易予測（シード固定で再現性確保）
            saved_state = np.random.get_state()
            np.random.seed(42)
            pred = self.run.__wrapped__(self, months_2024, source_country) if hasattr(self.run, '__wrapped__') else None
            np.random.set_state(saved_state)
            if pred is None:
                return 1.0
            y = np.array(actual, dtype=float)
            yhat = np.array(pred["median"], dtype=float)
            mask = y > 0
            if not mask.any():
                return 1.0
            ratio = np.mean(y[mask] / yhat[mask])
            return float(np.clip(ratio, 0.7, 1.3))  # ±30%上限
        except Exception:
            return 1.0

    def run(self, months, source_country="ALL"):
        if self.n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {self.n_samples}")
        if source_country != "ALL" and source_country not in PARAMS:
            raise ValueError(f"Unknown source_country '{source_country}'. Valid: {list(PARAMS.keys())} or 'ALL'")
        for ms in months:
            parts = ms.split('/')
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError(f"Invalid month format '{ms}'. Expected 'YYYY/MM'")
        countries = ALL_COUNTRIES if source_country == "ALL" else [source_country]
        nm = len(months)
        total = np.zeros((nm, self.n_samples))
        by_c = {c: np.zeros((nm, self.n_samples)) for c in countries}

        for mi, ms in enumerate(months):
            year, month = int(ms.split('/')[0]), int(ms.split('/')[1])
            all_vars = sample_all_vars(self.n_samples)
            for iso2 in countries:
                s = self._compute_country(iso2, month, year, all_vars)
                by_c[iso2][mi] = s
                total[mi] += s

        def pct(a, q): return [int(np.percentile(a[i], q)) for i in range(nm)]
        p10a = np.array(pct(total,10)); p50a = np.array(pct(total,50)); p90a = np.array(pct(total,90))
        lower = p50a - p10a; upper = p90a - p50a

        return {
            "months":months, "source_country":source_country, "n_samples":self.n_samples,
            "median":pct(total,50), "p10":pct(total,10), "p25":pct(total,25),
            "p75":pct(total,75), "p90":pct(total,90),
            "by_country":{c:{"median":pct(by_c[c],50),"p10":pct(by_c[c],10),"p90":pct(by_c[c],90)} for c in countries},
            "asymmetry_by_month":[round(float(u/max(l,1)),3) for u,l in zip(upper,lower)],
            "uncertainty_by_month":[round(float((p90a[i]-p10a[i])/max(p50a[i],1)*100),1) for i in range(nm)],
        }
