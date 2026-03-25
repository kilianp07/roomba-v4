"""Tests for roomba_v4.rest."""

import json
from unittest.mock import MagicMock, patch

import pytest

from roomba_v4.rest import RestClient, RestError

FAKE_CREDS = {
    "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "SecretKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "SessionToken": "FwoGZXIvYXdzEBAaDH...",
}


def _mock_urlopen(body, status=200):
    mock_resp = MagicMock()
    if isinstance(body, dict | list):
        mock_resp.read.return_value = json.dumps(body).encode()
    else:
        mock_resp.read.return_value = body
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestRestClient:
    def test_get_sends_sigv4_headers(self):
        client = RestClient("https://auth1.example.com", FAKE_CREDS)
        with patch("roomba_v4.rest.urllib.request.urlopen") as mock:
            mock.return_value = _mock_urlopen({"ok": True})
            result = client.get("/v1/user/automations")

        assert result == {"ok": True}
        req = mock.call_args[0][0]
        assert req.method == "GET"
        assert "auth1.example.com" in req.full_url
        assert "AWS4-HMAC-SHA256" in req.get_header("Authorization")
        assert req.get_header("X-amz-security-token") is not None

    def test_post_sends_body(self):
        client = RestClient("https://auth1.example.com", FAKE_CREDS)
        with patch("roomba_v4.rest.urllib.request.urlopen") as mock:
            mock.return_value = _mock_urlopen({"status": "ok"})
            result = client.post("/v1/robots/BLID/sec_message", {"command": "find"})

        assert result == {"status": "ok"}
        req = mock.call_args[0][0]
        assert req.method == "POST"
        assert b"find" in req.data

    def test_get_returns_list(self):
        client = RestClient("https://auth1.example.com", FAKE_CREDS)
        with patch("roomba_v4.rest.urllib.request.urlopen") as mock:
            mock.return_value = _mock_urlopen([{"id": 1}])
            result = client.get("/v1/items")
        assert result == [{"id": 1}]

    def test_get_returns_raw_bytes_on_non_json(self):
        client = RestClient("https://auth1.example.com", FAKE_CREDS)
        with patch("roomba_v4.rest.urllib.request.urlopen") as mock:
            mock.return_value = _mock_urlopen(b"\x00\x01binary")
            result = client.get("/v1/binary")
        assert result == b"\x00\x01binary"

    def test_http_error_raises_rest_error(self):
        import urllib.error

        client = RestClient("https://auth1.example.com", FAKE_CREDS)
        with patch("roomba_v4.rest.urllib.request.urlopen") as mock:
            mock.side_effect = urllib.error.HTTPError(
                "https://auth1.example.com/v1/bad",
                403,
                "Forbidden",
                {},
                MagicMock(read=lambda: b'{"message":"Not authorized"}'),
            )
            with pytest.raises(RestError) as exc_info:
                client.get("/v1/bad")
            assert exc_info.value.status == 403
            assert "Not authorized" in exc_info.value.body

    def test_trailing_slash_stripped_from_base_url(self):
        client = RestClient("https://auth1.example.com/", FAKE_CREDS)
        assert client.base_url == "https://auth1.example.com"
