from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SIM_STATE = ROOT / "Source/CivWar/Sim/SimState.h"
SIMULATION = ROOT / "Source/CivWar/Sim/Simulation.cpp"
NET_TYPES = ROOT / "Source/CivWar/Net/CWNetTypes.h"
REPLICATOR_HEADER = ROOT / "Source/CivWar/Net/CWBattleReplicator.h"
REPLICATOR_SOURCE = ROOT / "Source/CivWar/Net/CWBattleReplicator.cpp"
GAME_MODE = ROOT / "Source/CivWar/Game/CWGameMode.cpp"


class AttackTimingMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulation = SIMULATION.read_text(encoding="utf-8-sig")
        cls.replicator = REPLICATOR_SOURCE.read_text(encoding="utf-8-sig")
        cls.game_mode = GAME_MODE.read_text(encoding="utf-8-sig")

    def converted_time(self, start_sim, sim_now, snapshot_server):
        assignment = re.search(r"const float QAttackStartServerTime = (.+);", self.replicator)
        self.assertIsNotNone(assignment)
        condition, branches = assignment.group(1).split("?", 1)
        when_valid, otherwise = branches.split(":", 1)
        substitutions = {"U.AttackStartSimTime": "start_sim", "Sim.Time()": "sim_now", "SnapshotServerTime": "snapshot_server"}

        def evaluate(expression):
            for original, replacement in substitutions.items():
                expression = expression.replace(original, replacement)
            expression = re.sub(r"(\d+)\.f\b", r"\1.0", expression).strip()
            self.assertRegex(expression, r"^[a-z_0-9.() <>!=+\-]+$")
            return eval(expression, {"__builtins__": {}}, {"start_sim": start_sim, "sim_now": sim_now, "snapshot_server": snapshot_server})

        return evaluate(when_valid) if evaluate(condition) else evaluate(otherwise)

    def test_unstarted_sentinels_and_replication_field(self):
        self.assertIn("float AttackStartSimTime = -1.f;", SIM_STATE.read_text(encoding="utf-8-sig"))
        self.assertIn("UPROPERTY() float AttackStartServerTime = -1.f;", NET_TYPES.read_text(encoding="utf-8-sig"))
        self.assertEqual(-1.0, self.converted_time(-1, 15, 100))

    def test_metadata_is_written_only_at_existing_attack_sequence_increment(self):
        increment = "U.AttackSeq = static_cast<uint8_t>(U.AttackSeq + 1);"
        self.assertEqual(1, self.simulation.count(increment))
        self.assertEqual(1, self.simulation.count("U.AttackStartSimTime = SimTime;"))
        self.assertRegex(self.simulation, re.escape(increment) + r"\s+U\.AttackStartSimTime = SimTime;\s+U\.AttackResult = AttackOutcome::Windup;\s+U\.AttackEndSimTime = -1\.f;\s+Emit\(EventType::UnitAttackStart")

    def test_units_time_zero_is_valid_even_when_sequence_is_zero(self):
        self.assertEqual(99.0, self.converted_time(0, 1, 100))
        self.assertNotRegex(self.replicator, r"AttackSeq\s*(?:>|>=|==|!=)\s*0")

    def test_snapshot_formula_compensates_catchup_and_accumulator(self):
        self.assertAlmostEqual(99.83, self.converted_time(9.85, 10, 100 - .02), places=6)
        self.assertAlmostEqual(.35, 100.18 - self.converted_time(9.85, 10, 99.98), places=6)

    def test_first_item_and_late_join_keep_valid_attack_time(self):
        first_item = self.replicator.split("Units.Items.AddDefaulted_GetRef()", 1)[1].split("bool bUnitsRemoved", 1)[0]
        self.assertIn("Item.AttackStartServerTime = QAttackStartServerTime;", first_item)
        self.assertIn("UnitAttackStartSimTimes.Add(U.Id, U.AttackStartSimTime);", first_item)
        self.assertAlmostEqual(.2, 100.2 - self.converted_time(5, 5.2, 100.2), places=6)

    def test_same_attack_retains_stamp_instead_of_marking_every_snapshot_dirty(self):
        gate = "Item.AttackSeq != U.AttackSeq || !PreviousAttackStart || *PreviousAttackStart != U.AttackStartSimTime"
        self.assertIn(gate, self.replicator)
        self.assertEqual(1, self.replicator.count("Assign(Item.AttackStartServerTime, QAttackStartServerTime);"))
        block = re.search(re.escape("if (" + gate + ")") + r"\s*\{([^}]+)\}", self.replicator)
        self.assertIsNotNone(block)
        self.assertIn("Assign(Item.AttackStartServerTime, QAttackStartServerTime);", block.group(1))
        self.assertLess(self.replicator.index(gate), self.replicator.index("Assign(Item.AttackSeq, U.AttackSeq);"))

    def test_full_sequence_wrap_is_detected_from_sim_timestamp(self):
        self.assertIn("*PreviousAttackStart != U.AttackStartSimTime", self.replicator)
        first = self.converted_time(1, 1, 101)
        wrapped = self.converted_time(257, 257, 357)
        self.assertNotEqual(first, wrapped)

    def test_server_cache_cleared_and_removed_with_units(self):
        self.assertIn("TMap<int32, float> UnitAttackStartSimTimes;", REPLICATOR_HEADER.read_text(encoding="utf-8-sig"))
        self.assertIn("UnitAttackStartSimTimes.Reset();", self.replicator.split("void ACWBattleReplicator::SyncFromSim", 1)[0])
        self.assertIn("UnitAttackStartSimTimes.Remove(Units.Items[I].Id);", self.replicator)

    def test_world_snapshot_parameter_keeps_original_projectile_clock(self):
        signature = "const cw::Simulation& Sim, float ServerTime, float SnapshotServerTime"
        self.assertIn(signature, REPLICATOR_HEADER.read_text(encoding="utf-8-sig"))
        self.assertIn(signature, self.replicator)
        self.assertIn("Replicator->SyncFromSim(*Sim, ServerTime, ServerTime - Accumulator);", self.game_mode)
        self.assertLess(self.game_mode.index("Accumulator -= FixedStep;"), self.game_mode.index("Replicator->SyncFromSim(*Sim, ServerTime, ServerTime - Accumulator);"))
        projectiles = self.replicator.split("// ---------- 投射物", 1)[1]
        self.assertNotIn("SnapshotServerTime", projectiles)
        self.assertIn("ProjectileExpire.Add(Id, ServerTime + 0.5f);", projectiles)
        self.assertIn("*Expire <= ServerTime", projectiles)

    def test_no_clock_uses_client_match_time_snapshot(self):
        self.assertNotIn("GetMatchTime", self.replicator)
        self.assertIn("State->GetServerWorldTimeSeconds()", self.game_mode)


if __name__ == "__main__":
    unittest.main()
