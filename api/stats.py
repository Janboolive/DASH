from http.server import BaseHTTPRequestHandler
import json, urllib.request, os

SUPABASE_URL = "https://tejovvbopyrnmdevpzyy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def sb_get(table, params="", schema="public"):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if schema != "public":
        headers["Accept-Profile"] = schema
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            installs = sb_get("installs", "select=*&order=date.asc&limit=90")
            sync_log = sb_get("sync_log", "select=*&order=synced_at.desc&limit=1")
            data = {"installs": installs, "last_sync": sync_log[0] if sync_log else None}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, *args): pass
