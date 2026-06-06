# -*- coding: utf-8 -*-
# woow_line_bridge/tests/test_line_service.py
# LINE Service API 單元測試
import base64
import hashlib
import hmac
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase


class TestLineService(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = self.env['line.service']
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_bridge.login_channel_id', 'test_channel_id')
        ICP.set_param('woow_line_bridge.messaging_channel_secret', 'test_secret')
        ICP.set_param('woow_line_bridge.messaging_access_token', 'test_token')

    @patch('odoo.addons.woow_line_bridge.models.line_service.requests.post')
    def test_verify_id_token_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'sub': 'U1234567890', 'name': 'Test User', 'picture': ''},
        )
        result = self.service.verify_id_token('fake_id_token')
        self.assertIsNotNone(result)
        self.assertEqual(result['sub'], 'U1234567890')
        self.assertEqual(result['name'], 'Test User')

    @patch('odoo.addons.woow_line_bridge.models.line_service.requests.post')
    def test_verify_id_token_failure(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400, text='Invalid token')
        result = self.service.verify_id_token('bad_token')
        self.assertIsNone(result)

    def test_verify_webhook_signature_valid(self):
        secret = 'test_secret'
        body = b'{"events":[]}'
        expected = base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        self.assertTrue(self.service.verify_webhook_signature(body, expected))

    def test_verify_webhook_signature_invalid(self):
        self.assertFalse(self.service.verify_webhook_signature(b'body', 'wrong_sig'))

    def test_verify_webhook_signature_empty(self):
        self.assertFalse(self.service.verify_webhook_signature(b'', ''))
