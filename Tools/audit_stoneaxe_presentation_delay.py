from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


PREFIX = "CIVWAR_PRESENTATION_DELAY "
PAYLOAD = ("id", "team", "def", "row", "seq", "start_server", "outcome", "end_server", "x", "hp", "state", "hit_seq", "target", "max_hp", "rank", "flags")
FLOATS = {"start_server", "end_server", "x", "arrived", "now", "held_ms", "server_now"}
INTEGER_FIELDS = set(PAYLOAD) - FLOATS | {"pid", "serial", "pending", "removal"}
TIMESTAMP_ROUNDING_MS = Decimal("0.0011")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_text(path):
    data = Path(path).read_bytes()
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")


def fields(line, prefix):
    pairs = re.findall(r"([a-z_]+)=([^\s]+)", line.split(prefix, 1)[1])
    if len({key for key, value in pairs}) != len(pairs):
        raise ValueError("Duplicate field")
    return dict(pairs)


def audit(text, run):
    failures, missing = [], []
    queues = defaultdict(deque)
    selected, enqueued, delivered = {}, {}, {}
    removed = set()
    pids, enabled = set(), 0
    evidence = []
    authority = set()

    def fail(code, line=None, **detail):
        failures.append({"code": code, "line": line, **detail})

    for line_number, line in enumerate(text.splitlines(), 1):
        if "CIVWAR_ART_TIMING " in line:
            try:
                record = fields(line, "CIVWAR_ART_TIMING ")
                if record.get("run") == run and record.get("role") == "server" and record.get("event") == "replicate_attack":
                    authority.add((record["pid"], record["id"], record["seq"], Decimal(record["start_server"])))
            except (ValueError, KeyError, InvalidOperation):
                fail("malformed_authority_mapping", line_number)
        if PREFIX not in line:
            continue
        try:
            record = fields(line, PREFIX)
            if record.get("run") != run:
                continue
            if record.get("mode") != "local_presentation_only" or int(record["pid"]) <= 0:
                raise ValueError("Unexpected mode/process")
            pids.add(record["pid"])
            if record.get("status") in {"failed", "rejected"}:
                fail("probe_reported_failure", line_number, reason=record.get("reason", record["status"]))
                continue
            if record.get("status") == "enabled":
                if record.get("delay_ms") != "450" or record.get("network_transport") != "false":
                    raise ValueError("Unexpected delay or network scope")
                enabled += 1
                continue
            event = record["event"]
            if event == "reset":
                if int(record["pending"]) != 0 or any(queues.values()):
                    fail("reset_discarded_pending_snapshots", line_number)
                continue
            if event == "select":
                unit_id, team = int(record["id"]), int(record["team"])
                if unit_id in selected or team not in (0, 1) or record.get("cohort") != "first_ordinary_stoneaxe":
                    raise ValueError("Invalid or duplicate selected cohort")
                selected[unit_id] = {"id": unit_id, "team": team, "selection_line": line_number}
                continue
            if event not in {"enqueue", "enqueue_remove", "deliver", "deliver_remove"}:
                raise ValueError("Unknown delay event")
            for key in PAYLOAD + ("pid", "serial", "pending", "removal", "arrived", "now", "held_ms", "server_now"):
                number = Decimal(record[key])
                if not number.is_finite() or (key in INTEGER_FIELDS and number != number.to_integral_value()):
                    raise ValueError("Non-finite or non-integral field " + key)
            unit_id, serial = int(record["id"]), int(record["serial"])
            if unit_id not in selected or int(record["team"]) != selected[unit_id]["team"] or int(record["flags"]) & 1:
                raise ValueError("Unselected, team-changed or champion snapshot")
            if serial <= 0 or not 0 <= int(record["seq"]) <= 255 or record["removal"] != ("1" if event.endswith("remove") else "0"):
                raise ValueError("Invalid serial/sequence/removal")
            if int(record["pending"]) < 0 or int(record["pending"]) > 64:
                raise ValueError("Queue count outside declared bound")
            if event.startswith("enqueue"):
                if serial in enqueued or unit_id in removed:
                    raise ValueError("Duplicate serial or enqueue after removal")
                if record["now"] != record["arrived"] or Decimal(record["held_ms"]) != 0:
                    raise ValueError("Enqueue timestamp was not the recorded arrival")
                if queues[unit_id] and Decimal(record["arrived"]) < Decimal(enqueued[queues[unit_id][-1]]["arrived"]):
                    raise ValueError("Unit arrival order moved backwards")
                enqueued[serial] = {**record, "line": line_number}
                queues[unit_id].append(serial)
                if int(record["pending"]) != len(queues[unit_id]):
                    fail("enqueue_queue_count_mismatch", line_number, serial=serial)
                if event == "enqueue_remove":
                    removed.add(unit_id)
                continue
            if serial in delivered or serial not in enqueued:
                raise ValueError("Duplicate or orphan delivery")
            source = enqueued[serial]
            changed = [key for key in PAYLOAD + ("pid", "serial", "arrived", "removal") if record[key] != source[key]]
            if changed:
                fail("snapshot_fields_changed", line_number, serial=serial, fields=changed)
            if not queues[unit_id] or queues[unit_id][0] != serial:
                fail("per_unit_fifo_violation", line_number, serial=serial, expected=queues[unit_id][0] if queues[unit_id] else None)
                if serial in queues[unit_id]:
                    queues[unit_id].remove(serial)
            else:
                queues[unit_id].popleft()
            if int(record["pending"]) != len(queues[unit_id]):
                fail("delivery_queue_count_mismatch", line_number, serial=serial)
            held = Decimal(record["held_ms"])
            delta_ms = (Decimal(record["now"]) - Decimal(record["arrived"])) * 1000
            if held < 450:
                fail("delivery_before_450ms", line_number, serial=serial, held_ms=str(held))
            if abs(delta_ms - held) > TIMESTAMP_ROUNDING_MS:
                fail("held_time_inconsistent_with_timestamps", line_number, serial=serial)
            delivered[serial] = {**record, "line": line_number}
            evidence.append({"serial": serial, "id": unit_id, "enqueue_line": source["line"], "delivery_line": line_number,
                             "payload_fields_exact": not changed, "held_ms": float(held), "removal": event == "deliver_remove"})
        except (ValueError, KeyError, InvalidOperation) as error:
            fail("invalid_delay_record", line_number, detail=str(error))

    if not enabled:
        missing.append("explicit_local_delay_activation_missing")
    if len(pids) != 1:
        fail("expected_one_local_process", pids=sorted(pids))
    if len(selected) != 2 or sorted(value["team"] for value in selected.values()) != [0, 1]:
        missing.append("exactly_two_selected_ordinary_stoneaxes_one_per_team_required")
    if not enqueued:
        missing.append("actual_snapshots_missing")
    unmatched = sorted(set(enqueued) - set(delivered))
    if unmatched:
        missing.append("some_enqueued_snapshots_not_delivered")
    for unit_id, cohort in selected.items():
        snapshots = [record for record in enqueued.values() if int(record["id"]) == unit_id and record["removal"] == "0"]
        if not snapshots:
            missing.append("selected_unit_has_no_real_attack_snapshot")
            continue
        first = min(snapshots, key=lambda record: record["line"])
        matched = any((pid, source_id, sequence) == (first["pid"], first["id"], first["seq"]) and abs(stamp - Decimal(first["start_server"])) <= Decimal("0.000002") for pid, source_id, sequence, stamp in authority)
        if Decimal(first["start_server"]) < 0 or not matched:
            fail("initial_snapshot_without_stoneaxe_authority_mapping", first["line"], id=unit_id)
        cohort.update({"ordinary_flags_verified": all(not int(record["flags"]) & 1 for record in snapshots),
                       "matched_stoneaxe_only_authority_timing": matched, "definition_indices": sorted({int(record["def"]) for record in snapshots}),
                       "enqueued_serials": [serial for serial, record in enqueued.items() if int(record["id"]) == unit_id],
                       "delivered_serials": [serial for serial, record in delivered.items() if int(record["id"]) == unit_id]})
    report = {"status": "failed" if failures else ("not_verified" if missing else "passed"), "run": run,
              "scope": "Genuine standalone snapshot delivery through a local presentation-only delay; not network transport or active-match joining",
              "network_timing_approved": False, "production_approved": False, "process_ids": sorted(int(pid) for pid in pids),
              "payload_fields_checked": list(PAYLOAD), "payload_field_count": len(PAYLOAD), "enqueued": len(enqueued), "delivered": len(delivered),
              "removals_delivered": sum(row["removal"] for row in evidence), "minimum_held_ms": min((row["held_ms"] for row in evidence), default=None),
              "maximum_held_ms": max((row["held_ms"] for row in evidence), default=None), "unmatched_serials": unmatched,
              "fifo_scope": "per unit, not global across independent team queues", "selected": list(selected.values()), "serials": evidence,
              "timestamp_print_rounding_tolerance_ms": str(TIMESTAMP_ROUNDING_MS), "failures": failures, "unverified_requirements": missing,
              "limits": ["All 16 logged payload fields must match exactly; this is not a binary-memory dump of an FCWUnitNetItem.",
                         "The 450 ms threshold is not relaxed. A separate 0.0011 ms consistency tolerance accounts only for six-decimal timestamp and three-decimal millisecond logging.",
                         "StoneAxe identity is corroborated by selection cohort and the existing StoneAxe-only authority timing logger; flags must exclude Champion.",
                         "This audit does not replace or modify the independent attack-timing validator."]}
    report["local_presentation_delay_audit_passed"] = report["status"] == "passed"
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--capture-report", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("Preserve existing audit; choose a fresh report path")
    text = read_text(args.log)
    report = audit(text, args.run)
    capture = json.loads(read_text(args.capture_report))
    expected_arguments = ("-cwsingle=", "-cwstoneaxepilot", "-cwarttiming", "-cwartpresentationdelay=450", "-cwarttimingrun=" + args.run)
    command = capture.get("arguments", "")
    checks = {"capture_run_matches": capture.get("run") == args.run,
              "normal_process_exit": capture.get("exit_code") == 0 and capture.get("timed_out") is False and not capture.get("failure"),
              "standalone_capture": capture.get("mode") == "single_standalone" and "InitGame mode=single" in text,
              "explicit_delay_flags": all(flag in command for flag in expected_arguments) and "-cwhost" not in command and "-cwjoin" not in command,
              "capture_delay_enabled": capture.get("presentation_delay_test") is True and capture.get("presentation_delay_ms") == 450,
              "same_process": report["process_ids"] == [capture.get("pid")],
              "log_hash_matches_capture": digest(args.log) == capture.get("log", {}).get("sha256"),
              "no_network_approval": capture.get("network_timing_approved") is False}
    report["capture_checks"] = checks
    for name, passed in checks.items():
        if not passed:
            report["failures"].append({"code": "capture_evidence_mismatch", "check": name})
    if report["failures"]:
        report["status"] = "failed"
        report["local_presentation_delay_audit_passed"] = False
    report.update({"version": "stoneaxe_independent_delay_serial_audit_v1", "created_at": datetime.now(timezone.utc).isoformat(),
                   "sources": [{"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest(path)} for path in (args.log, args.capture_report)]})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(args.report.resolve()), "delivered": report["delivered"], "minimum_held_ms": report["minimum_held_ms"], "failures": len(report["failures"])}, ensure_ascii=False))
    raise SystemExit(1 if report["failures"] else (0 if report["status"] == "passed" else 2))


if __name__ == "__main__":
    main()
