"""Offline method-boundary checks; no database or network is accessed."""
import pathlib
import runpy
import sys
import types
import unittest
from unittest.mock import patch


class Denied(Exception):
    pass


class TestSignalDeskCompat(unittest.TestCase):
    def setUp(self):
        def reject(message, exception):
            raise exception(message)
        def whitelist(**options):
            def decorate(fn):
                fn.allowed_methods = options['methods']
                return fn
            return decorate
        self.frappe = types.SimpleNamespace(
            session=types.SimpleNamespace(user='pz.signal.desk@petrolzone.local'),
            local=types.SimpleNamespace(request=None),
            PermissionError=Denied, throw=reject, whitelist=whitelist,
        )
        with patch.dict(sys.modules, {'frappe': self.frappe}):
            module = runpy.run_path(str(pathlib.Path(__file__).parents[1] / 'pz_sales_contract/signal_desk_compat.py'))
        self.guard = module['is_get_request']

    def test_only_get_even_when_safe_exec_bypasses_decorator(self):
        self.assertEqual(self.guard.allowed_methods, ['GET'])
        for method in ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT']:
            with self.subTest(method=method):
                self.frappe.local.request = types.SimpleNamespace(method=method)
                self.assertIs(self.guard(), method == 'GET')

    def test_missing_request_fails_closed(self):
        self.assertFalse(self.guard())

    def test_wrong_users_denied_before_method_check(self):
        self.frappe.local.request = types.SimpleNamespace(method='GET')
        for user in ['Guest', 'Administrator', 'unrelated@example.test']:
            self.frappe.session.user = user
            with self.assertRaises(Denied):
                self.guard()


if __name__ == '__main__':
    unittest.main()
