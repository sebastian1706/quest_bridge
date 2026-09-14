# quest_bridge — Local End-to-End Teleop (G1)

Meta Quest → `quest_bridge` → G1 arm control, by using Unitree `xr_teleop`. 

## Local bring-up

Three terminals, started in this order.

### 1. Camera server (RealSense → WebRTC)

```bash
cd ~/quest_bridge
./start-teleimager-pc2.sh
```

Stops the conflicting `g1-realsense.service` (mybotshop's own ROS2 RealSense
node), resets the RealSense's USB state (equivalent to an unplug/replug, Leave it running in this terminal)

Check the raw camera feed directly, bypassing the Quest entirely, at:

```
https://172.16.169.18:60001/
```

(click "Start" — this is the built-in test client for the same stream the
Quest uses)

### 2. Pose/WebSocket bridge (Quest ↔ ZMQ)

```bash
cd ~/quest_bridge
sudo HAND_TRACKING=true IMG_SERVER_IP=172.16.169.18 bash ./start.sh
```

Prints the browser URL for the Quest at startup. Open it in the Quest
browser, accept the security warning, click AR/VR.

By default this shows the head_camera feed (monocular - same 2D image in both
eyes). For true stereo (real left/right parallax) from the ZED-M instead,
override all four together (must match zed_camera's webrtc_port/image_shape
in `teleimager-service-pc2/cam_config_server.yaml`; only one of
head_camera/zed_camera can be the active ego view at a time):

```bash
sudo HAND_TRACKING=true IMG_SERVER_IP=172.16.169.18 \
     WEBRTC_PORT=60004 BINOCULAR=true IMG_HEIGHT=376 IMG_WIDTH=1344 \
     bash ./start.sh
```

`start.sh` just forwards the shell environment through to `docker compose run`,
so any subset of `WEBRTC_PORT`/`BINOCULAR`/`IMG_HEIGHT`/`IMG_WIDTH` can be
overridden this way — see `zmq_publisher.py`'s module docstring for details
and the other 3 ZED-M resolutions available.

By default the camera feed shows as a small floating window with real-world
passthrough visible around it (`DISPLAY_MODE=ego`). For a fully immersive "as
if you were the camera" view instead — the feed fills the entire headset view,
**no passthrough at all** — add `DISPLAY_MODE=immersive`. Make sure the
operator is physically safe first (seated or spotted, no trip hazards, cable
slack): they will not be able to see their real surroundings.

First-time-per-port gotcha: the Quest's browser must separately visit and
accept each self-signed cert once — open `https://172.16.169.18:60001/` (and
`:60004/` for the ZED-M) directly in the **Quest's own browser** before
loading the Vuer bridge page, or the camera image silently fails to load
even though pose/hand-tracking still works fine.

`IMG_SERVER_IP` must point at wherever the camera server from step 1 is
running (same machine = same LAN IP). Without it, the Quest gets pose
tracking but no camera image (passthrough mode).

### 3. Robot arm control (xr_teleoperate)

```bash
conda activate tv
cd teleop
python teleop_hand_and_arm.py --input-mode=hand --tv-server-ip=192.168.123.164 --record --motion --ee=dex3
```

Consumes the `teledata` ZMQ stream published by step 2 and drives the G1's
arms (dex3 end effector). `--tv-server-ip` is this machine's address on the
robot's internal network — not the same interface as `IMG_SERVER_IP` above.

Stopping step 1 or 2 out from under step 3 leaves the arm control script
reading from a dead source — restart in the same order (1 → 2 → 3) if
anything upstream gets restarted.

### IPs may drift

Both `172.16.169.18` (LAN) and `192.168.123.164` (robot-internal) are this
machine's current addresses: check with `hostname -I` if either stops
being reachable, and the RealSense's `/dev/videoN` nodes can shift on
replug/reset (handled automatically by `start-teleimager-pc2.sh`, no action
needed there).

---
