# -*- coding: utf-8 -*-
"""Frozen B1 tooling review, distinct from calibration and P4 measurement gates."""
import json
import sys
import p4_guard as g
CAND = g.ROOT/'docs/验证/开发/p4-001/build-b1/candidate.json'
EXPECTED = 'b04b3823272be91422fcf812e613bb732b538179b83bd77c170aea25e428aced'


def check():
    g.permit_check()
    if g.sha(CAND) != EXPECTED:
        raise ValueError('B1 review candidate changed')
    c = g.load(CAND)
    for p,h in c['files'].items():
        if g.sha(g.safe_name(p)) != h:
            raise ValueError('B1 source/dependency changed: '+p)
    return {'candidate_sha256':EXPECTED,'scope':c['scope'],'measurement_status':'NOT_RUN'}


if __name__ == '__main__':
    try:
        c=check()
        if sys.argv[1]=='record':
            r=json.load(sys.stdin)
            if r.get('candidate_sha256')!=EXPECTED or r.get('verdict') not in ('pass','block') or not isinstance(r.get('findings'),list):
                raise ValueError('Wrong review identity/contract')
            target=CAND.parent/'independent-tooling-review.json'
            g.create(target,r)
            c['verdict']=r['verdict']
            print(json.dumps(c,ensure_ascii=False,indent=2))
            if r['verdict']!='pass' or any(i['severity'] in ('major','blocker') for i in r['findings']):
                raise SystemExit(1)
        else:
            print(json.dumps(c,ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
