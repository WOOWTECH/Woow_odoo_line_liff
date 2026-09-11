# -*- coding: utf-8 -*-
"""H-8: archive and delete used to leave orphan menus on LINE.

LINE's delete result was ignored and line_richmenu_id cleared no matter
what happened, and line.richmenu had no unlink() override even though
managers may delete records. A menu Odoo could no longer reach stayed on
LINE, counting toward LINE's 1000-menu limit.

Now action_archive() and unlink() delete on LINE first: 200 and 404
(already gone) proceed, anything else raises a UserError and keeps the
record + its LINE link intact. These tests drive the public button method
and unlink() with the LINE HTTP boundary mocked, per RULES.md.
"""
import base64
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

DELETE = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.delete'


def _resp(status_code, text=''):
    resp = MagicMock(status_code=status_code)
    resp.text = text
    return resp


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuArchive(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_access_token', 'test_token')
        self.menu = self.env['line.richmenu'].create({
            'name': 'archive test',
            'line_richmenu_id': 'richmenu-live-id',
            'state': 'active',
            'image': base64.b64encode(b'fake-image-bytes'),
            'image_filename': 'menu.png',
        })

    def test_archive_500_raises_and_keeps_record_intact(self):
        with patch(DELETE, return_value=_resp(500, 'internal error')):
            with self.assertRaises(UserError):
                self.menu.action_archive()

        self.menu.invalidate_recordset()
        self.assertEqual(self.menu.state, 'active')
        self.assertEqual(self.menu.line_richmenu_id, 'richmenu-live-id')

    def test_archive_404_proceeds(self):
        with patch(DELETE, return_value=_resp(404)):
            self.menu.action_archive()

        self.menu.invalidate_recordset()
        self.assertEqual(self.menu.state, 'archived')
        self.assertFalse(self.menu.line_richmenu_id)

    def test_archive_200_proceeds_and_delete_url_has_menu_id(self):
        calls = []

        def fake_delete(url, **kwargs):
            calls.append(url)
            return _resp(200)

        with patch(DELETE, side_effect=fake_delete):
            self.menu.action_archive()

        self.menu.invalidate_recordset()
        self.assertEqual(self.menu.state, 'archived')
        self.assertFalse(self.menu.line_richmenu_id)
        self.assertEqual(len(calls), 1)
        self.assertIn('richmenu-live-id', calls[0])

    def test_unlink_500_raises_and_record_survives(self):
        menu_id = self.menu.id
        with patch(DELETE, return_value=_resp(500, 'internal error')):
            with self.assertRaises(UserError):
                self.menu.unlink()

        self.assertTrue(self.env['line.richmenu'].browse(menu_id).exists())

    def test_unlink_404_proceeds(self):
        menu_id = self.menu.id
        with patch(DELETE, return_value=_resp(404)):
            self.menu.unlink()

        self.assertFalse(self.env['line.richmenu'].browse(menu_id).exists())

    def test_unlink_200_proceeds_and_delete_url_has_menu_id(self):
        calls = []

        def fake_delete(url, **kwargs):
            calls.append(url)
            return _resp(200)

        menu_id = self.menu.id
        with patch(DELETE, side_effect=fake_delete):
            self.menu.unlink()

        self.assertFalse(self.env['line.richmenu'].browse(menu_id).exists())
        self.assertEqual(len(calls), 1)
        self.assertIn('richmenu-live-id', calls[0])
