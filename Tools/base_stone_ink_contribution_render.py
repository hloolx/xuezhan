from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_ink_contribution_ue as adapter
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
    if not result.get("all43_existing_packages_unchanged") or len(result["files"]) != 5 or result["audit"].get("status") != "passed":
        raise ValueError("Exact five-package contribution graph/persistence audit required")
    if not all(result["audit"].get(key) for key in ("strict_nearest_guard_verified", "linear_rgb_ink_bilinear_verified", "exact_source_contribution_graph_verified", "native_basecolor_channelwise_ink_bound_verified")):
        raise ValueError("Independent linearRGB contribution formula and samplers not proven")
    current = adapter.source_inputs()
    for key in ("destination", "settings", "sources", "frozen_packages", "source_evidence", "mask_source", "contribution_source"):
        if report[key] != current[key]:
            raise ValueError("Frozen sources changed: " + key)
    adapter.check_records(result["files"] + report["frozen_packages"] + report["source_evidence"])
    return report


def validate_contribution_format(records, path):
    value = records[path]["format"].strip()
    if value not in ("PF_B8G8R8A8", "PF_R8G8B8A8"):
        raise ValueError("Contribution resource is not uncompressed linearRGBA8: " + value)
    return value


class InkContributionReview(renderer.BaseReview):
    def __init__(self, unreal, args, context):
        super().__init__(unreal, args, context)
        self.report.update(contribution_adapter=adapter.file_record(__file__), frozen_packages=43,
                           expected_actual_images=12, expected_required_resident_textures=5)
        self.report["limitations"] = ["Controlled12original/disabled/blue/red wide/front/side captures, not actual gameplay.",
                                      "Only714main cloth, held6unchanged; candidate02 sourceink preserves mixed paint contribution, not complete source mixedRGB.",
                                      "Offline8bit error is measured, nativeBC1 difference and final edge appearance still require actual visual review."]

    def request_dump(self, label):
        if label == "initial":
            if len(self.required_paths) != 4:
                raise ValueError("Baseline must first contain exactly3PBR plus strict guard")
            self.required_paths.add(self.context["result"]["contribution"])
        if len(self.required_paths) != 5:
            raise ValueError("Every dump must prove all5actual2048textures")
        return super().request_dump(label)

    def check_component(self):
        result = super().check_component()
        result["contribution_native_format"] = validate_contribution_format(self.current_residency, self.context["result"]["contribution"])
        return result

    def finish(self, status):
        if "error" in self.report:
            self.report["error"] = self.report["error"].replace("reach4actual2048textures", "reach5actual2048textures").replace("prove4resident2048textures", "prove5resident2048textures")
        if status == "actual8images_captured_pending_visual_and_pixel_control_review":
            if len(self.report["images"]) != 12 or {item["label"] for item in self.report["images"]} != {item[0] for item in SHOTS}:
                self.report["error"], status = "Exact12matched images missing", "failed"
            else:
                status = "actual12images_captured_pending_visual_and_pixel_control_review"
        try:
            adapter.check_records(self.context["frozen_packages"] + self.context["source_evidence"] + self.context["result"]["files"])
            self.report["all48_packages_and_sources_unchanged"] = True
        except Exception as error:
            self.report["preservation_error"], status = str(error), "failed"
        super().finish(status)


def configure_renderer():
    if adapter.sha(renderer.__file__) != RENDERER_SHA:
        raise ValueError("Frozen validated renderer changed")
    renderer.team, renderer.CAMERAS, renderer.SHOTS = adapter, CAMERAS, SHOTS
    renderer.check_team_report, renderer.BaseReview = check_team_report, InkContributionReview
    renderer.VERSION = "base_stone_source_contribution_actual12_5resident2048_v1"


def main():
    configure_renderer()
    renderer.main()


if __name__ == "__main__":
    main()
