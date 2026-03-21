import importlib.util
import pathlib
import unittest

ROVERCTL_PATH = pathlib.Path(__file__).resolve().parent / "bin" / "roverctl.py"
spec = importlib.util.spec_from_file_location("roverctl", ROVERCTL_PATH)
roverctl = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(roverctl)


class RoverCtlOrientationTest(unittest.TestCase):
    def test_sensor_faces_front_after_motor_rewire(self):
        self.assertFalse(roverctl.SENSOR_FACING_REAR)
        self.assertEqual(roverctl.SENSOR_HEADING_OFFSET, 0)

    def test_scan_recommends_forward_for_best_clearance(self):
        formatted = roverctl.format_scan_rows([(0, 40), (180, 15)], "test")
        self.assertIn("recommend_move=forward", formatted)


if __name__ == "__main__":
    unittest.main()
