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
    "US": dict(base=300000,fx="fx_usd",gdp="gdp_us",geo=None,flt="flt_us",cci="cci_us",stk="stk_us",clt="clt_us",
               idio=0.20,peaks={7:1.45,8:1.50,4:1.15},troughs={11:0.75,12:0.80}),  # idio 0.15→0.20: 長距離市場はボラ高い
    "AU": dict(base=53000,fx="fx_aud",gdp="gdp_au",geo=None,flt="flt_au",cci=None,stk=None,clt=None,
               idio=0.18,peaks={7:1.60,8:1.70,1:1.30,2:1.25},troughs={5:0.85,6:0.90}),  # 8月2.80→1.70: 月単位で過大だった
    "TH": dict(base=35000,fx="fx_thb",gdp=None,geo="geo_th",flt=None,cci=None,stk=None,clt=None,
               idio=0.20,peaks={4:1.20,10:1.15},troughs={}),
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
