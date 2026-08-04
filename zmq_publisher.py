"""
Quest 3 -> televuer -> ZMQ PUB (tcp://*:5555, topic "teledata").

Counterpart to receive_test.py (which remains a pure stdout test script) —
this script is intended for the productive connection to a ROS2 bridge node or any other ZMQ connection

Switch mode without rebuild:
  docker compose run -e HAND_TRACKING=true  zmq-publisher
  docker compose run -e HAND_TRACKING=false zmq-publisher

Camera image in headset (ego mode instead of passthrough only):
  IMG_SERVER_IP must be set to the LAN IP of this machine (reachable by the Quest),
  WEBRTC_PORT must match the webrtc_port in teleimager-service/cam_config_server.yaml
  (default: 60001). Parameters (img_shape/binocular) taken 1:1 from cam_config_server.yaml —
  must be kept in sync if the camera config changes.

ZMQ payload (msgpack-encoded, topic "teledata"):
  {
    "timestamp": float,
    "hand_mode": bool,
    "head_pose":        {"pos": [x,y,z], "quat": [x,y,z,w]},
    "left_wrist_pose":  {"pos": [...], "quat": [...]},
    "right_wrist_pose": {"pos": [...], "quat": [...]},
    "buttons": {...}   # field names depend on hand_mode, see build_buttons()
    # hand_mode only, needed for dex3/inspire/brainco retargeting:
    "left_hand_pos":  [[x,y,z], ...],   # (25,3) landmark positions
    "right_hand_pos": [[x,y,z], ...],   # (25,3) landmark positions
  }

Pose source depends on hand_mode:
  - hand_mode=False (controller): tv.tvuer.left/right_arm_pose (raw). Controller pose
    already follows the Unitree arm convention directly, no fix needed.
  - hand_mode=True (hand tracking): tv.get_tele_data().left/right_wrist_pose. The raw
    tv.tvuer.left/right_arm_pose is in OpenXR hand-tracking convention (different axis
    layout than the controller pose) and needs the rotation fix get_tele_data() applies.
    Note: get_tele_data() also re-expresses the pose relative to the (Unitree-specific)
    head/waist frame -- if that offset is not wanted for your robot, subtract it back out
    downstream; see left_wrist_pose/right_wrist_pose in televuer/src/televuer/tv_wrapper.py.
"""
import os
import time

import msgpack
import numpy as np
import zmq
from televuer import TeleVuerWrapper

hand_mode = os.environ.get("HAND_TRACKING", "false").lower() == "true"
host_ip = os.environ.get("HOST_IP", "") or "<PC-LAN-IP>"
img_server_ip = os.environ.get("IMG_SERVER_IP", "")
webrtc_port = os.environ.get("WEBRTC_PORT", "60001")
zmq_port = os.environ.get("ZMQ_PORT", "5555")
print(f"Mode: {'Hand tracking' if hand_mode else 'Controller'}")

if img_server_ip:
    display_mode = "ego"
    webrtc = True
    webrtc_url = f"https://{img_server_ip}:{webrtc_port}/offer"
    print(f"Camera image (ego mode) via {webrtc_url}")
else:
    display_mode = "pass-through"
    webrtc = False
    webrtc_url = None
    print("IMG_SERVER_IP not set -> passthrough mode, no camera image in headset.")

tv = TeleVuerWrapper(
    use_hand_tracking=hand_mode,
    binocular=False,
    img_shape=(480, 640),
    display_mode=display_mode,
    webrtc=webrtc,
    webrtc_url=webrtc_url,
    cert_file="/certs/cert.pem",
    key_file="/certs/key.pem",
)


def mat_to_pos_quat(mat):
    pos = mat[:3, 3].tolist()
    r = mat[:3, :3]
    tr = r[0, 0] + r[1, 1] + r[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        qw = 0.25 * s
        qx = (r[2, 1] - r[1, 2]) / s
        qy = (r[0, 2] - r[2, 0]) / s
        qz = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        qw = (r[2, 1] - r[1, 2]) / s
        qx = 0.25 * s
        qy = (r[0, 1] + r[1, 0]) / s
        qz = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        qw = (r[0, 2] - r[2, 0]) / s
        qx = (r[0, 1] + r[1, 0]) / s
        qy = 0.25 * s
        qz = (r[1, 2] + r[2, 1]) / s
    else:
        s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        qw = (r[1, 0] - r[0, 1]) / s
        qx = (r[0, 2] + r[2, 0]) / s
        qy = (r[1, 2] + r[2, 1]) / s
        qz = 0.25 * s
    return pos, [qx, qy, qz, qw]


def build_buttons(data):
    if hand_mode:
        return {
            "left_pinch": bool(data.left_hand_pinch),
            "left_pinchValue": float(data.left_hand_pinchValue),
            "left_squeeze": bool(data.left_hand_squeeze),
            "left_squeezeValue": float(data.left_hand_squeezeValue),
            "right_pinch": bool(data.right_hand_pinch),
            "right_pinchValue": float(data.right_hand_pinchValue),
            "right_squeeze": bool(data.right_hand_squeeze),
            "right_squeezeValue": float(data.right_hand_squeezeValue),
        }
    return {
        "left_trigger": bool(data.left_ctrl_trigger),
        "left_triggerValue": float(data.left_ctrl_triggerValue),
        "left_squeeze": bool(data.left_ctrl_squeeze),
        "left_aButton": bool(data.left_ctrl_aButton),
        "left_bButton": bool(data.left_ctrl_bButton),
        "left_thumbstick": bool(data.left_ctrl_thumbstick),
        "left_thumbstickValue": [float(v) for v in data.left_ctrl_thumbstickValue],
        "right_trigger": bool(data.right_ctrl_trigger),
        "right_triggerValue": float(data.right_ctrl_triggerValue),
        "right_squeeze": bool(data.right_ctrl_squeeze),
        "right_aButton": bool(data.right_ctrl_aButton),
        "right_bButton": bool(data.right_ctrl_bButton),
        "right_thumbstick": bool(data.right_ctrl_thumbstick),
        "right_thumbstickValue": [float(v) for v in data.right_ctrl_thumbstickValue],
    }


ctx = zmq.Context()
pub = ctx.socket(zmq.PUB)
pub.bind(f"tcp://*:{zmq_port}")
print(f"ZMQ PUB on tcp://*:{zmq_port}, topic 'teledata'")

print("=" * 60)
print("Waiting for Quest connection...")
print("Open in Quest browser:")
print(f"  https://{host_ip}:8012/?ws=wss://{host_ip}:8012")
print("Accept the security warning, then click AR/VR.")
print("=" * 60)

_last_ready = None
while True:
    data = tv.get_tele_data()
    if not data.motion_data_ready:
        if _last_ready is not False:
            print("[waiting] motion_data_ready=False")
            _last_ready = False
        time.sleep(0.1)
        continue
    _last_ready = True

    head_pos_quat = mat_to_pos_quat(tv.tvuer.head_pose)
    if hand_mode:
        # tv.tvuer.left/right_arm_pose is in raw OpenXR hand-tracking convention here
        # (different axis layout than the controller pose). get_tele_data() applies the
        # rotation fix (T_TO_UNITREE_HUMANOID_LEFT/RIGHT_ARM) needed to align it, same as
        # the waist-relative pose upstream uses for IK -- see left_wrist_pose/right_wrist_pose.
        left_pos_quat = mat_to_pos_quat(data.left_wrist_pose)
        right_pos_quat = mat_to_pos_quat(data.right_wrist_pose)
    else:
        # controller pose already follows the Unitree arm convention directly, no fix needed.
        left_pos_quat = mat_to_pos_quat(tv.tvuer.left_arm_pose)
        right_pos_quat = mat_to_pos_quat(tv.tvuer.right_arm_pose)

    payload = {
        "timestamp": time.time(),
        "hand_mode": hand_mode,
        "head_pose": {"pos": head_pos_quat[0], "quat": head_pos_quat[1]},
        "left_wrist_pose": {"pos": left_pos_quat[0], "quat": left_pos_quat[1]},
        "right_wrist_pose": {"pos": right_pos_quat[0], "quat": right_pos_quat[1]},
        "buttons": build_buttons(data),
    }
    if hand_mode:
        # (25,3) fingertip/joint landmark positions, Unitree hand-URDF convention,
        # relative to the wrist -- needed for dex3/inspire/brainco retargeting.
        payload["left_hand_pos"] = data.left_hand_pos.tolist()
        payload["right_hand_pos"] = data.right_hand_pos.tolist()
    pub.send_multipart([b"teledata", msgpack.packb(payload, use_bin_type=True)])

    pos_head = tv.tvuer.head_pose[:3, 3]
    if hand_mode:
        pos_left = data.left_wrist_pose[:3, 3]
        pos_right = data.right_wrist_pose[:3, 3]
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})  "
            f"pinch L={data.left_hand_pinchValue:.2f}  R={data.right_hand_pinchValue:.2f}"
        )
    else:
        pos_left = tv.tvuer.left_arm_pose[:3, 3]
        pos_right = tv.tvuer.right_arm_pose[:3, 3]
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})"
        )
    time.sleep(0.05)
