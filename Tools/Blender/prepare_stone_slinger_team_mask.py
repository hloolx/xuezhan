"""Lightweight UV/color mask for the slinger's existing blue scarf and sash."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parent))
import review_stone_slinger_texture as source


def record(path):
    return {"path":str(path.resolve()),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--color",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    geometry=source.BRANCH/"textured_v01/normal_repair_candidate_01/Unit_StoneSlinger_PBR_LocalNormalRepair.glb"
    _,_,arrays=source.read_glb(geometry)
    color=Image.open(args.color).convert("RGB")
    values=np.asarray(color,dtype=np.float32)
    height,width=values.shape[:2]
    y=arrays["POSITION"][:,1]
    face_y=y[arrays["indices"]]
    # Only waist/sash and scarf vertical zones. Other body areas are excluded
    # even if their baked texture contains an incidental cool highlight.
    selected=((face_y.max(1)>=.50)&(face_y.min(1)<=.90))|((face_y.max(1)>=.98)&(face_y.min(1)<=1.28))
    included=Image.new("L",color.size)
    excluded=Image.new("L",color.size)
    draws=[ImageDraw.Draw(excluded),ImageDraw.Draw(included)]
    uv=arrays["TEXCOORD_0"]
    for tri,pick in zip(arrays["indices"],selected):
        points=[(float(uv[i,0])*width,float(uv[i,1])*height) for i in tri]
        draws[int(pick)].polygon(points,fill=255)
    inside=np.asarray(included)>0
    outside=np.asarray(excluded)>0
    red,green,blue=values[:,:,0],values[:,:,1],values[:,:,2]
    blue_strength=np.clip((blue-red-4)/12,0,1)*np.clip((green-red-2)/8,0,1)*np.clip((blue-green+3)/6,0,1)
    mask=blue_strength*inside*(~outside)
    path=args.output/"T_StoneSlinger_ClothMask.png"
    Image.fromarray(np.uint8(np.rint(mask*255))).save(path)
    overlay=values.copy()
    overlay=overlay*(1-mask[:,:,None])+np.array([255,0,180])*mask[:,:,None]
    Image.fromarray(np.uint8(np.clip(overlay,0,255))).save(args.output/"mask_overlay.png")
    report={"status":"semantic_height_and_blue_cloth_mask_pending_model_review","source_geometry":record(geometry),
            "base_color":record(args.color),"mask":record(path),"texture_width":width,"texture_height":height,
            "selected_triangles":int(selected.sum()),"nonselected_uv_overlap_pixels_removed":int((inside&outside).sum()),
            "painted_pixels":int(np.count_nonzero(mask)),"coverage":float(np.count_nonzero(mask)/(width*height)),
            "skin_fur_boot_and_weapon_intent":"unchanged; only original blue pixels inside scarf/sash height bands",
            "runtime_approved":False,"production_approved":False}
    (args.output/"mask_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
