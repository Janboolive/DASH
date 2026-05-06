from http.server import BaseHTTPRequestHandler
import json, urllib.request, os

SUPABASE_URL = "https://tejovvbopyrnmdevpzyy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            url = f"{SUPABASE_URL}/rest/v1/reviews?select=*&order=date.desc&limit=500"
            req = urllib.request.Request(url, headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}"
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, *args): pass
