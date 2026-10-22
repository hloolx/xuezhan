"""Import one isolated Move sequence onto the existing frozen mammoth skeleton."""
from pathlib import Path
import hashlib
import json
import sys
import unreal as u

ROOT = Path(u.Paths.project_dir()).resolve()
sys.path.insert(0,str(ROOT/"Tools/Unreal"))
import import_beast_rider_preview as helper

OUT = ROOT/"RawAssets/Art/Tripo_v01/reviews/AstraPolish_20261021/mammoth/candidate_01"
manifest = json.loads((OUT/"manifest.json").read_text(encoding="utf-8-sig"))
if not manifest["numeric_gate"]:
    raise ValueError("DCC numeric gate failed")
clip_record = manifest["clips"][0]
if hashlib.sha256(Path(clip_record["path"]).read_bytes()).hexdigest() != clip_record["sha256"]:
    raise ValueError("Export changed")
base = "/Game/ArtPilot/StoneEraPreview/Mount_Mammoth/h2fe416188a42"
mesh = u.EditorAssetLibrary.load_asset(base+"/SK_Mount_Mammoth")
skeleton = u.EditorAssetLibrary.load_asset(base+"/SK_Mount_Mammoth_Skeleton")
roots = [ROOT/"Content/ArtPilot/StoneEraPreview/Mount_Mammoth",
         ROOT/"Content/ArtPilot/StoneEraPreview/Unit_BeastRider"]
protected = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in roots for p in root.rglob("*.uasset")}
(OUT/"original_packages_before.json").write_text(json.dumps(protected,indent=2),encoding="utf-8")
destination = "/Game/ArtPilot/VisualPolish/MammothGait/h"+clip_record["sha256"][:12]
options = helper.options(u,skeleton)
options.get_editor_property("anim_sequence_import_data").set_editor_property("custom_sample_rate",60)
clip = helper.task(u,clip_record["path"],destination,"A_Move_FourBeat",options,u.FbxFactory())
clip.set_editor_property("enable_root_motion",False)
clip.set_editor_property("rate_scale",1.)
duration = float(u.AnimationLibrary.get_sequence_length(clip))
evaluation = u.AnimPoseEvaluationOptions()
helper.set_properties(evaluation,{"evaluation_type":u.AnimDataEvalType.RAW,
                                 "should_retarget":False,"extract_root_motion":False,
                                 "optional_skeletal_mesh":mesh})
errors = []
for sample in manifest["physical_pose_reference"]["Move"]:
    pose = u.AnimPoseExtensions.get_anim_pose_at_time(clip,sample["time"],evaluation)
    for name,expected in sample["bones"].items():
        actual = u.AnimPoseExtensions.get_bone_pose(pose,name,u.AnimPoseSpaces.WORLD)
        t = actual.translation
        # FBX/UE changes handedness: Blender +Y is Unreal -Y.
        errors.append(sum((a-b)**2 for a,b in zip((t.x,-t.y,t.z),expected["head_cm"]))**.5)
u.EditorAssetLibrary.save_loaded_asset(clip,only_if_is_dirty=False)
after = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in roots for p in root.rglob("*.uasset")}
failures = []
if protected != after:
    failures.append("Original mount/rider packages changed")
if abs(duration-.5)>.001:
    failures.append("Duration mismatch")
if max(errors)>.05:
    failures.append("Physical bone bake mismatch")
if clip.get_editor_property("skeleton") != skeleton:
    failures.append("Wrong skeleton")
receipt = {"asset":clip.get_path_name(),"skeleton":skeleton.get_path_name(),"mesh":mesh.get_path_name(),
           "duration":duration,"max_physical_bone_error_cm":max(errors),
           "protected_original_package_count":len(protected),"original_packages_unchanged":protected==after,
           "source":clip_record,"failures":failures,"default_mapping_modified":False,
           "cook_directory":destination}
(OUT/"unreal_import.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
u.log("MAMMOTH_GAIT_IMPORT "+json.dumps(receipt))
if failures:
    raise RuntimeError(str(failures))
