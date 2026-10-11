# -*- coding: utf-8 -*-
"""B2 collector build/safety gates, separate from real calibration acceptance."""
import json
import subprocess
import sys
import p4_guard as g
R=g.ROOT/'docs/验证/开发/p4-001/build-b2'
B1=g.ROOT/'docs/验证/开发/p4-001/build-b1-r2/candidate.json'
B1_SHA='929079b09d1c1ac10f262ebc05e7d311ca5943d58eeb5731890199d803d17f3b'
FILES=['tools/p4_collect.py','tests/test_p4_collect.py']


def pre():
    g.permit_check()
    if g.sha(B1)!=B1_SHA:raise ValueError('B1 fixed candidate changed')
    c=g.load(B1)
    for p,h in c['files'].items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('B1 dependency changed: '+p)
    review=g.load(B1.parent/'independent-tooling-review.json')
    if review.get('candidate_sha256')!=B1_SHA or review.get('verdict')!='pass' or any(f['severity'] in ('major','blocker') for f in review['findings']):
        raise ValueError('B1 review not passed')
    return {'status':'PASS_PRECHECK','production_unlocked':False,'b1_candidate_sha256':B1_SHA}


def build():
    pre();h=g.load(R/'author/handoff.json')
    if (h.get('stage'),h.get('session'),h.get('unit'),h.get('status'))!=('P4','p4-001','collector','BUILT'):
        raise ValueError('Collector incomplete')
    if h.get('plan_sha256')!=g.sha(g.PLAN) or h.get('b1_candidate_sha256')!=B1_SHA or set(h.get('source_hashes',{}))!=set(FILES):
        raise ValueError('Wrong collector identity')
    if h.get('gpu_started') is not False or h.get('live_configuration_written') is not False:raise ValueError('Writer safety scope violated')
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source drift')
    if not isinstance(h.get('tests'),list) or not h['tests']:raise ValueError('No tests')
    for t in h['tests']:
        if type(t.get('returncode')) is not int or t['returncode']!=0:raise ValueError('Test failure')
        p=t.get('console_path','')
        if not p.startswith('docs/验证/开发/p4-001/build-b2/author/') or g.sha(g.safe_name(p))!=t.get('console_sha256'):raise ValueError('Test log not bound')
    commands=[[sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests','-v'],
              [sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','taskflows','-p','test_*.py','-v']]
    with (R/'independent-tests.console.txt').open('xb') as f:
        for cmd in commands:
            f.write(('COMMAND '+json.dumps(cmd)+'\n').encode('utf8'));f.flush()
            if subprocess.run(cmd,cwd=str(g.ROOT),stdout=f,stderr=subprocess.STDOUT).returncode:raise ValueError('Independent tests failed')
    pre()
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Collector changed during tests')
    pins=dict(g.load(B1)['files'])
    p3=g.load(g.ROOT/'docs/验证/开发/p3-001/revision-r2/candidate.json')
    pins.update(p3['files'])
    for p in FILES+['docs/P4/P4-B2采集器实现与首载brief.md','taskflows/p4_b2_gate.py','taskflows/mpv-scale-p4-build-b2.json',
                    'docs/验证/开发/p4-001/build-b1-r2/candidate.json','docs/验证/开发/p4-001/build-b1-r2/independent-tooling-review.json']:
        pins[p]=g.sha(g.safe_name(p))
    for p in R.rglob('*'):
        if p.is_file():pins[p.relative_to(g.ROOT).as_posix()]=g.sha(p)
    for p,v in pins.items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Dependency drift before freeze: '+p)
    g.create(R/'candidate.json',{'stage':'P4','session':'p4-001','scope':'B2-collector-pre-execution','files':pins,'production_unlocked':False,'measurements':'NOT_RUN'})
    return {'status':'PASS_BUILD_ONLY','candidate_sha256':g.sha(R/'candidate.json'),'bound_files':len(pins),'gpu_started':False,'production_unlocked':False}


def record():
    pre();c=g.load(R/'candidate.json')
    for p,v in c['files'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Candidate drift: '+p)
    r=json.load(sys.stdin)
    if r.get('candidate_sha256')!=g.sha(R/'candidate.json') or r.get('verdict') not in ('pass','block'):raise ValueError('Review identity mismatch')
    g.create(R/'safety-method-review.json',r)
    if r['verdict']!='pass' or any(f['severity'] in ('blocker','major') for f in r['findings']):raise ValueError('Safety/method review blocked')
    return {'status':'PASS_COLLECTOR_SAFETY_BUILD_ONLY','candidate_sha256':r['candidate_sha256'],'production_unlocked':False,'gpu_started':False,'measurements':'NOT_RUN'}


if __name__=='__main__':
    try:
        a=sys.argv[1]
        if a=='pre':result=pre()
        elif a=='build':result=build()
        elif a=='record':result=record()
        else:raise ValueError('Unknown action')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps({'status':'FAIL','error':str(e)},ensure_ascii=False));raise SystemExit(1)
