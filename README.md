# quest_bridge

Docker-based bridge between Meta Quest 3 and a robot.
Receives pose and button data from the Quest 3 via [televuer](https://github.com/unitreerobotics/televuer)
and publishes it via ZMQ (msgpack, topic `teledata`).

## Quick start

```powershell
# Windows
.\start.ps1
```

```bash
# Linux / Pi
./start.sh

# Fixed-base arm (UR): the pose convention must be "serial"
KINEMATICS=serial ./start.sh
```

> **`KINEMATICS` defaults to `unitree`.** Those poses are head/waist-relative and
> axis-corrected for a humanoid. Start a UR session with `KINEMATICS=serial`, otherwise the
> robot moves — just not in a way that matches the controller. The published payload carries
> the convention in use, so a subscriber can refuse a mismatch at startup.

The correct browser link is printed to the terminal at startup.
Accept the security warning → click AR/VR.

Alternatively, run directly with `docker compose` (IP must be provided manually):

```bash
docker compose run --service-ports --build -e HOST_IP=192.168.x.x zmq-publisher
```

Optional environment variables:

| Variable | Default | Description |
|---|---|---|
| `HOST_IP` | — | LAN IP of the host PC (set automatically by the start scripts) |
| `HAND_TRACKING` | `false` | `true` to use hand tracking instead of controllers |
| `KINEMATICS` | `unitree` | Pose convention of the published poses: `unitree` (humanoid, head/waist-relative) or `serial` (fixed-base arm such as a UR, raw poses), see [Pose source](#pose-source). **A UR needs `serial`.** |
| `IMG_SERVER_IP` | — | LAN IP of the camera server (ego mode) |
| `WEBRTC_PORT` | `60001` | Port of the WebRTC camera server |
| `ZMQ_PORT` | `5555` | Port of the ZMQ publisher (the port mapping in `docker-compose.yml` is fixed to `5555` and must be changed with it) |

`docker-compose.yml` forwards `KINEMATICS` like every other variable, so setting it in the
environment is enough:

```bash
KINEMATICS=serial ./start.sh
# or
KINEMATICS=serial docker compose run --service-ports --build -e HOST_IP=192.168.x.x zmq-publisher
```

## ZMQ Payload

Topic `teledata`, msgpack-encoded, sent as a ZMQ multipart message `[b"teledata", payload]`
at about 20 Hz:

```json
{
  "timestamp": 1234567890.0,
  "hand_mode": false,
  "kinematics": "unitree",
  "head_pose":        {"pos": [x, y, z], "quat": [x, y, z, w]},
  "left_wrist_pose":  {"pos": [x, y, z], "quat": [x, y, z, w]},
  "right_wrist_pose": {"pos": [x, y, z], "quat": [x, y, z, w]},
  "buttons": {
    "left_trigger": false,       "right_trigger": false,
    "left_triggerValue": 0.0,    "right_triggerValue": 0.0,
    "left_squeeze": false,       "right_squeeze": false,
    "left_aButton": false,       "right_aButton": false,
    "left_bButton": false,       "right_bButton": false,
    "left_thumbstick": false,    "right_thumbstick": false,
    "left_thumbstickValue": [0.0, 0.0],
    "right_thumbstickValue": [0.0, 0.0]
  }
}
```

Values: `*Value` fields are floats in `[0, 1]`, `*_thumbstickValue` is `[x, y]`, all other button
fields are booleans. Positions are in meters, quaternions in `[x, y, z, w]` order.
`kinematics` reports the pose convention in use, so a subscriber can refuse a mismatch at
startup instead of moving in ways that do not match the controller.

In **hand-tracking mode** (`hand_mode: true`), `buttons` contains instead:

```json
"buttons": {
  "left_pinch": false,         "right_pinch": false,
  "left_pinchValue": 0.0,      "right_pinchValue": 0.0,
  "left_squeeze": false,       "right_squeeze": false,
  "left_squeezeValue": 0.0,    "right_squeezeValue": 0.0
}
```

and the payload additionally contains the hand landmarks needed for dex3/inspire/brainco
retargeting (Unitree hand-URDF convention, relative to the wrist):

```json
"left_hand_pos":  [[x, y, z], ...],   // 25 x 3
"right_hand_pos": [[x, y, z], ...]    // 25 x 3
```

### Pose source

Which poses are published depends on `KINEMATICS`, **not** on the input mode. `HAND_TRACKING`
only selects controllers or hand tracking as the input source.

- **`KINEMATICS=unitree`** (default): poses from `tv.get_tele_data()` for both input modes.
  They are expressed relative to the operator's head/waist and axis-corrected, as expected by
  the Unitree humanoid IK (`teleop_hand_and_arm.py`). For hand tracking this also includes the
  rotation fix for the OpenXR hand-tracking convention.
- **`KINEMATICS=serial`**: raw poses from `tv.tvuer.head_pose` / `tv.tvuer.*_arm_pose` for both input
  modes, without the head/waist transform. Use this for a fixed-base arm such as a UR. The
  transformation into the robot base frame is the subscriber's responsibility.

> **Note:** With `KINEMATICS=serial` and `HAND_TRACKING=true`, the raw hand-tracking pose uses
> the OpenXR hand-tracking axis layout, which differs from the controller pose, and the rotation
> fix from `get_tele_data()` is not applied. The subscriber has to account for this. Controller
> input is not affected.

## Changes vs. upstream televuer

**Problem:** The upstream `on_controller_move` handler in
[televuer.py](https://github.com/unitreerobotics/televuer) writes the controller pose
directly into shared memory:

```python
# upstream (buggy)
self.left_arm_pose_shared[:] = event.value["left"]
```

When a controller is not connected or not yet tracked by the Quest, the Quest browser sends
a **msgpack ExtType** (`code=0, data=b'\x00'`) instead of a 16-float list — the JavaScript
encoding of `undefined`. The direct assignment then raises a `TypeError`.
Since the handler has a bare `except: pass`, the error is silently swallowed — and all
subsequent lines (buttons, `motion_data_ready = True`) are never reached.

**Effect:** Buttons don't work, and the stream only starts after briefly activating hand
tracking (because only then is `motion_data_ready` set to `True`).

**Fix in this repo** (`televuer/src/televuer/televuer.py`):

```python
# only write pose if it's a real list
left_pose = event.value.get("left")
right_pose = event.value.get("right")
if isinstance(left_pose, list):
    with self.left_arm_pose_shared.get_lock():
        self.left_arm_pose_shared[:] = left_pose
if isinstance(right_pose, list):
    with self.right_arm_pose_shared.get_lock():
        self.right_arm_pose_shared[:] = right_pose

# always process buttons, regardless of pose
left_controller = event.value.get("leftState", {})
right_controller = event.value.get("rightState", {})
```

Result:
- Buttons work immediately on connection
- Stream starts without prior hand tracking
- Single controllers (e.g. right only) work correctly
