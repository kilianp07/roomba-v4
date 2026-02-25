"""Client for the native MQTT bridge process."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

BRIDGE_SOCKET = "/tmp/roomba_bridge.sock"


def _find_bridge_binary() -> str | None:
    """Locate the mqtt_bridge binary."""
    # 1. Check PATH
    found = shutil.which("mqtt_bridge")
    if found:
        return found
    # 2. Check relative to package (development / editable install)
    local = Path(__file__).parent.parent.parent / "native" / "mqtt_bridge"
    if local.exists():
        return str(local)
    return None


class BridgeError(Exception):
    pass


class Bridge:
    """Manages the native MQTT bridge process and communicates over Unix socket."""

    def __init__(self, socket_path: str = BRIDGE_SOCKET):
        self.socket_path = socket_path
        self._proc = None
        self._sock = None

    def start(self):
        """Start the bridge process if not already running."""
        if self._proc and self._proc.poll() is None:
            return

        binary = _find_bridge_binary()
        if not binary:
            raise BridgeError("Bridge binary not found. Run: make -C native")

        # Clean up old socket
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self._proc = subprocess.Popen(
            [binary, self.socket_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for socket to appear
        for _ in range(50):
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.1)
        else:
            raise BridgeError("Bridge did not start (no socket)")

        self._connect_socket()

    def _connect_socket(self):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)
        self._sock.settimeout(15.0)

    def stop(self):
        """Stop the bridge process."""
        if self._sock:
            try:
                self.send("DISCONNECT")
            except Exception:
                pass
            self._sock.close()
            self._sock = None
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None

    def send(self, command: str) -> str:
        """Send a command to the bridge and return the response line."""
        if not self._sock:
            raise BridgeError("Not connected to bridge")
        self._sock.sendall((command + "\n").encode())
        return self._readline()

    def _readline(self) -> str:
        """Read one line from the bridge."""
        buf = b""
        while True:
            ch = self._sock.recv(1)
            if not ch:
                raise BridgeError("Bridge connection closed")
            if ch == b"\n":
                return buf.decode("utf-8", errors="replace")
            buf += ch

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
