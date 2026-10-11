# -*- coding: utf-8 -*-
"""Create-only P3 candidate revision gate. Does not weaken original guards/approval."""
from pathlib import Path, PurePosixPath
import argparse
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SESSION = 'p3-001'
REV_REL = 'docs/验证/开发/p3-001/revision-r2'
BASELINE = ROOT / 'docs/P3/P3候选修订基线-r2.json'
REVISION_ENV = ['taskflows/p3_revision_guard.py', 'taskflows/test_p3_revision_guard.py',
                'taskflows/mpv-scale-p3-revision-r2.json',
                'docs/P3/P3候选修订基线-r2.json', 'docs/P3/P3独立集成限域修正brief-v5.json',
                REV_REL + '/revision-context.json']


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def under_revision(name):
    if not isinstance(name, str) or ':' in name or '\\' in name:
        return False
    relative = PurePosixPath(name)
    return (relative.as_posix() == name and '..' not in relative.parts
            and not relative.is_absolute() and name.startswith(REV_REL + '/'))


def revision_folder(g):
    # source_path verifies canonical POSIX paths, existence, all ancestors and
    # link/reparse rejection. Context is create-only in the already fresh dir.
    context = g.source_path(REV_REL + '/revision-context.json')
    return context.parent


def preserved():
    p = module('taskflows/p3_guard.py', 'p3_original_guard')
    p.permit_check()  # original stage/session authorization is NOT remapped
    g = p.old_guard()
    b = p.load(BASELINE)
    if (b.get('stage'), b.get('session'), b.get('revision')) != ('P3', SESSION, 'r2'):
        raise ValueError('Revision baseline identity mismatch')
    if b.get('candidate_dir') != REV_REL:
        raise ValueError('Revision namespace mismatch')
    for name, h in b['preserved_p3_files'].items():
        if p.sha(g.source_path(name)) != h:
            raise ValueError('Prior P3 artifact changed: ' + name)
    for name, h in b['prior_source_files'].items():
        archive = b['prior_source_archive'] + '/' + name
        if p.sha(g.source_path(archive)) != h:
            raise ValueError('Prior failed candidate archive changed: ' + name)
        # Only the explicitly bounded correction surface may change.
        if name not in b['allowed_source_writes'] and p.sha(g.source_path(name)) != h:
            raise ValueError('Source outside revision write scope changed: ' + name)
    pins = [('docs/P3实施计划.json', 'frozen_plan_sha256'),
            ('docs/执行授权-P3.json', 'original_authorization_sha256'),
            (b['revision_brief'], 'revision_brief_sha256')]
    for name, key in pins:
        if p.sha(g.source_path(name)) != b[key]:
            raise ValueError('Revision authority changed: ' + name)
    revision_folder(g)
    return p, g, b


def relocated_candidate(g):
    # Only candidate()/tests lookup is redirected. Original permit_check above
    # still inspects the root stage permit, plan and authorization unchanged.
    directory = revision_folder(g)
    original_folder = g.folder
    g.folder = lambda session: directory if session == SESSION else original_folder(session)
    return g.candidate('P3', SESSION)


def check():
    p, g, _ = preserved()
    c, t, h = relocated_candidate(g)
    directory = revision_folder(g)
    for name in p.ENV_FILES + REVISION_ENV:
        if c['files'].get(name) != p.sha(g.source_path(name)):
            raise ValueError('Candidate omits revision execution dependency: ' + name)
    plan = p.load(p.PLAN)
    cases = {x['id']: x for x in t['cases']}
    for identifier in plan['required_tests']:
        if cases.get(identifier, {}).get('status') != 'PASS':
            raise ValueError('Objective case not passed: ' + identifier)
    for name in plan['write_paths']:
        if (ROOT / name).is_file() and c['files'].get(name) != p.sha(g.source_path(name)):
            raise ValueError('Candidate omits implemented plan scope: ' + name)
    bindings = t.get('evidence_manifest')
    bindings = bindings if isinstance(bindings, list) else [bindings]
    manifests = []
    for binding in bindings:
        if not isinstance(binding, dict) or not under_revision(binding.get('path')):
            raise ValueError('Historical/nonrevision manifest cannot prove current PASS')
        path = g.source_path(binding['path'])
        if p.sha(path) != binding.get('sha256'):
            raise ValueError('Revision manifest binding changed')
        manifest = p.load(path)
        if any(not under_revision(n) for n in manifest.get('files', {})):
            raise ValueError('Acceptance manifest contains historical/nonrevision bytes')
        manifests.append(path)
    sys.path.insert(0, str(ROOT / 'tools'))
    import p1_check_evidence as e
    problems = e.run_checks(directory, SESSION, 'P3', manifests,
                            directory / 'tests.json', directory / 'candidate.json', True, ROOT)
    if problems:
        raise ValueError('Revision evidence chain: ' + json.dumps(problems, ensure_ascii=False))
    import p3_check_evidence as semantic
    raw = t.get('objective_evidence_dirs')
    if not isinstance(raw, list) or len(raw) < 2 or len(raw) != len(set(raw)):
        raise ValueError('Both new author and independent matrix evidence required')
    for name in raw:
        if not under_revision(name):
            raise ValueError('Raw matrix outside revision')
        raw_dir = ROOT / name
        pin_path = g.source_path(name + '/source-pins.json')
        pins = p.load(pin_path).get('pins')
        if not isinstance(pins, dict) or not pins:
            raise ValueError('Raw matrix lacks execution source pins')
        for source, checksum in pins.items():
            if c['files'].get(source) != checksum or p.sha(g.source_path(source)) != checksum:
                raise ValueError('Raw matrix was not run on current candidate: ' + source)
        problems = semantic.run_full_gate(raw_dir, SESSION,
                                          raw_dir / 'objective-results.json',
                                          raw_dir / 'evidence-manifest.json', True, ROOT)
        if problems:
            raise ValueError('Semantic matrix gate failed: ' + json.dumps(problems, ensure_ascii=False))
    return {'status': 'PASS', 'stage': 'P3', 'session': SESSION, 'revision': 'r2',
            'candidate_sha256': h, 'required_objective_tests': len(plan['required_tests']),
            'candidate_dir': REV_REL, 'live_configuration_written': False,
            'human_subjective_acceptance_claimed': False}


def result(payload):
    machine = check()
    p, g, _ = preserved()
    for key in ['technical', 'adversarial']:
        if payload[key].get('candidate_sha256') != machine['candidate_sha256']:
            raise ValueError('Review candidate mismatch')
    blocked = any(payload[k].get('verdict') != 'pass' or
                  any(f.get('severity') in ['major', 'blocker'] for f in payload[k].get('findings', []))
                  for k in ['technical', 'adversarial'])
    directory = revision_folder(g)
    tests = p.load(directory / 'tests.json')
    r = dict(machine, status='REWORK' if blocked else 'PASS_OBJECTIVE', reviews=payload,
             backup=g.verified_backup(), pending_user_checks=tests.get('pending_user_checks', []),
             live_deployment_completed=False)
    p.create(directory / 'technical-status.json', r)
    return {k: v for k, v in r.items() if k != 'reviews'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preserved', 'check', 'result'])
    args = parser.parse_args()
    try:
        if args.action == 'preserved':
            _, _, b = preserved()
            r = {'status': 'PASS', 'preserved_p3_files': len(b['preserved_p3_files']),
                 'candidate_dir': REV_REL, 'stage': 'P3', 'session': SESSION}
        elif args.action == 'check':
            r = check()
        else:
            r = result(json.load(sys.stdin))
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
