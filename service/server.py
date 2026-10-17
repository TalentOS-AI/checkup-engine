#!/usr/bin/env python3
"""Localhost-only async checkup job server for the Azure gateway VM.

Listen on 127.0.0.1 only. The Cloudflare Worker authenticates with a shared
service token; visitors poll with a short-lived HMAC job token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Allow `python3 service/server.py` from the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from checkup_engine import llm as llm_mod  # noqa: E402
from checkup_engine.pipeline import CheckupError, run_checkup  # noqa: E402
from checkup_engine.render import render_html  # noqa: E402
from checkup_engine.schema import validate  # noqa: E402
from checkup_engine.ssrf import BlockedURLError, normalize_url  # noqa: E402
from service.errors import friendly  # noqa: E402

HOST = os.environ.get("CHECKUP_BIND", "127.0.0.1")
PORT = int(os.environ.get("CHECKUP_PORT", "8790"))
DATA_DIR = Path(os.environ.get("CHECKUP_DATA_DIR", "/var/lib/checkup-engine"))
SERVICE_TOKEN = os.environ.get("CHECKUP_SERVICE_TOKEN", "")
JOB_HMAC_SECRET = (os.environ.get("CHECKUP_JOB_HMAC") or SERVICE_TOKEN or "dev-only").encode()
DAILY_BUDGET_USD = float(os.environ.get("CHECKUP_DAILY_BUDGET_USD", "1.0"))
CACHE_TTL_S = int(os.environ.get("CHECKUP_CACHE_TTL_S", str(24 * 3600)))
JOB_TTL_S = int(os.environ.get("CHECKUP_JOB_TTL_S", "3600"))
MAX_WORKERS = int(os.environ.get("CHECKUP_WORKERS", "2"))
DEADLINE_S = int(os.environ.get("CHECKUP_DEADLINE_S", "75"))

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_queue: list[str] = []
_spend_day = ""
_spend_usd = 0.0
_cache: dict[str, tuple[float, dict]] = {}  # domain|lang -> (exp, report)


def _beijing_day() -> str:
    # UTC+8 calendar day string; budget resets 08:00 Beijing = 00:00 UTC.
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not SERVICE_TOKEN:
        return False
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], SERVICE_TOKEN):
        return True
    return hmac.compare_digest(handler.headers.get("X-Checkup-Token", ""), SERVICE_TOKEN)


def _sign_job(job_id: str, exp: int) -> str:
    msg = f"{job_id}|{exp}".encode()
    return hmac.new(JOB_HMAC_SECRET, msg, hashlib.sha256).hexdigest()


def _verify_job(job_id: str, token: str, exp_s: str | None) -> bool:
    try:
        exp = int(exp_s or "0")
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(_sign_job(job_id, exp), token or "")


def _domain_key(url: str, lang: str) -> str:
    host = urlparse(url).hostname or url
    return f"{host.lower()}|{lang}"


def _persist(job: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{job['id']}.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    if job.get("report"):
        (DATA_DIR / f"{job['id']}.html").write_text(render_html(job["report"]), encoding="utf-8")


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _run_one(job_id: str) -> None:
    global _spend_day, _spend_usd
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["updated_at"] = int(time.time())
        url, lang = job["url"], job["lang"]
        key = _domain_key(url, lang)
        cached = _cache.get(key)
        if cached and cached[0] > time.time():
            job["status"] = "done"
            job["report"] = cached[1]
            job["cached"] = True
            _persist(job)
            return
        day = _beijing_day()
        if _spend_day != day:
            _spend_day, _spend_usd = day, 0.0
        if _spend_usd >= DAILY_BUDGET_USD:
            job["status"] = "error"
            job["error"] = friendly("budget", lang)
            _persist(job)
            return

    client = None
    try:
        client = llm_mod.OpenAICompatClient()
    except llm_mod.LLMError:
        client = None

    try:
        report = run_checkup(url, lang=lang, llm=client,
                             progress=lambda stage, msg: _progress(job_id, stage, msg))
        errs = validate(report)
        if errs:
            raise CheckupError("report schema invalid")
        with _lock:
            job = _jobs[job_id]
            job["status"] = "done"
            job["report"] = report
            job["stage"] = "done"
            job["updated_at"] = int(time.time())
            cost = float((report.get("cost") or {}).get("est_cost_usd") or 0)
            _spend_usd += cost
            job["spend_today_usd"] = round(_spend_usd, 5)
            _cache[key] = (time.time() + CACHE_TTL_S, report)
            _persist(job)
    except (BlockedURLError, CheckupError) as exc:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "error"
            job["error"] = friendly(exc, lang)
            job["updated_at"] = int(time.time())
            _persist(job)
    except Exception as exc:  # noqa: BLE001
        # Log the real error locally; never put it in the visitor-facing payload.
        sys.stderr.write(f"[checkup] job {job_id} failed: {exc}\n{traceback.format_exc()}\n")
        with _lock:
            job = _jobs[job_id]
            job["status"] = "error"
            job["error"] = friendly("generic", lang)
            job["updated_at"] = int(time.time())
            _persist(job)


def _progress(job_id: str, stage: str, msg: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job["stage"] = stage
            job["stage_msg"] = msg[:200]
            job["updated_at"] = int(time.time())


def _worker_loop() -> None:
    while True:
        job_id = None
        with _lock:
            if _queue:
                job_id = _queue.pop(0)
        if job_id is None:
            time.sleep(0.2)
            continue
        _run_one(job_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "checkup-engine/0.1"

    def log_message(self, fmt, *args):  # quieter default
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 64_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path in ("/health", "/checkup/health"):
            return self._json(200, {"ok": True, "spend_today_usd": round(_spend_usd, 5),
                                    "day": _beijing_day()})
        parts = u.path.strip("/").split("/")
        # /checkup/jobs/{id}  or  /jobs/{id}
        if len(parts) >= 2 and parts[-2] in ("jobs",) and parts[-1]:
            job_id = parts[-1]
            qs = parse_qs(u.query)
            token = (qs.get("t") or [""])[0]
            exp = (qs.get("exp") or [""])[0]
            # Service token OR visitor job token.
            if not (_auth_ok(self) or _verify_job(job_id, token, exp)):
                return self._json(401, {"error": friendly("generic", "en")})
            with _lock:
                job = _jobs.get(job_id)
            if not job:
                # Try disk
                path = DATA_DIR / f"{job_id}.json"
                if path.is_file():
                    job = json.loads(path.read_text(encoding="utf-8"))
                else:
                    return self._json(404, {"error": friendly("generic", "en")})
            return self._json(200, _public_job(job))
        if len(parts) >= 2 and parts[-2] in ("report",) and parts[-1]:
            job_id = parts[-1]
            qs = parse_qs(u.query)
            if not (_auth_ok(self) or _verify_job(job_id, (qs.get("t") or [""])[0], (qs.get("exp") or [""])[0])):
                return self._json(401, {"error": friendly("generic", "en")})
            html_path = DATA_DIR / f"{job_id}.html"
            if not html_path.is_file():
                return self._json(404, {"error": friendly("generic", "en")})
            body = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"error": friendly("generic", "en")})

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path not in ("/checkup/jobs", "/jobs"):
            return self._json(404, {"error": friendly("generic", "en")})
        if not _auth_ok(self):
            return self._json(401, {"error": friendly("generic", "en")})
        body = self._read_json()
        lang = "en" if body.get("lang") == "en" else "zh"
        try:
            url = normalize_url(str(body.get("url") or ""))
        except BlockedURLError as exc:
            return self._json(400, {"error": friendly(exc, lang)})
        except Exception:
            return self._json(400, {"error": friendly("invalid", lang)})
        global _spend_day, _spend_usd
        with _lock:
            day = _beijing_day()
            if _spend_day != day:
                _spend_day, _spend_usd = day, 0.0
            if _spend_usd >= DAILY_BUDGET_USD:
                return self._json(429, {"error": friendly("budget", lang)})
            job_id = uuid.uuid4().hex
            exp = int(time.time()) + JOB_TTL_S
            token = _sign_job(job_id, exp)
            job = {"id": job_id, "url": url, "lang": lang, "status": "queued",
                   "stage": "queued", "created_at": int(time.time()), "updated_at": int(time.time()),
                   "exp": exp, "report": None, "error": None, "cached": False}
            _jobs[job_id] = job
            _queue.append(job_id)
            _persist(job)
        return self._json(202, {"jobId": job_id, "token": token, "exp": exp,
                                "pollPath": f"/checkup/jobs/{job_id}?t={token}&exp={exp}"})


def _public_job(job: dict) -> dict:
    out = {"jobId": job["id"], "status": job["status"], "stage": job.get("stage"),
           "url": job["url"], "lang": job["lang"], "cached": bool(job.get("cached")),
           "created_at": job.get("created_at"), "updated_at": job.get("updated_at")}
    if job["status"] == "done" and job.get("report"):
        r = job["report"]
        out["report"] = {
            "overall": r["scores"]["overall"],
            "summary": r.get("summary"),
            "business_summary": r.get("business_summary"),
            "scores": r["scores"],
            "recommendations": r["recommendations"],
            "cost": r.get("cost"),
            "timing": r.get("timing"),
            "disclaimer": r.get("disclaimer"),
            "mode": r.get("mode"),
            "generated_at": r.get("generated_at"),
            "final_url": r.get("final_url"),
        }
        out["reportHtmlPath"] = f"/checkup/report/{job['id']}?t=TOKEN&exp=EXP"
    if job["status"] == "error":
        out["error"] = job.get("error") or friendly("generic", job.get("lang", "zh"))
    return out


def main() -> None:
    global SERVICE_TOKEN, JOB_HMAC_SECRET
    for env_path in (os.environ.get("CHECKUP_ENV_FILE"),
                     "/etc/checkup-engine/env",
                     str(Path("/workspace/secrets/checkup-demo.env"))):
        if env_path:
            _load_env_file(env_path)
    # Reload after env file may have set the token.
    SERVICE_TOKEN = os.environ.get("CHECKUP_SERVICE_TOKEN", "") or SERVICE_TOKEN
    JOB_HMAC_SECRET = (os.environ.get("CHECKUP_JOB_HMAC") or SERVICE_TOKEN or "dev-only").encode()
    if not SERVICE_TOKEN:
        # Dev fallback: generate an ephemeral token and print it once (local only).
        tok = secrets.token_urlsafe(24)
        os.environ["CHECKUP_SERVICE_TOKEN"] = tok
        SERVICE_TOKEN = tok
        JOB_HMAC_SECRET = tok.encode()
        sys.stderr.write(f"[checkup] CHECKUP_SERVICE_TOKEN not set; generated ephemeral: {tok}\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(MAX_WORKERS):
        threading.Thread(target=_worker_loop, daemon=True).start()
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"refusing to bind to {HOST!r}; must be localhost only")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"[checkup] listening on http://{HOST}:{PORT} data={DATA_DIR}\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
