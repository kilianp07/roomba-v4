"""mitmproxy addon to capture iRobot auth flow in full detail.

Spike #28: capture the complete authentication chain to find
how the app obtains elevated AWS credentials.

Usage:
    mitmproxy -s tools/mitm_auth_capture.py --ssl-insecure
    mitmproxy -s tools/mitm_auth_capture.py --listen-host 0.0.0.0 --listen-port 8080 --ssl-insecure

    Then configure phone proxy to <this-machine-IP>:8080.
    Open iRobot app, login, navigate to robot, trigger a command.

Output: captures/auth_capture_YYYYMMDD_HHMMSS.jsonl (FULL payloads, no redaction)
"""

import json
import os
from datetime import datetime, timezone

# Capture everything iRobot + AWS related
DOMAINS = (
    ".irobot.com",
    ".irobotapi.com",
    ".gigya.com",
    ".amazonaws.com",
    ".amazoncognito.com",
)

# Auth-related paths we care about most
AUTH_PATHS = (
    "/accounts.login",
    "/accounts.getJWT",
    "/accounts.getAccountInfo",
    "/v2/login",
    "/v1/token",
    "/v1/user",
    "/v1/households",
    "/v1/robots",
    "/v2/robot",
    "/sec_message",
    "/identity",
    "/cognito",
    "/oauth",
    "/sts",
)


class AuthCapture:
    """Capture full auth flow without redaction."""

    def __init__(self):
        os.makedirs("captures", exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = f"captures/auth_capture_{ts}.jsonl"
        self._file = open(self._path, "a", encoding="utf-8")
        self._count = 0
        print(f"[auth-capture] Writing to {self._path}")
        print("[auth-capture] NO REDACTION — sensitive data will be logged")
        print(f"[auth-capture] Domains: {', '.join(DOMAINS)}")

    def _matches(self, host: str) -> bool:
        return any(host.endswith(d) for d in DOMAINS)

    def _is_auth_related(self, path: str) -> bool:
        return any(p in path.lower() for p in AUTH_PATHS)

    def _try_parse(self, raw: bytes):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Try URL-encoded form data
            try:
                from urllib.parse import parse_qs

                decoded = raw.decode("utf-8")
                if "=" in decoded and "&" in decoded:
                    return {
                        k: v[0] if len(v) == 1 else v
                        for k, v in parse_qs(decoded).items()
                    }
            except Exception:
                pass
            # Return hex for binary payloads
            if len(raw) > 0:
                return {"_raw_hex": raw[:512].hex(), "_raw_len": len(raw)}
            return None

    def response(self, flow):
        req = flow.request
        if not self._matches(req.host):
            return

        resp = flow.response
        is_auth = self._is_auth_related(req.path)

        record = {
            "seq": self._count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": req.method,
            "url": req.pretty_url,
            "host": req.host,
            "path": req.path,
            "status_code": resp.status_code,
            "is_auth": is_auth,
            "request_headers": dict(req.headers),
            "request_body": self._try_parse(req.raw_content),
            "response_headers": dict(resp.headers),
            "response_body": self._try_parse(resp.raw_content),
            "duration_ms": (
                round((resp.timestamp_end - req.timestamp_start) * 1000)
                if resp.timestamp_end and req.timestamp_start
                else None
            ),
        }

        self._file.write(json.dumps(record) + "\n")
        self._file.flush()
        self._count += 1

        # Console output
        marker = " ★" if is_auth else ""
        color = "\033[33m" if is_auth else "\033[2m"
        status_color = "\033[32m" if resp.status_code < 400 else "\033[31m"
        rst = "\033[0m"
        dur = f" {record['duration_ms']}ms" if record["duration_ms"] else ""

        # Show response body keys for auth requests
        body_hint = ""
        if is_auth and isinstance(record["response_body"], dict):
            keys = sorted(record["response_body"].keys())[:8]
            body_hint = f" → {{{', '.join(keys)}}}"

        print(
            f"  {color}#{self._count:03d} {req.method:7s}{rst} "
            f"{status_color}{resp.status_code}{rst} "
            f"{req.host}{req.path[:60]}{dur}{body_hint}{marker}"
        )

    def done(self):
        self._file.close()
        print(f"\n[auth-capture] {self._count} requests captured → {self._path}")
        print('[auth-capture] Analyze with: python3 -c "')
        print("  import json")
        print(f"  for line in open('{self._path}'):")
        print("    r = json.loads(line)")
        print("    if r['is_auth']: print(r['method'], r['status_code'], r['path'])")
        print('"')


addons = [AuthCapture()]
