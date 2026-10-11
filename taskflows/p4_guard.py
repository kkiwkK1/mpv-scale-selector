# -*- coding: utf-8 -*-
"""P4 explicit-chat planning permit. No live writes or subjective approval."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'docs/P4启动基线.json'
AUTH = ROOT / 'docs/执行授权-P4.json'
BRIEF = ROOT / 'docs/P4/P4执行约束与验收brief.md'
PLAN = ROOT / 'docs/P4实施计划.json'
ENV = ROOT / 'docs/P4/P4环境勘察.json'
SESSION = ROOT / 'docs/验证/开发/p4-001'
REQUIRED = ['PIC-%02d' % i for i in range(1, 5)] + ['PER-%02d' % i for i in range(1, 6)] + ['CAL-01','TIME-01','RIFE-01','EVI-01']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    data = Path(path).read_bytes()
    if b'\r' in data:
        raise ValueError('New JSON must be UTF-8/LF: ' + str(path))
    return json.loads(data.decode('utf8'))


def safe_name(name):
    if not isinstance(name, str) or not name or ':' in name or '\\' in name:
        raise ValueError('Noncanonical path')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != name or name == '.' or p.parts[0] in ('.pi','.git','.local','backups'):
        raise ValueError('Path escaped scope')
    path = ROOT / name
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            if part.is_symlink() or getattr(part.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Link/reparse path rejected')
    return path


def preserved():
    b = load(BASELINE)
    if (b.get('stage'), b.get('session')) != ('P4','p4-001'):
        raise ValueError('Baseline identity')
    for name, h in b['preserved_file_hashes'].items():
        if sha(safe_name(name)) != h:
            raise ValueError('Protected previous file changed: ' + name)
    if sha(AUTH) != b['authorization_sha256'] or sha(BRIEF) != b['brief_sha256']:
        raise ValueError('Authority changed')
    a = load(AUTH)
    if a.get('allow_isolated_implementation_and_tests') is not True or a.get('allow_live_configuration_write') is not False:
        raise ValueError('No isolated work authorization')
    for name, h in b['initial_external_runtime_pins'].items():
        if sha(Path(name)) != h:
            raise ValueError('Original relevant runtime changed: ' + name)
    prior = load(safe_name(b['prior_status_path']))
    if prior.get('status') != 'PASS_OBJECTIVE' or prior.get('candidate_sha256') != b['prior_candidate_sha256']:
        raise ValueError('Prior objective dependency mismatch')
    return b


def validate_plan(p, allowed):
    if p.get('stage') != 'P4' or p.get('session') != 'p4-001' or p.get('ready') != 'pass':
        raise ValueError('No ready P4 plan')
    req = p.get('required_tests')
    if not isinstance(req, list) or not all(isinstance(x,str) for x in req) or len(req)!=len(set(req)) or not set(REQUIRED).issubset(req):
        raise ValueError('Required test coverage malformed')
    paths = p.get('write_paths')
    if not isinstance(paths,list) or not paths or not all(isinstance(n,str) and n in allowed for n in paths) or len(paths)!=len(set(paths)):
        raise ValueError('Exact write_paths outside leader authorization')
    for name in paths:
        if name.endswith('/'):
            raise ValueError('Exact file paths required')
    for key in ['fairness','sampling','frame_pacing','rife','environment_safety','evidence','objective_user_split','resource_budget','execution_batches','limitations']:
        if not isinstance(p.get(key), dict) or not p[key]:
            raise ValueError('Missing structured method section: ' + key)
    if p.get('human_subjective_acceptance_claimed') is not False or p.get('live_configuration_write_allowed') is not False:
        raise ValueError('Invalid acceptance/live-write scope')
    return True


def plan_check():
    b = preserved()
    p = load(PLAN)
    validate_plan(p, set(b['allowed_write_paths']))
    for name in p['write_paths']:
        safe_name(name)
    env = load(ENV)
    if env.get('stage') != 'P4' or env.get('session') != 'p4-001':
        raise ValueError('Environment identity mismatch')
    if p.get('environment_sha256') != sha(ENV):
        raise ValueError('Plan not bound to observed environment')
    return {'status':'PASS','stage':'P4','session':'p4-001','plan_sha256':sha(PLAN),'environment_sha256':sha(ENV),'required_test_ids':REQUIRED,'live_configuration_write_allowed':False,'human_subjective_acceptance_claimed':False}


def create(path, obj):
    with Path(path).open('x',encoding='utf8',newline='\n') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)
        f.write('\n')


def permit(review):
    machine = plan_check()
    if review.get('verdict') != 'pass' or review.get('plan_sha256') != machine['plan_sha256']:
        raise ValueError('Plan adversarial review blocked/mismatched')
    if any(f.get('severity') in ['blocker','major'] for f in review.get('findings',[])):
        raise ValueError('Blocking plan finding remains')
    SESSION.mkdir(exist_ok=True)
    create(SESSION/'plan-adversarial-review.json',review)
    r = dict(machine, permission='isolated-P4-instrumentation-and-calibration-only',
             baseline_sha256=sha(BASELINE), authorization_sha256=sha(AUTH),
             guard_sha256=sha(Path(__file__)), guard_tests_sha256=sha(ROOT/'taskflows/test_p4_guard.py'),
             plan_review_sha256=sha(SESSION/'plan-adversarial-review.json'),
             production_measurement_requires_calibration_review=True)
    create(SESSION/'work-permit.json',r)
    return r


def permit_check():
    m = plan_check()
    r = load(SESSION/'work-permit.json')
    for k,p in [('baseline_sha256',BASELINE),('authorization_sha256',AUTH),('guard_sha256',Path(__file__)),('guard_tests_sha256',ROOT/'taskflows/test_p4_guard.py'),('plan_review_sha256',SESSION/'plan-adversarial-review.json')]:
        if r.get(k) != sha(p):
            raise ValueError('Permit input changed: ' + k)
    if r.get('plan_sha256') != m['plan_sha256'] or r.get('environment_sha256') != m['environment_sha256']:
        raise ValueError('Plan/environment changed after permit')
    return r


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preserved','plan-check','permit','permit-check'])
    a=parser.parse_args()
    try:
        if a.action=='permit':r=permit(json.load(sys.stdin))
        elif a.action=='permit-check':r=permit_check()
        elif a.action=='plan-check':r=plan_check()
        else:
            b=preserved();r={'status':'PASS','stage':'P4','session':'p4-001','preserved_files':len(b['preserved_file_hashes']),'prior_candidate_sha256':b['prior_candidate_sha256']}
        print(json.dumps(r,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':
    raise SystemExit(main())
