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
