# -*- coding: utf-8 -*-
"""B2 r2 checks reuse unchanged build gate in a new create-only namespace."""
import json
import subprocess
import sys
import p4_guard as g
import p4_b2_gate as base
OLD=base.R
R=g.ROOT/'docs/验证/开发/p4-001/build-b2-r2'
ORIGINAL_PRE=base.pre


def pre():
    result=ORIGINAL_PRE()
    c=g.load(OLD/'candidate.json')
    for p,h in c['files'].items():
        if g.sha(OLD/'blocked-source-snapshot'/p)!=h:
            raise ValueError('Old B2 archive changed: '+p)
        if p not in base.FILES and g.sha(g.safe_name(p))!=h:
            raise ValueError('Out-of-scope B2 dependency changed: '+p)
    return result


def build():
    pre()
    h=g.load(R/'author/handoff.json')
    if (h.get('stage'),h.get('session'),h.get('unit'),h.get('status'))!=('P4','p4-001','collector','BUILT'):
        raise ValueError('Collector incomplete')
    if h.get('plan_sha256')!=g.sha(g.PLAN) or h.get('b1_candidate_sha256')!=base.B1_SHA or set(h.get('source_hashes',{}))!=set(base.FILES):
        raise ValueError('Wrong collector identity')
    if h.get('gpu_started') is not False or h.get('live_configuration_written') is not False:
        raise ValueError('Writer scope violation')
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source drift')
    prefix=(R/'author').relative_to(g.ROOT).as_posix()+'/'
    if not isinstance(h.get('tests'),list) or not h['tests']:raise ValueError('No tests')
    for t in h['tests']:
        if type(t.get('returncode')) is not int or t['returncode']!=0:raise ValueError('Author test failed')
        p=t.get('console_path','')
        if not p.startswith(prefix) or g.sha(g.safe_name(p))!=t.get('console_sha256'):
            raise ValueError('R2 console not bound')
    with (R/'independent-tests.console.txt').open('xb') as log:
        for suite in [['-s','tests','-v'],['-s','taskflows','-p','test_*.py','-v']]:
            cmd=[sys.executable,'-B','-X','utf8','-m','unittest','discover']+suite
            log.write(('COMMAND '+json.dumps(cmd)+'\n').encode('utf8'));log.flush()
            if subprocess.run(cmd,cwd=str(g.ROOT),stdout=log,stderr=subprocess.STDOUT).returncode:
                raise ValueError('Independent tests failed')
    pre()
    for p,v in h['source_hashes'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source changed during tests')
    pins=dict(g.load(base.B1)['files'])
    pins.update(g.load(g.ROOT/'docs/验证/开发/p3-001/revision-r2/candidate.json')['files'])
    for p in base.FILES+['docs/P4/P4-B2采集器实现与首载brief.md','taskflows/p4_b2_gate.py','taskflows/mpv-scale-p4-build-b2.json','docs/验证/开发/p4-001/build-b1-r2/candidate.json','docs/验证/开发/p4-001/build-b1-r2/independent-tooling-review.json']:
        pins[p]=g.sha(g.safe_name(p))
    for p in R.rglob('*'):
        if p.is_file():pins[p.relative_to(g.ROOT).as_posix()]=g.sha(p)
    for p,v in pins.items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Dependency drift: '+p)
    c={'stage':'P4','session':'p4-001','scope':'B2-r2-build','files':pins,'production_unlocked':False,'measurements':'NOT_RUN'}
    g.create(R/'candidate.json',c)
    result={'status':'PASS_BUILD_ONLY','gpu_started':False,'production_unlocked':False}
    for p in ['docs/P4/P4-B2限域修正brief-v2.md','taskflows/p4_b2_rework_gate.py','taskflows/mpv-scale-p4-b2-rework-v2.json','taskflows/mpv-scale-p4-b2-rework-tail-v3.json',
              'docs/验证/开发/p4-001/build-b2/candidate.json','docs/验证/开发/p4-001/build-b2/contract-failed-review.json',
              'docs/验证/开发/p4-001/build-b2/contract-failed-review.raw.txt',
              'docs/验证/开发/p4-001/build-b2/blocked-source-snapshot/snapshot.json',
              'docs/验证/开发/p4-001/build-b2-r2/candidate.json']:
        c['files'][p]=g.sha(g.safe_name(p))
    c['scope']='B2-r2-collector-pre-execution'
    g.create(R/'candidate-r2.json',c)
    result['candidate_sha256']=g.sha(R/'candidate-r2.json')
    result['candidate_path']=(R/'candidate-r2.json').relative_to(g.ROOT).as_posix()
    result['bound_files']=len(c['files'])
    return result


def record():
    pre();c=g.load(R/'candidate-r2.json')
    for p,h in c['files'].items():
        if g.sha(g.safe_name(p))!=h:raise ValueError('New candidate drift: '+p)
    review=json.load(sys.stdin)
    if review.get('candidate_sha256')!=g.sha(R/'candidate-r2.json') or review.get('verdict') not in ('pass','block'):
        raise ValueError('Review identity mismatch')
    if any(f.get('severity') not in ('blocker','major','minor') for f in review.get('findings',[])):
        raise ValueError('Invalid severity contract')
    g.create(R/'safety-method-review.json',review)
    if review['verdict']!='pass' or any(f['severity'] in ('blocker','major') for f in review['findings']):
        raise ValueError('Review blocked')
    return {'status':'PASS_REVIEWED_COLLECTOR_BUILD_ONLY','candidate_sha256':review['candidate_sha256'],
            'gpu_started':False,'measurements':'NOT_RUN','production_unlocked':False}


if __name__=='__main__':
    try:
        action=sys.argv[1]
        if action=='pre':r=pre()
        elif action=='build':r=build()
        elif action=='record':r=record()
        else:raise ValueError('Unknown action')
        print(json.dumps(r,ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps({'status':'FAIL','error':str(e)},ensure_ascii=False));raise SystemExit(1)
