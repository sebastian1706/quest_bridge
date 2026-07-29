"""
Minimal test: Quest 3 -> televuer -> stdout
No ZMQ, no ROS. Just verify that data arrives.

Switch mode without rebuild:
  docker compose run -e HAND_TRACKING=true  xr-receive
  docker compose run -e HAND_TRACKING=false xr-receive

Camera image in headset (ego mode instead of passthrough only):
  IMG_SERVER_IP must be set to the LAN IP of this machine (reachable by the Quest),
  WEBRTC_PORT must match the webrtc_port in teleimager-service/cam_config_server.yaml
  (default: 60001). Parameters (img_shape/binocular) taken 1:1 from cam_config_server.yaml —
  must be kept in sync if the camera config changes.
    docker compose run -e IMG_SERVER_IP=172.16.168.58 xr-receive
"""
import os, time
from televuer import TeleVuerWrapper

hand_mode = os.environ.get("HAND_TRACKING", "false").lower() == "true"
host_ip = os.environ.get("HOST_IP", "") or "<PC-LAN-IP>"
img_server_ip = os.environ.get("IMG_SERVER_IP", "")
webrtc_port = os.environ.get("WEBRTC_PORT", "60001")
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

    # pos_head  = data.head_pose[:3, 3]
    # pos_left  = data.left_wrist_pose[:3, 3]
    # pos_right = data.right_wrist_pose[:3, 3]
    pos_head = tv.tvuer.head_pose[:3, 3]
    pos_left = tv.tvuer.left_arm_pose[:3, 3]
    pos_right = tv.tvuer.right_arm_pose[:3, 3]

    if hand_mode:
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            f"pinch L={data.left_hand_pinchValue:.2f}  R={data.right_hand_pinchValue:.2f}  "
            f"squeeze L={data.left_hand_squeezeValue:.2f}  R={data.right_hand_squeezeValue:.2f}"
        )
    else:
        # continue
        print(
            f"head=({pos_head[0]:+.3f}, {pos_head[1]:+.3f}, {pos_head[2]:+.3f})  "
            # f"L=({pos_left[0]:+.3f}, {pos_left[1]:+.3f}, {pos_left[2]:+.3f})  "
            f"R=({pos_right[0]:+.3f}, {pos_right[1]:+.3f}, {pos_right[2]:+.3f})  "
            # f"trig L={data.left_ctrl_trigger:.2f} R={data.right_ctrl_trigger:.2f}  "
            # f"A={data.right_ctrl_aButton}  B={data.right_ctrl_bButton}"
        )
    time.sleep(0.05)
