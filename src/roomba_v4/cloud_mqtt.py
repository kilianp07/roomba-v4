"""Cloud MQTT client for AWS IoT Core.

Connects to the iRobot cloud MQTT broker via WebSocket using the custom
authorizer credentials returned by cloud.get_iot_credentials().

The iRobot app authenticates over WSS (not raw MQTT+ALPN).  Credentials
are passed as HTTP headers in the WebSocket upgrade request:
  X-Amz-CustomAuthorizer-Name  = authorizer name
  X-Amz-CustomAuthorizer-Signature = iot_signature
  x-irobot-auth                = iot_token
"""

import json
import ssl
import time

import paho.mqtt.client as mqtt


class CloudMQTT:
    """MQTT client for AWS IoT Core using iRobot custom authorizer over WSS."""

    def __init__(self, iot_creds: dict):
        """Initialise from credentials returned by get_iot_credentials().

        Expected keys: mqtt_endpoint, iot_clientid, iot_token,
        iot_authorizer_name, iot_signature.
        """
        self.endpoint = iot_creds["mqtt_endpoint"]
        self.client_id = iot_creds["iot_clientid"]
        self.token = iot_creds["iot_token"]
        self.authorizer_name = iot_creds["iot_authorizer_name"]
        self.signature = iot_creds["iot_signature"]
        self._topics: list[str] = []

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            transport="websockets",
        )
        self._client.on_connect = self._make_on_connect()
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    @property
    def ws_headers(self) -> dict:
        """HTTP headers for the WebSocket upgrade (custom authorizer creds)."""
        return {
            "X-Amz-CustomAuthorizer-Name": self.authorizer_name,
            "X-Amz-CustomAuthorizer-Signature": self.signature,
            "x-irobot-auth": self.token,
            "User-Agent": "?SDK=Android&Version=2.17.1",
        }

    def connect(self, debug: bool = False):
        """Connect to AWS IoT Core over WSS on port 443."""
        if debug:
            self._client.on_log = self._on_log

        self._client.ws_set_options(path="/mqtt", headers=self.ws_headers)

        ctx = ssl.create_default_context()
        self._client.tls_set_context(ctx)

        self._client.connect(self.endpoint, port=443)
        self._client.loop_start()

    def subscribe(self, topics: list[str]):
        """Register topics — actual subscription happens on connect."""
        self._topics = list(topics)

    def publish(self, topic: str, payload: bytes = b""):
        """Publish a message."""
        self._client.publish(topic, payload)

    def disconnect(self):
        """Clean disconnect."""
        self._client.loop_stop()
        self._client.disconnect()

    # -- callbacks -----------------------------------------------------------

    def _make_on_connect(self):
        cloud_mqtt = self

        def _on_connect(client, userdata, flags, reason_code, properties):
            print(f"[cloud-mqtt] connected: {reason_code}")
            for topic in cloud_mqtt._topics:
                client.subscribe(topic)

        return _on_connect

    @staticmethod
    def _on_message(client, userdata, msg):
        ts = time.strftime("%H:%M:%S")
        try:
            payload = json.dumps(json.loads(msg.payload), indent=2)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload.hex()
        print(f"[{ts}] {msg.topic}\n{payload}\n")

    @staticmethod
    def _on_disconnect(client, userdata, flags, reason_code, properties):
        print(f"[cloud-mqtt] disconnected: {reason_code}")

    @staticmethod
    def _on_log(client, userdata, level, buf):
        print(f"[cloud-mqtt][log] {buf}")
