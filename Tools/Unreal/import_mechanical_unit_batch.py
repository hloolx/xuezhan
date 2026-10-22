"""Root-leased serial import of actual prepared mechanical units."""
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
import import_era_vehicle as vehicle
import import_era_assets as common


def main():
    import unreal
    plan = common.resolve(os.environ["CIVWAR_VEHICLE_IMPORT_PLAN"])
    results = []
    for entry in common.read(plan)["entries"]:
        try:
            result = vehicle.run(unreal, entry["manifest"], entry["report"])
            handoff = {"runtime_entry": result["runtime_entry"],
                       "cook_directories": [result["destination"]],
                       "source_report": str(common.resolve(entry["report"])),
                       "remaining": ["actual_gameplay"], "production_approved": False}
            common.write(Path(entry["report"]).with_name("runtime_handoff.json"), handoff)
            result = {"asset_id": result["asset_id"], "status": result["status"],
                      "report": entry["report"], "packages": len(result["packages"]),
                      "destination": result["destination"]}
        except Exception as error:
            result = {"status": "failed", "manifest": entry["manifest"], "error": str(error),
                      "traceback": traceback.format_exc()}
        results.append(result)
        common.write(plan.with_name("batch_report.json"), {"process_id": os.getpid(), "results": results})
    if any(row["status"] == "failed" for row in results):
        raise RuntimeError("Mechanical import failed; see per-item batch report")


if __name__ == "__main__":
    main()
