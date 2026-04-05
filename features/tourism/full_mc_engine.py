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
    "CN": dict(base=433000,fx="fx_cny",gdp="gdp_cn",geo="geo_cn",flt="flt_cn",cci="cci_cn",stk="stk_cn",clt="clt_cn",
               idio=0.22,peaks={10:2.20,5:1.60,9:1.20},troughs={2:0.45,1:0.55}),
    "TW": dict(base=400000,fx="fx_twd",gdp="gdp_tw",geo="geo_tw",flt="flt_tw",cci=None,stk=None,clt=None,
               idio=0.12,peaks={4:1.20,7:1.15,8:1.10},troughs={2:0.55}),
    "US": dict(base=300000,fx="fx_usd",gdp="gdp_us",geo=None,flt="flt_us",cci="cci_us",stk="stk_us",clt="clt_us",
               idio=0.15,peaks={7:1.45,8:1.50,4:1.15},troughs={11:0.75,12:0.80}),
    "AU": dict(base=53000,fx="fx_aud",gdp="gdp_au",geo=None,flt="flt_au",cci=None,stk=None,clt=None,
               idio=0.18,peaks={7:2.50,8:2.80,1:1.80,2:1.60},troughs={5:0.85,6:0.90}),
    "TH": dict(base=35000,fx="fx_thb",gdp=None,geo="geo_th",flt=None,cci=None,stk=None,clt=None,
               idio=0.20,peaks={4:1.20,10:1.15},troughs={}),
    "HK": dict(base=109000,fx="fx_usd",gdp=None,geo="geo_cn",flt=None,cci=None,stk=None,clt=None,
               idio=0.18,peaks={4:1.15,10:1.20},troughs={2:0.50}),
    "SG": dict(base=45000,fx="fx_usd",gdp=None,geo=None,flt=None,cci=None,stk=None,clt=None,
               idio=0.12,peaks={4:1.15,12:1.20},troughs={}),
}
ALL_COUNTRIES = list(PARAMS.keys())

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
        base_vars = sample_all_vars(500)
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

    # 国別1人1回あたり消費額 (円, 観光庁2024年調査)
    SPENDING_PER_VISITOR = {
        "KR": 72000, "CN": 210000, "TW": 125000, "US": 230000,
        "AU": 280000, "TH": 105000, "HK": 155000, "SG": 165000,
    }

    def spending_forecast(self, month=4, year=2026):
        """国別消費額予測（月次）"""
        months = [f"{year}/{month:02d}"]
        result = self.run(months, "ALL")
        spending = {}
        total_p10 = 0; total_p50 = 0; total_p90 = 0
        for iso2 in ALL_COUNTRIES:
            bc = result["by_country"][iso2]
            spv = self.SPENDING_PER_VISITOR.get(iso2, 120000)
            s_p10 = bc["p10"][0] * spv
            s_p50 = bc["median"][0] * spv
            s_p90 = bc["p90"][0] * spv
            spending[iso2] = {
                "visitors_p50": bc["median"][0],
                "spending_per_visitor": spv,
                "monthly_spending_p10": round(s_p10),
                "monthly_spending_p50": round(s_p50),
                "monthly_spending_p90": round(s_p90),
            }
            total_p10 += s_p10; total_p50 += s_p50; total_p90 += s_p90
        return {
            "month": f"{year}/{month:02d}",
            "by_country": spending,
            "total_p10_oku": round(total_p10 / 1e8, 1),
            "total_p50_oku": round(total_p50 / 1e8, 1),
            "total_p90_oku": round(total_p90 / 1e8, 1),
        }

    def run(self, months, source_country="ALL"):
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
