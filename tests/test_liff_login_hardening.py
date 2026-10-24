# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_liff_login_hardening.py
"""LIFF 登入強化（woow_paas_platform#1831：合併自 markstudio 站上 18.0.3.2.6 並通用化）。

- 中間頁發一次性 login_state，POST 必須帶回同一個值且只能用一次。
- 內部 SSO、後台 target、預約銜接都由 ir.config_parameter 驅動；
  沒設定的站點，Rich Menu 的自訂路徑照舊可用。
"""
import json
import re
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, TransactionCase, tagged

from ..controllers import liff_redirect as liff_redirect_module
from ..controllers.liff_redirect import LiffRedirectController
from ..controllers.liff_sso_policy import (
    ADMIN_TARGETS_PARAM, BINDING_PARAM, BOOKING_INTENT_KEY_PARAM, BOOKING_RESUME_PATH_PARAM,
    STATE_KEY,
    allowed_target, binding_for_claims, consume_challenge, is_safe_local_path,
    issue_challenge, parse_admin_targets, parse_booking_resume,
)

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
LOGIN_CHANNEL = '1234567890'
LINE_UID = 'U' + '0123abcd' * 4


@contextmanager
def bound_request(env, session=None):
    """只帶 env 的 request stub，讓 controller 的決策邏輯可在 TransactionCase 測。"""
    class _Req:
        pass
    stub = _Req()
    stub.env = env
    stub.session = session
    stub.make_response = lambda body, headers=None: body
    with patch.object(liff_redirect_module, 'request', stub):
        yield stub


@tagged('post_install', '-at_install', 'line_ci')
class TestTargetPolicy(TransactionCase):

    def test_rich_menu_paths_of_other_sites_still_allowed(self):
        """markstudio 原版只認固定清單，會讓其他站自訂的 Rich Menu 路徑 404。"""
        for good in list(LiffRedirectController.REDIRECT_TARGETS) + [
                'booking/42', 'shop', 'contactus', 'odoo/action-813',
                'my/orders/7', 'appointment/3', 'admin-bookings']:
            self.assertTrue(allowed_target(good), good)

    def test_unsafe_targets_rejected(self):
        for bad in ('', None, 42, '/my/home', 'my/', 'a//b', '../x', 'x/../y',
                    'book?x=1', '</script>', 'https://evil.example.com',
                    '//evil.example.com', 'x' * 65):
            self.assertFalse(allowed_target(bad), repr(bad))

    def test_safe_local_path(self):
        for good in ('/odoo/action-813', '/my/home', '/appointment/booking/resume'):
            self.assertTrue(is_safe_local_path(good), good)
        for bad in ('', 'odoo', '//evil.example.com', '/\\evil', '/a\nb', '/a\x7fb',
                    'https://evil.example.com', None, '/' + 'x' * 600):
            self.assertFalse(is_safe_local_path(bad), repr(bad))

    def test_admin_targets_parse(self):
        self.assertEqual(parse_admin_targets(''), {})
        self.assertEqual(parse_admin_targets('not json'), {})
        self.assertEqual(parse_admin_targets('[]'), {})
        self.assertEqual(parse_admin_targets('{"a": "/odoo/action-1"}'), {'a': '/odoo/action-1'})
        self.assertEqual(parse_admin_targets(
            '{"home": "/odoo"}', reserved_targets=LiffRedirectController.REDIRECT_TARGETS), {},
                         'the member home target must never be configured as an internal target')
        # 任一筆不合法 ⇒ 整份視為未設定，不做部分採用
        self.assertEqual(parse_admin_targets(
            '{"a": "/odoo/action-1", "b": "//evil.example.com"}'), {})
        self.assertEqual(parse_admin_targets('{"a/b": "/odoo"}'), {})

    def test_booking_resume_needs_both_values(self):
        self.assertEqual(parse_booking_resume('', ''), (None, None))
        self.assertEqual(parse_booking_resume('/appointment/booking/resume', ''), (None, None))
        self.assertEqual(parse_booking_resume('', 'reservation_module.booking_intents'), (None, None))
        self.assertEqual(parse_booking_resume('/r?x=1', 'k'), (None, None))
        self.assertEqual(
            parse_booking_resume('/appointment/booking/resume', 'reservation_module.booking_intents'),
            ('/appointment/booking/resume', 'reservation_module.booking_intents'))


@tagged('post_install', '-at_install', 'line_ci')
class TestLoginChallenge(TransactionCase):

    def test_challenge_is_single_use_and_bound(self):
        session, now = {}, time.time()
        nonce = issue_challenge(session, 'home', None, now, 5)
        self.assertFalse(consume_challenge(session, nonce, 'orders', None, now, 5),
                         'target 不同不可通過')
        nonce = issue_challenge(session, 'home', None, now, 5)
        self.assertFalse(consume_challenge(session, nonce, 'home', None, now, 6),
                         'config 不同不可通過')
        nonce = issue_challenge(session, 'home', None, now, 5)
        self.assertTrue(consume_challenge(session, nonce, 'home', None, now, 5))
        self.assertFalse(consume_challenge(session, nonce, 'home', None, now, 5),
                         '同一個 login_state 只能用一次')

    def test_challenge_expires(self):
        session, now = {}, time.time()
        nonce = issue_challenge(session, 'home', None, now, False)
        self.assertFalse(consume_challenge(session, nonce, 'home', None, now + 601, False))

    def test_site_without_config_record(self):
        """沒有 line.liff.config 的站點 config_id 為 False，仍要能登入。"""
        session, now = {}, time.time()
        nonce = issue_challenge(session, 'home', None, now, False)
        self.assertTrue(consume_challenge(session, nonce, 'home', None, now, False))

    def test_book_bridge_keeps_only_the_requested_booking_draft(self):
        """Clearing a previous login must not discard the selected booking draft."""
        class Session(dict):
            uid = 42

            def logout(self, keep_db=False):
                self.clear()
                self.uid = None

        key = 'liff_test.booking_intents'
        nonce = 'n' * 40
        other_nonce = 'x' * 40
        selected = {'slot_id': 7}
        session = Session({
            key: {nonce: selected, other_nonce: {'slot_id': 8}},
            'previous_account_data': 'must be cleared',
        })
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(BOOKING_RESUME_PATH_PARAM, '/appointment/booking/resume')
        ICP.set_param(BOOKING_INTENT_KEY_PARAM, key)

        with bound_request(self.env, session):
            LiffRedirectController()._render_liff_bridge_page('book', booking_nonce=nonce)

        self.assertIsNone(session.uid)
        self.assertNotIn('previous_account_data', session)
        self.assertEqual(session.get(key), {nonce: selected})


@tagged('post_install', '-at_install', 'line_ci')
class TestInternalSsoBinding(TransactionCase):

    def _payload(self, **kw):
        payload = {'sub': LINE_UID, 'aud': LOGIN_CHANNEL, 'iss': 'https://access.line.me',
                   'exp': time.time() + 300}
        payload.update(kw)
        return payload

    def _row(self, **kw):
        row = {'subject': LINE_UID, 'enabled': True, 'config_id': 3,
               'login_channel_id': LOGIN_CHANNEL, 'line_user_id': 1, 'partner_id': 2, 'user_id': 4}
        row.update(kw)
        return row

    def test_unbound_identity_is_not_internal(self):
        self.assertIsNone(binding_for_claims('[]', self._payload(), True, 3, LOGIN_CHANNEL, time.time()))
        self.assertIsNone(binding_for_claims('', self._payload(), True, 3, LOGIN_CHANNEL, time.time()))

    def test_valid_binding(self):
        raw = json.dumps([self._row()])
        self.assertEqual(binding_for_claims(raw, self._payload(), True, 3, LOGIN_CHANNEL, time.time())['user_id'], 4)

    def test_bound_identity_fails_closed(self):
        now = time.time()
        cases = [
            (json.dumps([self._row(enabled=False)]), self._payload(), True, 3),
            (json.dumps([self._row()]), self._payload(), False, 3),          # 只過 access token
            (json.dumps([self._row()]), self._payload(aud='999'), True, 3),
            (json.dumps([self._row()]), self._payload(exp=now - 1), True, 3),
            (json.dumps([self._row()]), self._payload(), True, False),        # 站點沒有 config
            (json.dumps([self._row(), self._row()]), self._payload(), True, 3),
            ('{bad json', self._payload(), True, 3),
        ]
        for raw, payload, verified, config_id in cases:
            with self.assertRaises(ValueError):
                binding_for_claims(raw, payload, verified, config_id, LOGIN_CHANNEL, now)


@tagged('post_install', '-at_install', 'line_ci')
class TestRedirectUrlConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        self.ctrl = LiffRedirectController()
        self.ICP = self.env['ir.config_parameter'].sudo()

    def test_default_site_keeps_github_main_behaviour(self):
        with bound_request(self.env):
            self.assertEqual(self.ctrl._get_redirect_url('orders', {}), '/my/orders')
            self.assertEqual(self.ctrl._get_redirect_url('booking/42', {}), '/my/ext-bookings/42')
            self.assertEqual(self.ctrl._get_redirect_url('odoo/action-813', {}), '/odoo/action-813')
            self.assertEqual(self.ctrl._get_redirect_url('shop/category/1', {}), '/shop/category/1')
            # 沒設定後台 target 時，同名 target 不會被當成後台入口
            self.assertEqual(self.ctrl._get_redirect_url('admin-bookings', {}), '/odoo')
            # 沒設定預約銜接時，booking_nonce 不影響 book 的去向
            self.assertEqual(
                self.ctrl._get_redirect_url('book', {'booking_nonce': 'n' * 40}),
                self.ctrl._get_redirect_url('book', {}))

    def test_admin_targets_from_config(self):
        self.ICP.set_param(ADMIN_TARGETS_PARAM, json.dumps({'admin-bookings': '/odoo/action-813'}))
        with bound_request(self.env):
            self.assertEqual(self.ctrl._get_redirect_url('admin-bookings', {}), '/odoo/action-813')

    def test_booking_resume_from_config(self):
        self.ICP.set_param(BOOKING_RESUME_PATH_PARAM, '/appointment/booking/resume')
        self.ICP.set_param(BOOKING_INTENT_KEY_PARAM, 'reservation_module.booking_intents')
        nonce = 'n' * 40
        with bound_request(self.env):
            self.assertEqual(self.ctrl._get_redirect_url('book', {'booking_nonce': nonce}),
                             '/appointment/booking/resume?booking_nonce=' + nonce)
            # nonce 格式不對就忽略
            self.assertNotIn('booking_nonce', self.ctrl._get_redirect_url('book', {'booking_nonce': 'x'}))

    def test_login_channel_falls_back_to_global_param(self):
        self.ICP.set_param('woow_line_base.login_channel_id', LOGIN_CHANNEL)
        with bound_request(self.env):
            self.assertEqual(self.ctrl._get_login_channel_id(self.env['line.liff.config'].browse()),
                             LOGIN_CHANNEL)


@tagged('post_install', '-at_install', 'line_ci')
class TestLoginStateOverHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.login_channel_id', LOGIN_CHANNEL)

    @staticmethod
    def _line_accepts(*args, **kwargs):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'sub': LINE_UID, 'name': 'LIFF 客人', 'aud': LOGIN_CHANNEL}
        return resp

    @staticmethod
    def _line_accepts_bound_staff(*args, **kwargs):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'sub': LINE_UID, 'name': 'LIFF staff member', 'aud': LOGIN_CHANNEL,
            'iss': 'https://access.line.me', 'exp': int(time.time()) + 300,
        }
        return resp

    def _session_uid(self):
        self.env.flush_all()
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {}}
        response = self.url_open(
            '/web/session/get_session_info', data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
        )
        return (response.json().get('result') or {}).get('uid')

    def _adopt_rotated_cookie(self, response):
        sid = response.cookies.get('session_id')
        self.assertTrue(sid, 'LIFF login must rotate the Odoo session cookie')
        self.opener.cookies.set('session_id', sid)

    def _bound_staff_accounts(self):
        """One LINE identity and partner with separate staff and portal users."""
        Config = self.env['line.liff.config'].sudo()
        config = Config._get_default_config()
        if not config:
            config = Config.create({'name': 'LIFF session test'})
        config.write({'login_channel_id': LOGIN_CHANNEL})

        partner = self.env['res.partner'].sudo().create({'name': 'LIFF dual account member'})
        Users = self.env['res.users'].sudo().with_context(no_reset_password=True)
        staff = Users.create({
            'name': 'LIFF staff member', 'login': 'liff_session_staff',
            'password': 'liff-staff-test-password', 'partner_id': partner.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        portal = Users.create({
            'name': 'LIFF portal member', 'login': 'liff_session_portal',
            'password': 'liff-portal-test-password', 'partner_id': partner.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        line_user = self.env['line.user'].sudo().create({
            'line_user_id': LINE_UID, 'display_name': 'LIFF staff member',
            'partner_id': partner.id, 'liff_config_id': config.id,
        })
        self.env['ir.config_parameter'].sudo().set_param(BINDING_PARAM, json.dumps([{
            'subject': LINE_UID, 'enabled': True, 'config_id': config.id,
            'login_channel_id': LOGIN_CHANNEL, 'line_user_id': line_user.id,
            'partner_id': partner.id, 'user_id': staff.id,
        }]))
        self.env['ir.config_parameter'].sudo().set_param(
            ADMIN_TARGETS_PARAM, json.dumps({'staff-dashboard': '/odoo'}))
        self.env.flush_all()
        return staff, portal

    def _login_state(self, target='home'):
        page = self.url_open('/liff/redirect/' + target, allow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text[:200])
        self.assertEqual(page.headers.get('Cache-Control'), 'no-store')
        state = re.search(r'var loginState="([A-Za-z0-9_-]{43})"', page.text).group(1)
        from odoo.http import root
        sid = page.cookies.get('session_id') or self.opener.cookies.get('session_id')
        self.assertIn(state, root.session_store.get(sid).get(STATE_KEY, {}))
        # HttpCase.authenticate installs a domainless cookie; Odoo's rotated
        # cookie has a host domain, and requests may send the stale one first.
        self.opener.cookies.set('session_id', sid)
        return state

    def test_post_without_login_state_is_refused(self):
        with patch(MOCK_POST, side_effect=self._line_accepts):
            resp = self.url_open('/liff/redirect/home', data={'id_token': 'fake'},
                                 allow_redirects=False)
        self.assertEqual(resp.status_code, 400)

    def test_login_state_cannot_be_replayed(self):
        state = self._login_state()
        with patch(MOCK_POST, side_effect=self._line_accepts):
            first = self.url_open('/liff/redirect/home',
                                  data={'id_token': 'fake', 'login_state': state},
                                  allow_redirects=False)
            second = self.url_open('/liff/redirect/home',
                                   data={'id_token': 'fake', 'login_state': state},
                                   allow_redirects=False)
        self.assertIn(first.status_code, (302, 303), first.text[:200])
        self.assertEqual(second.status_code, 400)

    def test_existing_cookie_does_not_skip_line_verification(self):
        """原本的 fast-path 會沿用既有 Odoo cookie 直接 302；共用裝置上會變成別人的帳號。"""
        self.authenticate('admin', 'admin')
        self.assertEqual(self._session_uid(), self.env.ref('base.user_admin').id)
        page = self.url_open('/liff/redirect/home', allow_redirects=False)
        self.assertEqual(page.status_code, 200)
        self.assertIn('var loginState=', page.text)
        self.assertFalse(self._session_uid(),
                         'GET bridge must clear the previous Odoo identity before LINE verification')

    def test_bound_staff_opens_member_home_as_portal_user(self):
        staff, portal = self._bound_staff_accounts()
        self.authenticate(staff.login, 'liff-staff-test-password')
        self.assertEqual(self._session_uid(), staff.id)

        state = self._login_state('home')
        with patch(MOCK_POST, side_effect=self._line_accepts_bound_staff):
            response = self.url_open(
                '/liff/redirect/home',
                data={'id_token': 'fake-id-token', 'login_state': state},
                allow_redirects=False,
            )
        self.assertIn(response.status_code, (302, 303), response.text[:200])
        self.assertTrue(response.headers.get('Location', '').endswith('/my/home'))
        self._adopt_rotated_cookie(response)
        self.assertEqual(self._session_uid(), portal.id,
                         'a LINE identity bound for staff SSO must still use portal on member targets')

    def test_bound_staff_opens_admin_target_as_internal_user(self):
        staff, portal = self._bound_staff_accounts()
        self.authenticate(portal.login, 'liff-portal-test-password')
        self.assertEqual(self._session_uid(), portal.id)

        state = self._login_state('staff-dashboard')
        with patch(MOCK_POST, side_effect=self._line_accepts_bound_staff):
            response = self.url_open(
                '/liff/redirect/staff-dashboard',
                data={'id_token': 'fake-id-token', 'login_state': state},
                allow_redirects=False,
            )
        self.assertIn(response.status_code, (302, 303), response.text[:200])
        self.assertTrue(response.headers.get('Location', '').endswith('/odoo'))
        self._adopt_rotated_cookie(response)
        self.assertEqual(self._session_uid(), staff.id,
                         'configured management targets must keep the explicit staff SSO binding')

    def test_custom_rich_menu_path_renders_bridge(self):
        page = self.url_open('/liff/redirect/shop/category/1', allow_redirects=False)
        self.assertEqual(page.status_code, 200)
