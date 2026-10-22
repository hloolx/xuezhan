import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location("stone_timing",ROOT/"Tools/validate_stone_era_timing.py")
TIMING=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIMING)


def line(event="contact",**changes):
    fields={"asset":"Unit_StoneSlinger","pid":2,"id":10,"seq":1,"start_server":100,"server_now":100.46,
            "phase":.46,"end_server":100.45,"outcome":2,"release_pending":1,"notify_damage":"false","event":event}
    fields.update(changes)
    return TIMING.PREFIX+" ".join(f"{k}={v}" for k,v in fields.items())


class StoneEraTimingTests(unittest.TestCase):
    def test_observed_release_uses_each_units_authoritative_windup(self):
        self.assertFalse(TIMING.analyze(line())["failures"])
        self.assertFalse(TIMING.analyze(line(asset="Champion_Stone",server_now=100.31,phase=.31,end_server=100.3))["failures"])

    def test_pose_does_not_authorize_damage_or_release(self):
        self.assertTrue(TIMING.analyze(line(outcome=1))["failures"])
        self.assertTrue(TIMING.analyze(line("contact_pose"))["failures"])

    def test_initial_snapshot_and_late_release_cannot_replay(self):
        log=line("observe",reason="initial_snapshot",release_pending=0)+"\n"+line()
        self.assertTrue(TIMING.analyze(log)["failures"])
        self.assertTrue(TIMING.analyze(line(server_now=101,phase=1))["failures"])

    def test_duplicate_contact_is_rejected(self):
        self.assertTrue(TIMING.analyze(line()+"\n"+line())["failures"])

    def test_wrong_clock_is_rejected(self):
        self.assertTrue(TIMING.analyze(line(phase=.01))["failures"])

    def test_absent_trace_does_not_claim_success(self):
        result=TIMING.analyze("No assets yet")
        self.assertEqual("no_new_asset_timing_observed",result["status"])
        self.assertFalse(result["network_transport_verified"])


if __name__=="__main__":
    unittest.main()
