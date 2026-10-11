# -*- coding: utf-8 -*-
"""B2-r3 scoped repair and one real 24fps identity run. Never production PASS."""
import json
import subprocess
import sys
import p4_guard as g
import p3_guard
R=g.ROOT/'docs/验证/开发/p4-001/build-b2-r3'
E=g.ROOT/'docs/验证/开发/p4-001/identity-run-002'
BASE=g.ROOT/'docs/P4/P4-B2-r3修订基线.json'
OLD=g.ROOT/'docs/验证/开发/p4-001/build-b2-r2/candidate-r2.json'
FILES={'tools/p4_collect.py','tests/test_p4_collect.py'}


def pre():
    g.permit_check()
    b=g.load(BASE)
    if g.sha(OLD)!=b['old_candidate_sha256']:raise ValueError('Old candidate changed')
    for p,h in b['archive_files'].items():
        if g.sha(g.safe_name(b['archive_path']+'/'+p))!=h:raise ValueError('Archive drift: '+p)
        if p not in FILES and g.sha(g.safe_name(p))!=h:raise ValueError('Out-of-scope source drift: '+p)
    for p,h in b['protected_current_files'].items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('Protected old P4 evidence changed: '+p)
    return {'status':'PASS_PRESERVED','stage':'P4','session':'p4-001','revision':'B2-r3','production_unlocked':False}


def build():
    pre();h=g.load(R/'author/handoff-corrected.json')
    if (h.get('stage'),h.get('session'),h.get('unit'),h.get('status'))!=('P4','p4-001','collector','BUILT'):raise ValueError('Author incomplete')
    if h.get('plan_sha256')!=g.sha(g.PLAN) or set(h.get('source_hashes',{}))!=FILES:raise ValueError('Wrong plan/source coverage')
    if h.get('b1_candidate_sha256')!='929079b09d1c1ac10f262ebc05e7d311ca5943d58eeb5731890199d803d17f3b':raise ValueError('Wrong B1 dependency')
    if h.get('gpu_started') is not False or h.get('live_configuration_written') is not False:raise ValueError('Writer exceeded scope')
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source pin mismatch: '+p)
    if not isinstance(h.get('tests'),list) or not h['tests']:raise ValueError('No author tests')
    prefix=(R/'author').relative_to(g.ROOT).as_posix()+'/'
    for t in h['tests']:
        if type(t.get('returncode')) is not int or t['returncode']!=0:raise ValueError('Author test failed')
        p=t.get('console_path','')
        if not p.startswith(prefix) or g.sha(g.safe_name(p))!=t.get('console_sha256'):raise ValueError('Test log missing/unbound')
    smoke=h.get('config_smoke',{});p=smoke.get('report_path','')
    if not p.startswith(prefix) or g.sha(g.safe_name(p))!=smoke.get('sha256') or smoke.get('gpu_started') is not False:
        raise ValueError('No bound non-GPU real config smoke')
    log=R/'independent-tests.console.txt'
    with log.open('xb') as f:
        for suite in [['-s','tests','-v'],['-s','taskflows','-p','test_*.py','-v']]:
            cmd=[sys.executable,'-B','-X','utf8','-m','unittest','discover']+suite
            f.write(('COMMAND '+json.dumps(cmd)+'\n').encode('utf8'));f.flush()
            if subprocess.run(cmd,cwd=str(g.ROOT),stdout=f,stderr=subprocess.STDOUT).returncode:raise ValueError('Independent tests failed')
    pre()
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source changed during tests')
    pins=dict(g.load(OLD)['files']);pins.update(h['source_hashes'])
    for p in ['docs/P4/P4-B2-r3修订基线.json','docs/P4/P4-B2首载修正brief-v3.md','taskflows/p4_b2_r3_gate.py','taskflows/mpv-scale-p4-b2-r3-real.json','taskflows/mpv-scale-p4-b2-r3-closeout-v4.json','taskflows/mpv-scale-p4-b2-r3-tail-v5.json','docs/P4/P4-B2-r3中断收尾brief.md',OLD.relative_to(g.ROOT).as_posix(),'docs/验证/开发/p4-001/identity-run-001/execution-report.json','docs/验证/开发/p4-001/identity-run-001/evidence-manifest.json']:
        pins[p]=g.sha(g.safe_name(p))
    for p in R.rglob('*'):
        if p.is_file():pins[p.relative_to(g.ROOT).as_posix()]=g.sha(p)
    for p,v in pins.items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Freeze dependency drift: '+p)
    g.create(R/'candidate.json',{'stage':'P4','session':'p4-001','scope':'B2-r3-config-identity-fix','files':pins,'production_unlocked':False,'measurements':'NOT_RUN'})
    return {'status':'PASS_BUILD_ONLY','candidate_path':(R/'candidate.json').relative_to(g.ROOT).as_posix(),'candidate_sha256':g.sha(R/'candidate.json'),'bound_files':len(pins)}


def candidate_check():
    pre()
    for p,h in g.load(R/'candidate.json')['files'].items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('Candidate drift: '+p)
    return g.sha(R/'candidate.json')


def review():
    h=candidate_check();r=json.load(sys.stdin)
    if r.get('candidate_sha256')!=h or r.get('verdict') not in ('pass','block') or not isinstance(r.get('findings'),list):raise ValueError('Review contract mismatch')
    if any(f.get('severity') not in ('blocker','major','minor') for f in r['findings']):raise ValueError('Invalid severity')
    g.create(R/'safety-method-review.json',r)
    if r['verdict']!='pass' or any(f['severity'] in ('blocker','major') for f in r['findings']):raise ValueError('Review blocked')
    return {'status':'PASS_FOR_ONE_ISOLATED_IDENTITY_RUN','candidate_sha256':h,'production_unlocked':False}


def post():
    h=candidate_check();review=g.load(R/'safety-method-review.json')
    if review.get('verdict')!='pass' or review.get('candidate_sha256')!=h or any(f['severity'] in ('blocker','major') for f in review['findings']):raise ValueError('No execution review')
    r=g.load(E/'execution-report.json')
    if (r.get('stage'),r.get('session'),r.get('candidate_sha256'))!=('P4','p4-001',h):raise ValueError('Execution identity mismatch')
    if r.get('status') not in ('MEASURED_IDENTITY_ONLY','NOT_ESTABLISHED','BLOCKED_ENV','REWORK'):raise ValueError('Invalid execution status')
    for k in ['performance_measured','production_unlocked','live_configuration_written']:
        if r.get(k) is not False:raise ValueError('Invalid claim: '+k)
    if r.get('source_unchanged') is not True:raise ValueError('Execution source changed')
    files=g.load(E/'evidence-manifest.json').get('files',{})
    actual={p.relative_to(g.ROOT).as_posix() for p in E.rglob('*') if p.is_file() and p!=E/'evidence-manifest.json'}
    if not files or set(files)!=actual:raise ValueError('Evidence coverage mismatch')
    prefix=E.relative_to(g.ROOT).as_posix()+'/'
    for p,v in files.items():
        if not p.startswith(prefix) or g.sha(g.safe_name(p))!=v:raise ValueError('Evidence drift '+p)
    backup=p3_guard.old_guard().verified_backup()
    return {'status':'EXECUTION_REPORT_VERIFIED','execution_status':r['status'],'candidate_sha256':h,'evidence_files':len(files),'evidence_manifest_sha256':g.sha(E/'evidence-manifest.json'),'gpu_started':r.get('gpu_started'),'performance_measured':False,'production_unlocked':False,'backup':backup}


if __name__=='__main__':
    try:
        action=sys.argv[1]
        funcs={'pre':pre,'build':build,'review':review,'post':post}
        print(json.dumps(funcs[action](),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)},ensure_ascii=False));raise SystemExit(1)
