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
```

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
| `IMG_SERVER_IP` | — | LAN IP of the camera server (ego mode) |
| `WEBRTC_PORT` | `60001` | Port of the WebRTC camera server |

## ZMQ Payload

Topic `teledata`, msgpack-encoded:

```json
{
  "timestamp": 1234567890.0,
  "hand_mode": false,
  "head_pose":        {"pos": [x, y, z], "quat": [x, y, z, w]},
  "left_wrist_pose":  {"pos": [x, y, z], "quat": [x, y, z, w]},
  "right_wrist_pose": {"pos": [x, y, z], "quat": [x, y, z, w]},
  "buttons": {
    "right_trigger": false,
    "right_squeeze": false,
    "right_aButton": false,
    "right_bButton": false,
    "left_trigger":  false,
    "left_squeeze":  false,
    "left_aButton":  false,
    "left_bButton":  false
  }
}
```

In hand tracking mode, `buttons` contains `pinch`/`pinchValue`/`squeeze`/`squeezeValue` per hand instead.

Poses are read directly from `tv.tvuer.*_arm_pose` — **without** the hip transformation
from `get_tele_data()`, which is designed for Unitree humanoid IK and not suitable for a
fixed robot arm. The coordinate transformation into the robot base frame is the subscriber's responsibility.

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
