"""Bounded startup must not hide a late start or a stop during continuous walking."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Tools"))
from validate_era_gameplay import validate_motion


class EraMotionDiagnosticTests(unittest.TestCase):
    valid = (
        "CIVWAR_UNIT_MOTION id=1 status=complete duration=2.000 stopped_frames=0 "
        "startup_seconds=0.083 startup_frame_seconds=0.017 "
        "startup_limit_seconds=0.117 buffer_seconds=0.100 sample_policy=bounded_start_v1"
    )

    def test_bounded_start_and_full_continuous_window(self):
        self.assertEqual(validate_motion([self.valid]), [])

    def test_startup_failure_cannot_pass_with_zero_stopped_frames(self):
        self.assertTrue(validate_motion([self.valid.replace("status=complete", "status=startup_failed")]))
        self.assertTrue(validate_motion([self.valid.replace("startup_seconds=0.083", "startup_seconds=0.150")]))

    def test_middle_stop_and_short_window_still_fail(self):
        self.assertTrue(validate_motion([self.valid.replace("stopped_frames=0", "stopped_frames=1")]))
        self.assertTrue(validate_motion([self.valid.replace("duration=2.000", "duration=1.900")]))

    def test_inflated_bound_cannot_hide_late_start(self):
        self.assertTrue(validate_motion([self.valid.replace("startup_limit_seconds=0.117", "startup_limit_seconds=0.500")]))

    def test_old_failed_samples_remain_failed(self):
        self.assertTrue(validate_motion(["CIVWAR_UNIT_MOTION id=1 stopped_frames=4 duration=2.002"]))


if __name__ == "__main__":
    unittest.main()
