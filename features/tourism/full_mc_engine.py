"""
全変数の同時分布からモンテカルロで予測を生成する。
p10=悲観, p50=ベース, p90=楽観 は分布から自然に出る。
"""
import numpy as np
from .variable_distributions import (
    VARIABLE_SPECS, VAR_NAMES, N_VARS, CORRELATION_MATRIX,
)

ELASTICITIES = {
    "fx": {"KR":-1.05,"CN":-0.95,"TW":-1.08,"US":-1.18,"AU":-1.22,"TH":-1.10,"HK":-1.00,"SG":-1.08},
    "gdp": 1.24, "flight": 0.60, "political_coef": -0.008,
    "consumer_confidence": 0.15, "stock_return": 0.08,
    "cultural_interest": 0.12,
}

COUNTRY_VAR_MAP = {
    "KR": {"fx":"fx_krw_jpy","gdp":"gdp_shock_kr","geo":"geo_kr","flight":"flight_kr",
           "conf":"consumer_confidence_kr","stock":"stock_return_kr","culture":"japan_interest_kr"},
    "CN": {"fx":"fx_cny_jpy","gdp":"gdp_shock_cn","geo":"geo_cn","flight":"flight_cn",
           "conf":"consumer_confidence_cn","stock":"stock_return_cn","culture":"japan_interest_cn"},
    "TW": {"fx":"fx_twd_jpy","gdp":"gdp_shock_tw","geo":"geo_tw","flight":"flight_tw"},
    "US": {"fx":"fx_usd_jpy","gdp":"gdp_shock_us","flight":"flight_us",
           "conf":"consumer_confidence_us","stock":"stock_return_us","culture":"japan_interest_us"},
    "AU": {"fx":"fx_aud_jpy","gdp":"gdp_shock_au","flight":"flight_au"},
    "TH": {"fx":"fx_thb_jpy","geo":"geo_th"},
    "HK": {"fx":"fx_usd_jpy","geo":"geo_cn"},
    "SG": {"fx":"fx_usd_jpy"},
}

BASE_VISITORS = {"KR":716000,"CN":433000,"TW":400000,"US":300000,"AU":53000,"TH":35000,"HK":109000,"SG":45000}

CALENDAR = {
    "KR":{7:1.35,8:1.40,4:1.15,3:1.10,2:0.75,9:0.70},
    "CN":{10:2.20,5:1.60,2:0.45,1:0.50,9:1.10},
    "TW":{4:1.20,7:1.15,8:1.10,2:0.55},
    "US":{7:1.45,8:1.50,4:1.15,11:0.75,12:0.80},
    "AU":{7:2.50,8:2.80,1:1.80,2:1.60,5:0.85,6:0.90},
    "TH":{4:1.20,10:1.15},
    "HK":{4:1.15,10:1.20,2:0.50},
    "SG":{4:1.15,12:1.20},
}

IDIO_VOL = {"KR":0.08,"CN":0.22,"TW":0.12,"US":0.15,"AU":0.18,"TH":0.20,"HK":0.18,"SG":0.12}


class FullMCEngine:
    def __init__(self, n_samples=5000):
        self.n_samples = n_samples
        self.var_idx = {v: i for i, v in enumerate(VAR_NAMES)}
        self.L = np.linalg.cholesky(CORRELATION_MATRIX)

    def _sample_all(self):
        z = np.random.standard_normal((self.n_samples, N_VARS))
        return z @ self.L.T

    def _z_to_val(self, z_arr, var_name):
        spec = VARIABLE_SPECS[var_name]
        raw = spec.mu + spec.sigma * z_arr
        return np.clip(raw, spec.min_val, spec.max_val)

    def _get_var(self, all_z, var_map, key):
        vname = var_map.get(key)
        if vname is None or vname not in self.var_idx:
            return np.zeros(self.n_samples)
        return self._z_to_val(all_z[:, self.var_idx[vname]], vname)

    def compute_country(self, country, month, all_z):
        vm = COUNTRY_VAR_MAP.get(country, {})
        base = BASE_VISITORS.get(country, 50000)
        cal = CALENDAR.get(country, {}).get(month, 1.0)

        fx = self._get_var(all_z, vm, "fx")
        gdp = self._get_var(all_z, vm, "gdp")
        geo = self._get_var(all_z, vm, "geo")
        flt = self._get_var(all_z, vm, "flight")
        conf = self._get_var(all_z, vm, "conf")
        stk = self._get_var(all_z, vm, "stock")
        cul = self._get_var(all_z, vm, "culture")

        fx_e = ELASTICITIES["fx"].get(country, -1.12)
        log_impact = (
            -fx_e * np.log1p(fx)
            + ELASTICITIES["gdp"] * np.log1p(gdp)
            + ELASTICITIES["flight"] * np.log1p(flt)
            + ELASTICITIES["political_coef"] * geo
            + ELASTICITIES["consumer_confidence"] * conf / 10
            + ELASTICITIES["stock_return"] * stk
            + ELASTICITIES["cultural_interest"] * cul / 10
        )
        idio = np.random.normal(0, IDIO_VOL.get(country, 0.15) / np.sqrt(12), self.n_samples)
        return np.maximum(base * cal * np.exp(log_impact + idio), 0)

    def run(self, months, source_country="ALL"):
        countries = list(BASE_VISITORS.keys()) if source_country == "ALL" else [source_country]
        n_m = len(months)
        all_samples = np.zeros((n_m, self.n_samples))
        by_country = {c: {"median":[],"p10":[],"p90":[]} for c in countries}

        for mi, ms in enumerate(months):
            year, month = int(ms.split("/")[0]), int(ms.split("/")[1])
            all_z = self._sample_all()
            month_total = np.zeros(self.n_samples)
            for c in countries:
                cs = self.compute_country(c, month, all_z)
                month_total += cs
                by_country[c]["median"].append(int(np.median(cs)))
                by_country[c]["p10"].append(int(np.percentile(cs, 10)))
                by_country[c]["p90"].append(int(np.percentile(cs, 90)))
            all_samples[mi] = month_total

        p10 = np.percentile(all_samples, 10, axis=1).astype(int)
        p25 = np.percentile(all_samples, 25, axis=1).astype(int)
        p50 = np.percentile(all_samples, 50, axis=1).astype(int)
        p75 = np.percentile(all_samples, 75, axis=1).astype(int)
        p90 = np.percentile(all_samples, 90, axis=1).astype(int)
        lower = p50 - p10
        upper = p90 - p50
        asym = upper / np.maximum(lower, 1)

        return {
            "months": months, "source_country": source_country, "n_samples": self.n_samples,
            "median": p50.tolist(), "p10": p10.tolist(), "p25": p25.tolist(),
            "p75": p75.tolist(), "p90": p90.tolist(),
            "by_country": by_country,
            "asymmetry_by_month": asym.tolist(),
            "uncertainty_by_month": ((p90 - p10) / np.maximum(p50, 1) * 100).tolist(),
        }
