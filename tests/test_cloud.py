"""Tests for roomba_v4.cloud."""

import json
from unittest.mock import MagicMock, patch

import pytest

from roomba_v4.cloud import (
    CloudError,
    discover_endpoints,
    fetch_robot_credentials,
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
        "v011": {"httpBase": "https://unauth2.prod.iot.irobotapi.com"},
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


class TestFetchRobotCredentials:
    @patch("roomba_v4.cloud.get_robots")
    @patch("roomba_v4.cloud.login_irobot")
    @patch("roomba_v4.cloud.login_gigya")
    @patch("roomba_v4.cloud.discover_endpoints")
    def test_full_flow(self, mock_discover, mock_gigya, mock_irobot, mock_robots):
        mock_discover.return_value = {
            "gigya_api_key": "key",
            "gigya_base": "https://accounts.us1.gigya.com",
            "http_base": "https://api.example.com",
        }
        mock_gigya.return_value = {
            "uid": "u",
            "uid_signature": "s",
            "signature_timestamp": "t",
        }
        mock_irobot.return_value = {"robots": {"AABB": {"password": ":1:0:x"}}}
        mock_robots.return_value = [{"blid": "AABB", "password": ":1:0:x"}]

        robots = fetch_robot_credentials("user@example.com", "pass")
        assert len(robots) == 1
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
