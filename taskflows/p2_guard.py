# -*- coding: utf-8 -*-
"""Explicit-chat-authorized P2 development guards; not human acceptance or an OS sandbox."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'docs/P2启动基线.json'
PLAN = ROOT / 'docs/P2实施计划.json'
SESSION = 'p2-001'
REQUIRED = ['CTL-01','CTL-02','CTL-03','CTL-04','CTL-05','CTL-06','CTL-07','CTL-08','CTL-09',
            'SHD-01','SHD-02','SHD-03','SHD-04','SHD-08','SHD-09','SHD-10','SHD-11','SHD-12','SHD-13','GEO-01','WINDOW-01','GEO-07','PIC-05']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    data = Path(p).read_bytes()
    if b'\r' in data:
        raise ValueError('New JSON must preserve UTF-8/LF bytes')
    return json.loads(data.decode('utf-8'))


def old_guard():
    spec = importlib.util.spec_from_file_location('stage_guard', ROOT / 'taskflows/guard.py')
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def preserved():
    b = load(BASELINE)
    for name, checksum in b['preserved_file_hashes'].items():
        if sha(ROOT / name) != checksum:
            raise ValueError('Protected baseline changed: ' + name)
    for name, checksum in b['prior_files'].items():
        if sha(ROOT / b['prior_source_archive'] / name) != checksum:
            raise ValueError('Prior source archive changed: ' + name)
    if sha(ROOT / 'docs/执行授权-P2.json') != b['authorization_sha256']:
        raise ValueError('Explicit authorization record changed')
    a = load(ROOT / 'docs/执行授权-P2.json')
    if a['stage'] != 'P2' or a['session'] != SESSION or a['allow_isolated_implementation_and_tests'] is not True or a['allow_live_configuration_write'] is not False:
        raise ValueError('No permission for this isolated stage')
    return b


def preflight():
    b = preserved()
    g = old_guard()
    if g.folder(SESSION).exists() or PLAN.exists():
        raise ValueError('P2 session/plan already exists: do not replay a source writer')
    _, _, h = g.candidate('P1', b['prior_session'])
    r = load(ROOT / 'docs/验证/开发/p1-002/technical-status.json')
    if h != b['prior_candidate_sha256'] or r['candidate_sha256'] != h or r['status'] != 'PASS_OBJECTIVE':
        raise ValueError('Prior objective checkpoint mismatch')
    for name in ['technical','safety']:
        review = r['reviews'][name]
        if review['verdict'] != 'pass' or any(f['severity'] in ['blocker','major'] for f in review['findings']):
            raise ValueError('Prior blocking review unresolved')
    return {'status':'PASS','stage':'P2','session':SESSION,'prior_objective_candidate':h,
            'human_subjective_acceptance_claimed':False,'backup':g.verified_backup(),'live_configuration_write_allowed':False}


def plan_check():
    preserved()
    p = load(PLAN)
    if p.get('stage') != 'P2' or p.get('session') != SESSION or p.get('ready') != 'pass':
        raise ValueError('No ready P2 stage plan')
    required = p.get('required_tests')
    if not isinstance(required,list) or not all(isinstance(x,str) for x in required) or not set(REQUIRED).issubset(set(required)) or len(required) != len(set(required)):
        raise ValueError('Plan must declare all mandatory unique objective test IDs')
    paths = p.get('write_paths')
    allowed = ('scripts/','script-opts/','shaders/','licenses/','tests/','tools/','docs/P2','docs/插件/缩放选择器-P2','docs/验证/开发/p2-001/')
    if not isinstance(paths,list) or not paths or any(not isinstance(x,str) or not x.startswith(allowed) or ':' in x or '\\' in x or '..' in Path(x).parts for x in paths):
        raise ValueError('Stage write paths outside allowed scope')
    return {'status':'PASS','stage':'P2','plan_sha256':sha(PLAN),'authorization_source':'explicit_user_chat','live_configuration_write_allowed':False}


def check():
    preserved()
    g = old_guard()
    _, t, h = g.candidate('P2', SESSION)
    plan = load(PLAN)
    cases = {x['id']:x for x in t['cases']}
    for identifier in plan['required_tests']:
        if identifier not in cases or cases[identifier].get('status') != 'PASS':
            raise ValueError('Mandatory objective test did not pass: ' + identifier)
    sys.path.insert(0,str(ROOT / 'tools'))
    import p1_check_evidence as e
    bindings = t['evidence_manifest']
    bindings = bindings if isinstance(bindings,list) else [bindings]
    problems = e.run_checks(g.folder(SESSION),SESSION,'P2',[ROOT / x['path'] for x in bindings],
                            g.folder(SESSION)/'tests.json',g.folder(SESSION)/'candidate.json',True,ROOT)
    if problems:
        raise ValueError('Evidence gate: ' + json.dumps(problems,ensure_ascii=False))
    return {'status':'PASS','stage':'P2','session':SESSION,'candidate_sha256':h,'required_objective_tests':len(plan['required_tests'])}


def result():
    machine = check()
    payload = json.load(sys.stdin)
    for key in ['technical','safety']:
        if payload[key]['candidate_sha256'] != machine['candidate_sha256']:
            raise ValueError('Review is for another candidate')
    blocked = any(payload[k]['verdict'] != 'pass' or any(f['severity'] in ['blocker','major'] for f in payload[k]['findings']) for k in ['technical','safety'])
    g = old_guard()
    _, t, _ = g.candidate('P2',SESSION)
    r = {**machine,'status':'REWORK' if blocked else 'PASS_OBJECTIVE','reviews':payload,
         'pending_user_checks':t.get('pending_user_checks',[]),'human_subjective_acceptance_claimed':False,
         'live_configuration_written':False,'live_deployment_completed':False,'backup':g.verified_backup()}
    with (g.folder(SESSION)/'technical-status.json').open('x',encoding='utf-8',newline='\n') as f:
        json.dump(r,f,ensure_ascii=False,indent=2);f.write('\n')
    return {k:v for k,v in r.items() if k != 'reviews'} | {'findings':[dict(f,reviewer=k) for k in ['technical','safety'] for f in payload[k]['findings']]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['preflight','plan-check','check','result'])
    a = p.parse_args()
    try:
        r = {'preflight':preflight,'plan-check':plan_check,'check':check,'result':result}[a.action]()
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'status':'FAIL','error':str(e)},ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
