import ast
import sys
from pathlib import Path

import pytest

from scene_factory.cli import main
from scene_factory.project import state
from scene_factory.spec import read_json

ROOT=Path(__file__).resolve().parents[1]


def test_v2_init_and_compile_without_blender(tmp_path,monkeypatch,capsys):
    def forbidden(*args,**kwargs): pytest.fail('compile must not execute subprocess/Blender')
    monkeypatch.setattr('subprocess.run',forbidden)
    project=tmp_path/'example'
    assert main(['init',str(project),'--schema-version','2'])==0
    assert main(['compile',str(project)])==0
    assert 'bpy' not in sys.modules
    assert state(project)['last_successful_build'] is None
    directory=project/state(project)['latest']['directory']
    for name in ('plan.json','resolved-scene.json','skills.lock.json','scene-v2.json'):
        assert (directory/name).is_file()


def test_cli_skills_and_migration(tmp_path,capsys):
    assert main(['skills','list','--query','cylinder'])==0
    assert 'cylinder' in capsys.readouterr().out
    assert main(['skills','show','cylinder'])==0
    assert main(['skills','show','missing'])==1
    assert main(['skills','validate','cylinder','--contract-only'])==0
    assert main(['skills','validate','cylinder','--contract-only','--activate'])==1
    project=tmp_path/'v1'; assert main(['init',str(project)])==0
    source=(project/'scene.json').read_bytes(); destination=tmp_path/'v2.json'
    assert main(['migrate',str(project/'scene.json'),str(destination)])==0
    assert read_json(destination)['schema_version']==2
    assert (project/'scene.json').read_bytes()==source
    assert main(['migrate',str(project/'scene.json'),str(destination)])==1


def test_failed_compile_status(tmp_path):
    project=tmp_path/'example'; assert main(['init',str(project),'--schema-version','2'])==0
    (project/'scene.json').write_text('{"schema_version":999}')
    assert main(['compile',str(project)])==1
    assert state(project)['latest']['status']=='failed'
    assert state(project)['last_successful_build'] is None


def test_all_worker_and_shared_modules_are_python311_compatible():
    for path in (ROOT/'src/scene_factory').rglob('*.py'):
        ast.parse(path.read_text(),feature_version=(3,11))
