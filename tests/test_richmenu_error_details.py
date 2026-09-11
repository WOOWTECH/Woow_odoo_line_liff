# -*- coding: utf-8 -*-
"""When LINE rejects a rich menu, the operator must see which button and why.

The error used to show only LINE's summary line ("The request body has 2
error(s)"), which does not say which of the six buttons is wrong, and a
rejected image showed a generic sentence with LINE's reason thrown away.

LINE_REJECTION below is LINE's real response body, captured on komibright on
2026-09-11 by sending a menu whose 3rd area had width 0 and whose 6th area had
an invalid URL.
"""
import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
MOCK_DELETE = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.delete'
TINY_PNG = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8Dw'
            'HwAFBQIAX8jx0gAAAABJRU5ErkJggg==')
LINE_REJECTION = {
    'message': 'The request body has 3 error(s)',
    'details': [
        {'message': 'Must be greater than or equal to 1', 'property': 'areas[2].bounds.width'},
        {'message': 'invalid uri scheme', 'property': 'areas[5].action.uri'},
        {'message': 'invalid uri', 'property': 'areas[5].action.uri'},
    ],
}
LABELS = ['產品系列', '最新消息', '安裝案例', '會員中心', '購物車', '聯絡我們']


def _line_response(status, body):
    text = json.dumps(body)
    return MagicMock(status_code=status, text=text, json=lambda: json.loads(text))


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuErrorsNameTheButton(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_access_token', 'test_token')
        self.menu = self.env['line.richmenu'].create({
            'name': 'Error details test', 'size': 'full', 'image': TINY_PNG,
            'image_filename': 'menu.png',
            'area_ids': [
                (0, 0, {'sequence': (i + 1) * 10, 'label': label,
                        'x': (i % 3) * 833, 'y': (i // 3) * 843, 'width': 833, 'height': 843,
                        'action_type': 'uri', 'action_value': 'https://example.com/'})
                for i, label in enumerate(LABELS)
            ],
        })

    def test_a_rejected_menu_names_each_button_line_complained_about(self):
        with patch(MOCK_POST, return_value=_line_response(400, LINE_REJECTION)):
            with self.assertRaises(UserError) as caught:
                self.menu.action_create_on_line()
        message = str(caught.exception)
        self.assertIn('第 6 格「聯絡我們」', message)
        self.assertIn('invalid uri', message)
        self.assertIn('第 3 格「安裝案例」', message)
        self.assertIn('Must be greater than or equal to 1', message)
        self.assertIn('400', message)

    def test_a_rejected_image_shows_lines_reason(self):
        def line_answers(url, **kwargs):
            if url.endswith('/content'):
                return _line_response(400, {'message': 'Image size must be 2500x1686 or 2500x843'})
            return _line_response(200, {'richMenuId': 'richmenu-e2e-new'})

        with patch(MOCK_POST, side_effect=line_answers), \
                patch(MOCK_DELETE, return_value=_line_response(200, {})) as delete:
            with self.assertRaises(UserError) as caught:
                self.menu.action_create_on_line()
        message = str(caught.exception)
        self.assertIn('Image size must be 2500x1686 or 2500x843', message)
        self.assertIn('400', message)
        self.assertIn('richmenu-e2e-new', delete.call_args.args[0],
                      'the half-built menu must still be removed from LINE')

    def test_a_rejection_without_details_still_shows_lines_summary(self):
        with patch(MOCK_POST, return_value=_line_response(400, {'message': 'Invalid request'})):
            with self.assertRaises(UserError) as caught:
                self.menu.action_create_on_line()
        self.assertIn('Invalid request', str(caught.exception))
