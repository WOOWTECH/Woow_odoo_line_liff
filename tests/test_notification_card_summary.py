# -*- coding: utf-8 -*-
"""H-17: the automatic LINE notification card must never paste the email text.

When a notification had no tracking values, the card took the whole email
Odoo had just rendered, stripped the tags and pushed the first 100
characters. Customers therefore received email prose, usually in English and
cut mid-sentence. Reproduced live on komibright on 2026-09-12:
  calendar invitation -> "Hello 孟緯 Elmo, Administrator invited you for the …
                          meeting. View 星期二 15 9月 2026 下午"
  quotation by email  -> "Hello, Your quotation S00126 amounting in NT$ 28,000
                          is ready for review. Do not hesitate to contact"
and received by a real markstudio customer on 2026-09-06. The card is now a
Chinese summary built from the record itself.
"""
import json
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
CUSTOMER_UID = 'U' + 'c' * 32
EMAIL_PROSE = ('Hello', 'invited you', 'Your quotation', 'ready for review',
               'Do not hesitate')


@tagged('post_install', '-at_install', 'line_ci')
class TestNotificationCardSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.auto_line_notify', 'True')
        ICP.set_param('woow_line_base.messaging_access_token', 'test_token')
        cls.customer = cls.env['res.partner'].create({
            'name': '王小明', 'email': 'customer@example.com', 'tz': 'Asia/Taipei'})
        cls.env['line.user'].create({
            'line_user_id': CUSTOMER_UID, 'display_name': '王小明',
            'partner_id': cls.customer.id, 'is_follower': True,
            'is_blocked': False, 'notification_enabled': True,
        })

    def _cards_pushed_to_the_customer(self, mock_post):
        cards = []
        for call in mock_post.call_args_list:
            payload = call.kwargs.get('json') or {}
            if payload.get('to') == CUSTOMER_UID:
                cards.extend(json.dumps(m, ensure_ascii=False) for m in payload.get('messages', []))
        return cards

    def _assert_no_email_prose(self, card):
        for phrase in EMAIL_PROSE:
            self.assertNotIn(phrase, card, f'the card must not copy the email text ({phrase!r})')

    def test_a_message_card_does_not_copy_the_message_text(self):
        with patch(MOCK_POST, return_value=MagicMock(status_code=200, text='{}')) as post:
            self.customer.message_post(
                body='<p>Hello 王小明, your document is ready for review. '
                     'Do not hesitate to contact us.</p>',
                partner_ids=self.customer.ids, message_type='comment',
                subtype_xmlid='mail.mt_comment')
        cards = self._cards_pushed_to_the_customer(post)
        self.assertEqual(len(cards), 1, 'the customer is notified once')
        self._assert_no_email_prose(cards[0])
        self.assertIn('王小明', cards[0], 'the card names the record it is about')
        self.assertIn('查看詳情', cards[0])

    def test_a_calendar_invitation_card_is_a_chinese_summary(self):
        if 'calendar.event' not in self.env:
            self.skipTest('calendar is not installed in this database')
        with patch(MOCK_POST, return_value=MagicMock(status_code=200, text='{}')) as post:
            self.env['calendar.event'].create({
                'name': '筋膜整復 60 分',
                'start': '2026-09-15 08:00:00', 'stop': '2026-09-15 09:00:00',
                'partner_ids': [(6, 0, self.customer.ids)],
            })
        cards = self._cards_pushed_to_the_customer(post)
        self.assertEqual(len(cards), 1, 'one invitation card for the customer')
        self._assert_no_email_prose(cards[0])
        self.assertIn('活動邀請', cards[0])
        self.assertIn('9/15（二）16:00', cards[0], 'time in the customer’s time zone')
        self.assertIn('筋膜整復 60 分', cards[0])

    def test_a_quotation_email_card_shows_the_quotation_and_its_amount(self):
        if 'sale.order' not in self.env:
            self.skipTest('sale is not installed in this database')
        product = self.env['product.product'].create({'name': 'A95R 淨水器', 'list_price': 28000})
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1,
                                   'price_unit': 28000, 'tax_id': [(6, 0, [])]})],
        })
        template = self.env.ref('sale.email_template_edi_sale')
        with patch(MOCK_POST, return_value=MagicMock(status_code=200, text='{}')) as post:
            composer = self.env['mail.compose.message'].with_context(
                default_model='sale.order', default_res_ids=order.ids,
                default_composition_mode='comment', default_template_id=template.id,
                mark_so_as_sent=True, force_email=True,
            ).create({})
            composer.action_send_mail()
        cards = self._cards_pushed_to_the_customer(post)
        self.assertTrue(cards, 'sending the quotation notifies the customer on LINE')
        for card in cards:
            self._assert_no_email_prose(card)
        self.assertTrue(any(f'報價單 {order.name}' in card for card in cards),
                        f'a card titled 報價單 {order.name}: {cards}')
        self.assertTrue(any('28,000' in card for card in cards), 'the card shows the amount')
