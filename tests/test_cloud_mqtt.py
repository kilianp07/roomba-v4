"""Tests for roomba_v4.cloud_mqtt."""

from unittest.mock import MagicMock, patch

from roomba_v4.cloud_mqtt import CloudMQTT

SAMPLE_CREDS = {
    "mqtt_endpoint": "a1234.iot.us-east-1.amazonaws.com",
    "iot_clientid": "client-abc",
    "iot_token": "token-xyz",
    "iot_authorizer_name": "my-authorizer",
    "iot_signature": "sig-123",
}


class TestCloudMQTTInit:
    def test_extracts_fields(self):
        c = CloudMQTT(SAMPLE_CREDS)
        assert c.endpoint == "a1234.iot.us-east-1.amazonaws.com"
        assert c.client_id == "client-abc"
        assert c.token == "token-xyz"
        assert c.authorizer_name == "my-authorizer"
        assert c.signature == "sig-123"

    def test_missing_key_raises(self):
        incomplete = {k: v for k, v in SAMPLE_CREDS.items() if k != "mqtt_endpoint"}
        try:
            CloudMQTT(incomplete)
            assert False, "Expected KeyError"
        except KeyError:
            pass

    @patch("roomba_v4.cloud_mqtt.mqtt.Client")
    def test_uses_websocket_transport(self, mock_client_cls):
        CloudMQTT(SAMPLE_CREDS)
        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args
        assert call_kwargs.kwargs.get("transport") == "websockets"


class TestWsHeaders:
    def test_contains_all_headers(self):
        c = CloudMQTT(SAMPLE_CREDS)
        headers = c.ws_headers
        assert headers["X-Amz-CustomAuthorizer-Name"] == "my-authorizer"
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "sig-123"
        assert headers["x-irobot-auth"] == "token-xyz"
        assert headers["User-Agent"] == "?SDK=Android&Version=2.17.1"

    def test_header_values_match_creds(self):
        creds = {**SAMPLE_CREDS, "iot_signature": "abc+/=", "iot_token": "tok=="}
        c = CloudMQTT(creds)
        headers = c.ws_headers
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "abc+/="
        assert headers["x-irobot-auth"] == "tok=="


class TestConnect:
    @patch("roomba_v4.cloud_mqtt.ssl.create_default_context")
    @patch("roomba_v4.cloud_mqtt.mqtt.Client")
    def test_connect_calls_broker(self, mock_client_cls, mock_ssl):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        c = CloudMQTT(SAMPLE_CREDS)
        c.connect()

        mock_instance.ws_set_options.assert_called_once_with(
            path="/mqtt", headers=c.ws_headers
        )
        mock_instance.tls_set_context.assert_called_once_with(mock_ctx)
        mock_instance.connect.assert_called_once_with(
            "a1234.iot.us-east-1.amazonaws.com", port=443
        )
        mock_instance.loop_start.assert_called_once()


class TestSubscribe:
    def test_subscribe_stores_topics(self):
        c = CloudMQTT(SAMPLE_CREDS)
        c.subscribe(["#", "$aws/things/AABB/#"])
        assert c._topics == ["#", "$aws/things/AABB/#"]


class TestDisconnect:
    @patch("roomba_v4.cloud_mqtt.mqtt.Client")
    def test_disconnect(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        c = CloudMQTT(SAMPLE_CREDS)
        c.disconnect()

        mock_instance.loop_stop.assert_called_once()
        mock_instance.disconnect.assert_called_once()
