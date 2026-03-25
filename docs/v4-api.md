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

HTTP-to-MQTT bridge — sends commands to the robot via the cloud broker.
Likely accepts the same JSON command payloads as the `cmd` MQTT topic
(see [Command Payloads](#command-payloads)). Returns 403 with login-level credentials.

### Robot Configuration

```
GET {httpBase}/v2/robot/<BLID>/config
```

Robot configuration — overlaps with shadow `state.reported` (`cap`, `digiCap`,
`sku`, `svcEndpoints`). Returns 403 with login-level credentials.

### Robot List

```
GET {httpBase}/v2/robots
```

Robot list — likely returns the same `robots` dict as the `/v2/login` response
(name, password, sku, softwareVer, cap, digiCap per robot). Returns 403 with
login-level credentials.

### Schedule

```
GET {httpBase}/v2/robot/<BLID>/schedule
PUT {httpBase}/v2/robot/<BLID>/schedule
```

Schedule CRUD. The schedule format uses parallel arrays indexed by day of week —
see [Schedule Format](#schedule-format) for the JSON structure. This REST
endpoint is inaccessible (403) but the same data is available in the shadow as
`cleanSchedule`.

### Persistent Maps (pmaps)

```
GET {httpBase}/v2/robot/<BLID>/pmaps
```

Map data. Maps are identified by `pmap_id` (UUID). The shadow's `pmaps` array
lists stored maps with `pmap_id` and version. Map image data (room boundaries,
coordinate system) is only available through this REST endpoint or the native
SDK. Returns 403 with login-level credentials.

### Regions / Rooms

```
GET {httpBase}/v2/robot/<BLID>/regions
PUT {httpBase}/v2/robot/<BLID>/regions
```

Room definitions within a map. Each region has a `region_id` and type (`rid` for
room). Used in room-specific clean commands (see [Start room-specific clean](#start-room-specific-clean)).
Returns 403 with login-level credentials.

## MQTT Protocol

Commands and state are exchanged via MQTT — either via the cloud (AWS IoT Core
WSS on port 443) or locally. The payload schemas are identical; only the
transport and auth differ.

### Local Connection — V3 vs V4 (Matter)

**V3 robots** (and older) expose a local MQTT broker on **port 8883** (TLS 1.2,
self-signed cert). The app connects directly via `LocalSecureSocketClient` with
BLID/password authentication over raw MQTT 3.1.1.

**V4 robots** (`ver: 4`, `matter: 1` in discovery) **do not open port 8883**.
The firmware replaces the local MQTT listener with the **Matter** protocol for
local control. Evidence from APK analysis (v7.17.6):

- `RoombaVersion3ProvisioningSubsystemImpl::initiateLocalConnection()` → port 8883
- `MatterSetupViewModelV2Impl::initiateLocalConnection()` → Matter commissioning
- No `RoombaVersion4` equivalent for `LocalSecureSocket`

Tested on X185040 (Roomba Combo X2, fw p25-705+9.3.6):
- UDP discovery (port 5678) responds: `nc: 0`, `proto: "mqtt"`, `ver: "4"`
- TCP port 8883: **Connection refused** (RST) — no listener
- All other ports (443, 1883, 8080): timeout (no service)
- Cloud MQTT shadow: only caps/config, no runtime state (`cleanMissionStatus`)

This means V4 robot control requires either:
1. **Cloud MQTT** (AWS IoT Core) — read-only shadow access with app credentials
2. **Matter** — local control via Matter protocol (requires commissioning)

### Topics

**Local** (V3 only — direct TLS connection on port 8883):

| Topic | Direction | Description |
|-------|-----------|-------------|
| `cmd` | Client → Robot | JSON commands |
| `$aws/things/{BLID}/shadow/update` | Client → Robot | Shadow state updates |
| `$aws/things/{BLID}/shadow/get` | Client → Robot | Request current shadow |

**Cloud** (AWS IoT Core, see [Cloud MQTT](#cloud-mqtt) for auth):

| Topic | Direction | Description |
|-------|-----------|-------------|
| `$aws/things/{BLID}/shadow/get` | App → Broker | Request shadow (empty payload) |
| `$aws/things/{BLID}/shadow/get/accepted` | Broker → App | Full shadow JSON |
| `$aws/things/{BLID}/shadow/update/accepted` | Broker → App | Shadow after robot update |
| `$aws/things/{BLID}/shadow/update/delta` | Broker → App | Desired-vs-reported diff |

### Command Payloads

Published to the `cmd` topic. All commands share a base structure:

```json
{
  "command": "<name>",
  "time": 1234567890,
  "initiator": "localApp"
}
```

`time` is the current Unix timestamp. `initiator` is `"localApp"` for local,
`"cloud"` for cloud-initiated commands.

#### Start (vacuum only)

```json
{
  "command": "start",
  "params": {
    "operatingMode": 2
  },
  "time": 1234567890,
  "initiator": "localApp"
}
```

#### Start (vacuum + mop)

```json
{
  "command": "start",
  "params": {
    "operatingMode": 6,
    "padWetness": {
      "disposable": 2,
      "reusable": 2
    }
  },
  "time": 1234567890,
  "initiator": "localApp"
}
```

#### Start (room-specific clean)

> Structure inferred from APK `PropertyBuilder` usage. Uses `pmap_id` and
> `regions` to target specific rooms on the stored map.

```json
{
  "command": "start",
  "params": {
    "pmap_id": "<persistent-map-uuid>",
    "regions": [
      {"region_id": "<room-id>", "type": "rid"}
    ]
  },
  "time": 1234567890,
  "initiator": "localApp"
}
```

#### Other commands

| Command | Payload | Description |
|---------|---------|-------------|
| `stop` | base only | Stop mission |
| `pause` | base only | Pause mission |
| `resume` | base only | Resume mission |
| `dock` | base only | Return to dock |
| `find` | base only | Robot beeps to locate |
| `evac` | base only | Trigger manual bin empty (auto-empty dock) |
| `train` | base only | Training / mapping run |

> Additional commands from APK: `quick`, `spot`, `wipe`, `patch`, `dlpkg`,
> `rechrg`, `sleep`, `off`, `fbeep`. Most are internal or legacy.

### Operating Mode & Pad Wetness

| Parameter | Values | Notes |
|-----------|--------|-------|
| `operatingMode` | `2` = vacuum, `6` = vacuum + mop | Passed in `params` of `start` command |
| `padWetness.disposable` | `1` = eco, `2` = normal, `3` = max | Both `disposable` and `reusable` set to same value |
| `padWetness.reusable` | `1` = eco, `2` = normal, `3` = max | Matches `cap.ppWetLvl` level count |

### Shadow State Schema (`state.reported`)

The full shadow contains the robot's current state. The cloud shadow only
exposes `cap`, `digiCap`, `svcEndpoints`, `sku`, and a few config keys (see
[Default Shadow Schema](#default-shadow-schema)). The local shadow includes the
full runtime state. Key structure from APK (`MissionStatus`, `RobotStatusInfo`):

#### `cleanMissionStatus`

The primary runtime state object, published by the robot on every state change:

```json
{
  "cleanMissionStatus": {
    "cycle": "clean",
    "phase": "run",
    "batPct": 85,
    "error": 0,
    "mssnM": 12,
    "expireM": -1,
    "rechrgM": -1,
    "sqft": 150,
    "notReady": 0,
    "flags": 4,
    "pos": {
      "theta": 45,
      "point": { "x": 100, "y": -200 }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `cycle` | string | Mission type (see below) |
| `phase` | string | Current phase (see below) |
| `batPct` | integer | Battery percentage (0–100) |
| `error` | integer | Error code (0 = none; see [Error Codes](#error-codes)) |
| `mssnM` | integer | Mission time in minutes |
| `expireM` | integer | Minutes until mission expires (-1 = no limit) |
| `rechrgM` | integer | Recharge time in minutes (-1 = not charging) |
| `sqft` | integer | Square feet cleaned |
| `notReady` | integer | Readiness state code (0 = ready; see [Readiness](#readiness-states)) |
| `flags` | integer | Bitmask: bit 0 = bin full, bit 1 = bin removed, bit 2 = dock known, bit 3 = audio active |
| `pos` | object | Robot position (`theta` heading, `point.x`/`point.y` in mm) |

#### `cycle` values

| Value | Description |
|-------|-------------|
| `none` | No mission |
| `clean` | Full clean |
| `spot` | Spot clean |
| `quick` | Quick clean |
| `dock` | Docking |
| `manual` | Manual drive |
| `evac` | Bin evacuation |
| `train` | Mapping / training run |

#### `phase` values

| Value | Description |
|-------|-------------|
| `stop` | Stopped / idle |
| `charge` | Charging on dock |
| `run` | Running mission |
| `stuck` | Stuck (needs help) |
| `hmPostMsn` | Returning to dock (mission complete) |
| `hmMidMsn` | Returning to dock mid-mission (recharge) |
| `hmUsrDock` | Returning to dock (user command) |
| `hmUsrChrg` | Returning to dock to charge (user command) |
| `chgerr` | Charging error |

> APK also defines `Evacuation`, `Refilling`, and `PadWashing` phases in the
> native `RobotMissionPhase` enum — these may appear on newer firmware.

#### Other `state.reported` keys

| Key | Type | Description |
|-----|------|-------------|
| `batPct` | integer | Battery percentage (also in `cleanMissionStatus`) |
| `bin` | object | Bin status (`present`, `full`) |
| `dock` | object | Dock state (see [Dock States](#dock-states)) |
| `signal` | object | Wi-Fi signal strength (`rssi`, `snr`) |
| `bbrun` | object | Brush/bumper runtime metrics |
| `wifiStat` | object | Wi-Fi connection status |
| `netinfo` | object | Network information |
| `lastCommand` | object | Last command received |
| `pose` | object | Robot pose (position + heading) |
| `pmaps` | array | Persistent map list (`pmap_id`, `pmap_version`) |
| `openOnly` | boolean | Clean open areas only |
| `twoPass` | boolean | Two-pass cleaning |
| `vacHigh` | boolean | High vacuum power |
| `noAutoPasses` | boolean | Disable automatic extra passes |
| `carpetBoost` | boolean | Carpet boost enabled |
| `binPause` | boolean | Pause when bin full |
| `schedHold` | boolean | Schedule paused |
| `langs` | array | Available language codes |
| `cleanSchedule` | object | Schedule data (see [Schedule](#schedule-format)) |
| `sku` | string | Robot model SKU |
| `softwareVer` | string | Firmware version |
| `cap` | object | Capability flags (see [Capability Flags](#capability-flags-cap)) |
| `digiCap` | object | Digital capabilities (see [Digital Capabilities](#digital-capabilities-digicap)) |
| `country` | string | Country code |
| `tzName` | string | Timezone name |

### Schedule Format

Schedules are stored in `cleanSchedule` in the shadow. The legacy format uses
parallel arrays indexed by day of week (Sunday = 0 through Saturday = 6):

```json
{
  "cleanSchedule": {
    "cycle": ["none", "start", "start", "none", "start", "start", "none"],
    "h":     [9,      8,       8,       9,      10,      8,       9],
    "m":     [0,      30,      30,      0,      0,       30,      0]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `cycle` | string[] | Per-day cycle type: `none` (disabled), `clean`, `quick`, `start` |
| `h` | integer[] | Hour for each day (0–23) |
| `m` | integer[] | Minute for each day (0–59) |

### Error Codes

The `error` field in `cleanMissionStatus` maps to these codes (from APK
`RobotErrorCode` enum):

| Code | Name | Description |
|------|------|-------------|
| 0 | `NO_ERROR` | No error |
| 1 | `ROBOT_STUCK` | Robot is stuck |
| 2 | `CLEAR_DEBRIS_EXTRACTOR` | Debris in extractor |
| 3 | `ROBOT_STUCK` | Robot stuck (variant) |
| 4 | `LEFT_WHEEL_STUCK` | Left wheel stuck |
| 5 | `RIGHT_WHEEL_STUCK` | Right wheel stuck |
| 6 | `ROBOT_ON_CLIFF` | Cliff detected |
| 7 | `LEFT_WHEEL_ERROR` | Left wheel error |
| 8 | `BIN_ERROR` | Bin error |
| 9 | `BUMPER_TROUBLE` | Bumper issue |
| 10 | `RIGHT_WHEEL_TROUBLE` | Right wheel issue |
| 14 | `BIN_MISSING` | Bin not installed |
| 15 | `MISC_ERROR` | Miscellaneous error |
| 16 | `MOTION_CALIBRATION` | Motion calibration needed |
| 17 | `COULD_NOT_FINISH` | Could not finish cleaning |
| 18 | `DOCKING_TROUBLE` | Docking trouble |
| 19 | `UNDOCKING_FAILED` | Undocking failed |
| 29 | `SOFTWARE_UPDATE_NEEDED` | Software update required |
| 31 | `BUMPER_COMMS` | Bumper comms issue |
| 32 | `SMART_MAP_PROBLEM` | Smart map problem |
| 35 | `UNRECOGNIZED_PAD` | Unrecognized cleaning pad |
| 36 | `BIN_FULL` | Bin full |
| 37 | `TANK_REFILL` | Tank needs refilling |
| 40 | `NAVIGATION_PROBLEM` | Navigation problem |
| 41 | `TIMED_OUT` | Mission timed out |
| 44 | `PUMP_ISSUE` | Pump issue |
| 45 | `LID_OPEN` | Lid open |
| 46 | `LOW_BATTERY` | Low battery |
| 65 | `HARDWARE_PROBLEM` | Hardware problem |
| 68 | `CAMERA_FAILURE` | Camera hardware failure |
| 73 | `PAD_TYPE_ERROR` | Pad type error |
| 74 | `MAX_SQFT_REACHED` | Max area reached |
| 101–121 | `BATTERY/CHARGING` | Battery and charging errors |
| 201–278 | `STARTING_ERROR_*` | Pre-mission check failures |
| 350–365 | `EVAC_DOCK_*` | Auto-empty dock errors |
| 1000+ | `SIDE_BRUSH/SUBSCRIPTION/NAV` | Extended error codes |

### Readiness States

The `notReady` field indicates why the robot cannot start a mission (0 = ready):

| Code | State | Description |
|------|-------|-------------|
| 0 | Ready | Can start |
| 1 | Cliff | Cliff detected |
| 2 | WheelDropBoth | Both wheels dropped |
| 3 | WheelDropLeft | Left wheel dropped |
| 4 | WheelDropRight | Right wheel dropped |
| 6 | BrushStall | Brush stalled |
| 7 | NoBin | Bin missing |
| 12 | InsufficientCharge | Battery too low |
| 13 | BinFull | Bin full |
| 16 | ChargingSleep | Charging / asleep |
| 17 | InvalidPad | Invalid cleaning pad |

> Full list has ~70 states in APK `RobotReadinessState` enum (cliff, wheel,
> brush, bin, charge, navigation, safety, dock, etc.).

### Dock States

Dock status codes from APK `DockState` class, grouped by subsystem:

**Evacuation (auto-empty):** 300–365

| Code | State |
|------|-------|
| 300 | Unknown |
| 301 | Ready |
| 302 | Evacuation in progress |
| 303 | Evacuation complete |
| 350 | Bag missing |
| 351 | Clogged |
| 352 | Vacuum inoperable |
| 353 | Bag full |
| 354 | Motor failure |
| 355 | Partial clog |
| 360 | Communication failure |

**Fluid replenishment (tank refill):** 400–464

| Code | State |
|------|-------|
| 401 | OK |
| 402 | Started |
| 403 | In progress |
| 404 | Complete |
| 405 | Complete (not enough water) |
| 450 | Tank missing |
| 451 | Tank level too low |
| 454 | Clog |
| 455 | Pump failure |

**Pad wash:** 600–669

| Code | State |
|------|-------|
| 601 | OK |
| 602 | In progress |
| 603 | Complete |
| 650 | Clear fluid tank missing |
| 651 | Clear fluid too low |
| 653 | Grey water tank missing |
| 654 | Grey water tank full |

**Pad dry:** 700–757

| Code | State |
|------|-------|
| 701 | OK |
| 702 | In progress |
| 703 | Complete |
| 750 | Motor stall |
| 756 | No pad attached |

## Cloud MQTT

The iRobot app communicates with robots via **AWS IoT Core** over WSS (WebSocket
Secure on port 443), not raw MQTT+ALPN. The connection uses a custom authorizer
(`ElPaso242Login-AspenIoTAuthorizer`) with credentials from the `/v2/login` response.

> Captured via `tools/probe_cloud_mqtt.py` — subscribing to shadow topics from the
> broker and analysing the IoT policy's allow/deny behaviour.

### Connection

| Parameter | Value |
|-----------|-------|
| Endpoint | `a2uowfjvhio0fa-ats.iot.us-east-1.amazonaws.com` |
| Port | 443 |
| Transport | WebSocket (`/mqtt` path) |
| Protocol | MQTT 3.1.1 |
| Client ID | `iot_clientid` from login response |

**WebSocket upgrade headers** (all required):

| Header | Value |
|--------|-------|
| `X-Amz-CustomAuthorizer-Name` | `iot_authorizer_name` from login response |
| `X-Amz-CustomAuthorizer-Signature` | `iot_signature` from login response |
| `x-irobot-auth` | `iot_token` from login response |
| `User-Agent` | `?SDK=Android&Version=2.17.1` |

> **Critical:** Without the exact `User-Agent` header, connections succeed but every
> subscribe/publish triggers an immediate disconnect. The Lambda authorizer inspects
> this header and returns a restricted IoT policy without it.

### IoT Policy (observed permissions)

Tested by subscribing/publishing to various topic patterns and observing
connect/disconnect behaviour:

| Action | Topic Pattern | Result |
|--------|--------------|--------|
| Subscribe | `$aws/things/{BLID}/shadow/get/accepted` | **Allowed** |
| Subscribe | `$aws/things/{BLID}/shadow/update/accepted` | **Allowed** |
| Subscribe | `$aws/things/{BLID}/shadow/update/delta` | **Allowed** |
| Publish | `$aws/things/{BLID}/shadow/get` | **Allowed** (triggers shadow read) |
| Publish | `$aws/things/{BLID}/shadow/update` | **Denied** (instant disconnect) |
| Subscribe | `$aws/things/{BLID}/shadow/name/{name}/*` | **Denied** (instant disconnect) |
| Subscribe | `v011-irbthbu/{BLID}/+` | **Denied** (instant disconnect) |
| Subscribe | `v011-irbthbu/+/{BLID}` | **Denied** (instant disconnect) |
| Subscribe | `#` (multi-level wildcard) | **Denied** (instant disconnect) |

> The app-level IoT token grants **read-only** access to the default (unnamed) shadow
> for each robot listed in the token's `devices` map. Write access and named shadows
> are reserved for the robot itself (device certificate auth) or elevated credentials.

### Topic Structure

Only the standard AWS IoT Device Shadow topics are accessible:

```
$aws/things/{BLID}/shadow/get           → publish (empty payload) to request shadow
$aws/things/{BLID}/shadow/get/accepted  → subscribe; receives full shadow JSON
$aws/things/{BLID}/shadow/update/accepted → subscribe; receives shadow after robot updates
$aws/things/{BLID}/shadow/update/delta  → subscribe; receives desired-vs-reported diff
```

The `irbtTopics` prefix (`v011-irbthbu`) from the discovery endpoint is inaccessible
with app-level credentials. It may be used for device-to-cloud or internal service
communication.

### Default Shadow Schema

The default shadow contains `state.reported` with robot capabilities and configuration.
The schema varies by SKU. Captured from two robots:

**`state.reported` keys (j557840 — Roomba Combo j5):**

```json
{
  "digiCap": {
    "appVer": 0
  },
  "nsmip": 2,
  "svcEndpoints": {
    "svcDeplId": "v011"
  },
  "sku": "j557840",
  "cap": {
    "binFullDetect": 2,
    "addOnHw": 3,
    "oMode": 10,
    "odoa": 7,
    "dockComm": 1,
    "maps": 3,
    "pmaps": 9,
    "mc": 2,
    "sem2umf": 2,
    "tLine": 2,
    "area": 1,
    "eco": 1,
    "multiPass": 2,
    "pp": 0,
    "team": 1,
    "pose": 2,
    "lang": 2,
    "hm": 0,
    "rNav": 2,
    "5ghz": 0,
    "prov": 3,
    "sched": 2,
    "svcConf": 1,
    "ota": 2,
    "log": 2,
    "langOta": 0,
    "ns": 1,
    "bleLog": 1,
    "expectingUserConf": 2,
    "idl": 1,
    "scrub": 0,
    "pw": 0,
    "floorTypeDetect": 3,
    "gentle": 1
  }
}
```

**`state.reported` keys (X185040 — Roomba Combo X2):**

```json
{
  "digiCap": {
    "appVer": 1,
    "cleaningProfiles": 2,
    "ddAutomation": 1,
    "perspective3DMap": 1,
    "timeline": 1
  },
  "nsmip": 2,
  "svcEndpoints": {
    "svcDeplId": "v011"
  },
  "sku": "X185040",
  "cap": {
    "5ghz": 1,
    "area": 1,
    "autoevac": 2,
    "binFullDetect": 0,
    "bleLog": 1,
    "carpetBoost": 3,
    "dPause": 1,
    "dSpot": 1,
    "dnd": 1,
    "dockComm": 1,
    "expectingUserConf": 2,
    "floorTypeDetect": 4,
    "idl": 0,
    "lang": 2,
    "langOta": 2,
    "lmap": 1,
    "log": 2,
    "maps": 6,
    "matter": 1,
    "mc": 3,
    "multiPass": 1,
    "ns": 1,
    "oMode": 550,
    "odoa": 1,
    "ota": 3,
    "p2maps": 3,
    "ppWetLvl": 3,
    "prov": 3,
    "pw": 4,
    "sched": 2,
    "scrub": 3,
    "suctionLvl": 4,
    "svcConf": 1,
    "tLine": 2,
    "vmStrat": 1,
    "mapMax": 5,
    "saSku": 1
  },
  "odoaMode": 0,
  "schedHold": false
}
```

### Capability Flags (`cap`)

Values are integers representing feature levels (0 = not supported, higher = more
capable). Flags vary by SKU.

| Flag | Description | j5 | X2 |
|------|-------------|:--:|:--:|
| `5ghz` | 5 GHz Wi-Fi | 0 | 1 |
| `addOnHw` | Add-on hardware support | 3 | — |
| `area` | Area cleaning | 1 | 1 |
| `autoevac` | Auto-empty dock | — | 2 |
| `binFullDetect` | Bin full detection | 2 | 0 |
| `bleLog` | BLE logging | 1 | 1 |
| `carpetBoost` | Carpet boost suction | — | 3 |
| `dPause` | Dock pause | — | 1 |
| `dSpot` | Dock spot clean | — | 1 |
| `dnd` | Do not disturb | — | 1 |
| `dockComm` | Dock communication | 1 | 1 |
| `eco` | Eco mode | 1 | — |
| `expectingUserConf` | User confirmation prompt | 2 | 2 |
| `floorTypeDetect` | Floor type detection | 3 | 4 |
| `gentle` | Gentle mode | 1 | — |
| `hm` | Unknown | 0 | — |
| `idl` | Idle detection | 1 | 0 |
| `lang` | Language support | 2 | 2 |
| `langOta` | Language OTA updates | 0 | 2 |
| `lmap` | Live map | — | 1 |
| `log` | Logging | 2 | 2 |
| `mapMax` | Max stored maps | — | 5 |
| `maps` | Map versions | 3 | 6 |
| `matter` | Matter protocol | — | 1 |
| `mc` | Mission control | 2 | 3 |
| `multiPass` | Multi-pass cleaning | 2 | 1 |
| `ns` | Night mode / silent | 1 | 1 |
| `oMode` | Operating modes (bitmask) | 10 | 550 |
| `odoa` | Obstacle detection/avoidance | 7 | 1 |
| `ota` | OTA firmware updates | 2 | 3 |
| `p2maps` | Persistent map v2 | — | 3 |
| `pmaps` | Persistent maps | 9 | — |
| `pose` | Pose estimation | 2 | — |
| `pp` | Pad present | 0 | — |
| `ppWetLvl` | Mop pad wetness levels | — | 3 |
| `prov` | Provisioning | 3 | 3 |
| `pw` | Power / pad wetness | 0 | 4 |
| `rNav` | Robot navigation | 2 | — |
| `saSku` | SA SKU | — | 1 |
| `sched` | Scheduling | 2 | 2 |
| `scrub` | Mopping/scrubbing | 0 | 3 |
| `sem2umf` | Semantic to UMF | 2 | — |
| `suctionLvl` | Suction levels | — | 4 |
| `svcConf` | Service configuration | 1 | 1 |
| `tLine` | Timeline | 2 | 2 |
| `team` | Team/multi-robot | 1 | — |
| `vmStrat` | Virtual map strategy | — | 1 |

### Digital Capabilities (`digiCap`)

App-side feature flags (set by the cloud, not the robot):

| Flag | Description | j5 | X2 |
|------|-------------|:--:|:--:|
| `appVer` | App version compatibility | 0 | 1 |
| `cleaningProfiles` | Cleaning profiles support | — | 2 |
| `ddAutomation` | Automation rules | — | 1 |
| `perspective3DMap` | 3D map view | — | 1 |
| `timeline` | Cleaning timeline | — | 1 |

### Other `state.reported` Keys

| Key | Type | Description |
|-----|------|-------------|
| `nsmip` | integer | Network service mode IP version (2 = IPv4+IPv6) |
| `svcEndpoints.svcDeplId` | string | Service deployment ID (matches discovery `svcDeplId`) |
| `sku` | string | Robot model SKU |
| `odoaMode` | integer | Obstacle avoidance mode (0 = default) — X2 only |
| `schedHold` | boolean | Schedule paused — X2 only |

### Shadow Metadata

Each key in `state.reported` has a `metadata.reported.{key}.timestamp` (Unix epoch)
recording when the robot last updated that value. The shadow also includes:

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Shadow version (monotonically increasing) |
| `timestamp` | integer | Server timestamp of the shadow read |

## Undiscovered Endpoints

_Endpoints found during MITM capture that aren't documented above._
_All return 403 with login-level Cognito credentials (see AWS Architecture blocker)._

| Method | Path | Status Codes | Notes |
|--------|------|-------------|-------|
| GET | `/v2/robot/<BLID>/ota` | 403 | OTA update info; `cap.ota` indicates support level |
| GET | `/v2/robot/<BLID>/timeline` | 403 | Cleaning history; `digiCap.timeline` enables UI |
| GET | `/v2/user` | 403 | User profile |
| GET | `/v2/user/associations` | 403 | Robot-user associations |
| POST | `/accounts.getJWT` | 200 | Gigya JWT — likely used for elevated Cognito auth |
| GET | `/v2/robot/<BLID>/account` | 403 | Robot account binding |
| GET | `/v2/robot/<BLID>/cloud/config` | 403 | Cloud-side config; shadow has `svcEndpoints` subset |
| GET | `/v2/robot/<BLID>/features` | 403 | Feature flags; shadow `cap` + `digiCap` overlap |
| GET | `/v2/robot/<BLID>/firmware` | 403 | Firmware info; `softwareVer` in login response |
| GET | `/v2/robot/<BLID>/missions` | 403 | Mission history |
| GET | `/v2/robot/<BLID>/preferences` | 403 | User preferences for this robot |
| GET | `/v2/robot/<BLID>/state` | 403 | Robot state; available via shadow instead |
