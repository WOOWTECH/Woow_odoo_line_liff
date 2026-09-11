# -*- coding: utf-8 -*-
"""Rich menu tap areas must stay inside the menu image.

LINE's API does not validate this: an area placed partly outside the image is
accepted and published, and that button simply cannot be tapped. On
2026-09-11 an area at x=2600 on a 2500-wide menu went live on komibright and
its 「聯絡我們」 button was unreachable until the menu was re-uploaded.
"""
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

SIX_BUTTON_GRID = [
    # (label, x, y, width, height) — the layout the tenants use today
    ('產品系列', 0, 0, 833, 843),
    ('最新消息', 833, 0, 834, 843),
    ('安裝案例', 1667, 0, 833, 843),
    ('會員中心', 0, 843, 833, 843),
    ('購物車', 833, 843, 834, 843),
    ('聯絡我們', 1667, 843, 833, 843),
]


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuAreasStayInsideTheImage(TransactionCase):

    def _menu(self):
        return self.env['line.richmenu'].create({
            'name': 'Bounds test', 'size': 'full',
            'area_ids': [
                (0, 0, {'sequence': (i + 1) * 10, 'label': label, 'x': x, 'y': y,
                        'width': w, 'height': h, 'action_type': 'uri',
                        'action_value': 'https://example.com/'})
                for i, (label, x, y, w, h) in enumerate(SIX_BUTTON_GRID)
            ],
        })

    def _area(self, menu, label):
        return menu.area_ids.filtered(lambda a: a.label == label)

    def test_the_standard_six_button_layout_is_accepted(self):
        menu = self._menu()
        self.assertEqual(len(menu.area_ids), 6)

    def test_an_area_past_the_right_edge_is_rejected_and_named(self):
        menu = self._menu()
        with self.assertRaises(ValidationError) as caught:
            self._area(menu, '聯絡我們').write({'x': 2600})
        message = str(caught.exception)
        self.assertIn('聯絡我們', message)
        self.assertIn('3433', message)   # 2600 + 833
        self.assertIn('2500', message)   # menu width

    def test_an_area_past_the_bottom_edge_is_rejected(self):
        menu = self._menu()
        with self.assertRaises(ValidationError) as caught:
            self._area(menu, '聯絡我們').write({'y': 1000})
        message = str(caught.exception)
        self.assertIn('1843', message)   # 1000 + 843
        self.assertIn('1686', message)   # menu height

    def test_an_area_with_no_width_is_rejected(self):
        menu = self._menu()
        with self.assertRaises(ValidationError):
            self._area(menu, '購物車').write({'width': 0})

    def test_switching_to_the_short_menu_rechecks_every_area(self):
        menu = self._menu()
        with self.assertRaises(ValidationError) as caught:
            menu.write({'size': 'compact'})   # 2500 × 843: the bottom row no longer fits
        self.assertIn('843', str(caught.exception))
