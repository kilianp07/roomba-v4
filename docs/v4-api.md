# iRobot v4 Cloud API Reference

> Captured via MITM proxy interception of the iRobot Home app.
> See `tools/mitm_irobot.py` for the capture setup.

## Authentication

### 1. Endpoint Discovery

```
GET https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US
```

Returns dynamic configuration:
- `gigya.api_key` — Gigya API key (rotates periodically)
- `gigya.datacenter_domain` — Gigya datacenter (e.g. `us1.gigya.com`)
- `deployments.{version}.httpBase` — iRobot API base URL

**Response schema** (captured):
```json
{
  "current_deployment": "v011",
  "gigya": {
    "api_key": "string",
    "datacenter_domain": "us1.gigya.com"
  },
  "deployments": {
    "v011": {
      "awsRegion": "us-east-1",
      "discoveryTTL": 86400,
      "httpBase": "https://unauth3.prod.iot.irobotapi.com",
      "httpBaseAuth": "https://auth3.prod.iot.irobotapi.com",
      "httpProdSecBaseAuth": "https://certificatefactory.prod.security.irobotapi.com",
      "iotTopics": "$aws",
      "irbtTopics": "v011-irbthbu",
      "mqtt": "a2uowfjvhio0fa-ats.iot.us-east-1.amazonaws.com",
      "mqttApp": "a2uowfjvhio0fa-ats.iot.us-east-1.amazonaws.com",
      "svcDeplId": "v011",
      "userServicesBase": "prod.user-services.irobotapi.com",
      "vStream": "https://vstream.prod.user-services.irobotapi.com"
    }
  }
}
```

**Key domains:**
- `httpBase` (unauth): used for `/v2/login` (no auth required beyond Gigya signature)
- `httpBaseAuth` (auth): requires AWS SigV4 with Cognito credentials for robot-specific endpoints
- `httpProdSecBaseAuth`: certificate factory for device provisioning
- `mqtt` / `mqttApp`: AWS IoT Core endpoint for MQTT connections
- `userServicesBase`: user services (vStream, etc.)

### 2. Gigya Login

```
POST https://accounts.{datacenter_domain}/accounts.login
Content-Type: application/x-www-form-urlencoded

apiKey={api_key}&loginID={email}&password={password}&targetEnv=mobile
```

**Response** (captured — relevant fields):

| Field | Type | Description |
|-------|------|-------------|
| `UID` | string | Gigya user ID |
| `UIDSignature` | string | HMAC signature for the UID |
| `signatureTimestamp` | string | Unix timestamp of the signature |
| `errorCode` | integer | 0 on success |
| `profile.firstName` | string | User first name |
| `profile.lastName` | string | User last name |
| `profile.email` | string | Account email |
| `sessionInfo.sessionToken` | string | Gigya session token |
| `sessionInfo.sessionSecret` | string | Gigya session secret |
| `sessionInfo.expires_in` | string | Session TTL |

### 3. iRobot Login

```
POST {httpBase}/v2/login
Content-Type: application/json

{
  "app_id": "ANDROID-C7FB240E-DF34-42D7-AE4E-A8C17079A294",
  "assume_robot_ownership": "0",
  "gigya": {
    "signature": "{UIDSignature}",
    "timestamp": "{signatureTimestamp}",
    "uid": "{UID}"
  }
}
```

**Response** (captured):

```json
{
  "robots": {
    "<BLID>": {
      "name": "string",
      "password": "string",
      "sku": "string",
      "softwareVer": "string",
      "svcDeplId": "v011",
      "user_cert": false,
      "cap": {
        "binFullDetect": 1, "oMode": 1, "odoa": 1, "maps": 1,
        "pmaps": 1, "scrub": 1, "carpetBoost": 1, "suctionLvl": 1,
        "ppWetLvl": 1, "multiPass": 1, "sched": 1, "ota": 1,
        "5ghz": 1, "matter": 1, "...": "~30 capability flags"
      },
      "digiCap": {
        "appVer": 1,
        "cleaningProfiles": 1,
        "ddAutomation": 1,
        "perspective3DMap": 1,
        "timeline": 1
      }
    }
  },
  "credentials": {
    "AccessKeyId": "string (AWS Cognito)",
    "SecretKey": "string",
    "SessionToken": "string",
    "Expiration": "ISO 8601",
    "CognitoId": "string"
  },
  "iot_token": "string (custom MQTT authorizer token)",
  "iot_clientid": "string",
  "iot_signature": "string",
  "iot_authorizer_name": "string",
  "mtu": true
}
```

> **Note:** Robot-specific REST endpoints (`/v2/robot/<BLID>/...`) on `httpBaseAuth`
> require AWS SigV4 signing using the Cognito `credentials` above. The `iot_token`
> is used for MQTT connections via the custom IoT authorizer.

## AWS Architecture

The v4 API sits behind AWS API Gateway with IAM authentication:

- **`httpBase`** (`unauth3.prod.iot.irobotapi.com`) — No IAM auth required. Used for `/v2/login`.
- **`httpBaseAuth`** (`auth3.prod.iot.irobotapi.com`) — Requires **AWS SigV4** with Cognito credentials.
- **Cognito Identity Pool** — The `/v2/login` response returns Cognito credentials with role `ElPasoData001-LoginCognitoAuthRole`, but this role only permits login-level access. Robot-specific endpoints require an elevated role (likely obtained by the app's Gigya SDK via a developer-authenticated Cognito identity flow).
- **IoT Custom Authorizer** (`ElPaso242Login-AspenIoTAuthorizer`) — Used for MQTT connections with the `iot_token`.

**`iot_token` structure** (base64-encoded JSON):
```json
{
  "cognito_id": "us-east-1:<uuid>",
  "clientid": "app-ANDROID-...",
  "expires_ts": 1772620859,
  "devices": {
    "<BLID>": 1
  }
}
```

> **Blocker:** Robot-specific REST endpoints (`/v2/robot/<BLID>/*`) return 403 because the
> Cognito `LoginCognitoAuthRole` lacks `execute-api:Invoke` permissions. The app likely uses
> the Gigya Android SDK to obtain a JWT via a developer-authenticated Cognito identity flow,
> producing credentials with an elevated IAM role. This flow is not reproducible via REST alone.
> The robot data (commands, state, maps) is primarily accessed via **MQTT** (local or cloud),
> not these REST endpoints.

## Robot Endpoints

> **Note:** All robot REST endpoints below require elevated Cognito credentials (see above).
> They return 403 with the login-level credentials. Robot control is done via MQTT instead.

### Secure Message (MQTT commands via HTTP)

```
POST {httpBase}/v2/robot/sec_message
```

_TODO_ — Request/response schema

### Robot Configuration

```
GET {httpBase}/v2/robot/<BLID>/config
```

_TODO_ — Response schema

### Robot List

```
GET {httpBase}/v2/robots
```

_TODO_ — Response schema, may duplicate login response

### Schedule

```
GET {httpBase}/v2/robot/<BLID>/schedule
PUT {httpBase}/v2/robot/<BLID>/schedule
```

_TODO_ — Schedule format, recurrence rules

### Persistent Maps (pmaps)

```
GET {httpBase}/v2/robot/<BLID>/pmaps
```

_TODO_ — Map data format, image URLs

### Regions / Rooms

```
GET {httpBase}/v2/robot/<BLID>/regions
PUT {httpBase}/v2/robot/<BLID>/regions
```

_TODO_ — Region schema, room naming

## Local MQTT Protocol

The robot also accepts direct MQTT connections on port **8883** (TLS 1.2):

| Topic | Direction | Description |
|-------|-----------|-------------|
| `cmd` | Client → Robot | JSON commands |
| `$aws/things/{BLID}/shadow/update` | Client → Robot | AWS IoT shadow updates |
| `$aws/things/{BLID}/shadow/get` | Client → Robot | Request current state |

Command payload format:
```json
{
  "command": "start",
  "time": 1234567890,
  "initiator": "localApp"
}
```

Known commands: `start`, `stop`, `dock`, `pause`, `resume`

Parameters (via shadow update):
- `operatingMode`: 2 = vacuum, 6 = vacuum + mop
- `padWetness`: _TODO_ — range and values

## Undiscovered Endpoints

_Endpoints found during MITM capture that aren't documented above._

| Method | Path | Status Codes | Notes |
|--------|------|-------------|-------|
| GET | `/v2/robot/<BLID>/ota` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/timeline` | 403 | _TODO_ |
| GET | `/v2/user` | 403 | _TODO_ |
| GET | `/v2/user/associations` | 403 | _TODO_ |
| POST | `/accounts.getJWT` | 200 | _TODO_ |
| GET | `/v2/robot/<BLID>/account` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/cloud/config` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/features` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/firmware` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/missions` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/preferences` | 403 | _TODO_ |
| GET | `/v2/robot/<BLID>/state` | 403 | _TODO_ |
