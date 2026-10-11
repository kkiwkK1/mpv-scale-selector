# -*- coding: utf-8 -*-
"""Read-only identity execution gates. Successful reporting is not P4 PASS."""
import json
import sys
import p4_guard as g
import p3_guard
C=g.ROOT/'docs/验证/开发/p4-001/build-b2-r2/candidate-r2.json'
SHA='0d0bf8e8f24b03ae04107bf1f439ad34cb01f187aa2e97f88a4fd8198d5dcb2a'
E=g.ROOT/'docs/验证/开发/p4-001/identity-run-001'


def pre():
    g.permit_check()
    if g.sha(C)!=SHA:raise ValueError('Collector candidate changed')
    for p,v in g.load(C)['files'].items():
        if g.sha(g.safe_name(p))!=v:raise ValueError('Source/dependency drift: '+p)
    r=g.load(C.parent/'safety-method-review.json')
    if r.get('verdict')!='pass' or r.get('candidate_sha256')!=SHA or any(f['severity'] in ('blocker','major') for f in r['findings']):raise ValueError('No safety review permission')
    return {'status':'PASS_READONLY_EXECUTION_PRECHECK','candidate_sha256':SHA,'production_unlocked':False}


def post():
    pre()
    report=g.load(E/'execution-report.json')
    if report.get('candidate_sha256')!=SHA or report.get('stage')!='P4' or report.get('session')!='p4-001':raise ValueError('Execution identity mismatch')
    if report.get('status') not in ('MEASURED_IDENTITY_ONLY','NOT_ESTABLISHED','BLOCKED_ENV','REWORK'):raise ValueError('Unrecognized execution status')
    for k in ['production_unlocked','performance_measured','live_configuration_written']:
        if report.get(k) is not False:raise ValueError('Unwarranted claim: '+k)
    if report.get('source_unchanged') is not True:raise ValueError('Source drift reported')
    m=g.load(E/'evidence-manifest.json')
    files=m.get('files',{})
    if not files:raise ValueError('Empty evidence tree')
    observed={p.relative_to(g.ROOT).as_posix() for p in E.rglob('*') if p.is_file() and p!=E/'evidence-manifest.json'}
    if set(files)!=observed:raise ValueError('Full tree coverage mismatch')
    prefix=E.relative_to(g.ROOT).as_posix()+'/'
    for p,v in files.items():
        if not p.startswith(prefix) or g.sha(g.safe_name(p))!=v:raise ValueError('Evidence mismatch '+p)
    backup=p3_guard.old_guard().verified_backup()
    return {'status':'EXECUTION_REPORT_VERIFIED','execution_status':report['status'],'candidate_sha256':SHA,
            'evidence_files':len(files),'evidence_manifest_sha256':g.sha(E/'evidence-manifest.json'),
            'gpu_started':report.get('gpu_started'),'performance_measured':False,'production_unlocked':False,'backup':backup}


if __name__=='__main__':
    try:
        print(json.dumps(pre() if sys.argv[1]=='pre' else post(),ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps({'status':'FAIL','error':str(e)},ensure_ascii=False));raise SystemExit(1)
