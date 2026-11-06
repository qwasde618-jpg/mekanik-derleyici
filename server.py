#!/usr/bin/env python3
"""Mekanik Kolaylıklar - derleme sunucusu (Arduino AVR).
POST /compile  {"code": "...", "board": "uno|nano|nano-old"}  ->  {"ok": true, "hex": "...", "log": "..."}
GET  /health
Sadece Python standart kütüphanesi + arduino-cli gerekir."""
import json, os, re, shutil, subprocess, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))
ALLOW = os.environ.get("ALLOW_ORIGIN", "*")          # örn: https://siten.com
CLI = os.environ.get("ARDUINO_CLI", "arduino-cli")
MAX_CODE = 64 * 1024
TIMEOUT = int(os.environ.get("COMPILE_TIMEOUT", "90"))
RATE = int(os.environ.get("RATE_PER_MIN", "12"))
JOBS = threading.BoundedSemaphore(int(os.environ.get("MAX_JOBS", "2")))
BOARDS = {
    "uno": "arduino:avr:uno",
    "nano": "arduino:avr:nano:cpu=atmega328",
    "nano-old": "arduino:avr:nano:cpu=atmega328old",
}
# Dosya sistemini okutmaya yarayan include'ları engelle (mutlak yol, .., sürücü harfi, ters eğik çizgi)
BAD_INC = re.compile(r'#\s*include(?:_next)?\s*[<"]\s*(?:/|[^>"\n]*\.\.|[^>"\n]*\\|[A-Za-z]:)')
hits = {}
lock = threading.Lock()


def rate_ok(ip):
    now = time.time()
    with lock:
        l = [t for t in hits.get(ip, []) if now - t < 60]
        if len(l) >= RATE:
            hits[ip] = l
            return False
        l.append(now)
        hits[ip] = l
        return True


def compile_code(code, board):
    d = tempfile.mkdtemp(prefix="mk")
    try:
        sk = os.path.join(d, "sketch")
        os.makedirs(sk)
        with open(os.path.join(sk, "sketch.ino"), "w", encoding="utf-8") as f:
            f.write(code)
        out = os.path.join(d, "out")
        p = subprocess.run(
            [CLI, "compile", "--fqbn", BOARDS[board], "--output-dir", out, sk],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=d,
            env={**os.environ, "HOME": os.environ.get("HOME", d)},
        )
        log = (p.stdout + p.stderr).replace(d, "")
        hx = os.path.join(out, "sketch.ino.hex")
        if p.returncode != 0 or not os.path.exists(hx):
            return False, "", log
        with open(hx, encoding="ascii") as f:
            return True, f.read(), log
    except subprocess.TimeoutExpired:
        return False, "", "Zaman aşımı: derleme çok uzun sürdü."
    finally:
        shutil.rmtree(d, ignore_errors=True)


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", ALLOW)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/health" else self._send(404, {"ok": False})

    def do_POST(self):
        if self.path != "/compile":
            return self._send(404, {"ok": False})
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if not rate_ok(ip):
            return self._send(429, {"ok": False, "error": "Çok fazla istek. Biraz bekle."})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_CODE + 1024:
                return self._send(413, {"ok": False, "error": "Kod çok büyük."})
            j = json.loads(self.rfile.read(n))
            code, board = str(j.get("code", "")), str(j.get("board", "uno"))
        except Exception:
            return self._send(400, {"ok": False, "error": "Geçersiz istek."})
        if board not in BOARDS:
            return self._send(400, {"ok": False, "error": "Bilinmeyen kart."})
        if not code.strip() or len(code) > MAX_CODE:
            return self._send(400, {"ok": False, "error": "Kod boş ya da çok büyük."})
        if BAD_INC.search(code):
            return self._send(400, {"ok": False, "error": "Bu #include satırına izin verilmiyor."})
        if not JOBS.acquire(timeout=20):
            return self._send(503, {"ok": False, "error": "Sunucu meşgul, tekrar dene."})
        try:
            ok, hx, log = compile_code(code, board)
        finally:
            JOBS.release()
        self._send(200, {"ok": ok, "hex": hx, "log": log[-6000:]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Dinleniyor: :%d" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
