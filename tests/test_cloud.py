"""Tests for roomba_v4.cloud."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from roomba_v4.cloud import (
    CloudError,
    discover_endpoints,
    fetch_robot_credentials,
    get_iot_credentials,
    get_robots,
    login_gigya,
    login_irobot,
)


def _mock_urlopen(response_data):
    """Create a mock for urllib.request.urlopen that returns response_data as JSON."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


DISCOVERY_RESPONSE = {
    "gigya": {
        "api_key": "3_test_api_key",
        "datacenter_domain": "us1.gigya.com",
    },
    "deployments": {
        "v005": {
            "httpBase": "https://unauth1.prod.iot.irobotapi.com",
            "httpBaseAuth": "https://auth1.prod.iot.irobotapi.com",
            "mqtt": "mqtt-endpoint.iot.us-east-1.amazonaws.com",
            "svcDeplId": "v005",
        },
        "v011": {
            "httpBase": "https://unauth2.prod.iot.irobotapi.com",
            "httpBaseAuth": "https://auth2.prod.iot.irobotapi.com",
            "mqtt": "mqtt-endpoint.iot.us-east-1.amazonaws.com",
            "svcDeplId": "v011",
        },
    },
}


class TestDiscoverEndpoints:
    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_discover_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(DISCOVERY_RESPONSE)
        result = discover_endpoints()
        assert result["gigya_api_key"] == "3_test_api_key"
        assert result["gigya_base"] == "https://accounts.us1.gigya.com"
        assert result["http_base"] == "https://unauth2.prod.iot.irobotapi.com"
        assert result["mqtt_endpoint"] == "mqtt-endpoint.iot.us-east-1.amazonaws.com"
        assert "v005" in result["deployments"]
        assert "v011" in result["deployments"]
        assert (
            result["deployments"]["v005"]["httpBaseAuth"]
            == "https://auth1.prod.iot.irobotapi.com"
        )

    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_discover_missing_api_key(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"gigya": {}, "deployments": {}})
        with pytest.raises(CloudError, match="No Gigya API key"):
            discover_endpoints()

    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_discover_missing_http_base(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            {
                "gigya": {"api_key": "key", "datacenter_domain": "dc"},
                "deployments": {},
            }
        )
        with pytest.raises(CloudError, match="No httpBase"):
            discover_endpoints()


class TestLoginGigya:
    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_login_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            {
                "errorCode": 0,
                "UID": "uid_123",
                "UIDSignature": "sig_abc",
                "signatureTimestamp": "1234567890",
            }
        )
        result = login_gigya(
            "user@example.com", "pass", "api_key", "https://accounts.us1.gigya.com"
        )
        assert result["uid"] == "uid_123"
        assert result["uid_signature"] == "sig_abc"
        assert result["signature_timestamp"] == "1234567890"

    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_login_bad_credentials(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            {
                "errorCode": 403042,
                "errorMessage": "Invalid LoginID",
            }
        )
        with pytest.raises(CloudError, match="Invalid LoginID"):
            login_gigya(
                "bad@example.com", "wrong", "api_key", "https://accounts.us1.gigya.com"
            )

    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_login_missing_uid(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            {
                "errorCode": 0,
                "UID": "",
                "UIDSignature": "sig",
                "signatureTimestamp": "ts",
            }
        )
        with pytest.raises(CloudError, match="Missing UID"):
            login_gigya(
                "user@example.com", "pass", "api_key", "https://accounts.us1.gigya.com"
            )


class TestLoginIrobot:
    @patch("roomba_v4.cloud.urllib.request.urlopen")
    def test_login_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            {
                "robots": {"AABB": {"password": ":1:0:x", "name": "Roomba"}},
            }
        )
        gigya_data = {"uid": "u", "uid_signature": "s", "signature_timestamp": "t"}
        resp = login_irobot(gigya_data, "https://api.example.com")
        assert "robots" in resp


class TestGetRobots:
    def test_robots_dict_format(self):
        login_resp = {
            "robots": {
                "AABBCCDD": {
                    "password": ":1:9999:secret",
                    "name": "My Roomba",
                    "sku": "R770060",
                    "softwareVer": "22.29.2",
                }
            }
        }
        robots = get_robots(login_resp)
        assert len(robots) == 1
        assert robots[0]["blid"] == "AABBCCDD"
        assert robots[0]["password"] == ":1:9999:secret"
        assert robots[0]["name"] == "My Roomba"
        assert robots[0]["svcDeplId"] == ""
        assert robots[0]["http_base_auth"] == ""

    def test_robots_list_format(self):
        login_resp = {
            "robots": [
                {
                    "blid": "AABBCCDD",
                    "password": ":1:9999:secret",
                    "name": "My Roomba",
                }
            ]
        }
        robots = get_robots(login_resp)
        assert len(robots) == 1
        assert robots[0]["blid"] == "AABBCCDD"

    def test_robots_empty(self):
        robots = get_robots({"robots": {}})
        assert robots == []

    def test_robots_missing_key(self):
        robots = get_robots({})
        assert robots == []

    def test_robots_with_deployments_resolves_http_base_auth(self):
        deployments = {
            "v005": {"httpBaseAuth": "https://auth1.example.com"},
            "v011": {"httpBaseAuth": "https://auth2.example.com"},
        }
        login_resp = {
            "robots": {
                "ROBOT_A": {
                    "password": "pw1",
                    "name": "Robot A",
                    "sku": "X185040",
                    "softwareVer": "9.3.6",
                    "svcDeplId": "v005",
                },
                "ROBOT_B": {
                    "password": "pw2",
                    "name": "Robot B",
                    "sku": "j557840",
                    "softwareVer": "24.29.6",
                    "svcDeplId": "v011",
                },
            }
        }
        robots = get_robots(login_resp, deployments)
        by_blid = {r["blid"]: r for r in robots}
        assert by_blid["ROBOT_A"]["svcDeplId"] == "v005"
        assert by_blid["ROBOT_A"]["http_base_auth"] == "https://auth1.example.com"
        assert by_blid["ROBOT_B"]["svcDeplId"] == "v011"
        assert by_blid["ROBOT_B"]["http_base_auth"] == "https://auth2.example.com"

    def test_robots_unknown_svc_depl_id(self):
        deployments = {"v005": {"httpBaseAuth": "https://auth1.example.com"}}
        login_resp = {
            "robots": {
                "ROBOT_X": {
                    "password": "pw",
                    "svcDeplId": "v099",
                }
            }
        }
        robots = get_robots(login_resp, deployments)
        assert robots[0]["svcDeplId"] == "v099"
        assert robots[0]["http_base_auth"] == ""


class TestFetchRobotCredentials:
    @patch("roomba_v4.cloud.get_iot_credentials")
    @patch("roomba_v4.cloud.get_robots")
    @patch("roomba_v4.cloud.login_irobot")
    @patch("roomba_v4.cloud.login_gigya")
    @patch("roomba_v4.cloud.discover_endpoints")
    def test_full_flow(
        self, mock_discover, mock_gigya, mock_irobot, mock_robots, mock_iot
    ):
        deployments = {"v005": {"httpBaseAuth": "https://auth1.example.com"}}
        mock_discover.return_value = {
            "gigya_api_key": "key",
            "gigya_base": "https://accounts.us1.gigya.com",
            "http_base": "https://api.example.com",
            "mqtt_endpoint": "mqtt.example.com",
            "deployments": deployments,
        }
        mock_gigya.return_value = {
            "uid": "u",
            "uid_signature": "s",
            "signature_timestamp": "t",
        }
        login_resp = {"robots": {"AABB": {"password": ":1:0:x"}}}
        mock_irobot.return_value = login_resp
        mock_robots.return_value = [{"blid": "AABB", "password": ":1:0:x"}]
        mock_iot.return_value = {"mqtt_endpoint": "mqtt.example.com"}

        robots, iot_creds = fetch_robot_credentials("user@example.com", "pass")
        assert len(robots) == 1
        assert iot_creds["mqtt_endpoint"] == "mqtt.example.com"
        mock_discover.assert_called_once()
        mock_gigya.assert_called_once_with(
            "user@example.com",
            "pass",
            "key",
            "https://accounts.us1.gigya.com",
        )
        mock_irobot.assert_called_once_with(
            {"uid": "u", "uid_signature": "s", "signature_timestamp": "t"},
            "https://api.example.com",
        )
        mock_robots.assert_called_once_with(login_resp, deployments)
        mock_iot.assert_called_once_with(login_resp, "mqtt.example.com")


class TestGetIotCredentials:
    def test_extracts_all_fields(self):
        token_payload = json.dumps({"expires_ts": 1700000000}).encode()
        iot_token = base64.b64encode(token_payload).decode()
        login_resp = {
            "iot_token": iot_token,
            "iot_clientid": "client-123",
            "iot_signature": "sig-abc",
            "iot_authorizer_name": "auth-name",
            "credentials": {
                "AccessKeyId": "AKIA...",
                "SecretKey": "secret",
                "SessionToken": "token",
                "Expiration": "2024-01-01T00:00:00Z",
            },
        }
        result = get_iot_credentials(login_resp, "mqtt.example.com")
        assert result["iot_token"] == iot_token
        assert result["iot_clientid"] == "client-123"
        assert result["iot_signature"] == "sig-abc"
        assert result["iot_authorizer_name"] == "auth-name"
        assert result["token_expires_ts"] == 1700000000
        assert result["cognito_credentials"]["AccessKeyId"] == "AKIA..."
        assert result["cognito_credentials"]["SecretKey"] == "secret"
        assert result["cognito_credentials"]["SessionToken"] == "token"
        assert result["mqtt_endpoint"] == "mqtt.example.com"

    def test_b64_decode_extracts_expires_ts(self):
        token_payload = json.dumps({"expires_ts": 9999999999, "other": "data"}).encode()
        iot_token = base64.b64encode(token_payload).decode()
        result = get_iot_credentials({"iot_token": iot_token}, None)
        assert result["token_expires_ts"] == 9999999999

    def test_missing_iot_token(self):
        result = get_iot_credentials({}, "mqtt.example.com")
        assert result["iot_token"] == ""
        assert result["token_expires_ts"] is None
        assert result["mqtt_endpoint"] == "mqtt.example.com"

    def test_invalid_b64_token(self):
        result = get_iot_credentials({"iot_token": "not-valid-b64!!!"}, None)
        assert result["token_expires_ts"] is None

    def test_missing_credentials(self):
        result = get_iot_credentials({}, None)
        assert result["cognito_credentials"]["AccessKeyId"] == ""
        assert result["cognito_credentials"]["SecretKey"] == ""
        assert result["cognito_credentials"]["SessionToken"] == ""
        assert result["cognito_credentials"]["Expiration"] == ""

    def test_connection_tokens_format(self):
        token_payload = json.dumps({"expires_ts": 1800000000}).encode()
        iot_token = base64.b64encode(token_payload).decode()
        login_resp = {
            "connection_tokens": [
                {
                    "client_id": "app-client-001",
                    "iot_token": iot_token,
                    "iot_signature": "sig-from-ct",
                    "iot_authorizer_name": "auth-from-ct",
                    "devices": ["BLID1", "BLID2"],
                }
            ],
            "credentials": {
                "AccessKeyId": "AK",
                "SecretKey": "SK",
                "SessionToken": "ST",
                "Expiration": "2026-01-01T00:00:00Z",
            },
        }
        result = get_iot_credentials(login_resp, "mqtt.example.com")
        assert result["iot_token"] == iot_token
        assert result["iot_clientid"] == "app-client-001"
        assert result["iot_signature"] == "sig-from-ct"
        assert result["iot_authorizer_name"] == "auth-from-ct"
        assert result["token_expires_ts"] == 1800000000
