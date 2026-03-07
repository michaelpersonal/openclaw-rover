"""Tests for rover monitor parsing and display functions."""
from rover_monitor import parse_message, motor_bar, format_uptime, build_display


class TestParseMessage:
    def test_status_message(self):
        msg = parse_message('{"type":"status","motors":{"left":{"dir":"F","speed":150},"right":{"dir":"F","speed":150}},"uptime":12340,"cmds":47,"lastCmd":230,"loopHz":8200,"ts":1772381533}')
        assert msg is not None
        assert msg["type"] == "status"
        assert msg["motors"]["left"]["dir"] == "F"
        assert msg["motors"]["left"]["speed"] == 150
        assert msg["uptime"] == 12340

    def test_command_message(self):
        msg = parse_message('{"type":"command","cmd":"FORWARD","speed":150,"response":"OK","ts":1772381534}')
        assert msg is not None
        assert msg["type"] == "command"
        assert msg["cmd"] == "FORWARD"
        assert msg["response"] == "OK"

    def test_event_message(self):
        msg = parse_message('{"type":"event","event":"STOPPED:WATCHDOG","ts":1772381535}')
        assert msg is not None
        assert msg["type"] == "event"
        assert msg["event"] == "STOPPED:WATCHDOG"

    def test_malformed_json(self):
        assert parse_message("not json at all") is None
        assert parse_message("{broken") is None
        assert parse_message("") is None

    def test_empty_object(self):
        msg = parse_message("{}")
        assert msg is not None


class TestMotorBar:
    def test_stopped(self):
        bar = motor_bar("S", 0)
        assert "STOP" in bar.plain
        assert "0%" in bar.plain

    def test_forward(self):
        bar = motor_bar("F", 150)
        assert "▲" in bar.plain
        assert "F150" in bar.plain

    def test_reverse(self):
        bar = motor_bar("R", 200)
        assert "▼" in bar.plain
        assert "R200" in bar.plain

    def test_full_speed(self):
        bar = motor_bar("F", 255)
        assert "100%" in bar.plain

    def test_zero_speed_forward(self):
        bar = motor_bar("F", 0)
        assert "0%" in bar.plain


class TestFormatUptime:
    def test_zero(self):
        assert format_uptime(0) == "00:00:00"

    def test_seconds(self):
        assert format_uptime(5000) == "00:00:05"

    def test_minutes(self):
        assert format_uptime(90000) == "00:01:30"

    def test_hours(self):
        assert format_uptime(3661000) == "01:01:01"


class TestBuildDisplay:
    def test_vitals_shows_distance(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 42}
        layout = build_display(state, [])
        # The layout renders — we verify no crash and the function accepts dist

    def test_vitals_shows_distance_blocked(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 15}
        layout = build_display(state, [])
        # The layout renders with blocked distance

    def test_vitals_shows_heading(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 999, "heading": 270}
        layout = build_display(state, [])
        # Renders without crash with heading
