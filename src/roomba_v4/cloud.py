"""Retrieve robot credentials from the iRobot cloud API.

Uses YOUR OWN iRobot account to fetch YOUR robots' MQTT passwords.
Same API the official iRobot Home app calls — no hacking involved.

Auth flow:
  1. Discover endpoints (get dynamic Gigya API key + iRobot httpBase)
  2. Gigya accounts.login → UID, UIDSignature, signatureTimestamp
  3. iRobot v2/login with Gigya signature → robots dict (with passwords)
"""

import json
import urllib.request
import urllib.parse

DISCOVERY_URL = (
    "https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US"
)
APP_ID = "ANDROID-C7FB240E-DF34-42D7-AE4E-A8C17079A294"


class CloudError(Exception):
    pass


def _post_form(url: str, data: dict) -> dict:
    """POST url-encoded form data, return parsed JSON."""
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    """POST JSON body, return parsed JSON."""
    encoded = json.dumps(body).encode()
    req = urllib.request.Request(url, data=encoded, headers=headers or {})
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_json(url: str) -> dict:
    """GET and return parsed JSON."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def discover_endpoints() -> dict:
    """Fetch iRobot discovery endpoint to get dynamic Gigya key and API base.

    Returns dict with keys: gigya_api_key, gigya_base, http_base.
    """
    try:
        data = _get_json(DISCOVERY_URL)
    except Exception as e:
        raise CloudError(f"Failed to fetch discovery endpoints: {e}")

    gigya = data.get("gigya", {})
    api_key = gigya.get("api_key")
    datacenter = gigya.get("datacenter_domain")

    if not api_key:
        raise CloudError("No Gigya API key in discovery response")
    if not datacenter:
        raise CloudError("No Gigya datacenter in discovery response")

    # Find httpBase from deployments
    deployments = data.get("deployments", {})
    http_base = None
    for ver in sorted(deployments.keys(), reverse=True):
        http_base = deployments[ver].get("httpBase")
        if http_base:
            break

    if not http_base:
        raise CloudError("No httpBase found in discovery deployments")

    return {
        "gigya_api_key": api_key,
        "gigya_base": f"https://accounts.{datacenter}",
        "http_base": http_base,
    }


def login_gigya(email: str, password: str, api_key: str, gigya_base: str) -> dict:
    """Login to Gigya. Returns dict with uid, uid_signature, signature_timestamp."""
    resp = _post_form(
        f"{gigya_base}/accounts.login",
        {
            "apiKey": api_key,
            "loginID": email,
            "password": password,
            "targetEnv": "mobile",
        },
    )
    if resp.get("errorCode", 0) != 0:
        raise CloudError(
            f"Gigya login failed: {resp.get('errorMessage', resp.get('errorDetails', 'unknown'))}"
        )

    uid = resp.get("UID")
    uid_sig = resp.get("UIDSignature")
    sig_ts = resp.get("signatureTimestamp")

    if not uid or not uid_sig or not sig_ts:
        raise CloudError(
            "Missing UID/UIDSignature/signatureTimestamp in Gigya response"
        )

    return {
        "uid": uid,
        "uid_signature": uid_sig,
        "signature_timestamp": sig_ts,
    }


def login_irobot(gigya_data: dict, http_base: str) -> dict:
    """Login to iRobot API with Gigya signature. Returns full response with robots."""
    body = {
        "app_id": APP_ID,
        "assume_robot_ownership": "0",
        "gigya": {
            "signature": gigya_data["uid_signature"],
            "timestamp": gigya_data["signature_timestamp"],
            "uid": gigya_data["uid"],
        },
    }
    try:
        resp = _post_json(f"{http_base}/v2/login", body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise CloudError(f"iRobot login failed: HTTP {e.code} — {err_body}")

    return resp


def get_robots(login_response: dict) -> list[dict]:
    """Extract robot list from iRobot login response.

    Returns list of dicts with keys: blid, password, name, sku, softwareVer.
    """
    robots_data = login_response.get("robots", {})

    robots = []
    if isinstance(robots_data, dict):
        for blid, info in robots_data.items():
            if isinstance(info, dict):
                robots.append(
                    {
                        "blid": blid,
                        "password": info.get("password", ""),
                        "name": info.get("name", ""),
                        "sku": info.get("sku", ""),
                        "softwareVer": info.get("softwareVer", ""),
                    }
                )
    elif isinstance(robots_data, list):
        for info in robots_data:
            robots.append(
                {
                    "blid": info.get("blid", info.get("robotid", "")),
                    "password": info.get("password", ""),
                    "name": info.get("name", ""),
                    "sku": info.get("sku", ""),
                    "softwareVer": info.get("softwareVer", ""),
                }
            )
    return robots


def fetch_robot_credentials(email: str, password: str) -> list[dict]:
    """Full flow: discover → gigya login → irobot login → extract robots.

    Returns list of dicts with keys: blid, password, name, sku, softwareVer.
    """
    endpoints = discover_endpoints()
    gigya_data = login_gigya(
        email,
        password,
        endpoints["gigya_api_key"],
        endpoints["gigya_base"],
    )
    login_resp = login_irobot(gigya_data, endpoints["http_base"])
    return get_robots(login_resp)
