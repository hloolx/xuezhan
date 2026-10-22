"""Export an existing, visually inspected preview without rebuilding its motion."""
import argparse
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_stone_slinger_gameplay as build

parser=argparse.ArgumentParser()
parser.add_argument("--candidate",type=Path,required=True)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
candidate=args.candidate.resolve()
report=build.read(candidate/"preview_report.json")
source=Path(report["blend"]["path"])
if build.exporter.file_record(source)!=report["blend"]:
    raise ValueError("Preview source changed")
args.output.resolve().mkdir(parents=True,exist_ok=False)
bpy.ops.wm.open_mainfile(filepath=str(source))
armature,=[obj for obj in bpy.context.scene.objects if obj.type=="ARMATURE"]
objects=[obj for obj in bpy.context.scene.objects if obj.type=="MESH"]
body,=[obj for obj in objects if not obj.name.startswith(("retained_loop_cord","released_cord","leather_pouch","loaded_stone"))]
# Stable object ordering is part of physical mesh sample correspondence.
objects=[body]+[obj for obj in objects if obj!=body]
build.export(args.output.resolve(),armature,objects,body,report)
