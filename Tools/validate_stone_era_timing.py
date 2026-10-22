"""Audit actual stone-era client animation evidence against received server times.

This does not claim real-network transport coverage: only StoneAxe currently
emits the separate, full server-side timing trace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "CIVWAR_STONE_ERA_TIMING "


def expected_windups(root=ROOT):
    rows = [row for name in ("Units", "Champions") for row in json.loads((root/f"Content/Data/{name}.json").read_text(encoding="utf-8-sig"))]
    return {row["VisualKey"]: float(row["AttackWindup"]) for row in rows if row["VisualKey"] in
            {"Unit_StoneSlinger", "Unit_BeastRider", "Champion_Stone"}}


def analyze(text, windups=None):
    windups = windups or expected_windups()
    failures, records, groups = [], [], {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if PREFIX not in line:
            continue
        try:
            fields = dict(re.findall(r"([A-Za-z_]+)=([^\s]+)", line.split(PREFIX,1)[1]))
            for key in ("start_server", "server_now", "phase", "end_server"):
                fields[key] = float(fields[key])
            for key in ("id", "pid", "seq", "outcome", "release_pending"):
                fields[key] = int(fields[key])
            fields["line"] = line_number
            if fields["asset"] not in windups:
                raise ValueError("Unknown asset")
            if fields.get("notify_damage") != "false":
                raise ValueError("Animation trace must never claim damage authority")
            key = tuple(fields[name] for name in ("asset","pid","id","seq","start_server"))
            groups.setdefault(key, []).append(fields)
            records.append(fields)
        except (ValueError, KeyError) as error:
            failures.append({"line":line_number,"reason":"Malformed timing trace: "+str(error)})
    coverage = {asset:{"attacks":0,"authoritative_release_observed":0,"contact_effects":0,"late_or_initial_suppressed":0,"cancellations":0} for asset in windups}
    for key, events in groups.items():
        asset = key[0]
        contact_time = windups[asset]
        coverage[asset]["attacks"] += 1
        contacts = [event for event in events if event["event"] == "contact"]
        coverage[asset]["contact_effects"] += len(contacts)
        coverage[asset]["authoritative_release_observed"] += any(event["event"]=="release_evidence" for event in events)
        coverage[asset]["cancellations"] += any(event["event"]=="cancel_observed" for event in events)
        suppression = any(event["event"]=="observe" and event.get("reason") in {"initial_snapshot","late","expired"} for event in events)
        coverage[asset]["late_or_initial_suppressed"] += suppression
        if len(contacts)>1:
            failures.append({"asset":asset,"id":key[2],"reason":"Repeated contact effect for one attack"})
        if suppression and contacts:
            failures.append({"asset":asset,"id":key[2],"reason":"Initial or late snapshot replayed an old contact effect"})
        for event in events:
            if event["event"]=="contact":
                valid = (event["outcome"]==2 and event["release_pending"]==1 and
                         event["end_server"]>=event["start_server"] and event["server_now"]>=event["end_server"] and
                         contact_time-.00001<=event["phase"]<=contact_time+.10001 and
                         event["server_now"]-event["end_server"]<=.10001)
                if not valid:
                    failures.append({"line":event["line"],"asset":asset,"reason":"Contact lacks timely authoritative release evidence"})
            if event["phase"]>=0 and abs(event["phase"]-max(0,event["server_now"]-event["start_server"]))>.002:
                failures.append({"line":event["line"],"asset":asset,"reason":"Animation age differs from server-time age"})
            if event["event"]=="contact_pose" and event["release_pending"]:
                failures.append({"line":event["line"],"asset":asset,"reason":"Pose contact improperly claimed a release effect"})
    return {"status":"client_received_metadata_consistent" if records and not failures else "failed" if failures else "no_new_asset_timing_observed",
            "failures":failures,"records":len(records),"coverage":coverage,"authoritative_windups":windups,
            "network_transport_verified":False,"server_damage_logic_modified":False,"production_approved":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    result=analyze(args.log.read_text(encoding="utf-8-sig",errors="replace"))
    content=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(content+"\n",encoding="utf-8")
    print(content)
    return int(bool(result["failures"]) or not result["records"])


if __name__=="__main__":
    raise SystemExit(main())
