# mybotshop / G1 systemd services (PC2)

Referenz für die Services aus dem mybotshop-SDK auf PC2 (Jetson Orin NX).
`sudo` erforderlich für alle Befehle.

## Kamera / Cockpit (in dieser Session an- und ausgeschaltet)

```
sudo systemctl start g1-realsense.service
sudo systemctl stop  g1-realsense.service
```
RealSense-Kopfkamera (D435I) als ROS2-Node (`/ubuntu/color/image_raw` etc.).
Muss gestoppt sein, damit `teleimager-pc2` (Docker, `pyrealsense2`) direkt auf
die Kamera zugreifen kann - beide können sie nicht gleichzeitig halten
("Device or resource busy").

```
sudo systemctl start karl-cockpit.service
sudo systemctl stop  karl-cockpit.service
```
"Karl Cockpit" - G1 Control & Mission Software, `mode=real`, Webserver auf
Port 9010 (nginx davor). Stoppen bricht den nginx-Reverse-Proxy (502 Bad
Gateway), das ist erwartetes Verhalten, kein Fehler.

## Übrige G1-/Robot-Services

Standen vor dieser Session auf `disabled` (kein Autostart) - unklar, ob sie
bewusst deaktiviert waren. **`g1-arm-29dof.service` steuert die physischen
Armmotoren** - vor dem Start sicherstellen, dass der Bereich um den Roboter
frei ist und jemand in Reichweite des Not-Aus ist.

```
sudo systemctl start g1-arm-29dof.service
sudo systemctl start g1-audio-service.service
sudo systemctl start g1-description.service
sudo systemctl start g1-domain-bridge.service
sudo systemctl start g1-highlevel-ros-controller.service
sudo systemctl start g1-led-service.service
sudo systemctl start g1-livox-mid360.service
sudo systemctl start g1-obstacle-avoidance.service
sudo systemctl start g1-pcd-to-scan.service
sudo systemctl start g1-state-publisher.service
sudo systemctl start g1-twist-mux.service
sudo systemctl start robot-gps-navi.service
sudo systemctl start robot-map-navi.service
sudo systemctl start robot-slam.service
sudo systemctl start robot-webserver.service
```

Zum Stoppen jeweils `start` durch `stop` ersetzen. Status prüfen:

```
systemctl status <service-name>
systemctl is-active <service-name>
```

## Diagnose

```
# Was hält gerade die Kamera-Devices?
fuser -v /dev/video0 /dev/video1 /dev/video2 /dev/video3 /dev/video4 /dev/video5

# RealSense-Serial-Number ermitteln
rs-enumerate-devices --compact
```
