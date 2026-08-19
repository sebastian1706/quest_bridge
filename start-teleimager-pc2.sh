#!/bin/bash
# Frees the RealSense from g1-realsense.service (the mybotshop ROS2 camera node), resets its USB state, then starts teleimager-pc2.

set -euo pipefail

cd "$(dirname "$0")"

IMAGE=quest_bridge-teleimager-pc2
CONTAINER=teleimager-pc2

echo "Stopping g1-realsense.service ..."
sudo systemctl stop g1-realsense.service || echo "  (already inactive)"

echo "Verifying no RealSense ROS2 node remains ..."
if ros2 node list 2>/dev/null | grep -qi "d435\|realsense"; then
  echo "ERROR: a RealSense ROS2 node is still running:" >&2
  ros2 node list | grep -i "d435\|realsense" >&2
  exit 1
fi

echo "Building teleimager-pc2 image ..."
sudo docker compose build teleimager-pc2

echo "Resetting RealSense USB state (equivalent to an unplug/replug) ..."
sudo docker run --rm --network host \
  --device-cgroup-rule='c 81:* rmw' -v /dev:/dev \
  --entrypoint python3 "$IMAGE" -c '
import sys
import time
import pyrealsense2 as rs

ctx = rs.context()
devices = ctx.query_devices()
if len(devices) == 0:
    print("No RealSense device found - check the USB connection.")
    sys.exit(1)

for d in devices:
    serial = d.get_info(rs.camera_info.serial_number)
    print(f"Hardware-resetting RealSense {serial} ...")
    d.hardware_reset()

# Reset causes the device to drop off and re-enumerate on the USB bus.
time.sleep(5)
print("Reset done.")
'

# A software hardware_reset() (above) doesn't always fully clear uvcvideo's
# driver state the way a physical unplug/replug would, which then makes
# librealsense's VIDIOC_S_FMT call fail with "Device or resource busy" once
# the server tries to open the camera. teleimager's image_server.py tries to
# work around this itself via `sudo modprobe -r uvcvideo`, but that runs
# inside the container, which has neither a `sudo` binary nor the
# CAP_SYS_MODULE/`/lib/modules` access needed to touch host kernel modules -
# it always fails there. Do the same reload here on the host instead, where
# it can actually succeed.
echo "Reloading uvcvideo driver to clear stale RealSense state ..."
sudo modprobe -r uvcvideo
sleep 1
sudo modprobe uvcvideo
sleep 2

echo "Starting teleimager-pc2 (any /dev/videoN the camera currently owns) ..."
sudo docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
sudo docker run --rm --name "$CONTAINER" --network host \
  --device-cgroup-rule='c 81:* rmw' -v /dev:/dev \
  "$IMAGE"
