# -*- coding: utf-8 -*-
import copy
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import p4_guard as g


def good():
    p={'stage':'P4','session':'p4-001','ready':'pass','required_tests':list(g.REQUIRED),
       'write_paths':['tools/p4_lib.py'],'human_subjective_acceptance_claimed':False,
       'live_configuration_write_allowed':False}
    for k in ['fairness','sampling','frame_pacing','rife','environment_safety','evidence','objective_user_split','resource_budget','execution_batches','limitations']:
        p[k]={'declared':True}
    return p


class P4PlanTests(unittest.TestCase):
    def test_positive(self):
        self.assertTrue(g.validate_plan(good(), {'tools/p4_lib.py'}))

    def test_missing_required_blocked(self):
        p=good();p['required_tests'].remove('RIFE-01')
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_duplicate_ids_blocked(self):
        p=good();p['required_tests'].append('RIFE-01')
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_old_source_write_blocked(self):
        p=good();p['write_paths']=['scripts/scale-selector.lua']
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_duplicate_writes_blocked(self):
        p=good();p['write_paths']*=2
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_unready_plan_blocked(self):
        p=good();p['ready']='block'
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_prose_instead_of_method_blocked(self):
        for k in ['sampling','rife','frame_pacing','objective_user_split']:
            p=good();p[k]='trust me'
            with self.subTest(k=k),self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_false_user_approval_blocked(self):
        p=good();p['human_subjective_acceptance_claimed']=True
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_live_write_blocked(self):
        p=good();p['live_configuration_write_allowed']=True
        with self.assertRaises(ValueError):g.validate_plan(p, {'tools/p4_lib.py'})

    def test_paths(self):
        for n in ['../a','/a','D:/a','a\\b','.pi/a','a//b','a/./b','']:
            with self.subTest(n=n),self.assertRaises(ValueError):g.safe_name(n)

    def test_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';g.create(p,{'status':'FAIL'})
            with self.assertRaises(FileExistsError):g.create(p,{'status':'PASS'})
            self.assertEqual(g.load(p),{'status':'FAIL'})

    def test_permit_checks_guard_self_binding(self):
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d)
            (tmp/'taskflows').mkdir()
            test=tmp/'taskflows/test_p4_guard.py';test.write_text('test',encoding='utf8')
            baseline=tmp/'baseline.json';g.create(baseline,{})
            auth=tmp/'auth.json';g.create(auth,{})
            review=tmp/'plan-adversarial-review.json';g.create(review,{})
            permit={'baseline_sha256':g.sha(baseline),'authorization_sha256':g.sha(auth),
                    'guard_sha256':'0'*64,'guard_tests_sha256':g.sha(test),
                    'plan_review_sha256':g.sha(review),'plan_sha256':'plan','environment_sha256':'env'}
            g.create(tmp/'work-permit.json',permit)
            with mock.patch.object(g,'ROOT',tmp),mock.patch.object(g,'SESSION',tmp),mock.patch.object(g,'BASELINE',baseline),mock.patch.object(g,'AUTH',auth),mock.patch.object(g,'plan_check',return_value={'plan_sha256':'plan','environment_sha256':'env'}):
                with self.assertRaisesRegex(ValueError,'guard_sha256'):g.permit_check()

    def test_load_rejects_crlf(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_bytes(b'{\r\n}\r\n')
            with self.assertRaises(ValueError):g.load(p)


if __name__=='__main__':unittest.main()
