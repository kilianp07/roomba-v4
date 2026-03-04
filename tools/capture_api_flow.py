#!/usr/bin/env python3
"""Drive the full iRobot API flow through a local proxy for MITM capture.

Usage:
    # Start mitmdump first:
    #   mitmdump -s tools/mitm_irobot.py --listen-host 0.0.0.0 --listen-port 8080 --ssl-insecure
    # Then run:
    python tools/capture_api_flow.py --email USER --password PASS [--proxy localhost:8080]

Replays the same HTTP calls the iRobot Home app makes, through a proxy,
so that mitm_irobot.py captures everything.  Zero external dependencies.
"""

import argparse
import hashlib
import hmac
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

APP_ID = "ANDROID-C7FB240E-DF34-42D7-AE4E-A8C17079A294"
DISCOVERY_URL = (
    "https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US"
)

# Accept any cert when going through mitmproxy
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# AWS Signature Version 4 (stdlib-only)
# ---------------------------------------------------------------------------


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _get_signature_key(
    secret: str, date_stamp: str, region: str, service: str
) -> bytes:
    k_date = _sign(("AWS4" + secret).encode(), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _aws_sigv4_headers(
    method: str,
    url: str,
    *,
    access_key: str,
    secret_key: str,
    session_token: str,
    region: str,
    service: str = "execute-api",
    body: bytes = b"",
) -> dict[str, str]:
    """Compute AWS SigV4 headers for a request."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    path = parsed.path or "/"
    query = parsed.query

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    # Canonical query string (sorted)
    params = urllib.parse.parse_qsl(query, keep_blank_values=True)
    canonical_qs = urllib.parse.urlencode(sorted(params))

    payload_hash = hashlib.sha256(body).hexdigest()

    headers_to_sign = {
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-security-token": session_token,
    }
    signed_headers = ";".join(sorted(headers_to_sign))
    canonical_headers = "".join(
        f"{k}:{v}\n" for k, v in sorted(headers_to_sign.items())
    )

    canonical_request = "\n".join(
        [
            method,
            path,
            canonical_qs,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    signing_key = _get_signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "x-amz-date": amz_date,
        "x-amz-security-token": session_token,
        "x-amz-content-sha256": payload_hash,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _make_opener(proxy: str):
    handler = urllib.request.ProxyHandler(
        {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    )
    return urllib.request.build_opener(
        handler, urllib.request.HTTPSHandler(context=_ctx)
    )


def _request(
    opener, method: str, url: str, *, headers: dict | None = None, body: bytes = b""
):
    """Generic HTTP request, returns parsed JSON or raw bytes on non-JSON."""
    req = urllib.request.Request(url, data=body if body else None, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with opener.open(req, timeout=20) as resp:
        data = resp.read()
        # Always try JSON first, fall back to raw bytes
        try:
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return data


def _get(opener, url: str, headers: dict | None = None):
    return _request(opener, "GET", url, headers=headers)


def _post_form(opener, url: str, data: dict):
    encoded = urllib.parse.urlencode(data).encode()
    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
    return _request(opener, "POST", url, headers=hdrs, body=encoded)


def _post_json(opener, url: str, body: dict, headers: dict | None = None):
    encoded = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    return _request(opener, "POST", url, headers=hdrs, body=encoded)


def _sigv4_get(opener, url: str, creds: dict, region: str):
    """GET with AWS SigV4 signing."""
    sig_headers = _aws_sigv4_headers(
        "GET",
        url,
        access_key=creds["AccessKeyId"],
        secret_key=creds["SecretKey"],
        session_token=creds["SessionToken"],
        region=region,
    )
    return _request(opener, "GET", url, headers=sig_headers)


def _sigv4_post(opener, url: str, body: dict, creds: dict, region: str):
    """POST JSON with AWS SigV4 signing."""
    encoded = json.dumps(body).encode()
    sig_headers = _aws_sigv4_headers(
        "POST",
        url,
        access_key=creds["AccessKeyId"],
        secret_key=creds["SecretKey"],
        session_token=creds["SessionToken"],
        region=region,
        body=encoded,
    )
    sig_headers["Content-Type"] = "application/json"
    return _request(opener, "POST", url, headers=sig_headers, body=encoded)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def run(email: str, password: str, proxy: str):
    opener = _make_opener(proxy)

    # 1. Discover endpoints
    print("[1/5] Discovering endpoints...")
    discovery = _get(opener, DISCOVERY_URL)
    gigya_key = discovery["gigya"]["api_key"]
    datacenter = discovery["gigya"]["datacenter_domain"]
    gigya_base = f"https://accounts.{datacenter}"

    deployments = discovery.get("deployments", {})
    current = discovery.get("current_deployment", sorted(deployments.keys())[-1])
    depl = deployments[current]
    http_base = depl.get("httpBase")
    http_base_auth = depl.get("httpBaseAuth")
    aws_region = depl.get("awsRegion", "us-east-1")
    print(f"    httpBase: {http_base}")
    print(f"    httpBaseAuth: {http_base_auth}")
    print(f"    region: {aws_region}")

    # 2. Gigya login
    print("[2/5] Gigya login...")
    gigya_resp = _post_form(
        opener,
        f"{gigya_base}/accounts.login",
        {
            "apiKey": gigya_key,
            "loginID": email,
            "password": password,
            "targetEnv": "mobile",
        },
    )
    if gigya_resp.get("errorCode", 0) != 0:
        print(f"    FAILED: {gigya_resp.get('errorMessage', gigya_resp)}")
        sys.exit(1)
    uid = gigya_resp["UID"]
    uid_sig = gigya_resp["UIDSignature"]
    sig_ts = gigya_resp["signatureTimestamp"]
    print(f"    UID: {uid[:8]}...")

    # 3. iRobot login
    print("[3/5] iRobot login...")
    try:
        login_resp = _post_json(
            opener,
            f"{http_base}/v2/login",
            {
                "app_id": APP_ID,
                "assume_robot_ownership": "0",
                "gigya": {
                    "signature": uid_sig,
                    "timestamp": sig_ts,
                    "uid": uid,
                },
            },
        )
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"    FAILED: HTTP {e.code} — {err_body[:200]}")
        sys.exit(1)

    robots = login_resp.get("robots", {})
    creds = login_resp.get("credentials", {})
    print(f"    Found {len(robots)} robot(s)")
    print(f"    AWS credentials: {'yes' if creds.get('AccessKeyId') else 'no'}")

    if not creds.get("AccessKeyId"):
        print(
            "    ERROR: No AWS credentials in login response, cannot call auth endpoints"
        )
        sys.exit(1)

    # 4. Probe robot endpoints with SigV4
    print("[4/5] Probing robot endpoints (SigV4)...")
    for blid, info in robots.items():
        name = info.get("name", blid)
        print(f"\n    Robot: {name} ({blid[:8]}...)")

        get_endpoints = [
            f"/v2/robot/{blid}/account",
            f"/v2/robot/{blid}/cloud/config",
            f"/v2/robot/{blid}/missions",
            f"/v2/robot/{blid}/schedule",
            f"/v2/robot/{blid}/pmaps",
            f"/v2/robot/{blid}/regions",
            f"/v2/robot/{blid}/firmware",
            f"/v2/robot/{blid}/features",
            f"/v2/robot/{blid}/preferences",
            f"/v2/robot/{blid}/state",
            f"/v2/robot/{blid}/ota",
            f"/v2/robot/{blid}/timeline",
        ]
        for ep in get_endpoints:
            url = f"{http_base_auth}{ep}"
            try:
                _sigv4_get(opener, url, creds, aws_region)
                print(f"      200 GET {ep}")
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode(errors="replace")[:120]
                except Exception:
                    pass
                print(f"      {e.code} GET {ep}  {body}")
            except Exception as e:
                print(f"      ERR GET {ep}: {e}")

    # 5. Try some additional discovery endpoints
    print("\n[5/5] Additional endpoints...")
    extra = [
        ("GET", f"{http_base_auth}/v2/robots"),
        ("GET", f"{http_base_auth}/v2/user"),
        ("GET", f"{http_base_auth}/v2/user/associations"),
        ("GET", f"{http_base}/v2/robots"),
    ]
    for method, url in extra:
        try:
            if method == "GET":
                _sigv4_get(opener, url, creds, aws_region)
            print(f"    200 {method} {url.split('.com')[1]}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode(errors="replace")[:120]
            except Exception:
                pass
            print(f"    {e.code} {method} {url.split('.com')[1]}  {body}")
        except Exception as e:
            print(f"    ERR {method} {url.split('.com')[1]}: {e}")

    print("\nDone! Check captures/ for the JSONL output.")


def main():
    parser = argparse.ArgumentParser(
        description="Drive iRobot API flow through MITM proxy"
    )
    parser.add_argument("--email", required=True, help="iRobot account email")
    parser.add_argument("--password", required=True, help="iRobot account password")
    parser.add_argument(
        "--proxy",
        default="localhost:8080",
        help="Proxy host:port (default: localhost:8080)",
    )
    args = parser.parse_args()
    run(args.email, args.password, args.proxy)


if __name__ == "__main__":
    main()
