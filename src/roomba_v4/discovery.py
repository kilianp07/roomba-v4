"""Discover Roomba robots on the local network via UDP port 5678."""

import json
import socket
import struct


def _get_subnet_broadcast() -> str | None:
    """Derive the subnet broadcast address from the default route interface."""
    try:
        # Connect to a public IP (no traffic sent) to find local address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Assume /24 — covers the vast majority of home networks
        parts = local_ip.split(".")
        parts[3] = "255"
        return ".".join(parts)
    except Exception:
        return None


def discover(timeout: float = 5.0, target: str | None = None) -> list[dict]:
    """Send iRobot discovery packet and collect responses.

    Args:
        timeout: How long to wait for responses.
        target: IP or broadcast address to probe. If None, tries subnet
                broadcast then falls back to 255.255.255.255.

    Returns a list of dicts with robot info (ip, blid, hostname, firmware, sku, etc).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    targets = []
    if target:
        targets.append(target)
    else:
        subnet_bc = _get_subnet_broadcast()
        if subnet_bc:
            targets.append(subnet_bc)
        targets.append("255.255.255.255")

    for addr in targets:
        sock.sendto(b"irobotmcs", (addr, 5678))

    robots = []
    seen = set()
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            if addr[0] in seen:
                continue
            seen.add(addr[0])
            robot = _parse_discovery(data, addr[0])
            if robot:
                robots.append(robot)
    except socket.timeout:
        pass
    finally:
        sock.close()

    return robots


def _parse_discovery(data: bytes, ip: str) -> dict | None:
    """Parse the iRobot discovery response."""
    try:
        # Response format: 2-byte length prefix, then JSON
        if len(data) < 2:
            return None

        # Try raw JSON first (some robots send plain JSON)
        try:
            info = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Try with 2-byte length prefix
            length = struct.unpack(">H", data[:2])[0]
            info = json.loads(data[2 : 2 + length])

        return {
            "ip": ip,
            "hostname": info.get("hostname", ""),
            "robotname": info.get("robotname", ""),
            "firmware": info.get("sw", ""),
            "sku": info.get("sku", ""),
            "blid": _extract_blid(info),
            "mac": info.get("mac", ""),
        }
    except Exception:
        return None


def _extract_blid(info: dict) -> str:
    """Extract BLID from discovery info."""
    hostname = info.get("hostname", "")
    # BLID is usually in the hostname: iRobot-BLID or Roomba-BLID
    for prefix in ("iRobot-", "Roomba-"):
        if hostname.startswith(prefix):
            return hostname[len(prefix) :]
    return hostname
