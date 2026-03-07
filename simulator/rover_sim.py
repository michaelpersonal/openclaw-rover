"""
Rover simulator — emulates Arduino firmware serial protocol.
Speaks the same command/response format over a virtual serial port.
"""
import os
import pty
import select
import time


class RoverSimulator:
    """Core protocol logic. No I/O — just state machine."""

    def __init__(self):
        self.left_speed = 0
        self.left_dir = "S"  # S=stopped, F=forward, R=reverse
        self.right_speed = 0
        self.right_dir = "S"
        self.cmd_count = 0
        self.start_time = time.time()
        self.last_cmd_time = None
        self.watchdog_fired = False
        self.obstacle_dist = 999  # cm, 999 = no obstacle
        self.obstacle_blocked = False
        self.heading = 0  # degrees, 0-359

    def _set_motors(self, left_speed, left_dir, right_speed, right_dir):
        self.left_speed = max(0, min(255, left_speed))
        self.left_dir = left_dir
        self.right_speed = max(0, min(255, right_speed))
        self.right_dir = right_dir

    def _stop_motors(self):
        self._set_motors(0, "S", 0, "S")

    def _motor_str(self, speed, direction):
        if direction == "S":
            return "S"
        return f"{direction}{speed}"

    def process_command(self, line):
        """Process a single command line. Returns response string."""
        self.cmd_count += 1
        self.last_cmd_time = time.time()
        self.watchdog_fired = False

        line = line.strip()
        if not line:
            return "ERR:EMPTY"

        parts = line.split(" ", 1)
        cmd = parts[0]
        arg = int(parts[1]) if len(parts) > 1 else 0

        if cmd == "FORWARD":
            if self.obstacle_blocked:
                return "ERR:OBSTACLE"
            speed = max(0, min(255, arg))
            self._set_motors(speed, "F", speed, "F")
            return "OK"
        elif cmd == "BACKWARD":
            speed = max(0, min(255, arg))
            self._set_motors(speed, "R", speed, "R")
            return "OK"
        elif cmd == "LEFT":
            speed = max(0, min(255, arg))
            self._set_motors(0, "S", speed, "F")
            return "OK"
        elif cmd == "RIGHT":
            speed = max(0, min(255, arg))
            self._set_motors(speed, "F", 0, "S")
            return "OK"
        elif cmd == "SPIN_LEFT":
            speed = max(0, min(255, arg))
            self._set_motors(speed, "R", speed, "F")
            return "OK"
        elif cmd == "SPIN_RIGHT":
            speed = max(0, min(255, arg))
            self._set_motors(speed, "F", speed, "R")
            return "OK"
        elif cmd == "STOP":
            self._stop_motors()
            return "OK"
        elif cmd == "PING":
            return "PONG"
        elif cmd == "SPIN_TO":
            self.heading = arg % 360
            return "OK"
        elif cmd == "SET_OBSTACLE":
            self.obstacle_dist = max(0, arg)
            self._check_obstacle()
            return "OK"
        elif cmd == "CLEAR_OBSTACLE":
            self.obstacle_dist = 999
            self.obstacle_blocked = False
            return "OK"
        elif cmd == "STATUS":
            return self._status_response()
        else:
            return f"ERR:UNKNOWN_CMD:{cmd}"

    def _check_obstacle(self):
        """Check if obstacle is within threshold. Returns 'STOPPED:OBSTACLE' if newly blocked, else None."""
        if self.obstacle_dist < 20 and not self.obstacle_blocked:
            self._stop_motors()
            self.obstacle_blocked = True
            return "STOPPED:OBSTACLE"
        elif self.obstacle_dist >= 20:
            self.obstacle_blocked = False
        return None

    def _status_response(self):
        now = time.time()
        uptime_ms = int((now - self.start_time) * 1000)
        last_cmd_ms = int((now - self.last_cmd_time) * 1000) if self.last_cmd_time else uptime_ms
        left = self._motor_str(self.left_speed, self.left_dir)
        right = self._motor_str(self.right_speed, self.right_dir)
        return f"STATUS:motors={left},{right};dist={self.obstacle_dist}cm;heading={self.heading};uptime={uptime_ms};cmds={self.cmd_count};last_cmd={last_cmd_ms}ms;loop=0hz"

    def check_watchdog(self, timeout_ms=500):
        """Check watchdog. Returns 'STOPPED:WATCHDOG' if triggered, else None."""
        if self.last_cmd_time is None or self.watchdog_fired:
            return None
        elapsed = (time.time() - self.last_cmd_time) * 1000
        if elapsed > timeout_ms:
            self._stop_motors()
            self.watchdog_fired = True
            return "STOPPED:WATCHDOG"
        return None


def run_simulator():
    """Run simulator with virtual serial port pair."""
    import tty
    master_fd, slave_fd = pty.openpty()
    # Disable echo so responses don't loop back as commands
    tty.setraw(slave_fd)
    tty.setraw(master_fd)
    slave_path = os.ttyname(slave_fd)
    print(f"Rover simulator started")
    print(f"Connect to: {slave_path}")
    print(f"Waiting for commands...\n")

    sim = RoverSimulator()
    buf = b""

    try:
        while True:
            # Check watchdog
            wd = sim.check_watchdog()
            if wd:
                os.write(master_fd, (wd + "\n").encode())
                elapsed = time.time() - sim.start_time
                print(f"[{elapsed:.1f}s] WATCHDOG → motors stopped")

            # Poll for incoming data (100ms timeout)
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if not ready:
                continue

            data = os.read(master_fd, 1024)
            if not data:
                break
            buf += data

            # Process complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                if not cmd:
                    continue

                response = sim.process_command(cmd)
                os.write(master_fd, (response + "\n").encode())

                elapsed = time.time() - sim.start_time
                left = sim._motor_str(sim.left_speed, sim.left_dir)
                right = sim._motor_str(sim.right_speed, sim.right_dir)
                print(f"[{elapsed:.1f}s] {cmd} → {response}  |  motors: L={left} R={right}")

    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        os.close(master_fd)
        os.close(slave_fd)


if __name__ == "__main__":
    run_simulator()
