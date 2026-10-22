from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_side_emblem_ue as adapter
import base_stone_team_render as renderer


RENDERER_SHA = "a80c42099235f243812ef3aef9d36219498e357d3ac636d0148eb01790251784"
CAMERAS = {**renderer.CAMERAS, "side_flag": {"target": [-147, 229, 43], "offset": [0, 260, 94.6322609092], "fov": 24}}
SHOTS = [(mode + "_" + crop, mode, crop) for crop in ("wide", "flag", "side_flag") for mode in ("original", "disabled", "blue", "red")]


class SideEmblemReview(renderer.BaseReview):
    def __init__(self, unreal, args, context):
        super().__init__(unreal, args, context)
        self.report.update(side_emblem_adapter=adapter.file_record(__file__), mask_candidate=context["mask_source"],
                           frozen_packages=34, previous_derived_packages_frozen=8, expected_actual_images=12)
        self.report["limitations"] = [
            "Controlled editor images, not the actual1600x900 gameplay rerun; current side camera uses the same+Y side and20degree downward view as the failed game-visible cluster0 flag, reframed as a closeup.",
            "Only714 selected cloth faces and cluster0 emblem protection; held6faces and other emblems remain outside approval.",
            "Original/disabled/blue/red at wide, previous front-flag regression and actual-game-visible side-flag closeup are all required.",
            "Do not infer success from mask numerics; inspect side emblem remains original pale-blue-gray while background changes and front triangular blue gaps stay absent.",
        ]

    def finish(self, status):
        if status == "actual8images_captured_pending_visual_and_pixel_control_review":
            if len(self.report["images"]) != 12 or {item["label"] for item in self.report["images"]} != {item[0] for item in SHOTS}:
                self.report["error"] = "Exact twelve matched images were not captured"
                status = "failed"
            else:
                status = "actual12images_captured_pending_visual_and_pixel_control_review"
        super().finish(status)


def configure_renderer():
    if adapter.sha(renderer.__file__) != RENDERER_SHA:
        raise ValueError("Frozen validated renderer changed")
    renderer.team = adapter
    renderer.VERSION = "base_stone_actual_ue_side_emblem12_controls_v1"
    renderer.CAMERAS, renderer.SHOTS = CAMERAS, SHOTS
    renderer.BaseReview = SideEmblemReview


def main():
    configure_renderer()
    renderer.main()


if __name__ == "__main__":
    main()
