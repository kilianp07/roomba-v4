"""SigV4-signed REST client for the iRobot authenticated API.

Each robot belongs to a specific service deployment (``svcDeplId``) whose
``httpBaseAuth`` endpoint must be used for REST calls.  This client
handles the AWS SigV4 signing automatically using the Cognito credentials
returned by ``/v2/login``.
"""

import json
import urllib.error
import urllib.request

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials


class RestError(Exception):
    """Raised on non-2xx responses from the iRobot REST API."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:200]}")


class RestClient:
    """SigV4-signed REST client for a specific robot's deployment endpoint."""

    def __init__(
        self,
        base_url: str,
        cognito_credentials: dict,
        region: str = "us-east-1",
    ):
        """Initialise from a robot's ``http_base_auth`` and Cognito credentials.

        *cognito_credentials* must contain ``AccessKeyId``, ``SecretKey``,
        and ``SessionToken``.
        """
        self.base_url = base_url.rstrip("/")
        self._creds = Credentials(
            cognito_credentials["AccessKeyId"],
            cognito_credentials["SecretKey"],
            cognito_credentials["SessionToken"],
        )
        self._region = region

    def get(self, path: str) -> dict | list | bytes:
        """SigV4-signed GET request.  Returns parsed JSON."""
        return self._request("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict | list | bytes:
        """SigV4-signed POST request.  Returns parsed JSON."""
        return self._request("POST", path, body)

    def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> dict | list | bytes:
        url = f"{self.base_url}{path}"
        data = json.dumps(body) if body is not None else None

        aws_req = AWSRequest(
            method=method,
            url=url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        SigV4Auth(self._creds, "execute-api", self._region).add_auth(aws_req)

        req = urllib.request.Request(
            url,
            data=data.encode() if data else None,
            method=method,
            headers=dict(aws_req.headers),
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return raw
        except urllib.error.HTTPError as e:
            raise RestError(e.code, e.read().decode(errors="replace")) from None
