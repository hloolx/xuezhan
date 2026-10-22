"""Run measured static/mechanical plans serially in the leased Blender process."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
import prepare_era_asset as static
import prepare_era_parts as parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else None)
    results = []
    for group in static.read(args.plan)["groups"]:
        plan = static.read(static.absolute(group["plan"]))
        for entry in plan["entries"]:
            try:
                if group["pipeline"] == "static":
                    result = static.prepare_geometry(entry, plan["output_root"], args.render)
                    output = Path(result["exports"]["fbx"]["path"]).parent
                    manifest = output/"manifest.json"
                elif group["pipeline"] == "parts":
                    result, output = parts.prepare(plan, entry, args.render)
                    manifest = output/"mechanism_manifest.json"
                else:
                    raise ValueError("Unknown explicit pipeline")
                results.append({"asset_id": entry["asset_id"], "status": result["status"],
                                "manifest": str(manifest), "output": str(output)})
            except Exception as error:
                results.append({"asset_id": entry["asset_id"], "status": "failed",
                                "error": str(error), "traceback": traceback.format_exc()})
            static.write(args.plan.with_name("dcc_batch_report.json"),
                         {"process_id": os.getpid(), "results": results})
    print(json.dumps(results))
    if any(row["status"] == "failed" for row in results):
        raise RuntimeError("DCC batch failed; see actual report")


if __name__ == "__main__":
    main()
