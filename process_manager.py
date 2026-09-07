"""Runs an arbitrary shell command as a supervised child process - used to
launch SITL and MAVProxy from inside this app instead of separate terminal
windows. Each ManagedProcess owns at most one running process; starting a
second one while the first is still running is a caller error.
"""
import subprocess
import threading


class ManagedProcess:
    def __init__(self, name):
        self.name = name
        self._proc = None
        self.on_output = None  # callback(line: str), called from a background thread
        self.on_exit = None  # callback(returncode: int), called from a background thread

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self):
        return self._proc.pid if self._proc is not None else None

    def start(self, command):
        if self.running:
            raise RuntimeError(f"{self.name} is already running")
        self._proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        threading.Thread(target=self._read_output, args=(self._proc,), daemon=True).start()

    def _read_output(self, proc):
        try:
            for line in proc.stdout:
                if self.on_output:
                    self.on_output(line.rstrip("\n"))
        except Exception:
            pass
        returncode = proc.wait()
        if self.on_exit:
            self.on_exit(returncode)

    def stop(self):
        """Force-kill the whole process tree. shell=True spawns a cmd.exe
        wrapper around the real command, so Popen.terminate() alone would
        only kill that wrapper and leave SITL/MAVProxy itself running;
        "taskkill /T" kills everything cmd.exe spawned. These are dev
        tools, not something that needs a graceful shutdown handshake."""
        if not self.running:
            return
        pid = self._proc.pid
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
