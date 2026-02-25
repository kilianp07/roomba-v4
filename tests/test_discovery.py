"""Tests for roomba_v4.discovery."""

import socket
import struct
from unittest.mock import MagicMock, patch

from roomba_v4.discovery import _extract_blid, _parse_discovery, discover


class TestDiscover:
    @patch("roomba_v4.discovery._get_subnet_broadcast", return_value=None)
    @patch("roomba_v4.discovery.socket.socket")
    def test_discover_finds_robot(
        self, mock_socket_cls, _mock_bc, sample_discovery_response
    ):
        sock = MagicMock()
        mock_socket_cls.return_value = sock
        sock.recvfrom.side_effect = [
            (sample_discovery_response, ("192.168.1.42", 5678)),
            socket.timeout(),
        ]

        robots = discover(timeout=1.0)
        assert len(robots) == 1
        assert robots[0]["ip"] == "192.168.1.42"
        assert robots[0]["robotname"] == "My Roomba"

    @patch("roomba_v4.discovery._get_subnet_broadcast", return_value=None)
    @patch("roomba_v4.discovery.socket.socket")
    def test_discover_timeout_empty(self, mock_socket_cls, _mock_bc):
        sock = MagicMock()
        mock_socket_cls.return_value = sock
        sock.recvfrom.side_effect = socket.timeout()

        robots = discover(timeout=0.1)
        assert robots == []

    @patch("roomba_v4.discovery._get_subnet_broadcast", return_value=None)
    @patch("roomba_v4.discovery.socket.socket")
    def test_discover_deduplicates(
        self, mock_socket_cls, _mock_bc, sample_discovery_response
    ):
        sock = MagicMock()
        mock_socket_cls.return_value = sock
        sock.recvfrom.side_effect = [
            (sample_discovery_response, ("192.168.1.42", 5678)),
            (sample_discovery_response, ("192.168.1.42", 5678)),
            socket.timeout(),
        ]

        robots = discover(timeout=1.0)
        assert len(robots) == 1

    @patch("roomba_v4.discovery._get_subnet_broadcast", return_value="10.0.0.255")
    @patch("roomba_v4.discovery.socket.socket")
    def test_discover_sends_subnet_broadcast(
        self, mock_socket_cls, _mock_bc, sample_discovery_response
    ):
        sock = MagicMock()
        mock_socket_cls.return_value = sock
        sock.recvfrom.side_effect = [
            (sample_discovery_response, ("10.0.0.42", 5678)),
            socket.timeout(),
        ]

        robots = discover(timeout=1.0)
        # Should send to both subnet broadcast and 255.255.255.255
        calls = [c[0] for c in sock.sendto.call_args_list]
        assert (b"irobotmcs", ("10.0.0.255", 5678)) in calls
        assert (b"irobotmcs", ("255.255.255.255", 5678)) in calls
        assert len(robots) == 1

    @patch("roomba_v4.discovery.socket.socket")
    def test_discover_explicit_target(self, mock_socket_cls, sample_discovery_response):
        sock = MagicMock()
        mock_socket_cls.return_value = sock
        sock.recvfrom.side_effect = [
            (sample_discovery_response, ("192.168.1.180", 5678)),
            socket.timeout(),
        ]

        robots = discover(timeout=1.0, target="192.168.1.180")
        sock.sendto.assert_called_once_with(b"irobotmcs", ("192.168.1.180", 5678))
        assert len(robots) == 1


class TestParseDiscovery:
    def test_parse_discovery_json(self, sample_discovery_response):
        result = _parse_discovery(sample_discovery_response, "192.168.1.42")
        assert result is not None
        assert result["ip"] == "192.168.1.42"
        assert result["hostname"] == "iRobot-AABBCCDD"
        assert result["blid"] == "AABBCCDD"
        assert result["firmware"] == "22.29.2+ubuntu-HEAD+build1234"
        assert result["sku"] == "R770060"
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_parse_discovery_prefixed(self, sample_discovery_response):
        raw_json = sample_discovery_response
        prefix = struct.pack(">H", len(raw_json))
        data = prefix + raw_json

        result = _parse_discovery(data, "10.0.0.1")
        assert result is not None
        assert result["ip"] == "10.0.0.1"

    def test_parse_discovery_invalid(self):
        assert _parse_discovery(b"\x00", "1.2.3.4") is None
        assert _parse_discovery(b"not json at all!!", "1.2.3.4") is None

    def test_parse_discovery_too_short(self):
        assert _parse_discovery(b"x", "1.2.3.4") is None


class TestExtractBlid:
    def test_extract_blid_irobot_prefix(self):
        assert _extract_blid({"hostname": "iRobot-AABBCCDD"}) == "AABBCCDD"

    def test_extract_blid_roomba_prefix(self):
        assert _extract_blid({"hostname": "Roomba-12345678"}) == "12345678"

    def test_extract_blid_no_prefix(self):
        assert _extract_blid({"hostname": "RAWBLID99"}) == "RAWBLID99"

    def test_extract_blid_empty(self):
        assert _extract_blid({}) == ""
