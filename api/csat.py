from http.server import BaseHTTPRequestHandler
import json, urllib.request, os

SUPABASE_URL = "https://tejovvbopyrnmdevpzyy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Читаем CSAT из схемы qazeta.csat
            url = f"{SUPABASE_URL}/rest/v1/csats?select=csat_score,platform"
            req = urllib.request.Request(url, headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Accept-Profile": "csat"   # указываем схему
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = json.loads(r.read())

            # Агрегируем по платформе
            by_platform = {}
            total_count = 0
            total_score = 0

            for row in rows:
                score = row.get("csat_score") or 0
                plat  = row.get("platform") or "Неизвестно"
                if plat not in by_platform:
                    by_platform[plat] = {"count": 0, "total": 0}
                by_platform[plat]["count"] += 1
                by_platform[plat]["total"] += score
                total_count += 1
                total_score += score

            platforms = []
            for plat, d in by_platform.items():
                platforms.append({
                    "platform": plat,
                    "count":    d["count"],
                    "avg":      round(d["total"] / d["count"], 2) if d["count"] else 0
                })

            data = {
                "total":    total_count,
                "avg":      round(total_score / total_count, 2) if total_count else 0,
                "platforms": sorted(platforms, key=lambda x: -x["count"])
            }

            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e), "total": 0, "avg": 0, "platforms": []}).encode())

    def log_message(self, *args):
        pass
