"""Connection to MAVProxy (or any MAVLink endpoint) plus background threads
for the automatic heartbeat (most GCS software only treats a link as
"connected" once HEARTBEATs start arriving at ~1Hz) and for receiving
whatever MAVProxy forwards back to us (e.g. commands the GCS issues).
"""
import threading

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

HEARTBEAT_INTERVAL_SECONDS = 1.0
RECV_POLL_TIMEOUT_SECONDS = 1.0


def _bind_udp_client_socket(conn):
    """pymavlink's udpout:/udp: client sockets are only bound implicitly, by
    the OS, on their first outgoing sendto() - normally harmless, but on
    Windows calling recvfrom() before that first send happens raises
    WSAEINVAL, and our receive thread can start before the heartbeat
    thread's first send wins that race. Bind explicitly and synchronously
    here, before either thread touches the socket, so there's no race.
    Only applies to pymavlink's UDP client mode; other connection types
    (TCP, serial, UDP server/"in") don't have this attribute shape.
    """
    port = getattr(conn, "port", None)
    if port is None or getattr(conn, "udp_server", True):
        return
    try:
        port.bind(("", 0))
    except OSError:
        pass  # already bound (e.g. reconnecting a reused object) - fine


class ConnectionManager:
    def __init__(self):
        self._conn = None
        self._send_lock = threading.Lock()
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()
        self._recv_thread = None
        self._stop_recv = threading.Event()
        self.conn_string = ""

        self.on_status = None  # callback(str) for log/status lines
        self.on_disconnect = None  # callback() invoked if the link drops
        self.on_message = None  # callback(msg) invoked for every message received

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
        _bind_udp_client_socket(conn)
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        self._stop_recv.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def disconnect(self):
        self._stop_heartbeat.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2)
        self._heartbeat_thread = None
        self._stop_recv.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=RECV_POLL_TIMEOUT_SECONDS + 1)
        self._recv_thread = None
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

    def _recv_loop(self):
        conn = self._conn
        while not self._stop_recv.is_set():
            try:
                msg = conn.recv_match(blocking=True, timeout=RECV_POLL_TIMEOUT_SECONDS)
            except Exception as exc:
                if self.on_status:
                    self.on_status(f"Receive error: {exc}")
                return
            if msg is None or msg.get_type() == "BAD_DATA":
                continue
            if self.on_message:
                self.on_message(msg)
