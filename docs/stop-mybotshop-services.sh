#!/bin/bash
# Stops the mybotshop/G1/Karl Cockpit services started earlier in this session.
# See docs/mybotshop-services.md for background and individual start commands.
# Requires sudo.

set -euo pipefail

services=(
  karl-nav
  karl-cockpit
  g1-survey-agent
  g1-realsense
  g1-arm-29dof
  g1-audio-service
  g1-description
  g1-domain-bridge
  g1-highlevel-ros-controller
  g1-led-service
  g1-livox-mid360
  g1-obstacle-avoidance
  g1-pcd-to-scan
  g1-state-publisher
  g1-twist-mux
  robot-gps-navi
  robot-map-navi
  robot-slam
  robot-webserver
)

for svc in "${services[@]}"; do
  echo "Stopping ${svc}.service ..."
  sudo systemctl stop "${svc}.service" || echo "  (already inactive or failed to stop: ${svc}.service)"
done

echo "Done. Remaining ROS2 nodes:"
ros2 node list || true
