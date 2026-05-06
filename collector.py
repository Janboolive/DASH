#!/usr/bin/env python3
"""
QazETA Collector → Supabase
Запускай локально когда нужно обновить данные на сайте
"""
import sys, subprocess, json, datetime, os, csv, time, re, io, urllib.request, urllib.parse

def install(p): subprocess.check_call([sys.executable,"-m","pip","install",p,"--quiet"])
try: from google_play_scraper import reviews as gp_reviews, Sort
except ImportError: install("google-play-scraper"); from google_play_scraper import reviews as gp_reviews, Sort
try: import gspread; from google.oauth2.service_account import Credentials
except ImportError: install("gspread"); install("google-auth"); import gspread; from google.oauth2.service_account import Credentials
try: from playwright.sync_api import sync_playwright
except ImportError: install("playwright"); from playwright.sync_api import sync_playwright

# ════════════════════════════════════════
# КОНФИГ
# ════════════════════════════════════════
SUPABASE_URL = "https://tejovvbopyrnmdevpzyy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

GOOGLE_PLAY_ID       = "com.qazeta"
APP_STORE_ID         = "6748705452"
REVIEWS_COUNT        = 500
SERVICE_ACCOUNT_FILE = "service_account.json"
SHEET_NAME           = "Qazeta Reviews"

ASC_KEY_ID    = "43675L2P9J"
ASC_ISSUER_ID = "71813043-0ff1-4ce0-89e9-7e8157179b7f"
ASC_VENDOR    = "93527820"
ASC_KEY_FILE  = "AuthKey_43675L2P9J.p8"

PLAY_BUCKET   = "gs://pubsite_prod_8396492704689147475"
PLAY_PACKAGE  = "com.qazeta"
DAYS_BACK     = 90

# ← ФИКС: полный путь к gsutil на Windows
GSUTIL = r"C:\Users\User\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gsutil.cmd"

# ════════════════════════════════════════
# SUPABASE
# ════════════════════════════════════════
def sb_request(method, path, data=None, params="", schema="public"):
    url = f"{SUPABASE_URL}/rest/v1/{path}?{params}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }
    if schema != "public":
        headers["Accept-Profile"] = schema
        headers["Content-Profile"] = schema
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read()
            return json.loads(text) if text else []
    except urllib.error.HTTPError as e:
        print(f"  Supabase ошибка {e.code}: {e.read().decode()}")
        return None

def sb_rpc(func_name, params=None):
    """Вызов PostgreSQL функции через Supabase RPC"""
    url = f"{SUPABASE_URL}/rest/v1/rpc/{func_name}"
    body = json.dumps(params or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  RPC ошибка: {e}")
        return None

def upsert_installs(rows):
    if not rows: return 0
    total = 0
    for i in range(0, len(rows), 50):
        result = sb_request("POST", "installs", rows[i:i+50])
        if result is not None: total += len(rows[i:i+50])
    return total

def upsert_reviews(rows):
    if not rows: return 0
    total = 0
    for i in range(0, len(rows), 50):
        result = sb_request("POST", "reviews", rows[i:i+50])
        if result is not None: total += len(rows[i:i+50])
    return total

def log_sync(installs_updated, reviews_added, status="ok", error=None):
    sb_request("POST", "sync_log", {
        "status": status,
        "installs_updated": installs_updated,
        "reviews_added": reviews_added,
        "error_message": error
    })

# ════════════════════════════════════════
# КАТЕГОРИЗАЦИЯ
# ════════════════════════════════════════
def categorize(score, text):
    t = text.lower()
    if any(w in t for w in ["вылетает","краш","не работает","ошибка","зависает","баг","crash","bug","error","не сканирует","не получается","не удается","не могу","poor","worst","unable"]) or score<=2:
        return ("Баг","Высокий" if score<=2 else "Средний")
    if any(w in t for w in ["неудобно","непонятно","интерфейс","кнопка","навигация","дизайн","ui","ux"]):
        return ("UX","Средний")
    if any(w in t for w in ["отлично","супер","круто","нравится","хорошо","спасибо","excellent","great","love","perfect","amazing"]) and score>=4:
        return ("Похвала","Низкий")
    if score<=3: return ("Баг","Средний")
    return ("Вопрос","Низкий")

# ════════════════════════════════════════
# ОТЗЫВЫ — GOOGLE PLAY
# ════════════════════════════════════════
def fetch_google_play_reviews():
    print("\n📱 Отзывы Google Play...")
    all_r, BATCH = [], 200
    for lang,country in [("ru","ru"),("en","us"),("kz","kz")]:
        try:
            fetched,ct=0,None
            while fetched<REVIEWS_COUNT:
                result,ct=gp_reviews(GOOGLE_PLAY_ID,lang=lang,country=country,sort=Sort.NEWEST,count=BATCH,continuation_token=ct)
                if not result: break
                all_r.extend(result); fetched+=len(result)
                if not ct: break
                time.sleep(0.5)
        except Exception as e: print(f"  [{lang}] Ошибка: {e}")
    seen,unique=set(),[]
    for r in all_r:
        rid=r.get("reviewId","")
        if rid and rid not in seen: seen.add(rid); unique.append(r)
        elif not rid: unique.append(r)
    rows=[]
    for r in unique:
        score=r.get("score",0); text=r.get("content","") or ""
        date=r.get("at",datetime.datetime.now())
        if isinstance(date,datetime.datetime): date=date.strftime("%Y-%m-%d")
        cat,pri=categorize(score,text)
        rows.append({"date":date,"source":"Google Play","rating":score,"text":text,
                     "author":r.get("userName",""),"version":r.get("reviewCreatedVersion",""),
                     "category":cat,"priority":pri})
    print(f"  ✅ {len(rows)}"); return rows

# ════════════════════════════════════════
# ОТЗЫВЫ — APP STORE
# ════════════════════════════════════════
def _parse_date(raw):
    raw=raw.strip()
    if not raw: return datetime.datetime.now().strftime("%Y-%m-%d")
    if re.match(r"\d{4}-\d{2}-\d{2}",raw): return raw[:10]
    now,low=datetime.datetime.now(),raw.lower()
    if "yesterday" in low: return (now-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    m=re.search(r"(\d+)\s*(day|hour|hr|week|month|min)",low)
    if m:
        n,u=int(m.group(1)),m.group(2)
        if "hour" in u or "hr" in u or "min" in u: return now.strftime("%Y-%m-%d")
        if "day" in u: return (now-datetime.timedelta(days=n)).strftime("%Y-%m-%d")
        if "week" in u: return (now-datetime.timedelta(weeks=n)).strftime("%Y-%m-%d")
        if "month" in u: return (now-datetime.timedelta(days=n*30)).strftime("%Y-%m-%d")
    months={"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    m=re.search(r"(\d{1,2})\s+(\w{3})\s*(\d{4})?",low)
    if m:
        try: return datetime.datetime(int(m.group(3)) if m.group(3) else now.year,months.get(m.group(2)[:3],now.month),int(m.group(1))).strftime("%Y-%m-%d")
        except: pass
    return now.strftime("%Y-%m-%d")

def fetch_app_store_reviews():
    print("\n🍎 Отзывы App Store...")
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_context(locale="en-US",user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36").new_page()
        try:
            page.goto(f"https://apps.apple.com/kz/app/qazeta/id{APP_STORE_ID}?see-all=reviews",wait_until="networkidle",timeout=30000)
            page.wait_for_timeout(3000)
            for i in range(50):
                page.evaluate("window.scrollBy(0,600)"); page.wait_for_timeout(800)
                if page.evaluate("window.innerHeight+window.scrollY>=document.body.scrollHeight-100") and i>5: break
            raw=page.evaluate(r"""()=>{
                const res=[],seen=new Set();
                for(const h3 of document.querySelectorAll('h3')){
                    const title=(h3.textContent||'').trim();
                    if(!title||title==='Ratings & Reviews'||title==='QazETA')continue;
                    if(seen.has(title))continue;seen.add(title);
                    let c=h3.parentElement;
                    for(let i=0;i<5;i++){if(!c.parentElement)break;if(c.parentElement.tagName==='LI'||c.parentElement.tagName==='ARTICLE'){c=c.parentElement;break;}c=c.parentElement;}
                    const s=c.querySelector('[aria-label*="star"],[class*="star"]');let score=0;
                    if(s){const m=(s.getAttribute('aria-label')||'').match(/(\d)/);if(m)score=parseInt(m[1]);}
                    const body=(c.innerText||'').replace(title,'').trim();
                    const lines=body.split('\n').map(l=>l.trim()).filter(l=>l);
                    let author='',rl=[];
                    for(let i=0;i<lines.length;i++){const l=lines[i];
                        if(/^\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(l))continue;
                        if(/\d+\s*(day|hour|hr|week|month|min)/i.test(l))continue;
                        if(/^yesterday$/i.test(l))continue;
                        if(!author&&l.length<30&&!l.includes('.')&&i<3){author=l;continue;}rl.push(l);}
                    const rt=rl.join(' ').trim();if(!rt&&score===0)continue;
                    let date='';const te=c.querySelector('time');if(te)date=te.getAttribute('datetime')||te.textContent||'';
                    res.push({title,body:rt,score,author,date:date.trim()});}return res;}""")
            for r in raw:
                body=r.get("body","")
                for marker in ["Developer Response","developer response","Hello! Thank you"]:
                    idx=body.find(marker)
                    if idx>=0: body=body[:idx].strip()
                title=r.get("title",""); full=f"{title}. {body}".strip(". ") if title and body else (title or body)
                full=" ".join(full.split())
                if len(full)<3: continue
                score=r.get("score",0); cat,pri=categorize(score,full)
                rows.append({"date":_parse_date(r.get("date","")),"source":"App Store","rating":score,
                             "text":full,"author":r.get("author",""),"version":"","category":cat,"priority":pri})
        except Exception as e: print(f"  Ошибка: {e}")
        finally: browser.close()
    print(f"  ✅ {len(rows)}"); return rows

# ════════════════════════════════════════
# СТАТИСТИКА GOOGLE PLAY (с фиксом gsutil)
# ════════════════════════════════════════
def check_gsutil():
    try: return subprocess.run([GSUTIL,"version"],capture_output=True).returncode==0
    except: return False

def fetch_play_stats():
    print("\n🤖 Статистика Google Play...")
    if not check_gsutil(): print("  ⚠️  gsutil не найден"); return {}
    tmp="play_reports_tmp"; os.makedirs(tmp,exist_ok=True)
    today=datetime.date.today()
    months=set((today-datetime.timedelta(days=i)).strftime("%Y%m") for i in range(DAYS_BACK+32))
    result={}
    for yyyymm in sorted(months):
        src=f"{PLAY_BUCKET}/stats/installs/installs_{PLAY_PACKAGE}_{yyyymm}_overview.csv"
        dst=f"{tmp}/installs_{yyyymm}.csv"
        r=subprocess.run([GSUTIL,"cp",src,dst],capture_output=True,text=True)
        if r.returncode!=0 or not os.path.exists(dst): continue
        try:
            with open(dst,encoding="utf-16") as f: content=f.read()
            for row in csv.DictReader(io.StringIO(content)):
                d=(row.get("Date") or "").strip()[:10]
                if not d: continue
                if d not in result: result[d]={"downloads":0,"deleted":0,"active":0,"user_installs":0,"user_uninstalls":0}
                result[d]["downloads"]      +=int(row.get("Daily Device Installs") or 0)
                result[d]["deleted"]        +=int(row.get("Daily Device Uninstalls") or 0)
                result[d]["active"]         +=int(row.get("Active Device Installs") or 0)
                result[d]["user_installs"]  +=int(row.get("Daily User Installs") or 0)
                result[d]["user_uninstalls"]+=int(row.get("Daily User Uninstalls") or 0)
        except Exception as e: print(f"  Ошибка {yyyymm}: {e}")
    print(f"  ✅ {len(result)} дней"); return result

# ════════════════════════════════════════
# СТАТИСТИКА APP STORE CONNECT
# ════════════════════════════════════════
def make_asc_token():
    try: import jwt
    except: install("PyJWT"); install("cryptography"); import jwt
    with open(ASC_KEY_FILE) as f: key=f.read()
    now=int(time.time())
    t=jwt.encode({"iss":ASC_ISSUER_ID,"iat":now,"exp":now+1200,"aud":"appstoreconnect-v1"},
        key,algorithm="ES256",headers={"kid":ASC_KEY_ID,"typ":"JWT"})
    return t if isinstance(t,str) else t.decode()

def fetch_asc_stats():
    print("\n🍎 Статистика App Store Connect...")
    if not os.path.exists(ASC_KEY_FILE): print(f"  ⚠️  {ASC_KEY_FILE} не найден"); return {}
    token=make_asc_token(); today=datetime.date.today(); result={}
    for i in range(1,DAYS_BACK+1):
        ds=(today-datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        params=urllib.parse.urlencode({"filter[frequency]":"DAILY","filter[reportType]":"INSTALLS","filter[reportDate]":ds,"filter[vendorNumber]":ASC_VENDOR})
        req=urllib.request.Request(f"https://api.appstoreconnect.apple.com/v1/salesReports?{params}",headers={"Authorization":f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req,timeout=15) as resp: text=resp.read().decode()
            r={"downloads":0,"deleted":0}
            for row in csv.DictReader(io.StringIO(text),delimiter="\t"):
                ev=(row.get("Event Type") or row.get("Product Type Identifier") or "").strip()
                u=int(row.get("Units") or row.get("Quantity") or 0)
                if ev in ("Install","1"): r["downloads"]+=u
                elif ev in ("Delete","F"): r["deleted"]+=u
            result[ds]=r
        except: result[ds]={"downloads":0,"deleted":0}
        if i%15==0: print(f"    {i}/{DAYS_BACK}...")
    print(f"  ✅ {len(result)} дней"); return result

# ════════════════════════════════════════
# СОХРАНЕНИЕ В SUPABASE
# ════════════════════════════════════════
def save_to_supabase(asc, play, reviews):
    print("\n💾 Сохраняем в Supabase...")
    cutoff=(datetime.date.today()-datetime.timedelta(days=DAYS_BACK)).isoformat()
    dates={d for d in set(list(asc)+list(play)) if d>=cutoff}

    install_rows=[]
    for date in sorted(dates):
        a=asc.get(date,{}); p=play.get(date,{})
        install_rows.append({
            "date":           date,
            "downloads":      a.get("downloads",0)+p.get("downloads",0),
            "asc_downloads":  a.get("downloads",0),
            "play_downloads": p.get("downloads",0),
            "deleted":        a.get("deleted",0)+p.get("deleted",0),
            "asc_deleted":    a.get("deleted",0),
            "play_deleted":   p.get("deleted",0),
            "active":         p.get("active",0),
            "user_installs":  p.get("user_installs",0),
            "user_uninstalls":p.get("user_uninstalls",0),
        })

    n_installs=upsert_installs(install_rows)
    n_reviews=upsert_reviews(reviews)
    print(f"  ✅ Установки: {n_installs} строк")
    print(f"  ✅ Отзывы: {n_reviews} строк")
    log_sync(n_installs, n_reviews)
    return n_installs, n_reviews

# ════════════════════════════════════════
# ЗАПУСК
# ════════════════════════════════════════
def main():
    print("="*55)
    print(f"  QazETA Collector → Supabase")
    print(f"  {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print("="*55)

    reviews  = fetch_google_play_reviews()
    reviews += fetch_app_store_reviews()
    print(f"\n📝 Отзывов: {len(reviews)} | Баг: {sum(1 for r in reviews if r['category']=='Баг')} | Похвала: {sum(1 for r in reviews if r['category']=='Похвала')}")

    asc  = fetch_asc_stats()
    play = fetch_play_stats()
    save_to_supabase(asc, play, reviews)

    print("\n" + "="*55)
    print("  ✅ Готово! Данные доступны на сайте.")
    print("="*55)

if __name__ == "__main__":
    main()

# ════════════════════════════════════════
# CSAT из продовой БД → Supabase
# ════════════════════════════════════════
PROD_DB = {
    "host":     "10.10.1.19",
    "port":     5432,
    "dbname":   "qazeta",
    "user":     "support",
    "password": "Eanav?QmHf#e",
}

def fetch_and_sync_csat():
    print("\n📊 CSAT из продовой БД...")
    try:
        import psycopg2
    except ImportError:
        install("psycopg2-binary")
        import psycopg2

    try:
        conn = psycopg2.connect(**PROD_DB)
        cur  = conn.cursor()
        cur.execute("""
            SELECT csat_score, COUNT(*) AS cnt, platform
            FROM qazeta.csat.csats
            GROUP BY csat_score, platform
            ORDER BY csat_score
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        print(f"  Получено {len(rows)} строк из продовой БД")
    except Exception as e:
        print(f"  ⚠️  Ошибка подключения к продовой БД: {e}")
        return 0

    # Сохраняем в Supabase таблицу csat_stats
    records = [{"platform": r[2] or "unknown", "csat_score": r[0], "count": r[1]} for r in rows]
    total = 0
    for i in range(0, len(records), 50):
        result = sb_request("POST", "csat_stats", records[i:i+50])
        if result is not None:
            total += len(records[i:i+50])

    print(f"  ✅ CSAT синхронизировано: {total} строк")
    return total