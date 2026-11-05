# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_liff_bind_confirmation.py
"""LINE email 對應到既有聯絡人時，要先收信確認才綁定。

修正前：LIFF 登入把 id_token 的 email 當成已驗證的信箱，直接綁定同 email 的
聯絡人並發出對方的 portal session——任何人只要讓自己 LINE 帳號的 email 等於
受害者的 email，就能以受害者身分登入。
"""
import json
import re
import time
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..controllers.liff_sso_policy import STATE_KEY
from ..models.line_liff_config import parse_shop_coordinates
from ..models.line_user import BIND_CONFIRM_TTL, mask_email

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
MOCK_SEND = 'odoo.addons.mail.models.mail_mail.MailMail.send'
LOGIN_CHANNEL = '1234567890'
ATTACKER_UID = 'U' + '9f' * 16
VICTIM_EMAIL = 'victim.customer@example.com'
TOKEN_RE = re.compile(r'/liff/bind/confirm\?token=([0-9a-f.]+)')


def _sent_tokens(env, email):
    mails = env['mail.mail'].sudo().search([('email_to', '=', email)])
    return [m for mail in mails for m in TOKEN_RE.findall(mail.body_html or '')]


@tagged('post_install', '-at_install', 'line_ci')
class TestBindConfirmationToken(TransactionCase):

    def setUp(self):
        super().setUp()
        self.victim = self.env['res.partner'].sudo().create(
            {'name': 'Victim Customer', 'email': VICTIM_EMAIL})
        self.other = self.env['res.partner'].sudo().create(
            {'name': 'Someone Else', 'email': 'someone.else@example.com'})
        self.line_user = self.env['line.user'].sudo().create(
            {'line_user_id': ATTACKER_UID, 'display_name': 'Attacker'})
        patcher = patch(MOCK_SEND, autospec=True, return_value=True)
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self):
        return self.line_user._request_bind_confirmation(self.victim)

    def _token(self):
        tokens = _sent_tokens(self.env, VICTIM_EMAIL)
        self.assertEqual(len(tokens), 1, tokens)
        return tokens[0]

    def test_mail_goes_to_the_existing_partner_and_token_checks_out(self):
        self.assertEqual(self._request(), (True, 'v***@example.com'))
        self.assertFalse(self.line_user.partner_id, 'requesting confirmation must not bind')
        token = self._token()
        self.assertEqual(self.line_user._check_bind_confirmation_token(token),
                         (self.line_user, self.victim))

    def test_resend_is_throttled(self):
        self._request()
        self._request()
        self.assertEqual(len(_sent_tokens(self.env, VICTIM_EMAIL)), 1)

    def test_rejected_tokens(self):
        self._request()
        token = self._token()
        check = self.env['line.user']._check_bind_confirmation_token
        line_id, partner_id, expires, sig = token.split('.')
        forged_sig = ('0' if sig[0] != '0' else '1') + sig[1:]
        for bad in (None, '', 'x', '1.2.3', '.'.join([line_id, partner_id, expires, forged_sig]),
                    '.'.join([line_id, str(self.other.id), expires, sig]),
                    '.'.join([line_id, partner_id, str(int(expires) + 60), sig]),
                    token + 'a' * 300):
            with self.subTest(token=bad):
                self.assertFalse(check(bad)[0])
        self.assertFalse(check(token, now=time.time() + BIND_CONFIRM_TTL + 5)[0], 'expired')

    def test_token_dies_when_partner_email_changes(self):
        self._request()
        token = self._token()
        self.victim.email = 'new-address@example.com'
        self.assertFalse(self.line_user._check_bind_confirmation_token(token)[0])

    def test_token_dies_when_line_user_bound_elsewhere(self):
        self._request()
        token = self._token()
        self.line_user.bind_partner(self.other.id)
        self.assertFalse(self.line_user._check_bind_confirmation_token(token)[0])

    def test_confirm_binds_once(self):
        self._request()
        token = self._token()
        line_user, partner = self.line_user._check_bind_confirmation_token(token)
        line_user._confirm_pending_bind(partner)
        self.assertEqual(self.line_user.partner_id, self.victim)
        self.assertFalse(self.line_user.pending_bind_partner_id)
        self.assertFalse(self.line_user._check_bind_confirmation_token(token)[0],
                         'a used link must not work again')

    def test_staff_contact_gets_no_self_service_mail(self):
        self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Staff', 'login': 'bind_staff_login', 'partner_id': self.victim.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        sent, _hint = self._request()
        self.assertFalse(sent)
        self.assertFalse(_sent_tokens(self.env, VICTIM_EMAIL))
        self.assertFalse(self.line_user.pending_bind_partner_id)

    def test_failed_send_is_reported_and_retryable(self):
        def fail(mails, *args, **kwargs):
            mails.write({'state': 'exception'})
        self.send.side_effect = fail
        sent, _hint = self._request()
        self.assertFalse(sent, 'the page must not claim the mail was sent')
        self.assertFalse(self.line_user.pending_bind_partner_id)

    def test_mask_email(self):
        self.assertEqual(mask_email('abc@example.com'), 'a***@example.com')
        self.assertEqual(mask_email(''), '')
        self.assertEqual(mask_email('not-an-email'), '')


@tagged('post_install', '-at_install', 'line_ci')
class TestBindConfirmationPartnerAlreadyBound(TransactionCase):
    """聯絡人已綁定另一個 LINE 帳號時，不可再走自助確認信綁第二個。"""

    def setUp(self):
        super().setUp()
        patcher = patch(MOCK_SEND, autospec=True, return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        LineUser = self.env['line.user'].sudo()
        # 先到者：上游 woow_line_base 為新 email 建立並綁定聯絡人
        self.first = LineUser.create_or_update_from_liff(
            {'sub': 'U' + 'a1' * 16, 'name': 'First', 'email': VICTIM_EMAIL})
        self.partner = self.first.partner_id
        # 後到者：email 對應到既有聯絡人，維持未綁定
        self.second = LineUser.create_or_update_from_liff(
            {'sub': 'U' + 'b2' * 16, 'name': 'Second', 'email': VICTIM_EMAIL})

    def test_precondition(self):
        self.assertTrue(self.partner)
        self.assertFalse(self.second.partner_id)
        self.assertEqual(self.partner.line_user_ids, self.first)

    def test_no_confirmation_mail_for_partner_bound_to_other_line_user(self):
        sent, hint = self.second._request_bind_confirmation(self.partner)
        self.assertFalse(sent)
        self.assertEqual(hint, 'v***@example.com')
        self.assertFalse(_sent_tokens(self.env, VICTIM_EMAIL))
        self.assertFalse(self.second.pending_bind_partner_id)

    def test_token_issued_before_other_binding_is_rejected(self):
        # 寄信之後才有別的 LINE 帳號綁上來：繞過 request 直接寫入待確認狀態
        self.second.sudo().write({'pending_bind_partner_id': self.partner.id})
        token = self.second._make_bind_confirmation_token(self.partner)
        self.assertEqual(self.env['line.user']._check_bind_confirmation_token(token),
                         (self.env['line.user'].browse(), self.env['res.partner'].browse()))

    def test_confirm_does_not_add_second_binding(self):
        self.second.sudo().write({'pending_bind_partner_id': self.partner.id})
        self.second._confirm_pending_bind(self.partner)
        self.assertEqual(self.partner.line_user_ids, self.first)
        self.assertFalse(self.second.partner_id)
        self.assertFalse(self.second.pending_bind_partner_id)

    def test_unbound_partner_still_gets_mail_and_binds(self):
        """正向對照：聯絡人沒綁任何 LINE 帳號時，流程與修正前相同。"""
        free = self.env['res.partner'].sudo().create(
            {'name': 'Free Customer', 'email': 'free.customer@example.com'})
        sent, _hint = self.second._request_bind_confirmation(free)
        self.assertTrue(sent)
        token = _sent_tokens(self.env, 'free.customer@example.com')[0]
        line_user, partner = self.second._check_bind_confirmation_token(token)
        self.assertEqual((line_user, partner), (self.second, free))
        line_user._confirm_pending_bind(partner)
        self.assertEqual(free.line_user_ids, self.second)

    def test_same_line_user_may_reconfirm_its_own_partner(self):
        """正向對照：已綁定本人的聯絡人不算「綁定給別人」。"""
        sent, _hint = self.first._request_bind_confirmation(self.partner)
        self.assertTrue(sent)


@tagged('post_install', '-at_install', 'line_ci')
class TestBindConfirmationOverHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.login_channel_id', LOGIN_CHANNEL)
        self.victim = self.env['res.partner'].sudo().create(
            {'name': 'Victim Customer', 'email': VICTIM_EMAIL})
        self.victim_user = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Victim Customer', 'login': 'victim_portal_login',
            'password': 'victim-portal-password', 'partner_id': self.victim.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        patcher = patch(MOCK_SEND, autospec=True, return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _line_returns_victim_email(*args, **kwargs):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'sub': ATTACKER_UID, 'name': 'Attacker', 'aud': LOGIN_CHANNEL, 'email': VICTIM_EMAIL}
        return resp

    def _session_uid(self):
        self.env.flush_all()
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {}}
        response = self.url_open('/web/session/get_session_info', data=json.dumps(payload),
                                 headers={'Content-Type': 'application/json'})
        return (response.json().get('result') or {}).get('uid')

    def _login_state(self, target='home'):
        page = self.url_open('/liff/redirect/' + target, allow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text[:200])
        state = re.search(r'var loginState="([A-Za-z0-9_-]{43})"', page.text).group(1)
        from odoo.http import root
        sid = page.cookies.get('session_id') or self.opener.cookies.get('session_id')
        self.assertIn(state, root.session_store.get(sid).get(STATE_KEY, {}))
        self.opener.cookies.set('session_id', sid)
        return state

    def _liff_login(self):
        state = self._login_state('home')
        with patch(MOCK_POST, side_effect=self._line_returns_victim_email):
            return self.url_open('/liff/redirect/home',
                                 data={'id_token': 'fake-id-token', 'login_state': state},
                                 allow_redirects=False)

    def _line_user(self):
        return self.env['line.user'].sudo().search([('line_user_id', '=', ATTACKER_UID)])

    def test_email_claim_does_not_log_in_as_the_existing_customer(self):
        response = self._liff_login()
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertIn('v***@example.com', response.text)
        self.assertNotEqual(self._session_uid(), self.victim_user.id)
        self.assertFalse(self._line_user().partner_id)
        self.assertEqual(len(_sent_tokens(self.env, VICTIM_EMAIL)), 1)

    def test_link_get_does_not_bind_post_with_csrf_does(self):
        self._liff_login()
        token = _sent_tokens(self.env, VICTIM_EMAIL)[0]

        page = self.url_open('/liff/bind/confirm?token=' + quote(token))
        self.assertEqual(page.status_code, 200, page.text[:300])
        self.assertFalse(self._line_user().partner_id,
                         'opening the link (mail scanners do) must not bind')

        no_csrf = self.url_open('/liff/bind/confirm', data={'token': token})
        self.assertNotEqual(no_csrf.status_code, 200)
        self.assertFalse(self._line_user().partner_id)

        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        done = self.url_open('/liff/bind/confirm', data={'token': token, 'csrf_token': csrf})
        self.assertEqual(done.status_code, 200, done.text[:300])
        self.assertIn('綁定完成', done.text)
        self.assertEqual(self._line_user().partner_id, self.victim)

        # 確認之後，從 LINE 重新開啟才以這份會員資料登入
        response = self._liff_login()
        self.assertIn(response.status_code, (302, 303), response.text[:300])
        self.opener.cookies.set('session_id', response.cookies.get('session_id'))
        self.assertEqual(self._session_uid(), self.victim_user.id)

    def test_invalid_link(self):
        page = self.url_open('/liff/bind/confirm?token=1.2.3.deadbeef')
        self.assertEqual(page.status_code, 400)
        self.assertIn('連結無效', page.text)

    def _api_bind(self, email):
        def line_ok(*args, **kwargs):
            resp = MagicMock(status_code=200)
            resp.json.return_value = {'sub': ATTACKER_UID, 'name': 'Attacker',
                                      'aud': LOGIN_CHANNEL, 'email': email}
            return resp
        with patch(MOCK_POST, side_effect=line_ok):
            return self.url_open('/api/line/bind', data=json.dumps({'id_token': 'fake-id-token'}),
                                 headers={'Content-Type': 'application/json'})

    def test_api_bind_existing_email_sends_confirmation_without_leaking(self):
        response = self._api_bind(VICTIM_EMAIL)
        self.assertEqual(response.status_code, 202, response.text[:300])
        body = response.json()
        self.assertEqual(body, {'status': 'confirmation_sent', 'email_hint': 'v***@example.com'})
        self.assertNotIn('Victim', response.text)
        self.assertFalse(self._line_user().partner_id)
        self.assertEqual(len(_sent_tokens(self.env, VICTIM_EMAIL)), 1)

    def test_api_bind_new_email_creates_contact(self):
        response = self._api_bind('brand-new@example.com')
        self.assertEqual(response.status_code, 200, response.text[:300])
        # woow_line_base 在驗證 LINE 用戶時就已為新 email 建立並綁定聯絡人
        self.assertEqual(response.json()['status'], 'already_bound')
        self.assertEqual(self._line_user().partner_id.email, 'brand-new@example.com')

    def test_confirm_post_refused_when_partner_bound_to_other_line_user(self):
        other = self.env['line.user'].sudo().create(
            {'line_user_id': 'U' + 'c3' * 16, 'display_name': 'Earlier'})
        self._liff_login()
        token = _sent_tokens(self.env, VICTIM_EMAIL)[0]
        # 寄信之後，聯絡人被另一個 LINE 帳號綁走
        other.bind_partner(self.victim.id)
        page = self.url_open('/liff/bind/confirm?token=' + quote(token))
        self.assertEqual(page.status_code, 400, page.text[:300])
        self.assertIn('連結無效', page.text)
        self.assertFalse(self._line_user().partner_id)
        self.assertEqual(self.victim.line_user_ids, other)

    def test_liff_login_with_partner_bound_to_other_line_user_asks_for_store(self):
        other = self.env['line.user'].sudo().create(
            {'line_user_id': 'U' + 'c3' * 16, 'display_name': 'Earlier'})
        other.bind_partner(self.victim.id)
        response = self._liff_login()
        self.assertEqual(response.status_code, 409, response.text[:300])
        self.assertFalse(_sent_tokens(self.env, VICTIM_EMAIL))
        self.assertFalse(self._line_user().partner_id)
        self.assertNotEqual(self._session_uid(), self.victim_user.id)


@tagged('post_install', '-at_install', 'line_ci')
class TestShopCoordinates(TransactionCase):

    def test_parse(self):
        self.assertEqual(parse_shop_coordinates('25.03', '121.56'), (25.03, 121.56))
        for bad in (('1;alert(1)', '121'), ('25', 'x'), ('nan', '1'), ('inf', '1'),
                    ('91', '1'), ('1', '181'), ('', ''), (None, None), ('1', '')):
            self.assertIsNone(parse_shop_coordinates(*bad), bad)

    def test_config_rejects_non_numeric_coordinates(self):
        config = self.env['line.liff.config'].sudo().create({'name': 'coordinate check'})
        config.write({'shop_latitude': '25.03', 'shop_longitude': '121.56'})
        with self.assertRaises(ValidationError):
            config.write({'shop_latitude': '25.03,alert(1)'})


@tagged('post_install', '-at_install', 'line_ci')
class TestPublicPageOutput(HttpCase):

    def test_locations_page_is_removed(self):
        # 18.0.3.5.0: the store-locations page (Leaflet + OpenStreetMap tiles) was removed
        self.assertEqual(self.url_open('/liff/locations').status_code, 404)

    def test_debug_page_encodes_liff_id(self):
        value = "x';alert(1)//</script>"
        self.env['ir.config_parameter'].sudo().set_param('woow_odoo_line_liff.liff_id_member', value)
        page = self.url_open('/liff/debug')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("liffId: '" + value, page.text)
        self.assertNotIn('</script>\';', page.text)
        self.assertIn('var liffId = ' + json.dumps(value).replace('</', '<\\/'), page.text)
