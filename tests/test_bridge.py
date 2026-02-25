"""Tests for roomba_v4.bridge."""

from unittest.mock import MagicMock, patch

import pytest

from roomba_v4.bridge import Bridge, BridgeError, _find_bridge_binary


class TestFindBridgeBinary:
    @patch("roomba_v4.bridge.shutil.which", return_value="/usr/local/bin/mqtt_bridge")
    def test_find_on_path(self, mock_which):
        assert _find_bridge_binary() == "/usr/local/bin/mqtt_bridge"

    @patch("roomba_v4.bridge.shutil.which", return_value=None)
    @patch("roomba_v4.bridge.Path")
    def test_find_local(self, mock_path_cls, mock_which):
        mock_local = MagicMock()
        mock_local.exists.return_value = True
        mock_local.__str__ = lambda s: "/project/native/mqtt_bridge"
        mock_path_cls.return_value.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = mock_local
        assert _find_bridge_binary() == "/project/native/mqtt_bridge"

    @patch("roomba_v4.bridge.shutil.which", return_value=None)
    @patch("roomba_v4.bridge.Path")
    def test_find_missing(self, mock_path_cls, mock_which):
        mock_local = MagicMock()
        mock_local.exists.return_value = False
        mock_path_cls.return_value.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = mock_local
        assert _find_bridge_binary() is None


class TestBridgeStart:
    @patch("roomba_v4.bridge._find_bridge_binary", return_value=None)
    def test_start_missing_binary(self, _):
        bridge = Bridge()
        with pytest.raises(BridgeError, match="Bridge binary not found"):
            bridge.start()

    @patch("roomba_v4.bridge.Bridge._connect_socket")
    @patch("roomba_v4.bridge.os.path.exists", side_effect=[False, True])
    @patch("roomba_v4.bridge.subprocess.Popen")
    @patch("roomba_v4.bridge._find_bridge_binary", return_value="/bin/mqtt_bridge")
    def test_start_creates_process(
        self, _find, mock_popen, mock_exists, _connect, mock_bridge_process
    ):
        mock_popen.return_value = mock_bridge_process
        bridge = Bridge()
        bridge.start()
        mock_popen.assert_called_once()
        assert bridge._proc is mock_bridge_process


class TestBridgeSend:
    def test_send_command(self):
        bridge = Bridge()
        bridge._sock = MagicMock()
        bridge._sock.recv.side_effect = [
            b"O",
            b"K",
            b" ",
            b"T",
            b"E",
            b"S",
            b"T",
            b"\n",
        ]

        resp = bridge.send("PING")
        bridge._sock.sendall.assert_called_once_with(b"PING\n")
        assert resp == "OK TEST"

    def test_readline_closed(self):
        bridge = Bridge()
        bridge._sock = MagicMock()
        bridge._sock.recv.return_value = b""

        with pytest.raises(BridgeError, match="Bridge connection closed"):
            bridge.send("PING")


class TestBridgeStop:
    def test_stop_sends_disconnect(self):
        bridge = Bridge()
        sock = MagicMock()
        bridge._sock = sock
        # readline for DISCONNECT response
        sock.recv.side_effect = [bytes([b]) for b in b"OK DISCONNECTED\n"]
        proc = MagicMock()
        proc.poll.return_value = None
        bridge._proc = proc

        bridge.stop()
        sock.sendall.assert_called_with(b"DISCONNECT\n")
        proc.terminate.assert_called_once()

    def test_context_manager(self):
        with (
            patch.object(Bridge, "start") as mock_start,
            patch.object(Bridge, "stop") as mock_stop,
        ):
            with Bridge():
                mock_start.assert_called_once()
            mock_stop.assert_called_once()
