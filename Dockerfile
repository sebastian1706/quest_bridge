FROM python:3.10-slim

RUN apt-get update && apt-get install -y git build-essential openssl libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /certs && \
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout /certs/key.pem -out /certs/cert.pem \
      -subj "/CN=xr-teleop"

WORKDIR /app

COPY televuer/ /opt/televuer/

RUN pip install numpy==1.26.4 && \
    pip install -e /opt/televuer && \
    pip install 'params-proto<3.0' pyzmq msgpack

COPY patch_vuer.py patch_vuer.py
RUN python3 patch_vuer.py

COPY receive_test.py receive_test.py
COPY haptic_receiver.py haptic_receiver.py
COPY haptics.js haptics.js
COPY zmq_publisher.py zmq_publisher.py