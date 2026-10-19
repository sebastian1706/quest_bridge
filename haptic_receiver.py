"""Return channel for force feedback: haptic commands from the robot side.

Split out of zmq_publisher.py so it can be tested without starting vuer.
See README, "Force feedback", for the wire format and how the amplitude reaches the controller.
"""
import threading
import time

import msgpack
import zmq


class HapticReceiver:
    """Return channel: haptic commands from the robot side.

    The robot-side teleoperator (lerobot_teleoperator_quest) PUB-*connects* here and this
    end SUB-*binds*, so only the bridge needs a stable address -- the robot PC can sit on
    any IP. Commands are msgpack `{"timestamp", "hand", "amplitude"}` with amplitude in
    [0, 1], sent as `[b"haptic", payload]`.

    Only the newest command matters -- a stale vibration is worse than none -- so the
    receive loop drains the queue and keeps the last message (same pattern as the forward
    channel in lerobot_teleoperator_quest/quest.py). ZMQ's CONFLATE option would be the
    obvious choice but does not support multi-part messages, and the topic is its own frame.

    `latest()` returns `(hand, amplitude)` or `(None, 0.0)` if nothing arrived within
    `stale_after_s` -- so a dead robot side stops the vibration instead of freezing it.

    Call `close()` before terminating the ZMQ context: an open socket in the polling
    thread makes `Context.term()` block forever.
    """

    def __init__(self, ctx, port, topic="haptic", stale_after_s=0.5):
        self.stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._hand = None
        self._amplitude = 0.0
        self._time = 0.0
        self._stop = threading.Event()
        self._socket = ctx.socket(zmq.SUB)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.setsockopt(zmq.RCVHWM, 4)
        self._socket.setsockopt(zmq.SUBSCRIBE, topic.encode())
        self._socket.bind(f"tcp://*:{port}")
        self._thread = threading.Thread(target=self._loop, name="haptic-rx", daemon=True)
        self._thread.start()

    def _loop(self):
        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)
        while not self._stop.is_set():
            if not poller.poll(100):
                continue
            # Keep only the newest message.
            while True:
                try:
                    _topic, raw = self._socket.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    break
                try:
                    payload = msgpack.unpackb(raw, raw=False)
                    amplitude = min(max(float(payload["amplitude"]), 0.0), 1.0)
                    hand = payload.get("hand")
                except (KeyError, TypeError, ValueError) as e:
                    print(f"[haptic] malformed message: {e}")
                    continue
                with self._lock:
                    self._hand, self._amplitude, self._time = hand, amplitude, time.monotonic()

    def latest(self):
        with self._lock:
            if time.monotonic() - self._time > self.stale_after_s:
                return None, 0.0
            return self._hand, self._amplitude

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._socket.close()
