from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re


PREFIX = "CIVWAR_ART_TIMING "
CONTACT_SECONDS = .35
CLOCK_TOLERANCE_SECONDS = .002
CONTACT_TOLERANCE_SECONDS = .1
SIM_STEP_TOLERANCE_SECONDS = .051
SERVER_EVENTS = {"start", "release", "cancel", "interrupted", "replicate_attack", "replicate_outcome"}
CLIENT_EVENTS = {"observe", "sample", "contact_pose", "contact", "suppress", "cancel_observed", "release_evidence", "release_skipped", "finished"}


def parse_lines(text, source):
    records, errors = [], []
    for line_number, line in enumerate(text.splitlines(), 1):
        if PREFIX not in line:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line.split(PREFIX, 1)[1]))
        fields["source"] = source
        fields["line"] = line_number
        try:
            for key in ("run", "role", "event"):
                if not fields.get(key):
                    raise ValueError("Missing " + key)
            for key in ("pid", "id", "seq"):
                fields[key] = int(fields[key])
            if fields["pid"] <= 0 or not 0 <= fields["seq"] <= 255:
                raise ValueError("Invalid process ID or uint8 attack sequence")
            if fields["role"] == "server" and fields["event"] in SERVER_EVENTS:
                fields["team"] = int(fields["team"])
                required = ["start_sim", "sim"]
                if fields["event"] == "replicate_attack":
                    required += ["start_server", "snapshot_server"]
                elif fields["event"] == "replicate_outcome":
                    fields["outcome"] = int(fields["outcome"])
                    required += ["start_server", "end_sim", "end_server", "snapshot_server"]
            elif fields["role"] == "client" and fields["event"] in CLIENT_EVENTS:
                fields["release_pending"] = int(fields["release_pending"])
                fields["outcome"] = int(fields["outcome"])
                required = ["start_server", "end_server", "server_now", "phase"]
            else:
                raise ValueError("Unknown timing role/event")
            for key in required:
                fields[key] = float(fields[key])
                if not math.isfinite(fields[key]):
                    raise ValueError("Non-finite timing value")
            records.append(fields)
        except (ValueError, KeyError) as error:
            errors.append({"code": "malformed_timing_record", "source": source, "line": line_number, "detail": str(error)})
    return records, errors


def analyze(records, run, parse_errors=None):
    selected = [record for record in records if record["run"] == run]
    failures = list(parse_errors or [])
    missing = []
    attacks = defaultdict(list)
    client_records = []
    for record in selected:
        if record["role"] == "server":
            attacks[(record["pid"], record["id"], record["seq"], record["start_sim"])].append(record)
        else:
            client_records.append(record)
    if not selected:
        missing.append("no_real_timing_records_for_requested_run")
    if len({key[0] for key in attacks}) > 1:
        failures.append({"code": "multiple_authoritative_processes", "detail": "Use a separate run token per match; mixed sessions cannot be associated safely"})
    mappings = []
    grouped_clients = defaultdict(lambda: defaultdict(list))
    for key, events in attacks.items():
        stamps = [event["start_server"] for event in events if event["event"] == "replicate_attack"]
        if stamps and max(stamps) - min(stamps) > CLOCK_TOLERANCE_SECONDS:
            failures.append({"code": "same_attack_replication_timestamp_changed", "attack": list(key)})
        for event in events:
            if event["event"] == "replicate_attack":
                mappings.append((key, event))
                expected = event["snapshot_server"] - (event["sim"] - event["start_sim"])
                if abs(expected - event["start_server"]) > CLOCK_TOLERANCE_SECONDS:
                    failures.append({"code": "incorrect_snapshot_clock_mapping", "attack": list(key), "error_seconds": event["start_server"] - expected})
    for record in client_records:
        candidates = {key for key, mapping in mappings if key[1:3] == (record["id"], record["seq"]) and abs(mapping["start_server"] - record["start_server"]) <= CLOCK_TOLERANCE_SECONDS}
        if len(candidates) != 1:
            missing.append("client_record_without_unique_server_attack_mapping")
            continue
        key = next(iter(candidates))
        grouped_clients[key][record["pid"]].append(record)
        if record.get("notify_damage") != "false":
            failures.append({"code": "client_damage_authority_not_false", "attack": list(key), "source": record["source"], "line": record["line"]})
        if record["event"] in {"sample", "contact_pose", "contact"} and abs(record["phase"] - max(0, record["server_now"] - record["start_server"])) > CLOCK_TOLERANCE_SECONDS:
            failures.append({"code": "client_phase_not_server_clock", "attack": list(key), "client_pid": record["pid"]})
    normal_teams, cancel_teams, late_clients, initial_clients, protocol_teams = set(), set(), set(), set(), set()
    comparisons = []
    for key, events in attacks.items():
        by_event = defaultdict(list)
        for event in events:
            by_event[event["event"]].append(event)
        starts, releases = by_event["start"], by_event["release"]
        cancels = by_event["cancel"] + by_event["interrupted"]
        outcomes = by_event["replicate_outcome"]
        expected_outcome = 2 if releases else (3 if cancels else None)
        terminal_events = releases or cancels
        for outcome in outcomes:
            if outcome["outcome"] != expected_outcome or not terminal_events or abs(outcome["end_sim"] - terminal_events[0]["sim"]) > CLOCK_TOLERANCE_SECONDS:
                failures.append({"code": "replicated_outcome_disagrees_with_authority", "attack": list(key)})
            if abs(outcome["end_server"] - (outcome["snapshot_server"] - (outcome["sim"] - outcome["end_sim"]))) > CLOCK_TOLERANCE_SECONDS:
                failures.append({"code": "incorrect_terminal_clock_mapping", "attack": list(key)})
        if terminal_events and not outcomes:
            missing.append("authoritative_end_replication_evidence_missing")
        if outcomes and max(event["end_server"] for event in outcomes) - min(event["end_server"] for event in outcomes) > CLOCK_TOLERANCE_SECONDS:
            failures.append({"code": "same_attack_terminal_timestamp_changed", "attack": list(key)})
        if len(starts) != 1:
            missing.append("missing_or_duplicate_server_start")
        if len(releases) > 1 or len(cancels) > 1 or (releases and cancels):
            failures.append({"code": "contradictory_authoritative_outcome", "attack": list(key)})
        if not releases and not cancels:
            missing.append("attack_outcome_not_observed")
        for release in releases:
            if abs((release["sim"] - key[3]) - CONTACT_SECONDS) > SIM_STEP_TOLERANCE_SECONDS:
                failures.append({"code": "server_release_not_expected_windup", "attack": list(key), "phase_seconds": release["sim"] - key[3]})
        attack_report = {"server_pid": key[0], "id": key[1], "seq": key[2], "start_sim": key[3],
                         "team": events[0]["team"], "authoritative_outcome": "release" if releases else ("cancel_or_interrupted" if cancels else "unobserved"), "clients": []}
        if not grouped_clients[key]:
            missing.append("attack_without_client_evidence")
        for client_pid, observations in grouped_clients[key].items():
            contacts = [event for event in observations if event["event"] == "contact"]
            samples = [event for event in observations if event["event"] == "sample"]
            received = [event for event in observations if event["event"] == "observe"]
            suppressed = [event for event in observations if event["event"] == "suppress"]
            cancellations = [event for event in observations if event["event"] == "cancel_observed"]
            finished = [event for event in observations if event["event"] == "finished"]
            if len(contacts) > 1:
                failures.append({"code": "duplicate_client_contact", "attack": list(key), "client_pid": client_pid})
            if not received:
                missing.append("client_attack_observation_missing")
            late = any(event.get("reason") in {"late", "expired"} or (event.get("reason") == "initial_snapshot" and event["server_now"] - event["start_server"] >= CONTACT_SECONDS) for event in received)
            late = late or any(event["event"] == "release_evidence" and event["server_now"] - event["start_server"] > CONTACT_SECONDS + CONTACT_TOLERANCE_SECONDS for event in observations)
            initial = any(event.get("reason") == "initial_snapshot" for event in received)
            if (late or initial) and contacts:
                failures.append({"code": "late_or_initial_attack_replayed", "attack": list(key), "client_pid": client_pid})
            closed = bool(suppressed or cancellations or finished) or any(event.get("reason") == "expired" and event["server_now"] - event["start_server"] >= 1 for event in received)
            if late and not contacts and closed:
                late_clients.add(client_pid)
            if initial and not contacts and closed:
                initial_clients.add(client_pid)
            for observed in cancellations:
                if not cancels or observed["outcome"] != 3 or not outcomes or abs(observed["end_server"] - outcomes[0]["end_server"]) > CLOCK_TOLERANCE_SECONDS:
                    failures.append({"code": "client_cancel_without_matching_authority", "attack": list(key), "client_pid": client_pid})
                else:
                    protocol_teams.add(attack_report["team"])
                if any(event["server_now"] > observed["server_now"] + CLOCK_TOLERANCE_SECONDS for event in samples):
                    failures.append({"code": "attack_pose_continues_after_cancel_received", "attack": list(key), "client_pid": client_pid})
            residual_samples = 0
            contact_deltas = []
            for contact in contacts:
                release_proven = bool(outcomes and releases and contact["outcome"] == 2 and abs(contact["end_server"] - outcomes[0]["end_server"]) <= CLOCK_TOLERANCE_SECONDS)
                if not release_proven:
                    failures.append({"code": "contact_without_authoritative_release_evidence", "attack": list(key), "client_pid": client_pid})
                if contact["release_pending"] and (contact["server_now"] < contact["end_server"] - CLOCK_TOLERANCE_SECONDS or contact["server_now"] - contact["end_server"] > CONTACT_TOLERANCE_SECONDS + CLOCK_TOLERANCE_SECONDS):
                    failures.append({"code": "contact_outside_authoritative_release_window", "attack": list(key)})
                if contact["phase"] < CONTACT_SECONDS - CLOCK_TOLERANCE_SECONDS:
                    failures.append({"code": "early_client_contact", "attack": list(key), "phase_seconds": contact["phase"]})
                if contact["phase"] - CONTACT_SECONDS > CONTACT_TOLERANCE_SECONDS + CLOCK_TOLERANCE_SECONDS:
                    if contact["release_pending"]:
                        failures.append({"code": "stale_contact_effect_replayed", "attack": list(key)})
                    else:
                        missing.append("contact_window_not_sampled_due_to_late_frame")
                if releases:
                    release_server = outcomes[0]["end_server"] if outcomes else contact["start_server"] + releases[0]["sim"] - key[3]
                    delta = contact["server_now"] - release_server
                    contact_deltas.append(delta)
                    if abs(delta) > CONTACT_TOLERANCE_SECONDS + SIM_STEP_TOLERANCE_SECONDS:
                        failures.append({"code": "client_contact_not_aligned_with_release", "attack": list(key), "delta_seconds": delta})
                    elif release_proven and contact["release_pending"] and samples and not late and not initial:
                        normal_teams.add(attack_report["team"])
                if cancels:
                    cancel_server = contact["start_server"] + cancels[0]["sim"] - key[3]
                    if contact["server_now"] >= cancel_server - CLOCK_TOLERANCE_SECONDS:
                        failures.append({"code": "contact_after_authoritative_cancel", "attack": list(key), "client_pid": client_pid, "effect_pending": bool(contact["release_pending"]), "reason": cancels[0].get("reason")})
            if cancels:
                cancel_phase = cancels[0]["sim"] - key[3]
                residual_samples = sum(event["phase"] >= cancel_phase for event in samples)
                if not contacts and cancellations and closed:
                    cancel_teams.add(attack_report["team"])
            if releases and not contacts and not late and not initial and not suppressed:
                missing.append("on_time_attack_without_contact_evidence")
            attack_report["clients"].append({"pid": client_pid, "sample_count": len(samples), "contact_count": len(contacts),
                                             "late_or_initial": late or initial, "contact_minus_authoritative_release_seconds": contact_deltas,
                                             "residual_attack_samples_after_cancel": residual_samples})
        comparisons.append(attack_report)
    coverage = {"normal_release_contact_teams": sorted(normal_teams), "cancel_without_contact_teams": sorted(cancel_teams),
                "late_no_replay_client_pids": sorted(late_clients), "initial_snapshot_no_replay_client_pids": sorted(initial_clients),
                "client_pids": sorted({event["pid"] for event in client_records}), "cancel_protocol_replicated": protocol_teams == {0, 1}}
    if normal_teams != {0, 1}:
        missing.append("both_team_normal_release_contact_coverage_required")
    if cancel_teams != {0, 1}:
        missing.append("both_team_cancellation_coverage_required")
    if not late_clients:
        missing.append("late_delivery_no_replay_coverage_required")
    if not initial_clients:
        missing.append("initial_snapshot_no_replay_coverage_required")
    if protocol_teams != {0, 1}:
        missing.append("both_team_authoritative_cancellation_delivery_not_verified")
    status = "failed" if failures else ("not_verified" if missing else "passed")
    return {"status": status, "timing_approved": status == "passed", "production_approved": False,
            "run": run, "record_count": len(selected), "attack_count": len(attacks), "coverage": coverage,
            "failures": failures, "unverified_requirements": sorted(set(missing)), "attacks": comparisons,
            "limits": ["Server release records observe queue/projectile emission, not confirmed target damage or a visual hit.",
                       "Client records observe actual runtime sampling, not merely an imported animation duration.",
                       "Cancellation requires observed matching server outcome and client cancellation; absence of a contact log alone is insufficient.",
                       "No network-latency or game-camera result is inferred from synthetic unit tests."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path, nargs="+", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run) or args.run == "unspecified":
        raise ValueError("Use a unique nonempty -cwarttimingrun token shared by this match's server and clients")
    report_path = args.report.resolve()
    if report_path.exists():
        raise FileExistsError("Preserve prior timing evidence; choose a fresh report path")
    records, parse_errors, sources = [], [], []
    for path in dict.fromkeys(path.resolve() for path in args.logs):
        data = path.read_bytes()
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig", errors="replace")
        parsed, errors = parse_lines(text, str(path))
        records.extend(parsed)
        parse_errors.extend(errors)
        sources.append({"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    report = analyze(records, args.run, parse_errors)
    report.update({"version": "stoneaxe_runtime_timing_diagnostic_v1", "created_at": datetime.now(timezone.utc).isoformat(), "sources": sources})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(report_path), "failures": len(report["failures"]), "unverified": report["unverified_requirements"]}, ensure_ascii=False))
    raise SystemExit(1 if report["failures"] else (0 if report["timing_approved"] else 2))


if __name__ == "__main__":
    main()
