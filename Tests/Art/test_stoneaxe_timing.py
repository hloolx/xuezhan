import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("timing", ROOT / "Tools/validate_stoneaxe_timing.py")
TIMING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIMING)


def server(event, unit_id=1, sequence=1, start=10, phase=0, team=0, **overrides):
    fields = {"run": "test", "role": "server", "event": event, "pid": 100, "id": unit_id, "seq": sequence,
              "start_sim": start, "sim": start + phase, "team": team, "reason": "queued_melee", "target": 2}
    if event == "replicate_attack":
        fields.update({"start_server": 100 + start, "snapshot_server": 100 + start + phase})
    elif event == "replicate_outcome":
        fields.update({"start_server": 100 + start, "snapshot_server": 100 + start + phase,
                       "end_sim": start + .35, "end_server": 100 + start + .35, "outcome": 2})
    fields.update(overrides)
    return TIMING.PREFIX + " ".join(str(key) + "=" + str(value) for key, value in fields.items())


def client(event, phase, unit_id=1, sequence=1, start=10, **overrides):
    fields = {"run": "test", "role": "client", "event": event, "pid": 200, "id": unit_id, "seq": sequence,
              "start_server": 100 + start, "server_now": 100 + start + phase, "phase": phase,
              "reason": "on_time", "release_pending": int(event == "contact"), "notify_damage": "false"}
    fields["outcome"] = 2 if event in {"contact", "release_evidence", "release_skipped"} else 1
    fields["end_server"] = 100 + start + .35 if fields["outcome"] == 2 else -1
    fields.update(overrides)
    return TIMING.PREFIX + " ".join(str(key) + "=" + str(value) for key, value in fields.items())


def normal(unit_id=1, sequence=1, start=10, team=0):
    args = {"unit_id": unit_id, "sequence": sequence, "start": start}
    return [server("start", team=team, **args), server("replicate_attack", phase=.02, team=team, **args),
            server("release", phase=.35, team=team, **args), server("replicate_outcome", phase=.35, team=team, **args), client("observe", .1, **args),
            client("sample", .351, **args), client("contact", .351, **args)]


def analyze(lines):
    records, errors = TIMING.parse_lines("\n".join(lines), "synthetic_fixture_not_runtime.log")
    return TIMING.analyze(records, "test", errors)


def codes(report):
    return {entry["code"] for entry in report["failures"]}


class StoneAxeTimingTests(unittest.TestCase):
    def test_release_effect_gate_reads_actual_cpp_and_never_guesses_from_pose_contact(self):
        presentation = (ROOT / "Source/CivWar/View/CWSkeletalUnitPresentation.cpp").read_text(encoding="utf-8-sig")
        condition = re.search(r"if \((!bReleaseEvidenceConsumed[^\n]+)\)", presentation).group(1)
        pending = re.search(r"bReleasePending = (AttackAge[^;]+);", presentation).group(1)

        def evaluate(expression, consumed, outcome, start, end, now, age):
            expression = expression.replace("static_cast<uint8>(cw::AttackOutcome::Released)", "2")
            for name, replacement in {"bReleaseEvidenceConsumed": "consumed", "AttackOutcome": "outcome", "AttackStartTime": "start", "AttackEndTime": "end", "ServerNow": "now", "AttackAge": "age", "ContactTime": "contact"}.items():
                expression = expression.replace(name, replacement)
            expression = expression.replace("&&", " and ").replace("!", "not ").replace("0.1f", "0.1")
            self.assertRegex(expression, r"^[a-z0-9.() <>=+\-]+$")
            return eval(expression, {"__builtins__": {}}, {"consumed": consumed, "outcome": outcome, "start": start, "end": end, "now": now, "age": age, "contact": .35})

        for outcome in (0, 1, 3):
            self.assertFalse(evaluate(condition, False, outcome, 10, 10.35, 10.35, .35))
        self.assertTrue(evaluate(condition, False, 2, 10, 10.35, 10.35, .35))
        self.assertTrue(evaluate(pending, False, 2, 10, 10.35, 10.38, .38))
        self.assertFalse(evaluate(pending, False, 2, 10, 10.35, 10.6, .6))
        self.assertFalse(evaluate(condition, True, 2, 10, 10.35, 10.35, .35))
        self.assertFalse(evaluate(condition, False, 2, 10, 10.4, 10.35, .35))
        self.assertFalse(evaluate(condition, False, 2, 10, -1, 10.35, .35))

    def test_terminal_metadata_is_read_only_stable_and_removed_with_units(self):
        simulation = (ROOT / "Source/CivWar/Sim/Simulation.cpp").read_text(encoding="utf-8-sig")
        replicator = (ROOT / "Source/CivWar/Net/CWBattleReplicator.cpp").read_text(encoding="utf-8-sig")
        state = (ROOT / "Source/CivWar/Sim/SimState.h").read_text(encoding="utf-8-sig")
        self.assertIn("AttackOutcome AttackResult = AttackOutcome::None;", state)
        self.assertEqual(1, simulation.count("RecordAttackEnd(U, AttackOutcome::Released, SimTime);"))
        self.assertEqual(4, simulation.count("RecordAttackEnd(U, AttackOutcome::Cancelled, SimTime);"))
        self.assertIn("RecordAttackEnd(Pending, AttackOutcome::Cancelled, SimTime);", simulation)
        self.assertIn("U.AttackEndSimTime = -1.f;", simulation)
        self.assertIn("Item.AttackOutcome != QAttackOutcome || !PreviousAttackEnd || *PreviousAttackEnd != U.AttackEndSimTime", replicator)
        self.assertIn("SnapshotServerTime - (Sim.Time() - U.AttackEndSimTime)", replicator)
        self.assertIn("UnitAttackEndSimTimes.Reset();", replicator)
        self.assertIn("UnitAttackEndSimTimes.Remove(Units.Items[I].Id);", replicator)

    def test_normal_pair_compares_same_server_clock_but_does_not_approve_missing_protocol(self):
        report = analyze(normal())
        self.assertEqual([], report["failures"])
        self.assertEqual("not_verified", report["status"])
        self.assertFalse(report["timing_approved"])
        self.assertFalse(report["coverage"]["cancel_protocol_replicated"])
        self.assertEqual([0], report["coverage"]["normal_release_contact_teams"])
        self.assertAlmostEqual(.001, report["attacks"][0]["clients"][0]["contact_minus_authoritative_release_seconds"][0])

    def test_both_team_normal_coverage_does_not_hide_missing_cancellation_or_late_join(self):
        report = analyze(normal() + normal(unit_id=9, team=1))
        self.assertEqual([0, 1], report["coverage"]["normal_release_contact_teams"])
        self.assertIn("both_team_cancellation_coverage_required", report["unverified_requirements"])
        self.assertIn("late_delivery_no_replay_coverage_required", report["unverified_requirements"])
        self.assertEqual("not_verified", report["status"])

    def test_canceled_attack_residual_contact_fails_without_claiming_damage(self):
        lines = normal()
        lines[2] = server("cancel", phase=.2, reason="invalid_target")
        report = analyze(lines)
        self.assertIn("contact_after_authoritative_cancel", codes(report))
        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["attacks"][0]["clients"][0]["residual_attack_samples_after_cancel"])
        self.assertIn("not confirmed target damage", report["limits"][0])

    def test_death_cancellation_without_contact_is_observation_not_protocol_proof(self):
        lines = [server("start"), server("replicate_attack"), server("cancel", phase=.2, reason="attacker_died"),
                 server("replicate_outcome", phase=.2, end_sim=10.2, end_server=110.2, outcome=3), client("observe", .1),
                 client("cancel_observed", .22, outcome=3, end_server=110.2), client("suppress", .22, reason="death", release_pending=0)]
        report = analyze(lines)
        self.assertEqual([], report["failures"])
        self.assertEqual([0], report["coverage"]["cancel_without_contact_teams"])
        self.assertFalse(report["timing_approved"])

    def test_late_and_expired_attacks_are_not_replayed(self):
        for phase, reason in ((.6, "late"), (1.2, "expired")):
            lines = normal()[:4] + [client("observe", phase, reason=reason), client("finished", 1.3)]
            report = analyze(lines)
            self.assertEqual([], report["failures"])
            self.assertEqual([200], report["coverage"]["late_no_replay_client_pids"])
            report = analyze(lines + [client("contact", phase)])
            self.assertIn("late_or_initial_attack_replayed", codes(report))

    def test_initial_snapshot_never_replays_historical_contact_even_before_contact(self):
        lines = normal()[:4] + [client("observe", .1, reason="initial_snapshot"), client("sample", .4), client("finished", 1.01)]
        report = analyze(lines)
        self.assertEqual([], report["failures"])
        self.assertEqual([200], report["coverage"]["initial_snapshot_no_replay_client_pids"])
        self.assertIn("late_or_initial_attack_replayed", codes(analyze(lines + [client("contact", .4)])))

    def test_sequence_zero_and_wrap_are_disambiguated_by_start_timestamp(self):
        report = analyze(normal(sequence=0) + normal(sequence=0, start=266))
        self.assertEqual([], report["failures"])
        self.assertEqual(2, report["attack_count"])
        self.assertEqual([10, 266], [attack["start_sim"] for attack in report["attacks"]])
        self.assertEqual([1, 1], [attack["clients"][0]["contact_count"] for attack in report["attacks"]])

    def test_client_cannot_use_stale_match_snapshot_as_continuous_phase(self):
        lines = normal()
        lines[5] = client("sample", .35, server_now=110.6)
        self.assertIn("client_phase_not_server_clock", codes(analyze(lines)))

    def test_accumulator_mapping_and_stable_same_attack_stamp(self):
        lines = normal()
        lines[1] = server("replicate_attack", phase=.05, snapshot_server=110.07)
        self.assertIn("incorrect_snapshot_clock_mapping", codes(analyze(lines)))
        lines = normal() + [server("replicate_attack", phase=.1, start_server=110.01, snapshot_server=110.11)]
        self.assertIn("same_attack_replication_timestamp_changed", codes(analyze(lines)))

    def test_duplicate_contact_and_early_contact_fail(self):
        self.assertIn("duplicate_client_contact", codes(analyze(normal() + [client("contact", .36)])))
        lines = normal()
        lines[-1] = client("contact", .2)
        self.assertIn("early_client_contact", codes(analyze(lines)))

    def test_late_render_frame_skips_effect_and_is_not_claimed_as_alignment_pass(self):
        lines = normal()
        lines[-1] = client("contact", .8, release_pending=0)
        report = analyze(lines)
        self.assertIn("contact_window_not_sampled_due_to_late_frame", report["unverified_requirements"])
        self.assertFalse(report["timing_approved"])
        lines[-1] = client("contact", .8, release_pending=1)
        self.assertIn("stale_contact_effect_replayed", codes(analyze(lines)))

    def test_missing_or_old_logs_never_pass(self):
        report = analyze(["CIVWAR_STONEAXE_CONTACT id=1 seq=1 phase=0.35"])
        self.assertEqual(0, report["record_count"])
        self.assertEqual("not_verified", report["status"])
        self.assertIn("no_real_timing_records_for_requested_run", report["unverified_requirements"])
        report = analyze([client("contact", .35)])
        self.assertIn("client_record_without_unique_server_attack_mapping", report["unverified_requirements"])

    def test_malformed_nonfinite_and_damage_claim_fail_closed(self):
        self.assertIn("malformed_timing_record", codes(analyze([client("sample", float("nan"))])))
        lines = normal()
        lines[-1] = client("contact", .35, notify_damage="true")
        self.assertIn("client_damage_authority_not_false", codes(analyze(lines)))

    def test_mixed_server_sessions_with_same_run_are_rejected(self):
        report = analyze(normal() + [server("start", unit_id=2, pid=300)])
        self.assertIn("multiple_authoritative_processes", codes(report))

    def test_late_observation_without_closed_window_does_not_prove_no_replay(self):
        report = analyze(normal()[:4] + [client("observe", .6, reason="late")])
        self.assertEqual([], report["coverage"]["late_no_replay_client_pids"])
        self.assertIn("late_delivery_no_replay_coverage_required", report["unverified_requirements"])

    def test_attack_pose_after_cancellation_received_fails(self):
        lines = [server("start"), server("replicate_attack"), server("cancel", phase=.2, reason="invalid_target"),
                 server("replicate_outcome", phase=.2, end_sim=10.2, end_server=110.2, outcome=3), client("observe", .1),
                 client("cancel_observed", .22, outcome=3, end_server=110.2), client("sample", .3)]
        self.assertIn("attack_pose_continues_after_cancel_received", codes(analyze(lines)))

    def test_full_synthetic_protocol_fixture_requires_all_coverage_to_pass_parser_only(self):
        lines = normal() + normal(unit_id=2, team=1)
        for unit_id, team, start in ((3, 0, 20), (4, 1, 21)):
            args = {"unit_id": unit_id, "team": team, "start": start}
            lines += [server("start", **args), server("replicate_attack", **args), server("cancel", phase=.2, **args),
                      server("replicate_outcome", phase=.2, end_sim=start + .2, end_server=start + 100.2, outcome=3, **args),
                      client("observe", .1, unit_id=unit_id, start=start),
                      client("cancel_observed", .25, unit_id=unit_id, start=start, outcome=3, end_server=start + 100.2),
                      client("finished", .25, unit_id=unit_id, start=start, outcome=3, end_server=start + 100.2)]
        for unit_id, reason, start in ((5, "late", 30), (6, "initial_snapshot", 40)):
            lines += normal(unit_id=unit_id, start=start)[:4] + [client("observe", .6, unit_id=unit_id, start=start, reason=reason), client("finished", 1.01, unit_id=unit_id, start=start)]
        report = analyze(lines)
        self.assertEqual([], report["failures"])
        self.assertEqual([], report["unverified_requirements"])
        self.assertEqual("passed", report["status"])
        self.assertFalse(report["production_approved"])

    def test_diagnostics_do_not_add_events_or_change_simulation_rules(self):
        simulation = (ROOT / "Source/CivWar/Sim/Simulation.cpp").read_text(encoding="utf-8-sig")
        replicator = (ROOT / "Source/CivWar/Net/CWBattleReplicator.cpp").read_text(encoding="utf-8-sig")
        presentation = (ROOT / "Source/CivWar/View/CWSkeletalUnitPresentation.cpp").read_text(encoding="utf-8-sig")
        self.assertEqual(1, simulation.count("U.AttackSeq = static_cast<uint8_t>(U.AttackSeq + 1);"))
        self.assertEqual(1, simulation.count('TraceArtTiming("start",'))
        self.assertEqual(1, simulation.count('TraceArtTiming("release",'))
        self.assertEqual(4, simulation.count('TraceArtTiming("cancel",'))
        self.assertIn('#if defined(WITH_ENGINE) && WITH_ENGINE\n#include "CoreMinimal.h"', simulation)
        self.assertIn("[[maybe_unused]]", simulation)
        self.assertIn("PendingHits.push_back(Hit);", simulation)
        self.assertIn("U.Windup -= Dt;", simulation)
        self.assertNotIn("EventType::UnitAttackCancel", simulation)
        self.assertNotIn("EventType::UnitAttackRelease", simulation)
        self.assertEqual(2, replicator.count("TraceAttackReplication(Sim, U, Item.AttackStartServerTime, SnapshotServerTime);"))
        self.assertIn('TEXT("cwarttiming")', presentation)
        self.assertIn("bContactConsumed = !bInitialized || Age < 0.f || Age >= ContactTime;", presentation)
        self.assertIn("bReleasePending = AttackAge - ContactTime <= 0.1f && ServerNow - AttackEndTime <= 0.1f;", presentation)
        self.assertIn("Component->SetPosition(FMath::Clamp(PartTime, 0.f, PartClip->GetPlayLength()), false);", presentation)
        self.assertIn("SamplePart(Body, Clip, Time);", presentation)


if __name__ == "__main__":
    unittest.main()
