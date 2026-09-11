# -*- coding: utf-8 -*-
"""H-7: "re-upload" can wipe every friend's menu.

action_reupload_to_line() used to delete the LINE-side menu first, then
rebuild it. If the rebuild failed (a bad tap area, an oversized image, the
wrong ratio...) Odoo rolled the transaction back, but the LINE-side deletion
could not be undone: every friend lost their rich menu while Odoo still
showed the record as active with its old richMenuId.

The fix builds the new menu first and only deletes the old one after the
build succeeds. These tests drive the public button method
(action_reupload_to_line) with the LINE HTTP boundary mocked, per RULES.md.
"""
import base64
import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
DELETE = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.delete'
CREATE_URL = 'https://api.line.me/v2/bot/richmenu'


def _resp(status_code, json_body=None, text=None):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body or {}
    resp.text = text if text is not None else (json.dumps(json_body) if json_body else '')
    return resp


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuReupload(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_access_token', 'test_token')
        self.menu = self.env['line.richmenu'].create({
            'name': 'reupload test',
            'line_richmenu_id': 'richmenu-old-id',
            'state': 'active',
            'image': base64.b64encode(b'fake-image-bytes'),
            'image_filename': 'menu.png',
            'area_ids': [(0, 0, {
                'x': 0, 'y': 0, 'width': 2500, 'height': 1686,
                'action_type': 'uri', 'action_value': 'https://example.com',
            })],
        })

    def test_rebuild_failure_keeps_old_menu_and_shows_line_message(self):
        """create() returns 400 → old menu untouched, LINE's message surfaces."""
        delete_calls = []

        def fake_post(url, **kwargs):
            if url == CREATE_URL:
                return _resp(400, {'message': 'The request body has 2 error(s)'})
            raise AssertionError(f'unexpected POST {url}')

        def fake_delete(url, **kwargs):
            delete_calls.append(url)
            return _resp(200)

        with patch(POST, side_effect=fake_post), patch(DELETE, side_effect=fake_delete):
            with self.assertRaises(UserError) as cm:
                self.menu.action_reupload_to_line()

        self.assertIn('The request body has 2 error(s)', str(cm.exception))
        self.assertFalse(delete_calls, f'no DELETE should have been sent, got {delete_calls}')

        self.menu.invalidate_recordset()
        self.assertEqual(self.menu.line_richmenu_id, 'richmenu-old-id')
        self.assertEqual(self.menu.state, 'active')

    def test_rebuild_success_stores_new_id_and_deletes_old_afterwards(self):
        calls = []

        def fake_post(url, **kwargs):
            calls.append(('POST', url))
            if url == CREATE_URL:
                return _resp(200, {'richMenuId': 'richmenu-new-id'})
            if url.endswith('/richmenu-new-id/content'):
                return _resp(200)
            raise AssertionError(f'unexpected POST {url}')

        def fake_delete(url, **kwargs):
            calls.append(('DELETE', url))
            return _resp(200)

        with patch(POST, side_effect=fake_post), patch(DELETE, side_effect=fake_delete):
            self.menu.action_reupload_to_line()

        self.menu.invalidate_recordset()
        self.assertEqual(self.menu.line_richmenu_id, 'richmenu-new-id')

        create_idx = calls.index(('POST', CREATE_URL))
        delete_idx = next(i for i, c in enumerate(calls) if c[0] == 'DELETE')
        self.assertLess(create_idx, delete_idx,
                         f'old menu was deleted before/without building the new one: {calls}')
        self.assertIn('richmenu-old-id', calls[delete_idx][1])
