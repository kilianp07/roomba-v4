"""Shared fixtures for roomba_v4 tests."""

import json
from unittest.mock import MagicMock

import pytest


SAMPLE_DISCOVERY_JSON = {
    "hostname": "iRobot-AABBCCDD",
    "robotname": "My Roomba",
    "ip": "192.168.1.42",
    "mac": "AA:BB:CC:DD:EE:FF",
    "sw": "22.29.2+ubuntu-HEAD+build1234",
    "sku": "R770060",
    "nc": 0,
    "proto": "mqtt",
    "cap": {"pose": 1, "ota": 2, "multiPass": 2, "carpetBoost": 1},
}


@pytest.fixture
def sample_discovery_response():
    """Raw JSON bytes as sent by a Roomba v4 robot."""
    return json.dumps(SAMPLE_DISCOVERY_JSON).encode()


@pytest.fixture
def robot_credentials():
    """Dummy robot credentials for testing."""
    return {
        "ip": "10.0.0.99",
        "blid": "DEADBEEF12345678",
        "password": ":1:9999999999:testpass",
    }


@pytest.fixture
def mock_bridge_process():
    """A mocked subprocess.Popen for the bridge binary."""
    proc = MagicMock()
    proc.poll.return_value = None  # process is running
    proc.terminate.return_value = None
    proc.wait.return_value = 0
    return proc
