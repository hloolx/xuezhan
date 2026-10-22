import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("delay_audit", ROOT / "Tools/audit_stoneaxe_presentation_delay.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def line(**values):
    return AUDIT.PREFIX + " ".join(str(key) + "=" + str(value) for key, value in {"run": "test", "mode": "local_presentation_only", "pid": 100, **values}.items())


def snapshot(event, serial, unit_id, team, now=10, pending=1, **changes):
    values = {"event": event, "serial": serial, "id": unit_id, "team": team, "def": 0, "row": 1, "seq": 1,
              "start_server": 10, "outcome": 1, "end_server": -1, "x": 20, "hp": 110, "state": 2, "hit_seq": 0,
              "target": 2, "max_hp": 110, "rank": 0, "flags": 0, "arrived": 10, "now": now,
              "held_ms": round((now - 10) * 1000, 3), "server_now": now, "pending": pending, "removal": 0}
    values.update(changes)
    return line(**values)


def fixture():
    return [line(status="enabled", delay_ms=450, network_transport="false"),
            line(event="select", id=3, team=0, cohort="first_ordinary_stoneaxe"),
            line(event="select", id=4, team=1, cohort="first_ordinary_stoneaxe"),
            "CIVWAR_ART_TIMING run=test role=server event=replicate_attack pid=100 id=3 seq=1 start_server=10",
            "CIVWAR_ART_TIMING run=test role=server event=replicate_attack pid=100 id=4 seq=1 start_server=10",
            snapshot("enqueue", 1, 3, 0), snapshot("enqueue", 2, 4, 1),
            snapshot("deliver", 2, 4, 1, 10.45, 0), snapshot("deliver", 1, 3, 0, 10.45, 0), line(event="reset", units=2, pending=0)]


def audit(lines):
    return AUDIT.audit("\n".join(lines), "test")


def codes(report):
    return {failure["code"] for failure in report["failures"]}


class DelaySerialAuditTests(unittest.TestCase):
    def test_cross_team_global_serial_inversion_is_valid(self):
        result = audit(fixture())
        self.assertEqual("passed", result["status"])
        self.assertEqual(16, result["payload_field_count"])
        self.assertEqual(450, result["minimum_held_ms"])
        self.assertFalse(result["network_timing_approved"])
        self.assertFalse(result["production_approved"])

    def test_every_payload_change_is_rejected(self):
        for field in AUDIT.PAYLOAD:
            lines = fixture()
            lines[8] = re.sub(r'\b' + field + r'=[^\s]+', field + '=999', lines[8])
            self.assertEqual("failed", audit(lines)["status"], field)

    def test_same_unit_out_of_order_is_rejected(self):
        lines = fixture()
        lines.insert(7, snapshot("enqueue", 3, 3, 0, pending=2, hp=100))
        lines[9] = snapshot("deliver", 3, 3, 0, 10.45, 1, hp=100)
        lines.insert(10, snapshot("deliver", 1, 3, 0, 10.5, 0))
        self.assertIn("per_unit_fifo_violation", codes(audit(lines)))

    def test_early_delivery_never_uses_rounding_tolerance_to_pass(self):
        lines = fixture()
        lines[8] = snapshot("deliver", 1, 3, 0, 10.449999, 0)
        self.assertIn("delivery_before_450ms", codes(audit(lines)))

    def test_forged_held_duration_disagrees_with_timestamps(self):
        lines = fixture()
        lines[8] = snapshot("deliver", 1, 3, 0, 10.1, 0, held_ms=450)
        self.assertIn("held_time_inconsistent_with_timestamps", codes(audit(lines)))

    def test_duplicate_and_orphan_serials_fail(self):
        for changed in (fixture() + [fixture()[8]], fixture()[:8] + [snapshot("deliver", 99, 3, 0, 10.45, 0)]):
            self.assertIn("invalid_delay_record", codes(audit(changed)))

    def test_changed_arrival_or_removal_flag_fails(self):
        for changes in ({"arrived": 9}, {"removal": 1}):
            lines = fixture()
            lines[8] = snapshot("deliver", 1, 3, 0, 10.45, 0, **changes)
            self.assertEqual("failed", audit(lines)["status"])

    def test_missing_delivery_cannot_pass(self):
        result = audit(fixture()[:8])
        self.assertEqual("not_verified", result["status"])
        self.assertEqual([1], result["unmatched_serials"])

    def test_overflow_rejection_or_pending_reset_fail(self):
        for record in (line(status="failed", reason="queue_overflow"), line(status="rejected"), line(event="reset", units=2, pending=1)):
            self.assertEqual("failed", audit(fixture() + [record])["status"])

    def test_champion_or_non_stoneaxe_authority_mapping_fails(self):
        lines = fixture()
        lines[5] = snapshot("enqueue", 1, 3, 0, flags=1)
        self.assertEqual("failed", audit(lines)["status"])
        lines = fixture()
        lines[3] = lines[3].replace("id=3", "id=9")
        self.assertIn("initial_snapshot_without_stoneaxe_authority_mapping", codes(audit(lines)))

    def test_extra_selected_target_or_nonlocal_scope_cannot_pass(self):
        self.assertNotEqual("passed", audit(fixture() + [line(event="select", id=9, team=1, cohort="first_ordinary_stoneaxe")])["status"])
        self.assertEqual("failed", audit([record.replace("mode=local_presentation_only", "mode=network") for record in fixture()])["status"])

    def test_delayed_removal_keeps_payload_and_fifo(self):
        lines = fixture()[:-1]
        lines += [snapshot("enqueue_remove", 3, 3, 0, now=11, arrived=11, held_ms=0, removal=1),
                  snapshot("deliver_remove", 3, 3, 0, now=11.45, arrived=11, held_ms=450, pending=0, removal=1)]
        report = audit(lines)
        self.assertEqual("passed", report["status"])
        self.assertEqual(1, report["removals_delivered"])


if __name__ == "__main__":
    unittest.main()
