#!/usr/bin/env python3
import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("bin") / "rover-drive-daemon.py"
    spec = importlib.util.spec_from_file_location("rover_drive_daemon", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_helpers():
    daemon = load_module()
    status = "STATUS:motors=S,S;dist=31cm;heading=224;uptime=123;cmds=4"
    scan = "SCAN:test\nangle=0 dist=12cm state=BLOCKED\nbest_angle=270 best_dist=999cm recommend_move=backward"

    assert daemon.parse_heading(status) == 224
    assert daemon.parse_scan_value("best_angle", scan) == "270"
    assert daemon.parse_scan_value("best_dist", scan) == "999cm"
    assert daemon.parse_scan_value("recommend_move", scan) == "backward"
    assert daemon.normalize_angle(494) == 134


def test_obstacle_promotes_state():
    daemon = load_module()
    state = {
        "last_event": "",
        "last_error": "",
        "action": "forward",
        "speed": 60,
    }

    obstacle = daemon.process_line(state, "STOPPED:OBSTACLE")

    assert obstacle is True
    assert state["last_event"] == "STOPPED:OBSTACLE"
    assert state["last_error"] == "ERR:OBSTACLE"
    assert state["action"] == "stop"
    assert state["speed"] == 0


def test_motors_are_stopped():
    daemon = load_module()
    assert daemon.motors_are_stopped("STATUS:motors=S,S;dist=16cm;heading=76")
    assert not daemon.motors_are_stopped("STATUS:motors=F60,F60;dist=99cm;heading=0")


if __name__ == "__main__":
    test_parse_helpers()
    test_obstacle_promotes_state()
    test_motors_are_stopped()
    print("ok")
