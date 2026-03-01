#!/usr/bin/env python3
"""End-to-end test: start simulator, send commands via serial, print results."""
import os
import pty
import tty
import time
import threading
import select
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rover_sim import RoverSimulator


def run_e2e():
    # Create virtual serial pair
    master_fd, slave_fd = pty.openpty()
    tty.setraw(slave_fd)
    tty.setraw(master_fd)
    slave_path = os.ttyname(slave_fd)

    print(f"=== Rover Simulator E2E Test ===")
    print(f"Virtual serial port: {slave_path}\n")

    sim = RoverSimulator()
    running = True

    # Simulator thread
    def sim_loop():
        buf = b""
        while running:
            wd = sim.check_watchdog()
            if wd:
                os.write(master_fd, (wd + "\n").encode())
                elapsed = time.time() - sim.start_time
                print(f"  [SIM {elapsed:.1f}s] WATCHDOG triggered → motors stopped")

            ready, _, _ = select.select([master_fd], [], [], 0.05)
            if not ready:
                continue
            try:
                data = os.read(master_fd, 1024)
            except OSError:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                if cmd:
                    response = sim.process_command(cmd)
                    os.write(master_fd, (response + "\n").encode())
                    elapsed = time.time() - sim.start_time
                    left = sim._motor_str(sim.left_speed, sim.left_dir)
                    right = sim._motor_str(sim.right_speed, sim.right_dir)
                    print(f"  [SIM {elapsed:.1f}s] {cmd} → {response}  |  L={left} R={right}")

    t = threading.Thread(target=sim_loop, daemon=True)
    t.start()
    time.sleep(0.1)

    def send(command):
        """Send command and receive response via virtual serial."""
        os.write(slave_fd, (command + "\n").encode())
        buf = b""
        deadline = time.time() + 2.0
        while time.time() < deadline:
            ready, _, _ = select.select([slave_fd], [], [], 0.1)
            if ready:
                buf += os.read(slave_fd, 1024)
                if b"\n" in buf:
                    resp = buf.decode("ascii").strip().split("\n")[0]
                    print(f"  [CMD] {command} → {resp}")
                    return resp
        print(f"  [CMD] {command} → TIMEOUT")
        return None

    # === Test sequence ===
    print("--- Test 1: PING/PONG ---")
    send("PING")

    print("\n--- Test 2: Move forward ---")
    send("FORWARD 150")
    time.sleep(0.3)

    print("\n--- Test 3: Check status while moving ---")
    send("STATUS")

    print("\n--- Test 4: Turn left ---")
    send("LEFT 120")
    time.sleep(0.2)

    print("\n--- Test 5: Spin right ---")
    send("SPIN_RIGHT 100")
    time.sleep(0.2)

    print("\n--- Test 6: Stop ---")
    send("STOP")

    print("\n--- Test 7: Check status after stop ---")
    send("STATUS")

    print("\n--- Test 8: Invalid command ---")
    send("DANCE 200")

    print("\n--- Test 9: Watchdog test (send command, wait 600ms) ---")
    send("FORWARD 180")
    print("  Waiting 700ms for watchdog...")
    time.sleep(0.7)
    # Read the watchdog message
    buf = b""
    deadline = time.time() + 1.0
    while time.time() < deadline:
        ready, _, _ = select.select([slave_fd], [], [], 0.1)
        if ready:
            buf += os.read(slave_fd, 1024)
            if b"\n" in buf:
                resp = buf.decode("ascii").strip().split("\n")[0]
                print(f"  [WATCHDOG] Received: {resp}")
                break

    print("\n--- Test 10: Status after watchdog ---")
    send("STATUS")

    print("\n=== All tests complete ===")

    running = False
    os.close(master_fd)
    os.close(slave_fd)


if __name__ == "__main__":
    run_e2e()
