#!/usr/bin/env python3
"""Tiny save API for sparing-data.json. LAN-only."""
import hmac, json, os, re, shutil, tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

DATA_FILE = os.environ.get('SPARING_DATA_FILE', '/data/sparing-data.json')
BACKUP_DIR = os.environ.get('SPARING_BACKUP_DIR', '/data/backups')
MAX_BODY = 1_048_576  # 1 MB
API_TOKEN = os.environ.get('SPARING_API_TOKEN')

# Origins tillatt via CORS. Ukjente origins får ingen ACAO-header.
_CORS_ALLOWLIST = [
    re.compile(r'^https://tommytv\.no$'),
    re.compile(r'^http://localhost(:\d+)?$'),
    re.compile(r'^http://127\.0\.0\.1(:\d+)?$'),
    re.compile(r'^http://nuc\.tommy\.tv(:\d+)?$'),
    re.compile(r'^http://192\.168\.\d+\.\d+(:\d+)?$'),
    re.compile(r'^http://10\.\d+\.\d+\.\d+(:\d+)?$'),
    re.compile(r'^http://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+(:\d+)?$'),
]


def _allowed_origin(origin: str | None) -> str | None:
    """Returner origin hvis den er i allowlisten, ellers None."""
    if not origin:
        return None
    for pattern in _CORS_ALLOWLIST:
        if pattern.match(origin):
            return origin
    return None


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not API_TOKEN:
            return False  # fail-closed: ingen token konfigurert
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return False
        return hmac.compare_digest(auth[7:].strip(), API_TOKEN)

    def do_POST(self):
        if self.path != '/save':
            self._respond(404, 'Not found')
            return
        if not self._authorized():
            self._respond(401, 'Ugyldig eller manglende token')
            return
        cl_header = self.headers.get('Content-Length')
        if cl_header is None:
            self._respond(400, 'Content-Length påkrevd')
            return
        length = int(cl_header)
        if length > MAX_BODY:
            self._respond(413, 'Forespørsel for stor')
            return
        try:
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
            # DATA_FILE er en enkeltfil-bind-mount (mountpoint) i prod, så
            # os.replace over den feiler (EBUSY/EXDEV). Serialiser til temp-fil
            # først (fanger JSON-feil før originalen røres), kopier så innholdet
            # in-place med copyfile. Backup er allerede tatt over.
            data_dir = os.path.dirname(DATA_FILE)
            os.makedirs(data_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                shutil.copyfile(tmp_path, DATA_FILE)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
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
                origin = _allowed_origin(self.headers.get('Origin'))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                if origin:
                    self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(data.encode())
            except Exception as e:
                self._respond(500, str(e))
        else:
            self._respond(404, 'Not found')

    def _respond(self, code, msg):
        origin = _allowed_origin(self.headers.get('Origin'))
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.end_headers()
        self.wfile.write(json.dumps({'status': msg}).encode())

    def do_OPTIONS(self):
        origin = _allowed_origin(self.headers.get('Origin'))
        self.send_response(204)
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Quiet logging

if __name__ == '__main__':
    print('Sparing API listening on :8881')
    HTTPServer(('0.0.0.0', 8881), Handler).serve_forever()
