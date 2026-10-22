"""Leased serial DCC: measured parts, real rig and five clips per vehicle."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_era_parts as parts
import prepare_mechanical_units as planning
import bake_era_vehicle_actions as bake


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--candidate", default="candidate_01")
    parser.add_argument("--render", action="store_true")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else None
    args = parser.parse_args(argv)
    plan = parts.static.read(args.plan)
    results = []
    for entry in plan["entries"]:
        try:
            actual, folder = parts.prepare(plan, entry, render=False)
            spec = parts.static.read(planning.RUN/entry["asset_id"]/"motion_measurements.json")
            output = parts.static.absolute(plan["output_root"])/entry["asset_id"]/args.candidate
            spec.update(scene=actual["blend"]["path"], scene_sha256=actual["blend"]["sha256"],
                        materials=actual["materials"], output=str(output))
            path = planning.RUN/entry["asset_id"]/(args.candidate+"_spec.json")
            parts.static.write(path, spec)
            result = bake.run(path, args.render)
            result = {"asset_id": entry["asset_id"], "status": result["status"],
                      "manifest": str(output/"vehicle_manifest.json"),
                      "bone_count": result["bone_count"]}
        except Exception as error:
            result = {"asset_id": entry["asset_id"], "status": "failed",
                      "error": str(error), "traceback": traceback.format_exc()}
        results.append(result)
        parts.static.write(args.plan.with_name(args.candidate+"_dcc_report.json"),
                           {"process_id": os.getpid(), "results": results})
    if any(row["status"] == "failed" for row in results):
        raise RuntimeError("Mechanical DCC failed; see the per-asset report")


if __name__ == "__main__":
    main()
