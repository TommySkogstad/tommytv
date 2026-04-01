#!/usr/bin/env python3
"""Tiny save API for sparing-data.json. LAN-only."""
import json, os, shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

DATA_FILE = '/data/sparing-data.json'
BACKUP_DIR = '/data/backups'

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/save':
            self._respond(404, 'Not found')
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            if 'accounts' not in data or 'entries' not in data:
                self._respond(400, 'Mangler accounts eller entries')
                return
            # Backup current file
            os.makedirs(BACKUP_DIR, exist_ok=True)
            if os.path.exists(DATA_FILE):
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                shutil.copy2(DATA_FILE, f'{BACKUP_DIR}/sparing-data.{ts}.json')
                # Keep only last 50 backups
                backups = sorted(
                    [f for f in os.listdir(BACKUP_DIR) if f.startswith('sparing-data.')],
                    reverse=True
                )
                for old in backups[50:]:
                    os.remove(os.path.join(BACKUP_DIR, old))
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._respond(200, 'Lagret')
        except json.JSONDecodeError:
            self._respond(400, 'Ugyldig JSON')
        except Exception as e:
            self._respond(500, str(e))

    def do_GET(self):
        if self.path == '/health':
            self._respond(200, 'ok')
        elif self.path == '/data':
            try:
                with open(DATA_FILE) as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(data.encode())
            except Exception as e:
                self._respond(500, str(e))
        else:
            self._respond(404, 'Not found')

    def _respond(self, code, msg):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'status': msg}).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Quiet logging

if __name__ == '__main__':
    print('Sparing API listening on :8881')
    HTTPServer(('0.0.0.0', 8881), Handler).serve_forever()
