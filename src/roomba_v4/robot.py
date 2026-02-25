"""High-level Roomba v4 robot control."""

import json
import time

from .bridge import Bridge


class Robot:
    """Control a Roomba v4 robot via the native MQTT bridge."""

    def __init__(self, ip: str, blid: str, password: str):
        self.ip = ip
        self.blid = blid
        self.password = password
        self._bridge = Bridge()
        self._connected = False

    def connect(self):
        """Start the bridge and connect to the robot."""
        self._bridge.start()
        resp = self._bridge.send(f"CONNECT {self.ip} {self.blid} {self.password}")
        if not resp.startswith("OK"):
            raise ConnectionError(f"Failed to connect: {resp}")
        self._connected = True

        # Subscribe to all topics for any state updates
        self._bridge.send("SUB #")
        shadow_topic = f"$aws/things/{self.blid}/#"
        self._bridge.send(f"SUB {shadow_topic}")

    def disconnect(self):
        """Disconnect from the robot."""
        self._bridge.stop()
        self._connected = False

    def _send_command(self, command: str, **extra):
        """Send a command to the robot on the 'cmd' topic."""
        if not self._connected:
            raise ConnectionError("Not connected")
        payload = {
            "command": command,
            "time": int(time.time()),
            "initiator": "localApp",
            **extra,
        }
        self._bridge.send(f"PUB cmd {json.dumps(payload)}")

    def start(self, mop: bool = False, wetness: int = 2):
        """Start a cleaning mission.

        Args:
            mop: Enable mopping (vacuum + mop). Default: vacuum only.
            wetness: Mop pad wetness 1=eco, 2=normal, 3=max. Only used if mop=True.
        """
        params = {}
        if mop:
            params["operatingMode"] = 6
            params["padWetness"] = {"disposable": wetness, "reusable": wetness}
        else:
            params["operatingMode"] = 2
        self._send_command("start", params=params)

    def stop(self):
        """Stop the current mission."""
        self._send_command("stop")

    def dock(self):
        """Send the robot back to its dock."""
        self._send_command("dock")

    def pause(self):
        """Pause the current mission."""
        self._send_command("pause")

    def resume(self):
        """Resume a paused mission."""
        self._send_command("resume")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def __repr__(self):
        return f"Robot(ip={self.ip!r}, blid={self.blid[:8]}...)"
