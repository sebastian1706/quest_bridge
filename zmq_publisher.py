"""
Quest 3 -> televuer -> ZMQ PUB (tcp://*:5555, Topic "teledata").

Pendant zu receive_test.py (das bleibt als reines stdout-Test-Skript
unveraendert) - dieses Skript ist fuer den produktiven Anschluss an einen
ROS2-Bridge-Node gedacht (siehe xr_pose_bridge.py im Hauptrepo).

Modus wählen ohne Rebuild:
  docker compose run -e HAND_TRACKING=true  zmq-publisher
  docker compose run -e HAND_TRACKING=false zmq-publisher

Kamerabild im Headset (ego-Modus statt nur Passthrough):
  IMG_SERVER_IP muss auf die LAN-IP dieses Rechners gesetzt werden (vom Quest
  erreichbar), WEBRTC_PORT muss zum webrtc_port in
  teleimager-service/cam_config_server.yaml passen (Default dort: 60001).
  Parameter (img_shape/binocular) 1:1 aus cam_config_server.yaml uebernommen -
  muss synchron gehalten werden, falls sich die Kamera-Config aendert.

ZMQ-Payload (msgpack-kodiert, Topic "teledata"):
  {
    "timestamp": float,
    "hand_mode": bool,
    "head_pose":        {"pos": [x,y,z], "quat": [x,y,z,w]},
    "left_wrist_pose":  {"pos": [...], "quat": [...]},
    "right_wrist_pose": {"pos": [...], "quat": [...]},
    "buttons": {...}   # Feldnamen je nach hand_mode, siehe build_buttons()
  }

  head_pose/left_wrist_pose/right_wrist_pose kommen NICHT aus televuers
  get_tele_data() (data.left_wrist_pose/right_wrist_pose), sondern direkt aus
  den rohen tv.tvuer.*_pose-Properties. Grund: get_tele_data() referenziert
  Wrist-Posen relativ zu einer virtuellen "Hueft"-Position (kopfgier-
  abhaengig) - das ist Unitree-Humanoid-IK-spezifisch und fuer einen
  ortsfesten Roboterarm nicht sinnvoll. Die Daten werden ohne
  Frame-Transformation gesendet; der Subscriber ist fuer die roboter-
  spezifische Koordinatentransformation zustaendig.
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
print(f"Modus: {'Hand-Tracking' if hand_mode else 'Controller'}")

if img_server_ip:
    display_mode = "ego"
    webrtc = True
    webrtc_url = f"https://{img_server_ip}:{webrtc_port}/offer"
    print(f"Kamerabild (ego-Modus) ueber {webrtc_url}")
else:
    display_mode = "pass-through"
    webrtc = False
    webrtc_url = None
    print("IMG_SERVER_IP nicht gesetzt -> reiner Passthrough-Modus, kein Kamerabild im Headset.")

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
        "left_triggerValue": float(tv.tvuer.left_ctrl_triggerValue),
        "left_squeeze": bool(data.left_ctrl_squeeze),
        "left_aButton": bool(data.left_ctrl_aButton),
        "left_bButton": bool(data.left_ctrl_bButton),
        "right_trigger": bool(data.right_ctrl_trigger),
        "right_triggerValue": float(tv.tvuer.right_ctrl_triggerValue),
        "right_squeeze": bool(data.right_ctrl_squeeze),
        "right_aButton": bool(data.right_ctrl_aButton),
        "right_bButton": bool(data.right_ctrl_bButton),
    }


ctx = zmq.Context()
pub = ctx.socket(zmq.PUB)
pub.bind(f"tcp://*:{zmq_port}")
print(f"ZMQ PUB auf tcp://*:{zmq_port}, Topic 'teledata'")

print("=" * 60)
print("Warte auf Quest-Verbindung...")
print("Auf der Quest im Browser oeffnen:")
print(f"  https://{host_ip}:8012/?ws=wss://{host_ip}:8012")
print("Sicherheitswarnung bestaetigen, dann AR/VR klicken.")
print("=" * 60)

_last_ready = None
while True:
    data = tv.get_tele_data()
    if not data.motion_data_ready:
        if _last_ready is not False:
            print("[warten] motion_data_ready=False")
            _last_ready = False
        time.sleep(0.1)
        continue
    _last_ready = True

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
    pub.send_multipart([b"teledata", msgpack.packb(payload, use_bin_type=True)])
    
    pos_head = tv.tvuer.head_pose[:3, 3]
    pos_left = tv.tvuer.left_arm_pose[:3, 3]
    pos_right = tv.tvuer.right_arm_pose[:3, 3]
    if hand_mode:
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"pinch L={data.left_hand_pinchValue:.2f}  R={data.right_hand_pinchValue:.2f}"
        )
    else:
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})"
        )
    time.sleep(0.05)
