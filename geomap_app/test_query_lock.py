"""A failing live request must not lock every subsequent member session."""
import threading
import unittest
from unittest.mock import patch
from geomap.databricks_source import _query
from databricks.sql.exc import RequestError


class QueryLockTests(unittest.TestCase):
    def test_connection_failure_releases_shared_query_lock(self):
        lock = threading.Lock()
        with patch('geomap.databricks_source._QUERY_LOCK', lock), patch(
            'geomap.databricks_source._connection', side_effect=ConnectionError('Unavailable')):
            with self.assertRaises(ConnectionError):
                _query('SELECT 1')
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_transport_failure_invalidates_connection_for_next_attempt(self):
        lock = threading.Lock()
        with patch('geomap.databricks_source._QUERY_LOCK', lock), patch(
            'geomap.databricks_source._connection', side_effect=RequestError('Unavailable')) as connection:
            with self.assertRaises(RequestError):
                _query('SELECT 1')
            connection.clear.assert_called_once()
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()


if __name__ == '__main__':
    unittest.main()
