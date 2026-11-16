"""Write editable JSON proposals; geometry always comes from registered skills."""
import argparse
from pathlib import Path
from scene_factory.damage_layout import acceptance_scene,normal_office,intersection_scene
from scene_factory.storage import write_json

REQUESTS={
    'normal':'家具付きの正常な3部屋オフィスを生成してください。',
    'A':'執務室の棚1台を転倒させ、椅子2脚を傾斜・移動してください。',
    'B':'棚板とキャビネット扉を脱落させ、椅子の脚1本を破断してください。',
    'C':'壁に欠損、会議室天井に部分崩落、柱に局所損傷を作ってください。',
    'D':'棚転倒、棚板脱落、壁欠損、天井崩落を組み合わせ、会議室入口を閉塞してください。',
    'E':'会議室の天井損傷を小さくし、執務室の倒れた棚を元に戻してください。',
    'F':'交差量の異なる3組で、軽微・中程度・重大な貫通の検証をしてください。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    output=parser.parse_args().output;output.mkdir(parents=True,exist_ok=True)
    for label,request in REQUESTS.items():
        spec=normal_office() if label=='normal' else intersection_scene() if label=='F' else acceptance_scene(label)
        path=output/(label+'.json')
        if path.exists():raise FileExistsError(path)
        write_json(path,dict(raw_request=request,scene_spec=spec,change_summary='Phase 3D '+label,
                            requested_quality_profile='interior' if label=='normal' else 'damaged_interior',
                            generation_budget=dict(max_nodes=700,max_seconds=3600,max_attempts=2)))


if __name__=='__main__':main()
