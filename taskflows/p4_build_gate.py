# -*- coding: utf-8 -*-
"""Independent read-only P4 B1 checks; no benchmark or final acceptance."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import p4_guard as g

UNITS = {
    'lib': ['tools/p4_lib.py', 'tests/test_p4_lib.py'],
    'analyze': ['tools/p4_analyze.py', 'tests/test_p4_analyze.py'],
    'evidence': ['tools/p4_check_evidence.py', 'tools/p4_verify.py', 'tests/test_p4_evidence.py'],
}


def check(unit, full=False):
    permit = g.permit_check()
    names = list(UNITS)
    selected = names[:names.index(unit)+1]
    pins = {}
    for name in selected:
        base = 'docs/验证/开发/p4-001/build-b1/' + name + '/'
        h = g.load(g.safe_name(base + 'handoff.json'))
        if (h.get('stage'),h.get('session'),h.get('unit'),h.get('status')) != ('P4','p4-001',name,'BUILT'):
            raise ValueError('Unfinished/wrong handoff ' + name)
        if h.get('plan_sha256') != permit['plan_sha256']:
            raise ValueError('Plan mismatch')
        if h.get('gpu_started') is not False or h.get('live_configuration_written') is not False:
            raise ValueError('Pure B1 scope not respected')
        actual = h.get('source_hashes',{})
        if set(actual) != set(UNITS[name]):
            raise ValueError('Unit exact source coverage ' + name)
        for p,v in actual.items():
            if g.sha(g.safe_name(p)) != v:
                raise ValueError('Source mismatch ' + p)
            pins[p] = v
        t = h.get('tests',{})
        if type(t.get('returncode')) is not int or t['returncode'] != 0:
            raise ValueError('Author tests did not pass')
        cp = t.get('console_path','')
        if not cp.startswith(base) or g.sha(g.safe_name(cp)) != t.get('console_sha256'):
            raise ValueError('Console is missing/not bound')
    command=[sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests']
    if not full:
        command += ['-p','test_p4_*.py']
    command += ['-v']
    subprocess.run(command,cwd=str(g.ROOT),check=True)
    if full:
        subprocess.run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','taskflows','-p','test_*.py','-v'],cwd=str(g.ROOT),check=True)
    for p,v in pins.items():
        if g.sha(g.safe_name(p)) != v:
            raise ValueError('Source changed during tests: ' + p)
    g.permit_check()
    return {'status':'PASS_BUILD_ONLY','unit':unit,'source_hashes':pins,'plan_sha256':permit['plan_sha256'],
            'gpu_started':False,'production_unlocked':False,'p4_measurement_status':'NOT_RUN'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('unit',choices=list(UNITS))
    p.add_argument('--full',action='store_true')
    args=p.parse_args()
    try:
        print(json.dumps(check(args.unit,args.full),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
