"""Tests for roomba_v4.robot."""

import json
from unittest.mock import patch, call

import pytest

from roomba_v4.robot import Robot


@pytest.fixture
def mock_bridge():
    with patch("roomba_v4.robot.Bridge") as MockBridge:
        bridge = MockBridge.return_value
        bridge.send.return_value = "OK CONNECTED"
        yield bridge


class TestRobotConnect:
    def test_connect(self, mock_bridge, robot_credentials):
        robot = Robot(**robot_credentials)
        robot.connect()

        calls = mock_bridge.send.call_args_list
        assert calls[0] == call(
            f"CONNECT {robot_credentials['ip']} {robot_credentials['blid']} {robot_credentials['password']}"
        )
        assert calls[1] == call("SUB #")
        assert calls[2] == call(f"SUB $aws/things/{robot_credentials['blid']}/#")
        assert robot._connected is True

    def test_connect_failure(self, mock_bridge, robot_credentials):
        mock_bridge.send.return_value = "ERR connect_failed rc=-2"
        robot = Robot(**robot_credentials)
        with pytest.raises(ConnectionError, match="Failed to connect"):
            robot.connect()


class TestRobotCommands:
    def _make_robot(self, mock_bridge, robot_credentials):
        robot = Robot(**robot_credentials)
        robot.connect()
        mock_bridge.send.reset_mock()
        return robot

    def test_start_vacuum(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.start()

        pub_call = mock_bridge.send.call_args[0][0]
        assert pub_call.startswith("PUB cmd ")
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "start"
        assert payload["params"]["operatingMode"] == 2
        assert payload["initiator"] == "localApp"

    def test_start_mop(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.start(mop=True, wetness=3)

        pub_call = mock_bridge.send.call_args[0][0]
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "start"
        assert payload["params"]["operatingMode"] == 6
        assert payload["params"]["padWetness"] == {"disposable": 3, "reusable": 3}

    def test_stop(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.stop()

        pub_call = mock_bridge.send.call_args[0][0]
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "stop"

    def test_dock(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.dock()

        pub_call = mock_bridge.send.call_args[0][0]
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "dock"

    def test_pause(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.pause()

        pub_call = mock_bridge.send.call_args[0][0]
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "pause"

    def test_resume(self, mock_bridge, robot_credentials):
        robot = self._make_robot(mock_bridge, robot_credentials)
        robot.resume()

        pub_call = mock_bridge.send.call_args[0][0]
        payload = json.loads(pub_call[len("PUB cmd ") :])
        assert payload["command"] == "resume"

    def test_send_not_connected(self, mock_bridge, robot_credentials):
        robot = Robot(**robot_credentials)
        with pytest.raises(ConnectionError, match="Not connected"):
            robot.stop()


class TestRobotMisc:
    def test_context_manager(self, mock_bridge, robot_credentials):
        with Robot(**robot_credentials) as robot:
            assert robot._connected is True
        mock_bridge.stop.assert_called()

    def test_repr(self, robot_credentials):
        robot = Robot(**robot_credentials)
        r = repr(robot)
        assert "10.0.0.99" in r
        assert "DEADBEEF" in r
