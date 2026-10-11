# -*- coding: utf-8 -*-
"""Read-only check of the retained independent core handoff; not final P3 acceptance."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'docs/验证/开发/p3-001/core-checks/core-delivery.json'
r = json.loads(path.read_text(encoding='utf8'))
assert r['status'] == 'PASS' and r['stage'] == 'P3' and r['session'] == 'p3-001'
assert isinstance(r.get('sourcehash'), dict) and r['sourcehash']
for name, checksum in r['sourcehash'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == checksum, name
run = ROOT / 'docs/验证/开发/p3-001/core-checks' / r['run']
s = json.loads((run / 'smoke-report.json').read_text(encoding='utf8'))
assert s['totals'] == {'cases': 12, 'passed': 12, 'failed': 0}, s['totals']
print(json.dumps({'status': 'PASS', 'scope': 'core-smoke-handoff-only',
                  'core_run': r['run'], 'core_source_files_pinned': len(r['sourcehash']),
                  'handoff_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'live_configuration_written': False,
                  'limitations': ['Decoder activity fallback is not GPU render-freshness proof; final matrix must distinguish this.',
                                  'No 35-ID matrix, full pixel golden comparisons, 8/10bit per gear or final reviews yet.']}, indent=2))
