"""Write reviewable disaster SceneSpecs; rendering/acceptance remain explicit."""
from pathlib import Path
import argparse
from scene_factory.effect_layout import acceptance_scene
from scene_factory.storage import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    for label in 'ABCDEF':
        path=args.output/(label+'.json')
        if path.exists():raise ValueError('Refusing to overwrite '+str(path))
        write_json(path,dict(raw_request='Phase 3E acceptance fixture '+label,
            scene_spec=acceptance_scene(label),change_summary='Disaster effects '+label,
            requested_quality_profile='disaster_interior',generation_budget=dict(max_nodes=1000,max_seconds=3600,max_attempts=2)))

if __name__=='__main__':main()
