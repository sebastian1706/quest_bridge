#!/bin/bash
# Frees the RealSense from g1-realsense.service (the mybotshop ROS2 camera node), resets
# its USB state, frees the ZED-M from zed-web.service (Haseeb's always-on WebRTC live-view
# - the ZED SDK allows only one process to hold the camera at a time), then starts
# teleimager-pc2.
#
# The robot carries a SECOND RealSense (D435, no "i" - the hip-mounted camera used by
# floorgps.service, always-on, unrelated to quest_bridge). This script must never touch
# it, not even indirectly: not reset it, and not make it visible to teleimager-pc2's
# container (its own enumeration code touches every RealSense it can see, regardless of
# which one is actually configured - see cam_config_server.yaml head_camera). So instead
# of a blanket `-v /dev:/dev` + `--device-cgroup-rule`, every step below discovers the
# head camera's *current* USB device and /dev/videoN nodes fresh at runtime, identified
# by its USB product string ("435i", distinguishing it from the hip camera's plain "435")
# rather than by number - those numbers are not stable across resets/replugs.
#
# Also passes through the ZED-M (cam_config_server.yaml zed_camera), found the same way
# by its USB product string ("ZED-M", exact match - the ZED also exposes a separate HID
# sub-device reported as "ZED-M Hid Device" on a different USB bus, which must NOT be
# matched here since it carries no video4linux nodes). Unlike the head camera, the ZED
# gets none of the reset/quirk treatment above - it's optional: if unplugged, the script
# just skips it and starts the container with the head camera only.
#
# zed_camera is `type: opencv` (V4L2 via OpenCV), not `type: uvc` (pyuvc/libuvc over raw
# USB) - see the ZED_CAMERA_BLOCK comment in cam_config_server.yaml for why. That means,
# unlike an earlier version of this script, only the ZED-M's /dev/videoN node needs to be
# passed through - no /dev/bus/usb/<bus> access required.

set -euo pipefail

cd "$(dirname "$0")"

IMAGE=quest_bridge-teleimager-pc2
CONTAINER=teleimager-pc2
HEAD_CAMERA_SERIAL="348522072474"  # must match cam_config_server.yaml head_camera.serial_number
CONFIG_HOST_PATH="teleimager-service-pc2/cam_config_server.yaml"  # source of truth; a
  # zed_camera-stripped copy is generated at runtime below when the ZED-M isn't present

echo "Stopping g1-realsense.service ..."
sudo systemctl stop g1-realsense.service || echo "  (already inactive)"

echo "Verifying no RealSense ROS2 node remains ..."
if ros2 node list 2>/dev/null | grep -qi "d435\|realsense"; then
  echo "ERROR: a RealSense ROS2 node is still running:" >&2
  ros2 node list | grep -i "d435\|realsense" >&2
  exit 1
fi

# The ZED SDK only ever allows one process to hold the camera open at a time (this is
# a ZED SDK limitation, not something either service imposes) - zed-web.service (Haseeb's
# WebRTC live-view + telemetry API, /home/unitree/haseeb/zed-demo/zed_web.py, always-on
# via systemd) already owns it whenever it's running, and its own source comments say as
# much: a second consumer has to stop zed-web first. Without this, the ZED-M enumerates
# fine, gets real /dev/videoN nodes, and matches cam_config_server.yaml's physical_path -
# but VIDIOC_REQBUFS inside the container fails with EBUSY the moment zed_camera tries to
# actually start streaming, which teleimager-server only reports as a generic "Cannot
# find UVCCamera for zed_camera" (indistinguishable from the ZED-M being absent).
echo "Stopping zed-web.service (ZED SDK allows only one camera owner at a time) ..."
sudo systemctl stop zed-web.service || echo "  (already inactive)"
if systemctl is-active --quiet zed-web.service; then
  echo "ERROR: zed-web.service is still active - the ZED-M will stay busy (EBUSY) for teleimager-pc2." >&2
  exit 1
fi

echo "Building teleimager-pc2 image ..."
sudo docker compose build teleimager-pc2

# Finds the head camera's current USB bus-id (stable across the resets below - unlike
# /dev/videoN numbers, a USB device's sysfs bus-id doesn't change on unbind/rebind or
# hardware_reset(), only on an actual replug into a different port).
find_head_usb_dev() {
  for dev in /sys/bus/usb/devices/*; do
    if [[ -f "$dev/product" ]] && grep -qi "435i" "$dev/product" 2>/dev/null; then
      basename "$dev"
      return 0
    fi
  done
  return 1
}

# Lists the given USB device's current /dev/videoN nodes, by resolving each
# video4linux device's "device" symlink and checking whether the USB bus-id appears as
# a path segment (not just a substring - "2-2.1" must not match "2-2.10").
list_video_nodes_for_usb_dev() {
  local usb_dev="$1"
  for v4l_dev in /sys/class/video4linux/video*; do
    local dev_path
    dev_path="$(readlink -f "$v4l_dev/device" 2>/dev/null)"
    if [[ "$dev_path" == *"/$usb_dev/"* || "$dev_path" == *"/$usb_dev" ]]; then
      echo "/dev/$(basename "$v4l_dev")"
    fi
  done
}

# ZED-M's product string is an exact match ("ZED-M"), unlike the head camera's
# substring match - it must not also match the ZED's own "ZED-M Hid Device" USB
# sub-device (a separate top-level entry under /sys/bus/usb/devices/, no video4linux
# nodes of its own).
find_zed_usb_dev() {
  for dev in /sys/bus/usb/devices/*; do
    if [[ -f "$dev/product" ]] && grep -qix "ZED-M" "$dev/product" 2>/dev/null; then
      basename "$dev"
      return 0
    fi
  done
  return 1
}

echo "Locating head camera (USB product string containing '435i') ..."
HEAD_USB_DEV="$(find_head_usb_dev)" || {
  echo "ERROR: could not find the head camera (product string containing '435i') under /sys/bus/usb/devices/ - is it connected?" >&2
  exit 1
}
echo "Found head camera at USB device $HEAD_USB_DEV"

echo "Locating ZED-M (optional) ..."
ZED_VIDEO_NODES=()
if ZED_USB_DEV="$(find_zed_usb_dev)"; then
  echo "Found ZED-M at USB device $ZED_USB_DEV"
  mapfile -t ZED_VIDEO_NODES < <(list_video_nodes_for_usb_dev "$ZED_USB_DEV")
  if [[ ${#ZED_VIDEO_NODES[@]} -eq 0 ]]; then
    # Even over V4L2, something opening the ZED-M raw (e.g. the ZED SDK, as
    # zed-web.service does) can leave uvcvideo unbound from its interfaces if killed
    # hard instead of releasing cleanly - its /dev/videoN nodes then disappear until
    # something rebinds the driver. Unlike the head camera, nothing else does that for
    # the ZED-M automatically, so retry once via the same sysfs unbind/rebind dance used
    # for the head camera below, scoped to just this device.
    echo "No /dev/videoN nodes under ZED-M's USB device ($ZED_USB_DEV) - retrying via a sysfs unbind/rebind (likely an orphaned uvcvideo binding from a previous run) ..."
    echo "$ZED_USB_DEV" | sudo tee /sys/bus/usb/drivers/usb/unbind >/dev/null
    sleep 1
    echo "$ZED_USB_DEV" | sudo tee /sys/bus/usb/drivers/usb/bind >/dev/null
    sleep 2
    mapfile -t ZED_VIDEO_NODES < <(list_video_nodes_for_usb_dev "$ZED_USB_DEV")
  fi
  if [[ ${#ZED_VIDEO_NODES[@]} -eq 0 ]]; then
    echo "WARNING: found the ZED-M's USB device ($ZED_USB_DEV) but still no /dev/videoN nodes under it after a rebind - starting without it."
  else
    echo "ZED-M video nodes: ${ZED_VIDEO_NODES[*]}"
  fi
else
  echo "ZED-M not connected - starting with the head camera only."
fi

# Disable USB3 Link Power Management (LPM) for the head camera specifically, via the
# kernel's USB quirks mechanism (vendorID:productID:quirks, 'u' = USB_QUIRK_NO_LPM).
# Without this, the kernel periodically negotiates the link into low-power U1/U2
# states; on this Jetson's tegra-xusb controller the RealSense doesn't comply
# ("Disable of device-initiated U1/U2 failed" in journalctl -k), and the controller
# eventually resets the port - a spontaneous disconnect/reconnect with a NEW device
# number, minutes into an otherwise-healthy run. Docker's --device mapping is fixed at
# container start, so that reconnect orphans the container's device nodes and crashes
# the server ("head_camera is ready... Running..." then it silently exits later).
#
# There is no per-device sysfs LPM toggle on this kernel - power/usb3_hardware_lpm_u1
# and _u2 are read-only status attributes, not controls (confirmed: mode 444). The
# usbcore quirks module parameter is the actual control, and it only takes effect at
# enumeration time, so it must be set here, BEFORE the resets below cause the device
# to re-enumerate - setting it after wouldn't apply to the already-enumerated device.
#
# Scoped to just this camera's vendor:product ID (8086:0b3a, the D435I) - the hip
# camera is a different product (8086:0b07, plain D435, floorgps.service) and is
# unaffected by this quirk.
HEAD_USB_VID="$(cat "/sys/bus/usb/devices/$HEAD_USB_DEV/idVendor")"
HEAD_USB_PID="$(cat "/sys/bus/usb/devices/$HEAD_USB_DEV/idProduct")"
QUIRK_ENTRY="${HEAD_USB_VID}:${HEAD_USB_PID}:u"
CURRENT_QUIRKS="$(cat /sys/module/usbcore/parameters/quirks)"
if [[ "$CURRENT_QUIRKS" != *"$QUIRK_ENTRY"* ]]; then
  NEW_QUIRKS="$QUIRK_ENTRY"
  [[ -n "$CURRENT_QUIRKS" ]] && NEW_QUIRKS="${CURRENT_QUIRKS},${QUIRK_ENTRY}"
  echo "$NEW_QUIRKS" | sudo tee /sys/module/usbcore/parameters/quirks >/dev/null
  echo "Disabled USB3 LPM for head camera ($HEAD_USB_VID:$HEAD_USB_PID) via usbcore quirks."
else
  echo "USB3 LPM already disabled for head camera ($HEAD_USB_VID:$HEAD_USB_PID)."
fi

mapfile -t HEAD_VIDEO_NODES < <(list_video_nodes_for_usb_dev "$HEAD_USB_DEV")
if [[ ${#HEAD_VIDEO_NODES[@]} -eq 0 ]]; then
  echo "ERROR: found the head camera's USB device ($HEAD_USB_DEV) but no /dev/videoN nodes under it." >&2
  exit 1
fi
echo "Head camera video nodes: ${HEAD_VIDEO_NODES[*]}"

DEVICE_ARGS=()
for node in "${HEAD_VIDEO_NODES[@]}"; do
  DEVICE_ARGS+=(--device "$node")
done

echo "Hardware-resetting head camera (RealSense firmware-level reset, head camera only) ..."
sudo docker run --rm --network host \
  "${DEVICE_ARGS[@]}" \
  --entrypoint python3 "$IMAGE" -c '
import sys
import time
import pyrealsense2 as rs

HEAD_CAMERA_SERIAL = "'"$HEAD_CAMERA_SERIAL"'"

ctx = rs.context()
devices = ctx.query_devices()
if len(devices) == 0:
    print("No RealSense device found - check the USB connection.")
    sys.exit(1)

target = next((d for d in devices if d.get_info(rs.camera_info.serial_number) == HEAD_CAMERA_SERIAL), None)
if target is None:
    found = [d.get_info(rs.camera_info.serial_number) for d in devices]
    print(f"ERROR: head camera {HEAD_CAMERA_SERIAL} not found among connected RealSense devices: {found}")
    sys.exit(1)

print(f"Hardware-resetting RealSense {HEAD_CAMERA_SERIAL} (head camera only) ...")
target.hardware_reset()

# Reset causes the device to drop off and re-enumerate on the USB bus.
time.sleep(5)
print("Reset done.")
'

# A software hardware_reset() (above) doesn't always fully clear uvcvideo's driver
# state the way a physical unplug/replug would, which then makes librealsense's
# VIDIOC_S_FMT call fail with "Device or resource busy" once the server tries to open
# the camera. teleimager's image_server.py tries to work around this itself via
# `sudo modprobe -r uvcvideo`, but that runs inside the container, which has neither a
# `sudo` binary nor the CAP_SYS_MODULE/`/lib/modules` access needed - it always fails
# there.
#
# Don't do a *module* reload here on the host either: uvcvideo is the *shared* driver
# for every UVC camera on this system (both RealSense units, plus video_hub_pc4's own
# cameras) - `modprobe -r uvcvideo` requires nothing be bound to it, which is never
# true here, so it always fails with "Module uvcvideo is in use", and even if it could
# succeed, unloading it would drop the hip camera (floorgps.service) and everything
# else on the bus, not just the head camera.
#
# Instead, unbind/rebind only the head camera's own USB *device* via sysfs - the same
# effect as a physical unplug/replug, scoped to just this one device.
echo "Resetting head camera's USB device via sysfs unbind/rebind (scoped to just this device, not the shared uvcvideo driver) ..."
echo "$HEAD_USB_DEV" | sudo tee /sys/bus/usb/drivers/usb/unbind >/dev/null
sleep 1
echo "$HEAD_USB_DEV" | sudo tee /sys/bus/usb/drivers/usb/bind >/dev/null
# 5s settle time - shorter delays weren't enough for all interfaces/extension-unit
# sysfs entries to be ready, causing "UVCIOC_CTRL_QUERY ... No such file or directory"
# when teleimager-server queried the serial number immediately after.
sleep 5

# The unbind/rebind above can change which /dev/videoN numbers the head camera owns
# (same USB port, but v4l2 minor numbers aren't guaranteed stable across a reset) -
# re-discover them now rather than reusing HEAD_VIDEO_NODES from before the reset.
mapfile -t HEAD_VIDEO_NODES < <(list_video_nodes_for_usb_dev "$HEAD_USB_DEV")
if [[ ${#HEAD_VIDEO_NODES[@]} -eq 0 ]]; then
  echo "ERROR: head camera's USB device ($HEAD_USB_DEV) has no /dev/videoN nodes after the reset - is it still connected?" >&2
  exit 1
fi
echo "Head camera video nodes after reset: ${HEAD_VIDEO_NODES[*]}"

for node in "${HEAD_VIDEO_NODES[@]}"; do
  holder_pid="$(fuser "$node" 2>/dev/null | tr -d ' ' || true)"
  if [[ -n "$holder_pid" ]]; then
    holder_cmd="$(ps -p "$holder_pid" -o args= 2>/dev/null || echo unknown)"
    echo "ERROR: $node belongs to the head camera but is already held open by PID $holder_pid ($holder_cmd)." >&2
    exit 1
  fi
done
echo "Head camera nodes free: ${HEAD_VIDEO_NODES[*]}"

# Re-check the ZED-M's nodes too, right before the final run - the head camera's
# unbind/rebind above only touches its own USB device, but re-discovering fresh here
# (rather than trusting the pre-reset ZED_VIDEO_NODES) costs nothing and avoids relying
# on v4l minor numbers staying put across someone else's USB activity in the meantime.
if [[ -n "${ZED_USB_DEV:-}" ]]; then
  mapfile -t ZED_VIDEO_NODES < <(list_video_nodes_for_usb_dev "$ZED_USB_DEV")
  if [[ ${#ZED_VIDEO_NODES[@]} -eq 0 ]]; then
    echo "WARNING: ZED-M's USB device ($ZED_USB_DEV) has no /dev/videoN nodes anymore - starting without it."
  fi
fi

DEVICE_ARGS=()
for node in "${HEAD_VIDEO_NODES[@]}" "${ZED_VIDEO_NODES[@]}"; do
  DEVICE_ARGS+=(--device "$node")
done

# cam_config_server.yaml is baked into the image at build time (Dockerfile COPY) and
# image_server.py's CONFIG_PATH is hard-coded, with no CLI override - so when the ZED-M
# isn't present, the only way to actually leave it unconfigured for this run (rather than
# have ImageServer.start() abort the whole server, head_camera included, the moment it
# can't find an OpenCVCamera for zed_camera - see image_server.py) is to bind-mount a
# zed_camera-stripped copy of the config over the image's copy at the exact same path.
CONFIG_MOUNT_ARGS=()
if [[ ${#ZED_VIDEO_NODES[@]} -eq 0 ]]; then
  STRIPPED_CONFIG="$(mktemp /tmp/cam_config_server.no-zed.XXXXXX.yaml)"
  trap 'rm -f "$STRIPPED_CONFIG"' EXIT
  awk '/# --- ZED_CAMERA_BLOCK_START/{skip=1} !skip; /# --- ZED_CAMERA_BLOCK_END/{skip=0}' \
    "$CONFIG_HOST_PATH" > "$STRIPPED_CONFIG"
  CONFIG_MOUNT_ARGS=(-v "$STRIPPED_CONFIG:/opt/teleimager/cam_config_server.yaml:ro")
  echo "ZED-M not present - starting with zed_camera stripped from cam_config_server.yaml for this run."
fi

if [[ ${#ZED_VIDEO_NODES[@]} -gt 0 ]]; then
  echo "Starting teleimager-pc2 (head camera + ZED-M nodes - hip camera stays invisible to this container) ..."
else
  echo "Starting teleimager-pc2 (head camera nodes only - hip camera stays invisible to this container) ..."
fi
sudo docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
sudo docker run --rm --name "$CONTAINER" --network host \
  "${DEVICE_ARGS[@]}" \
  "${CONFIG_MOUNT_ARGS[@]}" \
  "$IMAGE"
