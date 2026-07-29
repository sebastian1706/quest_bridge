# quest_bridge

Docker-basierter Bridge zwischen Meta Quest 3 und einem Roboter-Teleoperiations-System.
Empfängt Pose- und Button-Daten vom Quest 3 über [televuer](https://github.com/unitreerobotics/televuer)
und publiziert sie per ZMQ (msgpack, Topic `teledata`).

## Schnellstart

```powershell
# Windows
.\start.ps1
```

```bash
# Linux / Pi
./start.sh
```

Der korrekte Browser-Link wird beim Start im Terminal ausgegeben.  
Sicherheitswarnung bestätigen → AR/VR klicken.

Alternativ direkt mit `docker compose` (IP manuell angeben):

```bash
docker compose run --service-ports --build -e HOST_IP=192.168.x.x zmq-publisher
```

Optionale Env-Variablen:

| Variable | Default | Beschreibung |
|---|---|---|
| `HOST_IP` | — | LAN-IP des PCs (wird von den Start-Skripten automatisch gesetzt) |
| `HAND_TRACKING` | `false` | `true` für Hand-Tracking statt Controller |
| `IMG_SERVER_IP` | — | LAN-IP des Kamera-Servers (ego-Modus) |
| `WEBRTC_PORT` | `60001` | Port des WebRTC-Kamera-Servers |

## ZMQ-Payload

Topic `teledata`, msgpack-kodiert:

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

Im Hand-Tracking-Modus enthält `buttons` stattdessen `pinch`/`pinchValue`/`squeeze`/`squeezeValue` pro Hand.

Posen werden direkt aus `tv.tvuer.*_arm_pose` gelesen — **ohne** die Hüft-Transformation
aus `get_tele_data()`, die für Unitree-Humanoid-IK ausgelegt ist und für einen ortsfesten
Roboterarm nicht passt. Die Koordinatentransformation in das Roboter-Basisframe liegt beim
Subscriber.

## Änderung gegenüber upstream televuer

**Problem:** Der upstream `on_controller_move`-Handler in
[televuer.py](https://github.com/unitreerobotics/televuer) schreibt die Controller-Pose
direkt in den Shared Memory:

```python
# upstream (buggy)
self.left_arm_pose_shared[:] = event.value["left"]
```

Ist ein Controller nicht verbunden oder vom Quest noch nicht getrackt, schickt der
Quest-Browser statt einer 16-Float-Liste einen **msgpack ExtType** (`code=0, data=b'\x00'`),
die JavaScript-Kodierung von `undefined`. Die direkte Zuweisung wirft dann einen `TypeError`.
Da der Handler ein bare `except: pass` hat, wird der Fehler stumm verschluckt — und alle
nachfolgenden Zeilen (Buttons, `motion_data_ready = True`) werden nie erreicht.

**Folge:** Buttons funktionieren nicht, der Stream startet erst nachdem kurz Hand-Tracking
aktiv war (weil erst dann `motion_data_ready` auf `True` gesetzt wird).

**Fix in diesem Repo** (`televuer/src/televuer/televuer.py`):

```python
# Pose nur schreiben wenn es eine echte Liste ist
left_pose = event.value.get("left")
right_pose = event.value.get("right")
if isinstance(left_pose, list):
    with self.left_arm_pose_shared.get_lock():
        self.left_arm_pose_shared[:] = left_pose
if isinstance(right_pose, list):
    with self.right_arm_pose_shared.get_lock():
        self.right_arm_pose_shared[:] = right_pose

# Buttons immer verarbeiten, unabhängig von der Pose
left_controller = event.value.get("leftState", {})
right_controller = event.value.get("rightState", {})
```

Dadurch:
- Buttons funktionieren sofort ab Verbindungsaufbau
- Der Stream startet ohne vorheriges Hand-Tracking
- Einzelne Controller (z. B. nur rechts) funktionieren korrekt
