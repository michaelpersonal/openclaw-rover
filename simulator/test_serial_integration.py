"""Integration test: talk to simulator over virtual serial port pair."""
import os
import pty
import tty
import time
import threading
import select
import pytest
from rover_sim import RoverSimulator


class TestSerialIntegration:
    """Test the simulator via a real pty serial port pair."""

    def setup_method(self):
        self.master_fd, self.slave_fd = pty.openpty()
        # Disable echo so responses don't loop back as commands
        tty.setraw(self.slave_fd)
        tty.setraw(self.master_fd)
        self.sim = RoverSimulator()
        self.running = True
        self.sim_thread = threading.Thread(target=self._run_sim, daemon=True)
        self.sim_thread.start()
        time.sleep(0.05)  # let thread start

    def teardown_method(self):
        self.running = False
        os.close(self.master_fd)
        os.close(self.slave_fd)

    def _run_sim(self):
        """Simulator loop running in a thread."""
        buf = b""
        while self.running:
            ready, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not ready:
                continue
            try:
                data = os.read(self.master_fd, 1024)
            except OSError:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                if cmd:
                    response = self.sim.process_command(cmd)
                    os.write(self.master_fd, (response + "\n").encode())

    def _send_recv(self, command, timeout=1.0):
        """Send command via slave fd, read response."""
        os.write(self.slave_fd, (command + "\n").encode())
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([self.slave_fd], [], [], 0.1)
            if ready:
                buf += os.read(self.slave_fd, 1024)
                if b"\n" in buf:
                    return buf.decode("ascii").strip().split("\n")[0]
        return None

    def test_ping_pong(self):
        resp = self._send_recv("PING")
        assert resp == "PONG"

    def test_forward_ok(self):
        resp = self._send_recv("FORWARD 180")
        assert resp == "OK"

    def test_stop_ok(self):
        self._send_recv("FORWARD 180")
        resp = self._send_recv("STOP")
        assert resp == "OK"

    def test_status_response(self):
        self._send_recv("FORWARD 150")
        resp = self._send_recv("STATUS")
        assert resp.startswith("STATUS:motors=F150,F150;")

    def test_unknown_command(self):
        resp = self._send_recv("DANCE 100")
        assert resp.startswith("ERR:")

    def test_multiple_commands(self):
        assert self._send_recv("FORWARD 100") == "OK"
        assert self._send_recv("LEFT 80") == "OK"
        assert self._send_recv("STOP") == "OK"
        resp = self._send_recv("STATUS")
        assert "motors=S,S;" in resp
