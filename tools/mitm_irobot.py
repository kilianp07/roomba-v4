"""mitmproxy addon to capture iRobot cloud API traffic.

Usage:
    mitmproxy -s tools/mitm_irobot.py --ssl-insecure
    mitmproxy -s tools/mitm_irobot.py --listen-host 0.0.0.0 --listen-port 8080 --ssl-insecure

Captures are written as JSONL to captures/irobot_YYYYMMDD_HHMMSS.jsonl
"""

import json
import os
import re
from datetime import datetime, timezone

# Domains to capture (substrings matched against request host)
DOMAINS = (".irobot.com", ".irobotapi.com", ".gigya.com", ".amazonaws.com")

# Keys whose values get redacted in logged payloads
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "apiKey",
        "api_key",
        "secret",
        "UIDSignature",
        "uid_signature",
        "signature",
        "signatureTimestamp",
        "cookie",
        "authorization",
        "x-amz-security-token",
    }
)

# BLID pattern: 32-char hex or alphanumeric robot identifiers in URL paths
BLID_RE = re.compile(r"/[A-F0-9]{12,32}(?=/|$)", re.IGNORECASE)

# ANSI colour helpers
_RST = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_METHOD_COLORS = {
    "GET": "\033[36m",  # cyan
    "POST": "\033[33m",  # yellow
    "PUT": "\033[35m",  # magenta
    "PATCH": "\033[35m",
    "DELETE": "\033[31m",  # red
    "OPTIONS": "\033[2m",  # dim
}


def _status_color(code: int) -> str:
    if code < 300:
        return "\033[32m"  # green
    if code < 400:
        return "\033[36m"  # cyan
    if code < 500:
        return "\033[33m"  # yellow
    return "\033[31m"  # red


def _redact(obj):
    """Recursively redact sensitive keys in a dict/list structure."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]"
            if k.lower() in {s.lower() for s in SENSITIVE_KEYS}
            else _redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def _normalize_path(path: str) -> str:
    """Replace BLIDs in URL paths with <BLID> for readability."""
    return BLID_RE.sub("/<BLID>", path)


def _try_parse_json(raw: bytes):
    """Attempt to parse bytes as JSON, return None on failure."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _safe_headers(headers) -> dict:
    """Extract headers as a plain dict, redacting sensitive ones."""
    out = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "cookie", "x-amz-security-token"):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


class IRobotCapture:
    """mitmproxy addon that logs iRobot API traffic to JSONL."""

    def __init__(self):
        os.makedirs("captures", exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = f"captures/irobot_{ts}.jsonl"
        self._file = open(self._path, "a", encoding="utf-8")
        self._count = 0

    def _matches(self, host: str) -> bool:
        return any(host.endswith(d) for d in DOMAINS)

    def response(self, flow):
        req = flow.request
        if not self._matches(req.host):
            return

        resp = flow.response

        # Parse bodies
        req_body = _try_parse_json(req.raw_content)
        resp_body = _try_parse_json(resp.raw_content)

        # Build record
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": req.method,
            "url": req.pretty_url,
            "path": req.path,
            "host": req.host,
            "status_code": resp.status_code,
            "request_headers": _safe_headers(req.headers),
            "request_body": _redact(req_body) if req_body is not None else None,
            "response_headers": _safe_headers(resp.headers),
            "response_body": _redact(resp_body) if resp_body is not None else None,
            "duration_ms": (
                round(
                    (flow.response.timestamp_end - flow.request.timestamp_start) * 1000
                )
                if flow.response.timestamp_end and flow.request.timestamp_start
                else None
            ),
        }

        # Write JSONL
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()
        self._count += 1

        # Console output
        self._log_console(record)

    def _log_console(self, record: dict):
        method = record["method"]
        status = record["status_code"]
        path = _normalize_path(record["path"])
        host = record["host"]
        duration = record.get("duration_ms")

        mc = _METHOD_COLORS.get(method, "")
        sc = _status_color(status)
        dur_str = f" {_DIM}{duration}ms{_RST}" if duration else ""

        print(
            f"  {mc}{_BOLD}{method:7s}{_RST} {sc}{status}{_RST} "
            f"{_DIM}{host}{_RST}{path}{dur_str}"
        )

    def done(self):
        self._file.close()
        print(f"\n[iRobot MITM] Captured {self._count} requests → {self._path}")


addons = [IRobotCapture()]
