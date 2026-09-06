"""Connection to MAVProxy (or any MAVLink endpoint) plus a background
heartbeat thread, since most GCS software only treats a link as "connected"
once HEARTBEATs start arriving at ~1Hz.
"""
import threading

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

HEARTBEAT_INTERVAL_SECONDS = 1.0


class ConnectionManager:
    def __init__(self):
        self._conn = None
        self._send_lock = threading.Lock()
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()
        self.conn_string = ""

        self.on_status = None  # callback(str) for log/status lines
        self.on_disconnect = None  # callback() invoked if the link drops

        # Fields sent in the auto-heartbeat; editable via the GUI while connected.
        self.heartbeat_type = mavlink.MAV_TYPE_QUADROTOR
        self.heartbeat_autopilot = mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA
        self.heartbeat_base_mode = mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        self.heartbeat_custom_mode = 0
        self.heartbeat_system_status = mavlink.MAV_STATE_STANDBY

    @property
    def connected(self):
        return self._conn is not None

    def connect(self, conn_string, source_system, source_component, baud):
        conn = mavutil.mavlink_connection(
            conn_string,
            source_system=source_system,
            source_component=source_component,
            baud=baud,
        )
        self._conn = conn
        self.conn_string = conn_string
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def disconnect(self):
        self._stop_heartbeat.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2)
        self._heartbeat_thread = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None

    def send(self, msg):
        with self._send_lock:
            if self._conn is None:
                raise RuntimeError("Not connected")
            self._conn.mav.send(msg)

    def _heartbeat_loop(self):
        while not self._stop_heartbeat.is_set():
            try:
                hb = mavlink.MAVLink_heartbeat_message(
                    type=self.heartbeat_type,
                    autopilot=self.heartbeat_autopilot,
                    base_mode=self.heartbeat_base_mode,
                    custom_mode=self.heartbeat_custom_mode,
                    system_status=self.heartbeat_system_status,
                    mavlink_version=3,
                )
                self.send(hb)
            except Exception as exc:
                if self.on_status:
                    self.on_status(f"Heartbeat send failed, disconnecting: {exc}")
                self._stop_heartbeat.set()
                if self.on_disconnect:
                    self.on_disconnect()
                break
            self._stop_heartbeat.wait(HEARTBEAT_INTERVAL_SECONDS)
