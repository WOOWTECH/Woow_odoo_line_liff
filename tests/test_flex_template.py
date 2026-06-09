# -*- coding: utf-8 -*-
# woow_line_bridge/tests/test_flex_template.py
# Flex Message 模板結構驗證
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase


class TestFlexTemplate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.tmpl = self.env['line.flex.template']
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_bridge.shop_name', 'Test Studio')
        ICP.set_param('woow_line_bridge.liff_id_member', '1234-test')
        ICP.set_param('woow_line_bridge.shop_latitude', '25.0330')
        ICP.set_param('woow_line_bridge.shop_longitude', '121.5654')

    def _validate_bubble(self, flex):
        """驗證基本 bubble 結構"""
        self.assertEqual(flex['type'], 'bubble')
        self.assertIn('header', flex)
        self.assertIn('body', flex)
        self.assertEqual(flex['header']['type'], 'box')
        self.assertEqual(flex['body']['type'], 'box')

    def _get_accent_color(self, flex):
        """取得 header accent strip 的顏色"""
        return flex['header']['contents'][0]['backgroundColor']

    def test_build_welcome_structure(self):
        result = self.tmpl.build_welcome('TestUser')
        self._validate_bubble(result)
        # 驗證 header accent strip 使用 STATUS_INFO
        self.assertEqual(self._get_accent_color(result), '#3B82F6')

    def test_build_welcome_empty_name(self):
        result = self.tmpl.build_welcome('')
        self._validate_bubble(result)
        body_texts = [c['text'] for c in result['body']['contents'] if c.get('type') == 'text']
        self.assertTrue(any('您好' in t for t in body_texts))

    def test_build_booking_confirmed_structure(self):
        booking = MagicMock()
        booking.name = 'BK001'
        booking.id = 1
        booking.start_datetime = None
        booking.appointment_type_id.name = 'Test Service'
        booking.staff_user_id = False
        result = self.tmpl.build_booking_confirmed(booking)
        self._validate_bubble(result)
        self.assertIn('footer', result)
        # 驗證有 action buttons
        footer_contents = result['footer']['contents']
        self.assertTrue(len(footer_contents) >= 2)

    def test_build_booking_cancelled_structure(self):
        booking = MagicMock()
        booking.name = 'BK002'
        booking.start_datetime = None
        booking.appointment_type_id.name = 'Test Service'
        result = self.tmpl.build_booking_cancelled(booking)
        self._validate_bubble(result)
        # 驗證紅色 accent strip (STATUS_ERROR)
        self.assertEqual(self._get_accent_color(result), '#EF4444')

    def test_build_booking_cancelled_with_reason(self):
        booking = MagicMock()
        booking.name = 'BK003'
        booking.start_datetime = None
        booking.appointment_type_id.name = 'Test Service'
        result = self.tmpl.build_booking_cancelled(booking, reason='客戶要求')
        body_contents = result['body']['contents']
        # 有取消原因的 info_row
        has_reason = any(
            c.get('type') == 'box' and
            any(sub.get('text', '').startswith('取消原因') for sub in c.get('contents', []) if sub.get('type') == 'text')
            for c in body_contents
        )
        self.assertTrue(has_reason)

    def test_build_booking_reminder_with_nav(self):
        booking = MagicMock()
        booking.name = 'BK004'
        booking.id = 4
        booking.start_datetime = None
        booking.appointment_type_id.name = 'Test Service'
        result = self.tmpl.build_booking_reminder(booking, hours_before=24)
        self._validate_bubble(result)
        # 有 Google Maps 導航按鈕（因 lat/lng 已設定）
        footer_contents = result['footer']['contents']
        nav_buttons = [b for b in footer_contents if 'Google' in b.get('action', {}).get('label', '')]
        self.assertTrue(len(nav_buttons) >= 1)

    def test_build_booking_payment_required_structure(self):
        booking = MagicMock()
        booking.name = 'BK005'
        booking.id = 5
        booking.start_datetime = None
        booking.appointment_type_id.name = 'Test Service'
        result = self.tmpl.build_booking_payment_required(booking, payment_url='https://pay.example.com')
        self._validate_bubble(result)
        # 橙色 accent strip (STATUS_WARNING)
        self.assertEqual(self._get_accent_color(result), '#F59E0B')
        # 有付款按鈕
        footer_contents = result['footer']['contents']
        pay_buttons = [b for b in footer_contents if '付款' in b.get('action', {}).get('label', '')]
        self.assertTrue(len(pay_buttons) >= 1)

    def test_build_news_card_structure(self):
        news = MagicMock()
        news.id = 1
        news.title = '測試新聞'
        news.summary = '這是摘要'
        news.image = None
        result = self.tmpl.build_news_card(news)
        self._validate_bubble(result)
        self.assertIn('footer', result)
        # 沒有 hero（因為沒圖片）
        self.assertNotIn('hero', result)

    def test_build_news_card_with_binary_image(self):
        news = MagicMock()
        news.id = 2
        news.title = '有圖新聞'
        news.summary = ''
        news.image = b'\x89PNG'
        result = self.tmpl.build_news_card(news)
        self.assertIn('hero', result)
        self.assertIn('/liff/news/image/2', result['hero']['url'])
        self.assertTrue(result['hero']['url'].startswith('https://'))
