"""CLI for roomba_v4.

Usage:
    roomba-v4 discover [--target IP] [--timeout SEC]
    roomba-v4 getblid --target IP [--timeout SEC]
    roomba-v4 getpassword
    roomba-v4 cloud-mqtt [--duration SEC]
    roomba-v4 start [--mop] [--wetness 1|2|3] [--ip IP] [--blid BLID] [--password PASS]
    roomba-v4 stop   [--ip IP] [--blid BLID] [--password PASS]
    roomba-v4 dock   [--ip IP] [--blid BLID] [--password PASS]
    roomba-v4 pause  [--ip IP] [--blid BLID] [--password PASS]
    roomba-v4 resume [--ip IP] [--blid BLID] [--password PASS]
"""

import argparse
import getpass
import os
import sys
import time

DEFAULT_IP = os.environ.get("ROOMBA_IP", "")
DEFAULT_BLID = os.environ.get("ROOMBA_BLID", "")
DEFAULT_PASS = os.environ.get("ROOMBA_PASSWORD", "")


def _require_credentials(args):
    """Exit with a clear error if credentials are missing."""
    missing = []
    if not args.ip:
        missing.append("--ip (or ROOMBA_IP)")
    if not args.blid:
        missing.append("--blid (or ROOMBA_BLID)")
    if not args.password:
        missing.append("--password (or ROOMBA_PASSWORD)")
    if missing:
        print(
            "Error: missing required credentials:\n  "
            + "\n  ".join(missing)
            + "\n\nSet them via environment variables or command-line arguments.\n"
            "Example:\n"
            "  export ROOMBA_IP=192.168.1.100\n"
            "  export ROOMBA_BLID=XXXXXXXX\n"
            "  export ROOMBA_PASSWORD=:1:1234:secret",
            file=sys.stderr,
        )
        sys.exit(1)


def _add_credential_args(parser):
    """Add --ip, --blid, --password to a subparser."""
    parser.add_argument("--ip", default=DEFAULT_IP, help="Robot IP address")
    parser.add_argument("--blid", default=DEFAULT_BLID, help="Robot BLID")
    parser.add_argument("--password", default=DEFAULT_PASS, help="Robot password")


def cmd_discover(args):
    from .discovery import discover

    print("Searching for Roomba robots...")
    robots = discover(timeout=args.timeout, target=args.target or None)
    if not robots:
        print("No robots found.")
        return
    for r in robots:
        print(f"\n  Name:     {r['robotname']}")
        print(f"  IP:       {r['ip']}")
        print(f"  BLID:     {r['blid']}")
        print(f"  SKU:      {r['sku']}")
        print(f"  Firmware: {r['firmware']}")
        if r.get("mac"):
            print(f"  MAC:      {r['mac']}")


def cmd_getblid(args):
    from .discovery import discover

    target = args.target or args.ip
    if not target:
        print("Error: --target <IP> is required for getblid.", file=sys.stderr)
        sys.exit(1)
    robots = discover(timeout=args.timeout, target=target)
    if not robots:
        print("No robot found.", file=sys.stderr)
        sys.exit(1)
    print(robots[0]["blid"])


def cmd_getpassword(args):
    from .cloud import CloudError, fetch_robot_credentials

    print("Login with your iRobot Home app credentials.")
    print(
        "(This calls the same API the official app uses — your data, your account.)\n"
    )

    email = input("iRobot email: ").strip()
    if not email:
        print("Error: email is required.", file=sys.stderr)
        sys.exit(1)
    password = getpass.getpass("iRobot password: ")
    if not password:
        print("Error: password is required.", file=sys.stderr)
        sys.exit(1)

    print("\nFetching robot credentials...")
    try:
        robots, iot_creds = fetch_robot_credentials(email, password)
    except CloudError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

    if not robots:
        print("No robots found on this account.")
        sys.exit(1)

    for r in robots:
        print(f"\n  Name:     {r.get('name', '?')}")
        print(f"  BLID:     {r['blid']}")
        print(f"  Password: {r['password']}")
        print(f"  SKU:      {r.get('sku', '?')}")
        print(f"  Firmware: {r.get('softwareVer', '?')}")
    print("\nExport example (for the first robot):")
    first = robots[0]
    print(f'  export ROOMBA_BLID="{first["blid"]}"')
    print(f'  export ROOMBA_PASSWORD="{first["password"]}"')

    if iot_creds.get("mqtt_endpoint"):
        print(f"\n  Cloud MQTT endpoint: {iot_creds['mqtt_endpoint']}")
    if iot_creds.get("token_expires_ts"):
        print(f"  IoT token expires:   {iot_creds['token_expires_ts']}")


def cmd_cloud_mqtt(args):
    from .cloud import CloudError, fetch_robot_credentials
    from .cloud_mqtt import CloudMQTT

    email = os.environ.get("IROBOT_EMAIL", "").strip()
    password = os.environ.get("IROBOT_PASSWORD", "").strip()

    if not email or not password:
        print("Login with your iRobot Home app credentials.\n")
        if not email:
            email = input("iRobot email: ").strip()
        if not password:
            password = getpass.getpass("iRobot password: ")

    if not email or not password:
        print("Error: email and password are required.", file=sys.stderr)
        sys.exit(1)

    print("\nFetching robot credentials...")
    try:
        robots, iot_creds = fetch_robot_credentials(email, password)
    except CloudError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

    if not iot_creds.get("mqtt_endpoint"):
        print("Error: no MQTT endpoint returned by the cloud API.", file=sys.stderr)
        sys.exit(1)

    # Per-robot shadow topics (multi-level wildcard # is denied by IoT policy)
    topics = []
    for r in robots:
        b = r["blid"]
        topics.append(f"$aws/things/{b}/shadow/get/accepted")
        topics.append(f"$aws/things/{b}/shadow/update/accepted")
        topics.append(f"$aws/things/{b}/shadow/update/delta")

    print(f"Connecting to {iot_creds['mqtt_endpoint']}...")
    client = CloudMQTT(iot_creds)
    client.connect(debug=getattr(args, "debug", False))
    client.subscribe(topics)

    # Wait for subscriptions, then request current shadows
    time.sleep(2)
    for r in robots:
        client.publish(f"$aws/things/{r['blid']}/shadow/get")

    print(f"Listening for {args.duration}s (Ctrl+C to stop)...\n")
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        client.disconnect()


def cmd_robot(args):
    from .robot import Robot

    _require_credentials(args)

    robot = Robot(args.ip, args.blid, args.password)
    try:
        robot.connect()
        command = args.command

        if command == "start":
            robot.start(mop=args.mop, wetness=args.wetness)
            mode = "vacuum + mop" if args.mop else "vacuum"
            print(f"Start command sent ({mode}).")
        elif command == "stop":
            robot.stop()
            print("Stop command sent.")
        elif command == "dock":
            robot.dock()
            print("Dock command sent.")
        elif command == "pause":
            robot.pause()
            print("Pause command sent.")
        elif command == "resume":
            robot.resume()
            print("Resume command sent.")

    finally:
        robot.disconnect()


def main():
    parser = argparse.ArgumentParser(
        prog="roomba-v4", description="Roomba v4 local control"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # discover
    p_discover = sub.add_parser("discover", help="Find robots on the network")
    p_discover.add_argument(
        "--timeout", type=float, default=5.0, help="Discovery timeout (seconds)"
    )
    p_discover.add_argument(
        "--target", default="", help="Target IP (default: auto-detect subnet broadcast)"
    )

    # getblid
    p_getblid = sub.add_parser("getblid", help="Get BLID from a robot IP")
    p_getblid.add_argument("--target", default="", help="Robot IP address")
    p_getblid.add_argument(
        "--ip", default=DEFAULT_IP, help="Robot IP (alias for --target)"
    )
    p_getblid.add_argument(
        "--timeout", type=float, default=5.0, help="Discovery timeout (seconds)"
    )

    # getpassword
    sub.add_parser("getpassword", help="Fetch robot password from iRobot cloud")

    # cloud-mqtt
    p_cloud_mqtt = sub.add_parser(
        "cloud-mqtt", help="Connect to cloud MQTT and log messages"
    )
    p_cloud_mqtt.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Listen duration in seconds (default: 60)",
    )
    p_cloud_mqtt.add_argument(
        "--debug", action="store_true", help="Enable MQTT debug logging"
    )

    # Robot control commands
    for cmd in ("start", "stop", "dock", "pause", "resume"):
        p = sub.add_parser(cmd, help=f"{cmd.capitalize()} the robot")
        _add_credential_args(p)
        if cmd == "start":
            p.add_argument(
                "--mop", action="store_true", help="Enable mopping (vacuum + mop)"
            )
            p.add_argument(
                "--wetness",
                type=int,
                default=2,
                choices=[1, 2, 3],
                help="Mop wetness: 1=eco, 2=normal, 3=max",
            )

    args = parser.parse_args()

    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "getblid":
        cmd_getblid(args)
    elif args.command == "getpassword":
        cmd_getpassword(args)
    elif args.command == "cloud-mqtt":
        cmd_cloud_mqtt(args)
    else:
        cmd_robot(args)


if __name__ == "__main__":
    main()
