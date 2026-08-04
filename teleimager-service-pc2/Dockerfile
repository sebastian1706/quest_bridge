FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    git build-essential openssl v4l-utils \
    libusb-1.0-0-dev libturbojpeg-dev libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Cert für WebRTC (Quest muss einmalig vertrauen)
RUN mkdir -p /root/.config/xr_teleoperate && \
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout /root/.config/xr_teleoperate/key.pem \
      -out /root/.config/xr_teleoperate/cert.pem \
      -subj "/CN=teleimager"

WORKDIR /app

# teleimager ist ein eigenstaendiges Repo (bei Unitrees xr_teleoperate nur als
# Git-Submodule eingebunden) - direkt klonen statt umstaendlich das komplette
# xr_teleoperate-Monorepo dafuer mitzuziehen.
# Kein pyrealsense2 hier (anders als teleimager-service/): PC2 nutzt die
# G1-Stock-UVC-Kameras (pupil-labs-uvc, Teil des [server]-Extras), kein RealSense.
RUN git clone --depth 1 https://github.com/unitreerobotics/teleimager.git /opt/teleimager && \
    pip install -e "/opt/teleimager[server]" psutil

# Ueberschreibt die Beispiel-Config (Fake-Kameras) aus dem geklonten Repo mit
# unserer echten Kamera-Konfiguration. image_server.py laedt die Config immer
# von diesem Pfad (relativ zum installierten Package), kein CLI-Flag dafuer.
COPY cam_config_server.yaml /opt/teleimager/cam_config_server.yaml

CMD ["teleimager-server"]
