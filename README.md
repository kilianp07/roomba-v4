# roomba-v4

Local control of iRobot Roomba v4 protocol robots (Combo Max 705 and similar) without cloud dependencies.

## Why

iRobot's v4 protocol (used in newer models like the Combo Max) has no open-source support. The official app requires cloud connectivity. This project reverse-engineers the local MQTT-over-TLS protocol so you can control your robot entirely on your LAN.

## Prerequisites

- Python 3.10+
- OpenSSL 3 development headers
- A C compiler (cc/gcc/clang)

**macOS:**
```bash
brew install openssl@3
```

**Debian/Ubuntu:**
```bash
sudo apt install libssl-dev
```

## Build

Compile the native TLS+MQTT bridge:

```bash
make -C native
```

Optionally install the binary to `~/.local/bin`:

```bash
make -C native install
```

## Install

```bash
pip install -e ".[dev]"
```

## Usage

### Discover robots on your network

```bash
roomba-v4 discover
```

If broadcast discovery doesn't find anything (common with AP isolation or routers that filter broadcast traffic), target the robot's IP directly:

```bash
roomba-v4 discover --target 192.168.1.100
```

### Get BLID from a known IP

```bash
roomba-v4 getblid --target 192.168.1.100
# prints: XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Useful for scripting or initial setup — outputs just the BLID, nothing else.

### Extract the robot password

```bash
roomba-v4 getpassword
```

Prompts for your iRobot Home app credentials (email + password), then fetches your robot's MQTT password from the iRobot cloud API. This calls the same API the official app uses — it accesses your own account data, nothing more.

### Control your robot

```bash
# Set credentials
export ROOMBA_IP=192.168.1.100
export ROOMBA_BLID=XXXXXXXXXXXXXXXX
export ROOMBA_PASSWORD=":1:1234567890:secretkey"

# Commands
roomba-v4 start              # Start vacuuming
roomba-v4 start --mop        # Vacuum + mop
roomba-v4 start --mop --wetness 3  # Vacuum + mop (max wetness)
roomba-v4 stop               # Stop mission
roomba-v4 dock               # Return to dock
roomba-v4 pause              # Pause mission
roomba-v4 resume             # Resume paused mission
```

Credentials can also be passed as arguments:

```bash
roomba-v4 start --ip 192.168.1.100 --blid XXXX --password ":1:..."
```

## Configuration

| Environment variable | Description |
|---|---|
| `ROOMBA_IP` | Robot IP address |
| `ROOMBA_BLID` | Robot BLID (from discovery or hostname) |
| `ROOMBA_PASSWORD` | Robot MQTT password (use `roomba-v4 getpassword` to retrieve it) |

## Architecture

```
┌──────────────┐       Unix socket       ┌──────────────────┐     TLS+MQTT     ┌─────────┐
│  Python CLI  │ ◄────────────────────► │  mqtt_bridge (C)  │ ◄──────────────► │  Roomba  │
│  (robot.py)  │   line-based protocol   │  OpenSSL + MQTT   │   port 8883      │          │
└──────────────┘                         └──────────────────┘                   └─────────┘
```

- **`mqtt_bridge`** (C): Handles TLS 1.2 with cipher/sigalgs workarounds and implements MQTT 3.1.1 packet encoding. Communicates with Python via a Unix domain socket using a simple line protocol (`CONNECT`, `SUB`, `PUB`, `PING`, `DISCONNECT`).
- **`robot.py`**: High-level Python API wrapping the bridge. Sends JSON commands on the `cmd` MQTT topic.
- **`discovery.py`**: UDP discovery on port 5678. Sends to both subnet broadcast and `255.255.255.255`, or to a specific target IP via `--target`.
- **`cloud.py`**: Fetches robot credentials from the iRobot cloud API (Gigya auth + iRobot login).
- **`__main__.py`**: CLI entry point.

## Protocol Notes

- The robot uses TLS 1.2 on port 8883 with a self-signed certificate.
- The robot's TLS implementation has broken RSA-PSS signatures. The bridge forces PKCS1v1.5 (`RSA+SHA256`) via OpenSSL sigalgs configuration.
- MQTT 3.1.1 with BLID as client ID, username, and password.
- Commands are JSON payloads published to the `cmd` topic with `initiator: "localApp"`.
- Discovery uses the `"irobotmcs"` magic packet on UDP port 5678.

## Known Limitations

- **No state feedback**: The robot does not publish any MQTT messages. Control is command-only (fire-and-forget).
- **Broadcast discovery may fail**: Some networks block UDP broadcast (AP isolation, router filtering). Use `--target <IP>` as a workaround.
- **Single robot**: The bridge handles one connection at a time.
- **Password extraction**: `getpassword` requires your iRobot cloud account credentials. The Gigya/iRobot API may change without notice.

## License

MIT
