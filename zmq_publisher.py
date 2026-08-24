"""
Quest 3 -> televuer -> ZMQ PUB (tcp://*:5555, topic "teledata").

Counterpart to receive_test.py (which remains a pure stdout test script) —
this script is intended for the productive connection to a ROS2 bridge node or any other ZMQ connection

Switch mode without rebuild:
  docker compose run -e HAND_TRACKING=true  zmq-publisher
  docker compose run -e HAND_TRACKING=false zmq-publisher

Switch target kinematics without rebuild (default: unitree):
  docker compose run -e KINEMATICS=unitree zmq-publisher   # G1 etc. via teleop_hand_and_arm.py
  docker compose run -e KINEMATICS=serial  zmq-publisher   # fixed-base arm, e.g. a UR5e subscriber

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

Pose source depends on KINEMATICS, independent of hand_mode (hand_mode only picks
hand-tracking vs. controller as the *input* source; KINEMATICS picks the *output*
convention):
  - KINEMATICS=unitree (default): tv.get_tele_data().head/left/right_wrist_pose, for both
    hand-tracking and controller input. get_tele_data() re-expresses the pose relative to
    the (moving) head/waist frame and, for hand-tracking, additionally applies the rotation
    fix needed because the raw hand-tracking pose is in OpenXR convention (different axis
    layout than the controller pose, which already matches). This is what
    teleop_hand_and_arm.py's IK (a Unitree humanoid) expects.
  - KINEMATICS=serial: tv.tvuer.head/left/right_arm_pose (raw, no head/waist-relative
    transform) -- for a fixed-base arm (e.g. a UR5e subscriber), where the Unitree-specific
    moving-waist/head transform would be wrong.
"""
import os
import time

import msgpack
import numpy as np
import zmq
from televuer import TeleVuerWrapper

hand_mode = os.environ.get("HAND_TRACKING", "false").lower() == "true"
unitree_target = os.environ.get("KINEMATICS", "unitree").lower() == "unitree"
host_ip = os.environ.get("HOST_IP", "") or "<PC-LAN-IP>"
img_server_ip = os.environ.get("IMG_SERVER_IP", "")
webrtc_port = os.environ.get("WEBRTC_PORT", "60001")
zmq_port = os.environ.get("ZMQ_PORT", "5555")
print(f"Mode: {'Hand tracking' if hand_mode else 'Controller'}")
print(f"Kinematics target: {'Unitree humanoid (head/waist-relative)' if unitree_target else 'Serial arm (raw pose)'}")

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
    # "head_yaw" (tv_wrapper.py default) also rotates the wrist-pose target by the operator's
    # live head yaw, coupling arm orientation to head rotation. This robot's camera isn't
    # head-tracked (fixed RealSense mount, no steerable neck), so that coupling only produced
    # unwanted arm drift when the operator turned their head. "head_position" keeps the wrist
    # pose correctly re-centered on the operator's live head *position* (so walking around still
    # works right) but drops the *rotation* coupling entirely - see
    # transform_IPunitree_Brobot_world_arm_to_head_then_waist() in tv_wrapper.py.
    arm_reference_mode="head_position",
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

    if unitree_target:
        # Unitree humanoid IK (teleop_hand_and_arm.py's arm_ik.solve_ik) expects the
        # head/waist-relative, axis-corrected pose that get_tele_data() produces --
        # for hand-tracking AND controller input alike (see tv_wrapper.py: both branches
        # run the basis-change + head/waist transform, controller just skips the extra
        # initial-arm-rotation fix since its raw pose already matches that convention).
        head_pos_quat = mat_to_pos_quat(data.head_pose)
        left_pos_quat = mat_to_pos_quat(data.left_wrist_pose)
        right_pos_quat = mat_to_pos_quat(data.right_wrist_pose)
    else:
        # Serial-kinematics / fixed-base arm: raw pose, no Unitree-specific head/waist
        # transform (that transform assumes a moving humanoid waist/head, not a bolted-down base).
        head_pos_quat = mat_to_pos_quat(tv.tvuer.head_pose)
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

    # reuse what was just computed/published above -- same source as the payload, no re-derivation
    pos_head, pos_left, pos_right = head_pos_quat[0], left_pos_quat[0], right_pos_quat[0]
    if hand_mode:
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})  "
            f"pinch L={data.left_hand_pinchValue:.2f}  R={data.right_hand_pinchValue:.2f}"
        )
    else:
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})"
        )
    time.sleep(0.05)
