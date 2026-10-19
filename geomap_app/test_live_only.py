"""The app must require Databricks and never substitute provider records."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


class LiveOnlyTest(unittest.TestCase):
    def test_default_and_rejected_modes(self):
        path = Path(__file__).parent / 'geomap' / 'config.py'
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runpy.run_path(str(path))['MODE'], 'databricks')
        for mode in ['demo', 'synthetic', '']:
            with patch.dict(os.environ, {'GEOMAP_MODE': mode}):
                with self.assertRaisesRegex(ValueError, 'Only GEOMAP_MODE=databricks'):
                    runpy.run_path(str(path))

    def test_connection_failure_is_not_replaced(self):
        from geomap.data import get_source
        get_source.clear()
        with patch('geomap.databricks_source.DatabricksSource', side_effect=RuntimeError('Connection unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Connection unavailable'):
                get_source()
        get_source.clear()


if __name__ == '__main__':
    unittest.main(verbosity=2)
