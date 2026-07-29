#!/bin/bash
export HOST_IP=$(hostname -I | awk '{print $1}')

if [ -z "$HOST_IP" ]; then
    echo "No LAN IP found." >&2
    exit 1
fi

docker compose run --service-ports --build zmq-publisher
