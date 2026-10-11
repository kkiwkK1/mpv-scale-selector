# -*- coding: utf-8 -*-
"""Machine gates for B1 r2 scoped repairs; no live/GPU execution."""
import json
import subprocess
import sys
from pathlib import Path
import p4_guard as g
R = g.ROOT/'docs/验证/开发/p4-001/build-b1-r2'
OLD = g.ROOT/'docs/验证/开发/p4-001/build-b1'
UNITS = {'analysis':['tools/p4_lib.py','tools/p4_analyze.py','tests/test_p4_lib.py','tests/test_p4_analyze.py'],
         'evidence':['tools/p4_check_evidence.py','tools/p4_verify.py','tests/test_p4_evidence.py']}
MUTABLE = {p for v in UNITS.values() for p in v}


def pre():
    permit=g.permit_check()
    c=g.load(OLD/'candidate.json')
    for p,h in c['files'].items():
        if g.sha(OLD/'blocked-source-snapshot'/p)!=h:
            raise ValueError('Original source archive changed: '+p)
        if p not in MUTABLE and g.sha(g.safe_name(p))!=h:
            raise ValueError('Out-of-scope dependency changed: '+p)
    return permit


def handoff(unit):
    h=g.load(R/unit/'handoff.json')
    if (h.get('stage'),h.get('session'),h.get('unit'),h.get('status'))!=('P4','p4-001',unit,'BUILT'):
        raise ValueError('Unfinished handoff')
    if h.get('plan_sha256')!=g.sha(g.PLAN) or set(h.get('source_hashes',{}))!=set(UNITS[unit]):
        raise ValueError('Wrong plan/source coverage')
    if h.get('gpu_started') is not False or h.get('live_configuration_written') is not False:
        raise ValueError('Scope violation')
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source SHA mismatch: '+p)
    if not isinstance(h.get('tests'),list) or not h['tests']:raise ValueError('No tests')
    for t in h['tests']:
        if type(t.get('returncode')) is not int or t['returncode']!=0:raise ValueError('Author check failed')
        p=t.get('console_path','')
        if not p.startswith('docs/验证/开发/p4-001/build-b1-r2/'+unit+'/') or g.sha(g.safe_name(p))!=t.get('console_sha256'):
            raise ValueError('Console not bound')
    return h['source_hashes']


def run_checks(unit):
    pre();pins=handoff('analysis')
    if unit=='evidence':pins.update(handoff('evidence'))
    R.mkdir(exist_ok=True)
    log=R/(unit+'.machine.console.txt')
    args=[sys.executable,'-B','-X','utf8','-m','unittest','discover']
    cmds=([args+['-s','tests','-p','test_p4_lib.py','-v'],args+['-s','tests','-p','test_p4_analyze.py','-v']]
          if unit=='analysis' else [args+['-s','tests','-v'],args+['-s','taskflows','-p','test_*.py','-v']])
    with log.open('xb') as f:
        for cmd in cmds:
            f.write(('COMMAND '+json.dumps(cmd)+'\n').encode('utf8'));f.flush()
            proc=subprocess.run(cmd,cwd=str(g.ROOT),stdout=f,stderr=subprocess.STDOUT)
            if proc.returncode:raise ValueError('Independent tests failed; see '+str(log))
    pre()
    for p,h in pins.items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('Source changed during tests')
    return {'status':'PASS_BUILD_ONLY','unit':unit,'source_hashes':pins,'console_path':log.relative_to(g.ROOT).as_posix(),'console_sha256':g.sha(log),'production_unlocked':False}


def freeze():
    pre();pins=handoff('analysis');pins.update(handoff('evidence'))
    old=g.load(OLD/'candidate.json')
    for p in old['files']:pins[p]=g.sha(g.safe_name(p))
    for p in ['docs/P4/P4-B1限域修正brief-v2.md','taskflows/p4_b1_rework_gate.py','taskflows/mpv-scale-p4-b1-rework-v2.json',
              'docs/验证/开发/p4-001/build-b1/independent-tooling-review.json',
              'docs/验证/开发/p4-001/build-b1/blocked-source-snapshot/snapshot.json']:
        pins[p]=g.sha(g.safe_name(p))
    for p in R.rglob('*'):
        if p.is_file():pins[p.relative_to(g.ROOT).as_posix()]=g.sha(p)
    c={'stage':'P4','session':'p4-001','scope':'B1-tooling-r2-not-calibration','files':pins,'production_unlocked':False,'measurements':'NOT_RUN'}
    g.create(R/'candidate.json',c)
    return {'candidate_sha256':g.sha(R/'candidate.json'),'candidate_path':(R/'candidate.json').relative_to(g.ROOT).as_posix(),'bound_files':len(pins),'measurements':'NOT_RUN'}


def record():
    pre();c=g.load(R/'candidate.json')
    for p,h in c['files'].items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('Frozen candidate drift '+p)
    review=json.load(sys.stdin)
    if review.get('candidate_sha256')!=g.sha(R/'candidate.json') or review.get('verdict') not in ('pass','block') or not isinstance(review.get('findings'),list):
        raise ValueError('Review identity mismatch')
    g.create(R/'independent-tooling-review.json',review)
    if review['verdict']!='pass' or any(f['severity'] in ('blocker','major') for f in review['findings']):
        raise ValueError('Review blocked; original findings retained')
    return {'status':'PASS_REVIEWED_BUILD_ONLY','candidate_sha256':review['candidate_sha256'],'gpu_started':False,'production_unlocked':False,'measurements':'NOT_RUN'}


if __name__=='__main__':
    try:
        action=sys.argv[1]
        if action=='pre':r=pre()
        elif action in UNITS:r=run_checks(action)
        elif action=='freeze':r=freeze()
        elif action=='record':r=record()
        else:raise ValueError('Unknown action')
        print(json.dumps(r,ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
