import time
import pytest
from rover_sim import RoverSimulator


class TestCommandParsing:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_forward(self):
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "OK"
        assert self.sim.left_speed == 180
        assert self.sim.left_dir == "F"
        assert self.sim.right_speed == 180
        assert self.sim.right_dir == "F"

    def test_backward(self):
        resp = self.sim.process_command("BACKWARD 150")
        assert resp == "OK"
        assert self.sim.left_dir == "R"
        assert self.sim.right_dir == "R"

    def test_left(self):
        resp = self.sim.process_command("LEFT 120")
        assert resp == "OK"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"
        assert self.sim.right_speed == 120
        assert self.sim.right_dir == "F"

    def test_right(self):
        resp = self.sim.process_command("RIGHT 120")
        assert resp == "OK"
        assert self.sim.left_speed == 120
        assert self.sim.left_dir == "F"
        assert self.sim.right_speed == 0
        assert self.sim.right_dir == "S"

    def test_spin_left(self):
        resp = self.sim.process_command("SPIN_LEFT 100")
        assert resp == "OK"
        assert self.sim.left_dir == "R"
        assert self.sim.right_dir == "F"

    def test_spin_right(self):
        resp = self.sim.process_command("SPIN_RIGHT 100")
        assert resp == "OK"
        assert self.sim.left_dir == "F"
        assert self.sim.right_dir == "R"

    def test_stop(self):
        self.sim.process_command("FORWARD 200")
        resp = self.sim.process_command("STOP")
        assert resp == "OK"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"
        assert self.sim.right_speed == 0
        assert self.sim.right_dir == "S"

    def test_ping(self):
        resp = self.sim.process_command("PING")
        assert resp == "PONG"

    def test_unknown_command(self):
        resp = self.sim.process_command("DANCE 100")
        assert resp.startswith("ERR:")

    def test_empty_command(self):
        resp = self.sim.process_command("")
        assert resp.startswith("ERR:")

    def test_speed_clamped_high(self):
        self.sim.process_command("FORWARD 300")
        assert self.sim.left_speed == 255

    def test_speed_clamped_low(self):
        self.sim.process_command("FORWARD -10")
        assert self.sim.left_speed == 0

    def test_command_count(self):
        assert self.sim.cmd_count == 0
        self.sim.process_command("PING")
        self.sim.process_command("PING")
        assert self.sim.cmd_count == 2


class TestStatus:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_status_when_stopped(self):
        resp = self.sim.process_command("STATUS")
        assert resp.startswith("STATUS:motors=S,S;")
        assert "cmds=1;" in resp

    def test_status_when_moving(self):
        self.sim.process_command("FORWARD 180")
        resp = self.sim.process_command("STATUS")
        assert "motors=F180,F180;" in resp
        assert "cmds=2;" in resp

    def test_status_format(self):
        resp = self.sim.process_command("STATUS")
        assert "motors=" in resp
        assert "uptime=" in resp
        assert "cmds=" in resp
        assert "last_cmd=" in resp
        assert "loop=" in resp


class TestWatchdog:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_no_watchdog_before_first_command(self):
        result = self.sim.check_watchdog()
        assert result is None

    def test_no_watchdog_right_after_command(self):
        self.sim.process_command("FORWARD 180")
        result = self.sim.check_watchdog()
        assert result is None

    def test_watchdog_fires_after_timeout(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0  # fake 1s ago
        result = self.sim.check_watchdog()
        assert result == "STOPPED:WATCHDOG"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"

    def test_watchdog_fires_only_once(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0
        self.sim.check_watchdog()  # fires
        result = self.sim.check_watchdog()  # should not fire again
        assert result is None

    def test_watchdog_resets_on_new_command(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0
        self.sim.check_watchdog()  # fires
        self.sim.process_command("FORWARD 100")  # reset
        assert self.sim.watchdog_fired is False
        assert self.sim.left_speed == 100


class TestObstacle:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_default_distance_is_999(self):
        assert self.sim.obstacle_dist == 999

    def test_set_obstacle(self):
        resp = self.sim.process_command("SET_OBSTACLE 15")
        assert resp == "OK"
        assert self.sim.obstacle_dist == 15

    def test_clear_obstacle(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("CLEAR_OBSTACLE")
        assert resp == "OK"
        assert self.sim.obstacle_dist == 999

    def test_status_includes_dist(self):
        self.sim.process_command("SET_OBSTACLE 42")
        resp = self.sim.process_command("STATUS")
        assert "dist=42cm" in resp

    def test_obstacle_auto_stops_motors(self):
        self.sim.process_command("FORWARD 180")
        self.sim.process_command("SET_OBSTACLE 10")
        assert self.sim.left_dir == "S"
        assert self.sim.right_dir == "S"

    def test_obstacle_blocks_forward(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "ERR:OBSTACLE"
        assert self.sim.left_dir == "S"

    def test_obstacle_allows_backward(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("BACKWARD 150")
        assert resp == "OK"
        assert self.sim.left_dir == "R"

    def test_obstacle_allows_left(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("LEFT 120")
        assert resp == "OK"

    def test_obstacle_allows_right(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("RIGHT 120")
        assert resp == "OK"

    def test_obstacle_allows_spin_left(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("SPIN_LEFT 100")
        assert resp == "OK"

    def test_obstacle_allows_spin_right(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("SPIN_RIGHT 100")
        assert resp == "OK"

    def test_obstacle_allows_stop(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("STOP")
        assert resp == "OK"

    def test_obstacle_clears_when_distance_increases(self):
        self.sim.process_command("SET_OBSTACLE 10")
        assert self.sim.obstacle_blocked is True
        self.sim.process_command("SET_OBSTACLE 25")
        assert self.sim.obstacle_blocked is False
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "OK"

    def test_set_obstacle_returns_stopped_obstacle(self):
        """SET_OBSTACLE should trigger auto-stop as a side effect."""
        self.sim.process_command("FORWARD 180")
        resp = self.sim.process_command("SET_OBSTACLE 10")
        assert resp == "OK"
        assert self.sim.obstacle_blocked is True


class TestHeading:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_default_heading_is_0(self):
        assert self.sim.heading == 0

    def test_spin_to_sets_heading(self):
        resp = self.sim.process_command("SPIN_TO 90")
        assert resp == "OK"
        assert self.sim.heading == 90

    def test_spin_to_wraps_360(self):
        resp = self.sim.process_command("SPIN_TO 360")
        assert resp == "OK"
        assert self.sim.heading == 0

    def test_spin_to_clamps_negative(self):
        resp = self.sim.process_command("SPIN_TO 0")
        assert resp == "OK"
        assert self.sim.heading == 0

    def test_status_includes_heading(self):
        self.sim.process_command("SPIN_TO 45")
        resp = self.sim.process_command("STATUS")
        assert "heading=45;" in resp
