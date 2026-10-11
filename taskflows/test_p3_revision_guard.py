# -*- coding: utf-8 -*-
"""Revision namespace tests. Pure temp/mocks; never touch live mpv or evidence."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
import p3_revision_guard as r


class RevisionNamespaceTests(unittest.TestCase):
    def test_current_artifact_allowed(self):
        self.assertTrue(r.under_revision(r.REV_REL + '/author/full-r1/evidence-manifest.json'))

    def test_historical_manifest_not_current_proof(self):
        self.assertFalse(r.under_revision('docs/验证/开发/p3-001/implementer/full-r2/evidence-manifest.json'))

    def test_other_revision_not_current_proof(self):
        self.assertFalse(r.under_revision('docs/验证/开发/p3-001/revision-r3/tests.json'))

    def test_path_traversal_rejected(self):
        for name in [r.REV_REL + '/../tests.json', r.REV_REL + '/x/../../tests.json',
                     r.REV_REL + '//tests.json', r.REV_REL + '/./tests.json',
                     r.REV_REL + '/C:/tests.json', r.REV_REL + '/x\\tests.json']:
            self.assertFalse(r.under_revision(name), name)

    def test_other_session_and_absolute_rejected(self):
        for name in ['docs/验证/开发/p3-002/revision-r2/tests.json',
                     '/' + r.REV_REL + '/tests.json', None, 4]:
            self.assertFalse(r.under_revision(name), name)

    def test_candidate_lookup_only_redirected(self):
        directory = Path('temp-revision-context')
        original = mock.Mock(side_effect=lambda session: Path('original') / session)
        g = SimpleNamespace(folder=original)
        g.candidate = mock.Mock(side_effect=lambda stage, session:
                                 (stage, g.folder(session), g.folder('p2-001')))
        with mock.patch.object(r, 'revision_folder', return_value=directory):
            result = r.relocated_candidate(g)
        self.assertEqual(result, ('P3', directory, Path('original/p2-001')))
        self.assertEqual(original.call_args.args, ('p2-001',))

    def test_context_resolves_through_original_safe_path_gate(self):
        safe = mock.Mock(return_value=Path('safe-revision/revision-context.json'))
        g = SimpleNamespace(source_path=safe)
        self.assertEqual(r.revision_folder(g), Path('safe-revision'))
        safe.assert_called_once_with(r.REV_REL + '/revision-context.json')

    def test_context_path_rejection_propagates(self):
        g = SimpleNamespace(source_path=mock.Mock(side_effect=ValueError('reparse')))
        with self.assertRaisesRegex(ValueError, 'reparse'):
            r.revision_folder(g)


if __name__ == '__main__':
    unittest.main()
