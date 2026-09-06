"""Background repeat-sending of a fixed MAVLink message/command on a timer.

Independent of ConnectionManager's own automatic HEARTBEAT loop - this
manages user-added repeats (from either the Message or Command tab), each
running on its own thread so rates can differ and one can be paused/removed
without affecting the others.
"""
import itertools
import threading
import time

PAUSE_POLL_SECONDS = 0.2


class RepeatEntry:
    def __init__(self, entry_id, label, kind, builder, interval_seconds):
        self.id = entry_id
        self.label = label
        self.kind = kind  # "message" or "command", for display only
        self.builder = builder  # no-arg callable returning a fresh mavlink message
        self.interval_seconds = interval_seconds
        self.paused = False
        self.send_count = 0
        self.last_sent = None
        self.last_error = None
        self._stop_event = threading.Event()
        self._thread = None

    def start(self, send_fn):
        self._thread = threading.Thread(target=self._run, args=(send_fn,), daemon=True)
        self._thread.start()

    def _run(self, send_fn):
        while not self._stop_event.is_set():
            if self.paused:
                self._stop_event.wait(PAUSE_POLL_SECONDS)
                continue
            try:
                send_fn(self.builder())
                self.send_count += 1
                self.last_sent = time.time()
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
            self._stop_event.wait(self.interval_seconds)

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


class RepeatManager:
    def __init__(self, conn_mgr):
        self.conn_mgr = conn_mgr
        self.entries = {}
        self._next_id = itertools.count(1)

    def add(self, label, kind, builder, interval_seconds):
        entry_id = next(self._next_id)
        entry = RepeatEntry(entry_id, label, kind, builder, interval_seconds)
        self.entries[entry_id] = entry
        entry.start(self.conn_mgr.send)
        return entry_id

    def remove(self, entry_id):
        entry = self.entries.pop(entry_id, None)
        if entry is not None:
            entry.stop()

    def set_interval(self, entry_id, interval_seconds):
        entry = self.entries.get(entry_id)
        if entry is not None:
            entry.interval_seconds = interval_seconds

    def set_paused(self, entry_id, paused):
        entry = self.entries.get(entry_id)
        if entry is not None:
            entry.paused = paused

    def stop_all(self):
        for entry_id in list(self.entries.keys()):
            self.remove(entry_id)
