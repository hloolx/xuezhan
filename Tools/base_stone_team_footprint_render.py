from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_footprint_ue as adapter
import base_stone_team_render as renderer


class FootprintReview(renderer.BaseReview):
    def __init__(self, unreal, args, context):
        super().__init__(unreal, args, context)
        self.report["footprint_adapter"] = adapter.file_record(__file__)
        self.report["additional_previous_safe1_packages_frozen"] = 4
        self.report["mask_candidate"] = context["mask_source"]
        self.report["limitations"][-1] = "Exact nearest texel support fixes internal raster gaps only; unchanged white/pale pigment and true protected boundaries remain protected. Actual closeup must confirm no triangular wireframe."


def main():
    renderer.team = adapter
    renderer.VERSION = "base_stone_actual_ue_nearest_footprint_controls_v1"
    renderer.BaseReview = FootprintReview
    renderer.main()


if __name__ == "__main__":
    main()
