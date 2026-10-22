from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_ue as adapter
import base_stone_team_render as renderer
from base_stone_side_emblem_render import CAMERAS, SHOTS


RENDERER_SHA = "a80c42099235f243812ef3aef9d36219498e357d3ac636d0148eb01790251784"


def check_team_report(path):
    report = adapter.read(path)
    if report.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or report.get("dry_run"):
        raise ValueError("Actual successful fresh reopen required")
    result = report["result"]
    if not result.get("validated_in_fresh_process") or result["initial_process_id"] == result["validation_process_id"]:
        raise ValueError("A genuinely independent process is required")
    if not result.get("all38_existing_packages_unchanged") or len(result["files"]) != 5 or result["audit"].get("status") != "passed":
        raise ValueError("Exact five-package dual-mask graph/persistence audit required")
    if not all(result["audit"].get(key) for key in ("dual_mask_guard_nearest_verified", "local_protection_bilinear_verified", "exact_multiplicative_graph_verified")):
        raise ValueError("Independent sampler types and multiplicative guard not proven")
    current = adapter.source_inputs()
    for key in ("destination", "settings", "sources", "frozen_packages", "source_evidence", "mask_source", "protection_source"):
        if report[key] != current[key]:
            raise ValueError("Frozen sources changed: " + key)
    adapter.check_records(result["files"] + report["frozen_packages"] + report["source_evidence"])
    return report


class DualMaskReview(renderer.BaseReview):
    def __init__(self, unreal, args, context):
        super().__init__(unreal, args, context)
        self.report.update(dual_mask_adapter=adapter.file_record(__file__), frozen_packages=38,
                           expected_actual_images=12, expected_required_resident_textures=5)
        self.report["limitations"] = ["Controlled12original/disabled/blue/red wide/front/side captures, not actual gameplay.",
                                      "Only714main cloth, held6unchanged; independent local protection can only reduce strict nearest guard dye.",
                                      "Side emblem core AND antialias fringe must be visually reviewed; no automatic acceptance from CPU proof."]

    def request_dump(self, label):
        if label == "initial":
            if len(self.required_paths) != 4:
                raise ValueError("Baseline must first contain exactly3PBR plus strict guard")
            self.required_paths.add(self.context["result"]["protection"])
        if len(self.required_paths) != 5:
            raise ValueError("Every dump must prove all5actual2048textures")
        return super().request_dump(label)

    def finish(self, status):
        if "error" in self.report:
            self.report["error"] = self.report["error"].replace("reach4actual2048textures", "reach5actual2048textures").replace("prove4resident2048textures", "prove5resident2048textures")
        if status == "actual8images_captured_pending_visual_and_pixel_control_review":
            if len(self.report["images"]) != 12 or {item["label"] for item in self.report["images"]} != {item[0] for item in SHOTS}:
                self.report["error"], status = "Exact12matched images missing", "failed"
            else:
                status = "actual12images_captured_pending_visual_and_pixel_control_review"
        super().finish(status)


def configure_renderer():
    if adapter.sha(renderer.__file__) != RENDERER_SHA:
        raise ValueError("Frozen validated renderer changed")
    renderer.team, renderer.CAMERAS, renderer.SHOTS = adapter, CAMERAS, SHOTS
    renderer.check_team_report, renderer.BaseReview = check_team_report, DualMaskReview
    renderer.VERSION = "base_stone_dual_mask_actual12_5resident2048_v1"


def main():
    configure_renderer()
    renderer.main()


if __name__ == "__main__":
    main()
