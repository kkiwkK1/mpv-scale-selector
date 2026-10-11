# -*- coding: utf-8 -*-
"""P3 chat-authorized isolation guards. Hash gates, not OS sandbox/user approval."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SESSION = 'p3-001'
STAGE = 'P3'
BASELINE = ROOT / 'docs/P3启动基线.json'
PLAN = ROOT / 'docs/P3实施计划.json'
AUTH = ROOT / 'docs/执行授权-P3.json'
REQUIRED = ['CTL-%02d' % i for i in range(1, 10)] + [
    'SHD-%02d' % i for i in range(1, 14)] + [
    'GEO-%02d' % i for i in range(1, 8)] + [
    'WINDOW-01', 'PIC-05', 'UNIT-P2-01', 'UNIT-P3-01',
    'PER-04-COMPUTE', 'EVI-01']
ENV_FILES = ['tools/mpv_config_backup.py', 'tools/check_preparation.py',
             'taskflows/guard.py', 'taskflows/p3_guard.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    raw = Path(path).read_bytes()
    if b'\r' in raw:
        raise ValueError('Stage JSON must be UTF-8/LF: ' + str(path))
    return json.loads(raw.decode('utf8'))


def create(path, obj):
    with Path(path).open('x', encoding='utf8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def old_guard():
    spec = importlib.util.spec_from_file_location('p3_stage_guard', ROOT / 'taskflows/guard.py')
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def safe_name(name):
    if not isinstance(name, str) or not name or ':' in name or '\\' in name:
        raise ValueError('Noncanonical scope path')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != name or p.parts[0] in ('.git', '.pi', '.local', 'backups'):
        raise ValueError('Scope path escaped project')
    return name


def preserved():
    b = load(BASELINE)
    for name, checksum in b['preserved_file_hashes'].items():
        if sha(ROOT / safe_name(name)) != checksum:
            raise ValueError('Protected file changed: ' + name)
    for name, checksum in b['prior_files'].items():
        if sha(ROOT / b['prior_source_archive'] / safe_name(name)) != checksum:
            raise ValueError('P2 source archive changed: ' + name)
    if sha(AUTH) != b['authorization_sha256']:
        raise ValueError('Authorization record changed')
    a = load(AUTH)
    if a.get('stage') != STAGE or a.get('session') != SESSION or a.get('allow_isolated_implementation_and_tests') is not True or a.get('allow_live_configuration_write') is not False:
        raise ValueError('No isolated P3 authorization')
    return b


def preflight():
    b = preserved()
    g = old_guard()
    if PLAN.exists() or g.folder(SESSION).exists():
        raise ValueError('P3 plan/session already exists: no blind replay of writer')
    _, _, h = g.candidate('P2', b['prior_session'])
    r = load(ROOT / 'docs/验证/开发/p2-001/technical-status.json')
    if h != b['prior_candidate_sha256'] or r.get('candidate_sha256') != h or r.get('status') != 'PASS_OBJECTIVE':
        raise ValueError('Prior P2 objective checkpoint mismatch')
    for key in ['technical', 'safety']:
        q = r['reviews'][key]
        if q.get('verdict') != 'pass' or any(f.get('severity') in ['blocker', 'major'] for f in q.get('findings', [])):
            raise ValueError('Prior blocking finding unresolved')
    return {'status': 'PASS', 'stage': STAGE, 'session': SESSION,
            'prior_objective_candidate_sha256': h, 'backup': g.verified_backup(),
            'live_configuration_write_allowed': False,
            'human_subjective_acceptance_claimed': False}


def plan_check():
    b = preserved()
    p = load(PLAN)
    if p.get('stage') != STAGE or p.get('session') != SESSION or p.get('ready') != 'pass':
        raise ValueError('No ready P3 plan')
    req = p.get('required_tests')
    if not isinstance(req, list) or not all(isinstance(x, str) for x in req) or len(req) != len(set(req)) or not set(REQUIRED).issubset(set(req)):
        raise ValueError('Plan must include mandatory unique P3 objective IDs')
    paths = p.get('write_paths')
    if not isinstance(paths, list) or not paths:
        raise ValueError('No concrete write scope')
    allowed = set(b['allowed_write_paths'])
    for name in paths:
        if safe_name(name) not in allowed:
            raise ValueError('Plan write path not in leader scope: ' + name)
    return {'status': 'PASS', 'stage': STAGE, 'plan_sha256': sha(PLAN),
            'required_objective_tests': len(req), 'authorization_source': 'explicit_user_chat'}


def permit(payload):
    machine = plan_check()
    if payload.get('verdict') != 'pass' or payload.get('plan_sha256') != machine['plan_sha256'] or any(f.get('severity') in ['blocker', 'major'] for f in payload.get('findings', [])):
        raise ValueError('Plan adversarial review blocked or reviewed another plan')
    directory = old_guard().folder(SESSION)
    directory.mkdir(exist_ok=False)
    create(directory / 'plan-adversarial-review.json', payload)
    result = {**machine, 'session': SESSION, 'permission': 'isolated-P3-work-only',
              'plan_review_sha256': sha(directory / 'plan-adversarial-review.json'),
              'baseline_sha256': sha(BASELINE), 'authorization_sha256': sha(AUTH),
              'human_subjective_acceptance_claimed': False, 'live_configuration_write_allowed': False}
    create(directory / 'work-permit.json', result)
    return result


def permit_check():
    machine = plan_check()
    r = load(old_guard().folder(SESSION) / 'work-permit.json')
    if r.get('plan_sha256') != machine['plan_sha256'] or r.get('baseline_sha256') != sha(BASELINE) or r.get('authorization_sha256') != sha(AUTH):
        raise ValueError('Frozen work permit changed inputs')
    qpath = old_guard().folder(SESSION) / 'plan-adversarial-review.json'
    if sha(qpath) != r.get('plan_review_sha256') or load(qpath).get('verdict') != 'pass':
        raise ValueError('Plan review changed')
    return r


def check():
    permit_check()
    g = old_guard()
    c, t, h = g.candidate(STAGE, SESSION)
    for name in ENV_FILES:
        if c['files'].get(name) != sha(ROOT / name):
            raise ValueError('Candidate omits executed environment dependency: ' + name)
    p = load(PLAN)
    cases = {x['id']: x for x in t['cases']}
    for identifier in p['required_tests']:
        if identifier not in cases or cases[identifier].get('status') != 'PASS':
            raise ValueError('Objective case not passed: ' + identifier)
    for name in p['write_paths']:
        path = ROOT / name
        if path.is_file() and name not in c['files']:
            raise ValueError('Candidate omits an implemented scope file: ' + name)
    sys.path.insert(0, str(ROOT / 'tools'))
    import p1_check_evidence as e
    bindings = t['evidence_manifest']
    bindings = bindings if isinstance(bindings, list) else [bindings]
    problems = e.run_checks(g.folder(SESSION), SESSION, STAGE,
                            [ROOT / x['path'] for x in bindings],
                            g.folder(SESSION) / 'tests.json',
                            g.folder(SESSION) / 'candidate.json', True, ROOT)
    if problems:
        raise ValueError('Evidence gate: ' + json.dumps(problems, ensure_ascii=False))
    return {'status': 'PASS', 'stage': STAGE, 'session': SESSION,
            'candidate_sha256': h, 'required_objective_tests': len(p['required_tests'])}


def result(payload):
    machine = check()
    for key in ['technical', 'adversarial']:
        q = payload[key]
        if q.get('candidate_sha256') != machine['candidate_sha256']:
            raise ValueError('Review candidate mismatch')
    blocked = any(payload[k].get('verdict') != 'pass' or any(f.get('severity') in ['blocker', 'major'] for f in payload[k].get('findings', [])) for k in ['technical', 'adversarial'])
    _, t, _ = old_guard().candidate(STAGE, SESSION)
    r = {**machine, 'status': 'REWORK' if blocked else 'PASS_OBJECTIVE', 'reviews': payload,
         'backup': old_guard().verified_backup(),
         'pending_user_checks': t.get('pending_user_checks', []),
         'human_subjective_acceptance_claimed': False,
         'live_configuration_written': False, 'live_deployment_completed': False}
    create(old_guard().folder(SESSION) / 'technical-status.json', r)
    return {k: v for k, v in r.items() if k != 'reviews'} | {'findings': [dict(f, reviewer=k) for k in ['technical', 'adversarial'] for f in payload[k].get('findings', [])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'plan-check', 'permit', 'permit-check', 'check', 'result'])
    a = parser.parse_args()
    try:
        if a.action in ['permit', 'result']:
            r = {'permit': permit, 'result': result}[a.action](json.load(sys.stdin))
        else:
            r = {'preflight': preflight, 'plan-check': plan_check,
                 'permit-check': permit_check, 'check': check}[a.action]()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'status': 'FAIL', 'error': str(e)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
