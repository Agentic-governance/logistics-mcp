"""全チェック実行+失敗時即修正。全PASS→exit(0), 失敗→exit(1)"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/supply-chain-risk'))
import subprocess, sqlite3, json, numpy as np
from datetime import datetime

os.chdir(os.path.expanduser('~/supply-chain-risk'))
failures = []

def check(name, condition, fix_fn=None):
    if condition:
        print("  ✅ " + name)
    else:
        print("  ❌ " + name)
        failures.append(name)
        if fix_fn:
            print("     → 修正中...")
            try: fix_fn(); print("     → 修正完了")
            except Exception as e: print("     → 修正失敗: " + str(e))

# CHECK-1: DB品質
print("\n[CHECK-1] DB品質")
conn = sqlite3.connect('data/tourism_stats.db')
ji_cnt = conn.execute("SELECT COUNT(*) FROM japan_inbound WHERE arrivals > 1000").fetchone()[0]
ji_ctrs = conn.execute("SELECT COUNT(DISTINCT source_country) FROM japan_inbound").fetchone()[0]
check("japan_inbound 1000行以上", ji_cnt >= 1000)
check("japan_inbound 15カ国以上", ji_ctrs >= 15)

try:
    mi_total = conn.execute("SELECT COUNT(*) FROM monthly_indicators").fetchone()[0]
    fx_cnt = conn.execute("SELECT COUNT(*) FROM monthly_indicators WHERE fx_rate_jpy IS NOT NULL").fetchone()[0]
    stock_cnt = conn.execute("SELECT COUNT(*) FROM monthly_indicators WHERE stock_return IS NOT NULL").fetchone()[0]
except: mi_total=0; fx_cnt=0; stock_cnt=0

def fix_stock():
    subprocess.run([sys.executable, '-c', '''
import sqlite3, asyncio
from datetime import datetime
async def f():
    try:
        import yfinance as yf
        T={"KR":"^KS11","CN":"000300.SS","US":"^GSPC","AU":"^AXJO","TW":"^TWII","DE":"^GDAXI","GB":"^FTSE"}
        conn=sqlite3.connect("data/tourism_stats.db")
        for c,tk in T.items():
            try:
                h=yf.download(tk,start="2019-01-01",interval="1mo",progress=False,auto_adjust=True)
                prev=None
                for dt,row in h.iterrows():
                    cl=float(row["Close"].iloc[0] if hasattr(row["Close"],"iloc") else row["Close"])
                    ret=(cl-prev)/prev if prev and prev>0 else None
                    conn.execute("INSERT INTO monthly_indicators(source_country,year,month,stock_return,retrieved_at)VALUES(?,?,?,?,?) ON CONFLICT(source_country,year,month) DO UPDATE SET stock_return=excluded.stock_return",(c,dt.year,dt.month,ret,datetime.now().isoformat()))
                    prev=cl
                conn.commit()
            except: pass
        conn.close()
    except: pass
asyncio.run(f())
'''], timeout=300)

check("monthly_indicators FX 800行以上", fx_cnt >= 800)
check("monthly_indicators 株価 70行以上", stock_cnt >= 70, fix_fn=fix_stock)

try:
    gv_cnt = conn.execute("SELECT COUNT(*) FROM gravity_variables_v2").fetchone()[0]
    gv_tmi = conn.execute("SELECT COUNT(*) FROM gravity_variables_v2 WHERE travel_momentum_index IS NOT NULL").fetchone()[0]
except: gv_cnt=0; gv_tmi=0
check("gravity_variables_v2 80行以上", gv_cnt >= 80)
check("gravity_variables_v2 TMI全行", gv_tmi == gv_cnt and gv_cnt > 0)
conn.close()

# CHECK-2: MCエンジン
print("\n[CHECK-2] MCエンジン")
try:
    from features.tourism.full_mc_engine import FullMCEngine
    engine = FullMCEngine(n_samples=500)
    r = engine.run([f"2026/{m:02d}" for m in range(4,10)], "ALL")
    asym = np.array(r.get("asymmetry_by_month",[1]*6))
    cn_w = (r["by_country"]["CN"]["p90"][0]-r["by_country"]["CN"]["p10"][0])/max(r["by_country"]["CN"]["median"][0],1)
    kr_w = (r["by_country"]["KR"]["p90"][0]-r["by_country"]["KR"]["p10"][0])/max(r["by_country"]["KR"]["median"][0],1)
    print(f"  p10/p50/p90: {r['p10'][0]:,}/{r['median'][0]:,}/{r['p90'][0]:,}")
    print(f"  CN帯幅:{cn_w:.3f} KR帯幅:{kr_w:.3f}")
    check("MC 非対称性", np.any(np.abs(asym-1)>0.05))
    check("MC CN帯幅>KR帯幅", cn_w > kr_w)
except Exception as e:
    check("MCエンジン動作", False); print("     " + str(e))

# CHECK-3: GPモデル
print("\n[CHECK-3] GPモデル")
gp_dir = 'models/tourism'
gp_files = [f for f in os.listdir(gp_dir) if f.startswith('gp_') and f.endswith('.pt')] if os.path.exists(gp_dir) else []
check("GP 5カ国以上学習済み", len(gp_files) >= 5)

# CHECK-4: API
print("\n[CHECK-4] API")
import urllib.request
def api_get(path, t=30):
    try:
        with urllib.request.urlopen("http://localhost:8000"+path, timeout=t) as r:
            return json.loads(r.read())
    except: return {"_error":True}

health = api_get('/docs', 5)
if '_error' in health:
    print("  サーバー起動中...")
    subprocess.Popen(['.venv311/bin/uvicorn','api.main:app','--host','0.0.0.0','--port','8000'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    import time; time.sleep(6)

ts = api_get('/api/v1/tourism/three-scenarios?source_country=ALL', 60)
if '_error' not in ts:
    data = ts.get('data', ts)
    scens = data.get('scenarios', {})
    check("three-scenarios 3シナリオ", all(k in scens for k in ['base','optimistic','pessimistic']))
    base = scens.get('base',{}).get('median',[])
    opt = scens.get('optimistic',{}).get('median',[])
    pes = scens.get('pessimistic',{}).get('median',[])
    if base and opt and pes:
        mid = len(base)//2
        check("悲観<ベース<楽観", pes[mid]<base[mid]<opt[mid])
    by_c = data.get('by_country',{})
    if 'CN' in by_c and 'KR' in by_c:
        cn_m=by_c['CN'].get('median',[0])[0]; cn_lo=by_c['CN'].get('p10',[0])[0]; cn_hi=by_c['CN'].get('p90',[0])[0]
        kr_m=by_c['KR'].get('median',[0])[0]; kr_lo=by_c['KR'].get('p10',[0])[0]; kr_hi=by_c['KR'].get('p90',[0])[0]
        if cn_m>0 and kr_m>0:
            check("API CN帯幅>KR帯幅", (cn_hi-cn_lo)/cn_m > (kr_hi-kr_lo)/kr_m)
else:
    check("three-scenarios API", False)

import time
t0=time.time()
mr = api_get('/api/v1/tourism/market-ranking', 25)
check(f"market-ranking 25秒以内({time.time()-t0:.1f}s)", '_error' not in mr)

# CHECK-5: ダッシュボード
print("\n[CHECK-5] ダッシュボード")
try:
    with open('dashboard/inbound.html') as f: html = f.read()
    check("inbound.html three-scenarios API", 'three-scenarios' in html)
    check("inbound.html フォールバック", 'STATIC' in html or 'fallback' in html.lower())
    check("inbound.html 世界地図", 'worldMap' in html or 'world-atlas' in html)
    check("inbound.html 日本地図", 'japanMap' in html or 'japan.topojson' in html)
    check("inbound.html Chart.js", 'Chart(' in html or 'chart.umd' in html)
except: check("inbound.html存在", False)

# CHECK-6: PPML
print("\n[CHECK-6] PPML")
try:
    from features.tourism.gravity_model import TourismGravityModel
    m = TourismGravityModel(); r2 = getattr(m,'r_squared',None) or getattr(m,'pseudo_r2',None)
    if r2 is None:
        result = m.fit(); r2 = getattr(result,'pseudo_r2',getattr(result,'r_squared',0))
    check(f"PPML R²>0.85 (={r2})", r2 is not None and r2 > 0.85)
except Exception as e: check("PPMLモデル", False); print("     "+str(e))

# 最終レポート
print("\n" + "="*55)
print(f"完了: {datetime.now().strftime('%H:%M:%S')}, 失敗: {len(failures)}件")
if failures:
    for f in failures: print("  ❌ " + f)
    sys.exit(1)
else:
    print("✅ 全チェック PASS")
    sys.exit(0)
