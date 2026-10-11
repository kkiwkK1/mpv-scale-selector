# -*- coding: utf-8 -*-
"""P3 guard policy regression with only temporary synthetic files/mocks."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('p3_guard_tested', Path(__file__).with_name('p3_guard.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class P3GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='p3-guard-unit-')
        self.root = Path(self.tmp.name)
        self.plan = self.root / 'plan.json'
        self.scope = ['scripts/selector.lua', 'tests/test_selector.py']
        # Separate lists: mutating the plan must not also mutate the allowed scope.
        self.base = {'allowed_write_paths': list(self.scope)}
        self.obj = {'stage': 'P3', 'session': 'p3-001', 'ready': 'pass',
                    'required_tests': list(g.REQUIRED), 'write_paths': list(self.scope)}
        self.patches = [patch.object(g, 'ROOT', self.root), patch.object(g, 'PLAN', self.plan),
                        patch.object(g, 'preserved', return_value=self.base)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.addCleanup(self.tmp.cleanup)

    def write_plan(self):
        self.plan.write_text(json.dumps(self.obj), encoding='utf8')

    def test_ready_plan(self):
        self.write_plan()
        self.assertEqual(g.plan_check()['status'], 'PASS')

    def test_missing_case(self):
        self.obj['required_tests'].remove('GEO-06')
        self.write_plan()
        with self.assertRaises(ValueError):
            g.plan_check()

    def test_duplicate_case(self):
        self.obj['required_tests'].append('GEO-06')
        self.write_plan()
        with self.assertRaises(ValueError):
            g.plan_check()

    def test_unapproved_scope(self):
        self.obj['write_paths'].append('tools/mpv_config_backup.py')
        self.write_plan()
        with self.assertRaises(ValueError):
            g.plan_check()

    def test_blocked_plan(self):
        self.obj['ready'] = 'block'
        self.write_plan()
        with self.assertRaises(ValueError):
            g.plan_check()

    def test_invalid_paths(self):
        for name in ['../secret', '.pi/session', 'D:/MPV/a', 'a\\b', 'a/../b', '/home/a', 'a//b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.safe_name(name)

    def test_utf8_lf_required(self):
        self.plan.write_bytes(b'{\r\n"a":1\r\n}')
        with self.assertRaises(ValueError):
            g.load(self.plan)

    def test_create_only(self):
        g.create(self.plan, {'a': 1})
        with self.assertRaises(FileExistsError):
            g.create(self.plan, {'a': 2})

    def test_plan_review_wrong_fingerprint(self):
        self.write_plan()
        with self.assertRaises(ValueError):
            g.permit({'verdict': 'pass', 'plan_sha256': '0' * 64, 'findings': []})

    def test_plan_review_major_not_accepted(self):
        self.write_plan()
        with self.assertRaises(ValueError):
            g.permit({'verdict': 'pass', 'plan_sha256': g.sha(self.plan),
                      'findings': [{'severity': 'major'}]})

    def test_required_matrix(self):
        self.assertEqual(len(g.REQUIRED), len(set(g.REQUIRED)))
        for identifier in ['SHD-05', 'SHD-06', 'SHD-07', 'GEO-02', 'GEO-06', 'EVI-01', 'PER-04-COMPUTE', 'UNIT-P2-01', 'UNIT-P3-01']:
            self.assertIn(identifier, g.REQUIRED)


if __name__ == '__main__':
    unittest.main()
