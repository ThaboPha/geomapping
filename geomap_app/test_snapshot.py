import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from geomap.snapshot_source import SnapshotSource


class SnapshotTrialTests(unittest.TestCase):
    def test_partial_snapshot_cannot_start_or_fall_back_to_sql(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'manifest.json').write_text(json.dumps({'complete':False,'format_version':1}))
            with patch('databricks.sql.connect',side_effect=AssertionError('Must never connect')):
                with self.assertRaisesRegex(ValueError,'incomplete'):
                    SnapshotSource(folder)

    def test_path_traversal_is_rejected(self):
        from geomap.snapshot_source import REQUIRED
        with tempfile.TemporaryDirectory() as folder:
            datasets={name:dict(file='../secret.parquet') for name in REQUIRED}
            Path(folder,'manifest.json').write_text(json.dumps(dict(complete=True,format_version=1,datasets=datasets)))
            with self.assertRaisesRegex(ValueError,'path'):
                SnapshotSource(folder)

    def test_snapshot_is_not_a_membership_directory(self):
        src=SnapshotSource.__new__(SnapshotSource)
        self.assertFalse(src.member_lookup_enabled)
        with self.assertRaises(NotImplementedError):
            src.find_members('12345')
