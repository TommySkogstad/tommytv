#!/usr/bin/env python3
"""Tester for sparing-api.py — CORS-allowlist, body-grense, atomisk skriving."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
_TEST_TOKEN = "test-token-123"


def start_server(data_file: str, backup_dir: str, api_token: str = _TEST_TOKEN) -> tuple:
    """Start sparing-api på en tilfeldig port. Returnerer (server, port)."""
    os.environ["SPARING_DATA_FILE"] = data_file
    os.environ["SPARING_BACKUP_DIR"] = backup_dir
    os.environ["SPARING_API_TOKEN"] = api_token

    # Last modulen på nytt per test (unngå cachede env-verdier).
    spec = importlib.util.spec_from_file_location("sparing_api_mod", HERE / "sparing-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    server = HTTPServer(("127.0.0.1", 0), mod.Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def post(port: int, path: str, body: bytes, headers: dict | None = None) -> tuple[int, bytes]:
    req = Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlopen(req) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def get(port: int, path: str, headers: dict | None = None) -> tuple[int, dict]:
    req = Request(f"http://127.0.0.1:{port}{path}", method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlopen(req) as r:
            return r.status, dict(r.headers)
    except HTTPError as e:
        return e.code, dict(e.headers)


def options(port: int, origin: str) -> dict:
    req = Request(f"http://127.0.0.1:{port}/save", method="OPTIONS")
    req.add_header("Origin", origin)
    req.add_header("Access-Control-Request-Method", "POST")
    try:
        with urlopen(req) as r:
            return dict(r.headers)
    except HTTPError as e:
        return dict(e.headers)


class CORSAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_file = os.path.join(self.tmp.name, "sparing-data.json")
        with open(data_file, "w") as f:
            json.dump({"accounts": [], "entries": []}, f)
        self.server, self.port = start_server(data_file, os.path.join(self.tmp.name, "backups"))

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()

    def _get_with_origin(self, origin: str) -> dict:
        req = Request(f"http://127.0.0.1:{self.port}/data", method="GET")
        req.add_header("Origin", origin)
        with urlopen(req) as r:
            return dict(r.headers)

    def test_lan_origin_faar_acao_header(self):
        """Kjent LAN-origin skal reflekteres i ACAO-header."""
        headers = self._get_with_origin("http://nuc.tommy.tv:8880")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertEqual(acao, "http://nuc.tommy.tv:8880")

    def test_lan_origin_uten_port_faar_acao_header(self):
        """nuc.tommy.tv uten portnummer skal også tillates."""
        headers = self._get_with_origin("http://nuc.tommy.tv")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertEqual(acao, "http://nuc.tommy.tv")

    def test_localhost_origin_faar_acao_header(self):
        headers = self._get_with_origin("http://localhost:8880")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertEqual(acao, "http://localhost:8880")

    def test_tommytv_no_origin_faar_acao_header(self):
        headers = self._get_with_origin("https://tommytv.no")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertEqual(acao, "https://tommytv.no")

    def test_ukjent_origin_faar_ikke_wildcard(self):
        """Ukjent ekstern origin skal IKKE få Access-Control-Allow-Origin: *."""
        headers = self._get_with_origin("https://evil.example.com")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertNotEqual(acao, "*", "Wildcard CORS er ikke tillatt for ukjent origin")
        self.assertNotEqual(acao, "https://evil.example.com")

    def test_ingen_origin_header_gir_ikke_wildcard(self):
        """Request uten Origin skal ikke gi ACAO: *."""
        req = Request(f"http://127.0.0.1:{self.port}/data", method="GET")
        with urlopen(req) as r:
            headers = dict(r.headers)
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertNotEqual(acao, "*")

    def test_post_save_ukjent_origin_faar_ikke_acao(self):
        """POST /save med ukjent origin skal ikke gi Access-Control-Allow-Origin: *."""
        body = json.dumps({"accounts": [], "entries": []}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/save", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", "https://evil.example.com")
        req.add_header("Authorization", f"Bearer {_TEST_TOKEN}")
        with urlopen(req) as r:
            headers = dict(r.headers)
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertNotEqual(acao, "*")

    def test_options_preflight_lan_origin_tillatt(self):
        """OPTIONS fra LAN-origin skal få CORS-godkjenning."""
        headers = options(self.port, "http://nuc.tommy.tv:8880")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertEqual(acao, "http://nuc.tommy.tv:8880")

    def test_options_preflight_ukjent_origin_blokkert(self):
        """OPTIONS fra ukjent origin skal ikke gi wildcard CORS."""
        headers = options(self.port, "https://evil.example.com")
        acao = headers.get("Access-Control-Allow-Origin", "")
        self.assertNotEqual(acao, "*")
        self.assertNotEqual(acao, "https://evil.example.com")


class BodySizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_file = os.path.join(self.tmp.name, "sparing-data.json")
        with open(data_file, "w") as f:
            json.dump({"accounts": [], "entries": []}, f)
        self.server, self.port = start_server(data_file, os.path.join(self.tmp.name, "backups"))

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()

    def test_stor_body_avvises(self):
        """Body over MAX_BODY (1 MB) skal gi 413 eller 400."""
        stor_body = b"x" * (1_048_576 + 1)
        req = Request(f"http://127.0.0.1:{self.port}/save", data=stor_body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Content-Length", str(len(stor_body)))
        req.add_header("Authorization", f"Bearer {_TEST_TOKEN}")
        try:
            with urlopen(req) as r:
                status = r.status
        except HTTPError as e:
            status = e.code
        self.assertIn(status, (400, 413), f"Forventet 400 eller 413, fikk {status}")

    def test_normal_body_godtas(self):
        """Normal-størrelse body under MAX_BODY skal godtas."""
        body = json.dumps({"accounts": [], "entries": []}).encode()
        code, _ = post(self.port, "/save", body, {"Authorization": f"Bearer {_TEST_TOKEN}"})
        self.assertEqual(code, 200)

    def test_manglende_content_length_avvises(self):
        """POST /save uten Content-Length skal avvises med 400."""
        body = json.dumps({"accounts": [], "entries": []}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/save", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        # urllib legger til Content-Length automatisk — vi overstyrer til tom verdi
        # ved å lage en raw socket-forespørsel. Enklere: bruk http.client direkte.
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        # send() omgår automatisk Content-Length-tillegg
        conn.putrequest("POST", "/save")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Authorization", f"Bearer {_TEST_TOKEN}")
        # Sender IKKE Content-Length — serveren skal avvise dette
        conn.endheaders(body)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "sparing-data.json")
        with open(self.data_file, "w") as f:
            json.dump({"accounts": ["original"], "entries": []}, f)
        self.server, self.port = start_server(
            self.data_file, os.path.join(self.tmp.name, "backups")
        )

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()

    def test_post_save_oppdaterer_fil(self):
        """POST /save skal skrive ny data til filen."""
        ny_data = {"accounts": ["ny_konto"], "entries": [{"beloep": 1000}]}
        body = json.dumps(ny_data).encode()
        code, _ = post(self.port, "/save", body, {"Authorization": f"Bearer {_TEST_TOKEN}"})
        self.assertEqual(code, 200)

        with open(self.data_file) as f:
            lagret = json.load(f)
        self.assertEqual(lagret["accounts"], ["ny_konto"])

    def test_post_ugyldig_json_beholder_gammel_fil(self):
        """POST /save med ugyldig JSON skal ikke overskrive eksisterende data."""
        code, _ = post(self.port, "/save", b"ikke-json{", {"Authorization": f"Bearer {_TEST_TOKEN}"})
        self.assertEqual(code, 400)

        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(data["accounts"], ["original"])


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_file = os.path.join(self.tmp.name, "sparing-data.json")
        with open(data_file, "w") as f:
            json.dump({"accounts": [], "entries": []}, f)
        self.server, self.port = start_server(data_file, os.path.join(self.tmp.name, "backups"))

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()

    def test_health_returnerer_200(self):
        code, _ = get(self.port, "/health")
        self.assertEqual(code, 200)

    def test_ukjent_sti_returnerer_404(self):
        code, _ = get(self.port, "/finnes-ikke")
        self.assertEqual(code, 404)


class BackupRotationTests(unittest.TestCase):
    """Verifiser at backup-rotasjon oppretter filer og beholder maks 50."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "sparing-data.json")
        self.backup_dir = os.path.join(self.tmp.name, "backups")
        with open(self.data_file, "w") as f:
            json.dump({"accounts": [], "entries": []}, f)
        self.server, self.port = start_server(self.data_file, self.backup_dir)

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()

    def _save(self, accounts=None):
        body = json.dumps({"accounts": accounts or [], "entries": []}).encode()
        code, _ = post(self.port, "/save", body, {"Authorization": f"Bearer {_TEST_TOKEN}"})
        self.assertEqual(code, 200)

    def test_backup_opprettes_ved_lagring(self):
        """Første POST /save skal opprette én backup av eksisterende fil."""
        self._save(["konto1"])
        backups = os.listdir(self.backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("sparing-data."))

    def test_maks_50_backups_beholdes(self):
        """Etter 51 lagringer skal kun 50 backups bevares."""
        import time
        for i in range(51):
            self._save([f"konto-{i}"])
            time.sleep(0.01)
        backups = [
            f for f in os.listdir(self.backup_dir)
            if f.startswith("sparing-data.")
        ]
        self.assertLessEqual(len(backups), 50)


if __name__ == "__main__":
    unittest.main()
