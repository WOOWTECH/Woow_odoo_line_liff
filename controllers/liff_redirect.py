# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/liff_redirect.py
# ★ LIFF → Portal 自動登入跳轉（整個整合的命脈）
# 流程：驗證 LINE ID Token → 找到/建立 portal user → session.authenticate → 302 redirect
import json
import logging
import re
import secrets
import string
import time

from odoo import http, SUPERUSER_ID
from odoo.http import request
from urllib.parse import urlencode
from .liff_sso_policy import (
    ADMIN_TARGETS_PARAM, BINDING_PARAM, BOOKING_INTENT_KEY_PARAM, BOOKING_RESUME_PATH_PARAM,
    allowed_target, binding_for_claims, consume_challenge, is_safe_local_path,
    issue_challenge, parse_admin_targets, parse_booking_resume,
)

_logger = logging.getLogger(__name__)

# B-2：只接受安全字元的 target，避免任意字串（含 <script> breakout payload）
# 被當成合法 target 一路帶進 inline <script>。
_SAFE_TARGET_RE = re.compile(r'^[A-Za-z0-9_/-]{1,64}$')
_SAFE_BOOKING_NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{32,128}$')

# B-2：這兩個 LIFF 中間頁都會把 target 這類外部可控字串內嵌進 inline <script>，
# 補一個保守但不影響既有 liff.line-scdn.net SDK 運作的 CSP 當第三層防線。
_LIFF_BRIDGE_CSP = (
    "default-src 'self' https:; "
    "script-src 'self' 'unsafe-inline' https://static.line-scdn.net https:; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


def _json_for_script(value):
    """json.dumps() 但跳脫 <, >，避免內嵌進 inline <script> 時被
    ``</script>`` 提前結束（B-2 反射型 XSS）。json.dumps 本身不會跳脫
    HTML 特殊字元，直接插值進 <script> 是不安全的。
    """
    return json.dumps(value).replace('<', '\\u003c').replace('>', '\\u003e')


class LiffRedirectController(http.Controller):
    """LIFF 自動登入跳轉 Controller

    核心機制：
    1. LIFF 前端取得 ID Token
    2. POST 到 /liff/redirect/<target>，帶 id_token
    3. 後端驗證 ID Token → 取得 LINE UID
    4. 查找或建立 line.user → 查找或建立 portal user
    5. request.session.authenticate() 建立 session
    6. 302 redirect 到目標 URL，附加 ?liff=1

    支援的 target：
    - book → line.liff.config.rebook_path（未設定時安全預設 /my/home；
      不同客戶有沒有裝預約模組、預約模組的實際路徑都不一樣，寫死
      /appointment/1/schedule 在沒裝該模組的實例上一律 404）
    - my-bookings → /my/ext-bookings
    - profile → /my/account
    - booking/<id> → /my/ext-bookings/<id>

    REDIRECT_TARGETS 是這個對照表唯一的真相來源；_render_liff_bridge_page
    的前端 fallback 表也是從這裡複製，不要再另外維護一份。
    """

    # 目標 URL 對照表（唯一真相來源，見上方 docstring）
    REDIRECT_TARGETS = {
        'book': '/my/home',
        'my-bookings': '/my/ext-bookings',
        'profile': '/my/account',
        'home': '/my/home',
        'orders': '/my/orders',
        'invoices': '/my/invoices',
    }

    # ------------------------------------------------------------------
    # 共用認證邏輯（DRY：從 liff_redirect + liff_redirect_booking 提取）
    # ------------------------------------------------------------------

    def _get_liff_id(self):
        """讀取 LIFF ID：先看 line.liff.config 再 fallback 到 ir_config_parameter"""
        Config = request.env['line.liff.config'].sudo()
        config = Config._get_default_config()
        if config and config.liff_id_member:
            return config.liff_id_member
        return request.env['ir.config_parameter'].sudo().get_param(
            'woow_odoo_line_liff.liff_id_member', ''
        )

    @staticmethod
    def _sanitize_booking_nonce(booking_nonce):
        """Only pass a server-generated booking intent nonce through LIFF."""
        if isinstance(booking_nonce, str) and _SAFE_BOOKING_NONCE_RE.fullmatch(booking_nonce):
            return booking_nonce
        return None

    def _get_admin_targets(self):
        """站點設定的後台 target（內部 SSO 用）；未設定或格式不對時為空。"""
        raw = request.env['ir.config_parameter'].sudo().get_param(ADMIN_TARGETS_PARAM, '')
        targets = parse_admin_targets(raw)
        if raw and not targets:
            _logger.warning('%s 格式不正確，視為未設定', ADMIN_TARGETS_PARAM)
        return targets

    def _get_booking_resume(self):
        """預約模組的續訂路徑與草稿 session key；兩者都合法才回傳，否則 (None, None)。"""
        ICP = request.env['ir.config_parameter'].sudo()
        return parse_booking_resume(ICP.get_param(BOOKING_RESUME_PATH_PARAM, ''),
                                    ICP.get_param(BOOKING_INTENT_KEY_PARAM, ''))

    def _get_login_channel_id(self, config):
        """LINE Login Channel ID：先看 line.liff.config，再退回 woow_line_base 的全域設定。"""
        channel_id = config.login_channel_id if config else ''
        if not channel_id:
            channel_id = request.env['ir.config_parameter'].sudo().get_param(
                'woow_line_base.login_channel_id', '')
        return channel_id or ''

    def _sanitize_target(self, target):
        """B-2：白名單過濾 target。不合法就退回預設值 'book'，不原樣回吐——
        這兩個中間頁會把 target 內嵌進 inline <script>，任何不在安全字元集
        內的字串都不應該被接受，即使後面還有跳脫處理。
        """
        if target and _SAFE_TARGET_RE.match(target):
            return target
        return 'book'

    def _authenticate_liff_user(self, target='book', **kwargs):
        """驗證 LIFF token 並建立 Odoo session

        從 POST body 或 kwargs 取得 id_token/access_token，
        驗證後建立/更新 LINE 用戶、確保 portal user、authenticate session。

        :param target: LIFF target 名稱，用於 token 過期時 refresh 回同一個 target
        :return: (user, None) on success, (None, redirect_response) on failure
        """
        config = request.env['line.liff.config'].sudo()._get_default_config()
        booking_nonce = self._sanitize_booking_nonce(kwargs.get('booking_nonce'))
        if not allowed_target(target) or not consume_challenge(
                request.session, kwargs.get('login_state'), target, booking_nonce,
                time.time(), config.id if config else False):
            return None, request.make_response('登入驗證已過期，請關閉此頁後重新點選 LINE 選單。',
                                               headers=[('Cache-Control', 'no-store')], status=400)
        # 取得 token
        id_token = kwargs.get('id_token', '')
        access_token = kwargs.get('access_token', '')
        if not id_token and not access_token:
            try:
                body = json.loads(request.httprequest.get_data(as_text=True))
                id_token = body.get('id_token', '')
                access_token = body.get('access_token', '')
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if not id_token and not access_token:
            _logger.warning('liff_redirect: 缺少 id_token 和 access_token')
            return None, request.redirect('/web/login?error=no_token')

        # 驗證：優先 ID Token，備援 Access Token
        line_service = request.env['line.api.service'].sudo()
        payload = None
        id_token_verified = False
        login_channel_id = self._get_login_channel_id(config)
        if not login_channel_id:
            return None, request.redirect('/web/login?error=line_configuration')

        if id_token:
            payload = line_service.verify_id_token(id_token, login_channel_id=login_channel_id)
            id_token_verified = bool(payload)
            if payload:
                _logger.debug('liff_redirect: ID Token 驗證成功')

        if not payload and access_token:
            payload = line_service.verify_access_token(access_token)
            if payload:
                _logger.debug('liff_redirect: Access Token 驗證成功（備援）')

        if not payload:
            _logger.warning('liff_redirect: 所有 token 驗證失敗（多半是快取的 ID Token 過期）')
            # 不要 302 到 /web/login，改成回一小段 HTML 讓 LIFF 重新 login 拿 fresh token
            html = (
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Refreshing...</title>'
                '<style>body{display:flex;align-items:center;justify-content:center;min-height:100vh;background:#F5F5F5;margin:0;font-family:sans-serif}'
                '.s{width:40px;height:40px;border:4px solid #E5E5E5;border-top-color:#333;border-radius:50%;animation:r .8s linear infinite;margin:0 auto 16px}'
                '@keyframes r{to{transform:rotate(360deg)}}</style></head>'
                '<body><div style="text-align:center"><div class="s"></div>'
                '<p style="color:#666;font-size:14px">重新驗證中...</p></div>'
                '<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>'
                '<script>'
                '(function(){'
                'var liffId=__LIFFID__;var target=__TARGET__;var nonceSuffix=__NONCE_SUFFIX__;'
                "if(typeof liff==='undefined'||!liffId){window.location.href='/web/login?error=invalid_token';return;}"
                'liff.init({liffId:liffId}).then(function(){'
                'try{liff.logout();}catch(e){}'
                "liff.login({redirectUri:window.location.origin+'/liff/redirect/'+target+nonceSuffix});"
                "}).catch(function(){window.location.href='/web/login?error=invalid_token';});"
                '})();'
                '</script></body></html>'
            )
            safe_target = self._sanitize_target(target)
            booking_nonce = self._sanitize_booking_nonce(kwargs.get('booking_nonce'))
            nonce_suffix = '?booking_nonce=' + booking_nonce if booking_nonce else ''
            html = html.replace(
                '__LIFFID__', _json_for_script(self._get_liff_id())
            ).replace('__TARGET__', _json_for_script(safe_target)).replace(
                '__NONCE_SUFFIX__', _json_for_script(nonce_suffix))
            return None, request.make_response(html, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Content-Security-Policy', _LIFF_BRIDGE_CSP),
            ])

        line_uid = payload.get('sub')
        if not line_uid:
            return None, request.redirect('/web/login?error=no_uid')

        # Internal SSO is separate from email/profile matching and portal provisioning.
        try:
            internal_user = self._resolve_internal_sso_user(
                payload, id_token_verified, config, login_channel_id)
        except ValueError:
            _logger.warning('LIFF internal SSO denied by explicit binding policy')
            request.session.logout(keep_db=True)
            return None, request.redirect('/web/login?error=line_sso_denied')
        if internal_user:
            return self._establish_identity_session(internal_user, target, kwargs)
        admin_targets = self._get_admin_targets()
        if target in admin_targets:
            # No mapping: require normal credentials, never inherit another account's cookie.
            request.session.logout(keep_db=True)
            return None, request.redirect('/web/login?' + urlencode({'redirect': admin_targets[target]}))

        # 建立或更新 LINE 用戶
        LineUser = request.env['line.user'].sudo()
        try:
            line_user = LineUser.create_or_update_from_liff(payload)
        except Exception:
            _logger.exception('liff_redirect: LINE 用戶建立/更新失敗 uid=%s', line_uid)
            line_user = None
        if not line_user:
            return None, request.redirect('/web/login?error=user_creation_failed')

        # 確保有對應的 portal user
        partner, user = self._ensure_portal_user(line_user, payload)
        if not user:
            request.session.logout(keep_db=True)
            return None, request.redirect('/web/login?error=login_failed')

        return self._establish_identity_session(user, target, kwargs)

    def _resolve_internal_sso_user(self, payload, id_token_verified, config, login_channel_id):
        env = request.env
        raw = env['ir.config_parameter'].sudo().get_param(BINDING_PARAM, '[]')
        # 沒有 line.liff.config 時 config_id 為 False：有對應綁定的身分會被拒絕（fail closed），
        # 沒有綁定的身分照常走 portal 登入。
        binding = binding_for_claims(raw, payload, id_token_verified,
                                     config.id if config else False,
                                     login_channel_id, time.time())
        if not binding:
            return None
        line = env['line.user'].sudo().browse(binding['line_user_id']).exists()
        user = env['res.users'].sudo().browse(binding['user_id']).exists()
        if not (line and user and user.active and not user.share
                and user.id != SUPERUSER_ID and not user.has_group('base.group_system')
                and line.line_user_id == payload['sub']
                and line.liff_config_id.id == config.id
                and line.partner_id.id == binding['partner_id'] == user.partner_id.id):
            raise ValueError('Internal SSO binding no longer matches')
        return user

    def _establish_identity_session(self, user, target, kwargs):
        """Use Odoo's rotating session lifecycle and honor the normal MFA step."""
        if not user.exists() or not user.active:
            return None, request.redirect('/web/login?error=login_failed')
        booking_nonce = self._sanitize_booking_nonce(kwargs.get('booking_nonce'))
        _resume_path, booking_key = self._get_booking_resume()
        intents = request.session.get(booking_key, {}) if booking_key else {}
        intent = intents.get(booking_nonce) if isinstance(intents, dict) and booking_nonce else None
        request.session.logout(keep_db=True)
        # Only carry the selected server-stored booking draft, never account/session data.
        if intent and target == 'book':
            request.session[booking_key] = {booking_nonce: intent}
        user_env = request.env(user=user.id, su=False)
        mfa_url = user.with_env(user_env)._mfa_url()
        if mfa_url:
            # Fail closed for MFA accounts: use the full native login flow.
            # Do not leave a partial session that can outlive/replay an SSO binding.
            destination = self._get_redirect_url(target, kwargs)
            return None, request.redirect('/web/login?' + urlencode({'redirect': destination}))
        request.session.pre_uid = user.id
        request.session.pre_login = user.login
        try:
            request.session.finalize(user_env)
            request.update_env(user=user.id, su=False)
            request.update_context(**request.session.context)
            if user.share:
                request.session.liff_authenticated_at = time.time()
            user.with_env(user_env)._update_last_login()
            request.env.cr.commit()
        except Exception:
            request.session.logout(keep_db=True)
            _logger.exception('LIFF session finalization failed')
            return None, request.redirect('/web/login?error=login_failed')
        return user, None

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------

    # readonly=False：Odoo 18 把 auth='none' 路由預設成唯讀交易，但 POST 會建立
    # LINE 用戶與 portal user、寫登入紀錄。唯讀交易裡的寫入會被上面
    # _authenticate_liff_user 的 except 吞掉，Odoo 的「改用讀寫重試」因此不會
    # 發生，整個請求變成 500（有唯讀副本或測試環境時必定發作）。
    @http.route(['/liff/redirect', '/liff/redirect/<path:target>'], type='http',
                auth='none', methods=['GET', 'POST'], website=False, csrf=False,
                readonly=False)
    def liff_redirect(self, target='book', **kwargs):
        """LIFF 自動登入跳轉端點

        GET: 返回中間頁，前端 JS 取得 ID Token 後 POST 回來
        POST: 驗證 ID Token，建立 session，302 redirect
        """
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(target, **kwargs)

        user, error = self._authenticate_liff_user(target=target, **kwargs)
        if error:
            return error

        redirect_url = self._get_redirect_url(target, kwargs)

        _logger.info('LIFF authentication completed: uid=%s target=%s', user.id, target)
        return request.redirect(redirect_url)

    @http.route('/liff/redirect/booking/<int:booking_id>', type='http',
                auth='none', methods=['GET', 'POST'], website=False, csrf=False,
                readonly=False)
    def liff_redirect_booking(self, booking_id, **kwargs):
        """LIFF 跳轉到特定預約詳情"""
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(f'booking/{booking_id}')

        user, error = self._authenticate_liff_user(target=f'booking/{booking_id}', **kwargs)
        if error:
            return error

        redirect_url = f'/my/ext-bookings/{booking_id}'
        return request.redirect(redirect_url)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _render_liff_bridge_page(self, target, **kwargs):
        """渲染 LIFF 中間頁（取得 ID Token 用）

        使用 auth='none' 所以不能用 request.render()，直接回 HTML。
        Always verify LINE identity: an existing Odoo cookie may belong to someone else.
        """
        if not allowed_target(target):
            return request.not_found()

        # B-2：從這裡開始 target 會被內嵌進下面的 inline <script>，先過白名單。
        target = self._sanitize_target(target)
        booking_nonce = self._sanitize_booking_nonce(kwargs.get('booking_nonce'))

        Config = request.env['line.liff.config'].sudo()
        config = Config._get_default_config()
        login_state = issue_challenge(request.session, target, booking_nonce, time.time(),
                                      config.id if config else False)
        liff_id = config.liff_id_member if config else ''
        if not liff_id:
            ICP = request.env['ir.config_parameter'].sudo()
            liff_id = ICP.get_param('woow_odoo_line_liff.liff_id_member', '')

        # 直接跳轉對照表（fallback）：複製 REDIRECT_TARGETS（唯一真相來源），
        # 不要在這裡另外維護一份容易跟主表兜不起來的複本。'book' 再用
        # line.liff.config.rebook_path 覆寫（跟 _get_redirect_url 一致）。
        direct_urls = dict(self.REDIRECT_TARGETS)
        custom_book = self._get_custom_book_path()
        if custom_book:
            direct_urls['book'] = custom_book

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loading...</title>
<style>body{{display:flex;align-items:center;justify-content:center;min-height:100vh;background:#F5F5F5;margin:0;font-family:sans-serif;}}
.s{{width:40px;height:40px;border:4px solid #E5E5E5;border-top-color:#333333;border-radius:50%;animation:r .8s linear infinite;margin:0 auto 16px;}}
@keyframes r{{to{{transform:rotate(360deg)}}}}
.err{{color:#EF4444;font-size:13px;margin-top:12px;word-break:break-all;max-width:90vw;}}</style></head>
<body><div style="text-align:center"><div class="s" id="sp"></div>
<p id="st" style="color:#666666;font-size:14px;">正在登入中...</p>
<p id="er" class="err" style="display:none;"></p></div>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
(function(){{
var serverTarget={_json_for_script(target)};
var bookingNonce={_json_for_script(booking_nonce)};
var loginState={_json_for_script(login_state)};
var fallbacks={_json_for_script(direct_urls)};
var liffId={_json_for_script(liff_id)};
var $st=document.getElementById('st');
var $er=document.getElementById('er');
var $sp=document.getElementById('sp');
function showErr(msg){{$sp.style.display='none';$st.textContent='登入失敗';$er.style.display='block';$er.textContent=msg;}}
var target=serverTarget;
sessionStorage.removeItem('liff_target');
function bookingRedirectUri(){{
  var url=window.location.origin+'/liff/redirect/'+target;
  return bookingNonce ? url+'?booking_nonce='+encodeURIComponent(bookingNonce) : url;
}}
function fb(reason){{
  sessionStorage.removeItem('liff_target');
  if(reason){{showErr(reason);return;}}
  var u=fallbacks[target]||'/my/home';window.location.href=u;
}}
if(!liffId){{fb('LIFF ID 未設定');return;}}
if(typeof liff==='undefined'){{fb('LIFF SDK 載入失敗');return;}}
liff.init({{liffId:liffId}}).then(function(){{
  if(!liff.isLoggedIn()){{$st.textContent='正在跳轉 LINE 登入...';liff.login({{redirectUri:bookingRedirectUri()}});return;}}
  $st.textContent='正在驗證身份...';
  var t=null,a=null;
  try{{t=liff.getIDToken();}}catch(e){{}}
  try{{a=liff.getAccessToken();}}catch(e){{}}
  if(!t&&!a){{fb('無法取得 LINE Token（ID Token 和 Access Token 皆為空）');return;}}
  sessionStorage.removeItem('liff_target');
  var f=document.createElement('form');f.method='POST';f.action='/liff/redirect/'+target;
  var stateInput=document.createElement('input');stateInput.type='hidden';stateInput.name='login_state';stateInput.value=loginState;f.appendChild(stateInput);
  if(bookingNonce){{var n=document.createElement('input');n.type='hidden';n.name='booking_nonce';n.value=bookingNonce;f.appendChild(n);}}
  if(t){{var i=document.createElement('input');i.type='hidden';i.name='id_token';i.value=t;f.appendChild(i);}}
  if(a){{var i2=document.createElement('input');i2.type='hidden';i2.name='access_token';i2.value=a;f.appendChild(i2);}}
  document.body.appendChild(f);f.submit();
}}).catch(function(e){{fb('LIFF 初始化失敗: '+(e.message||e.code||JSON.stringify(e)));}});
}})();
</script></body></html>"""
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store'),
            ('Content-Security-Policy', _LIFF_BRIDGE_CSP),
        ])

    def _find_portal_user_for_partner(self, partner):
        """依 partner 找對應的 share portal user（B-3：免密碼登入守門）。

        如果這個 partner 已經被一個「非 share」的內部使用者佔用（例如
        partner 剛好是某位員工），絕對不能默默忽略、另外幫他建一個 portal
        user 就算了事——這裡必須明確拒絕整個登入，讓呼叫端把使用者導去
        /web/login，而不是悄悄降級。

        :return: (user, blocked) — user 是找到的 share=True res.users
                 recordset（可能是空 recordset），blocked=True 代表撞到
                 內部使用者、呼叫端必須直接拒絕登入。
        """
        Users = request.env['res.users'].sudo()
        user = Users.search([
            ('partner_id', '=', partner.id), ('share', '=', True),
        ], limit=1)
        if user:
            return user, False

        internal_user = Users.search([
            ('partner_id', '=', partner.id), ('share', '=', False),
        ], limit=1)
        if internal_user:
            _logger.warning(
                'liff_redirect: partner %s(id=%s) 已綁定非 share 的內部使用者 '
                '%s(id=%s)，拒絕透過 LIFF 建立免密碼 session（B-3 帳號接管防護）',
                partner.name, partner.id, internal_user.login, internal_user.id,
            )
            return Users.browse(), True

        return Users.browse(), False

    def _ensure_portal_user(self, line_user, id_token_payload):
        """確保 LINE 用戶有對應的 portal user

        查找順序：
        1. line_user 已有 partner_id → 查 partner 的 user
        2. 用 email 查現有 partner
        3. 建立新 partner + portal user

        :param line_user: line.user record
        :param id_token_payload: LINE verify API 回傳的 payload
        :return: (partner, user) tuple；user 為 falsy 代表登入應被拒絕
        """
        Partner = request.env['res.partner'].sudo()

        email = id_token_payload.get('email', '') or line_user.email or ''
        name = id_token_payload.get('name', '') or line_user.display_name or 'LINE User'

        # 情況 1：line_user 已綁定 partner
        if line_user.partner_id:
            partner = line_user.partner_id
            user, blocked = self._find_portal_user_for_partner(partner)
            if blocked:
                return partner, None
            if user:
                return partner, user
            # partner 存在但沒有 user，建立 portal user
            # 用 _safe_login 保底：email 為空時 fallback 到 line_<uid>@line.placeholder
            user = self._create_portal_user(partner, self._safe_login(line_user, email))
            return partner, user

        # 情況 2：用 email 查現有 partner
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                line_user.bind_partner(partner.id)
                user, blocked = self._find_portal_user_for_partner(partner)
                if blocked:
                    return partner, None
                if user:
                    return partner, user
                user = self._create_portal_user(partner, self._safe_login(line_user, email))
                return partner, user

        # 情況 3：建立新 partner + portal user
        # email 只用於真實信箱，placeholder 不設到 partner（避免佔走 email 欄位）
        partner = Partner.create({
            'name': name,
            'email': email or False,
            'image_1920': False,
        })
        line_user.bind_partner(partner.id)

        user = self._create_portal_user(partner, self._safe_login(line_user, email))
        return partner, user

    def _safe_login(self, line_user, email):
        """Login 永不為空：優先 email，退回 line_<uid>@line.placeholder。

        搭配 __init__.py 的 _fix_empty_login post_init：post_init 補歷史資料，
        _safe_login 防未來所有 code path。
        """
        return (email or '').strip() or f'line_{line_user.line_user_id}@line.placeholder'

    def _create_portal_user(self, partner, login):
        """建立 portal user

        :param partner: res.partner record
        :param login: 登入帳號（通常是 email）
        :return: res.users record or None
        """
        from odoo import api, SUPERUSER_ID

        # auth='none' 下 request.env.uid 為 None，ORM 內部 cache 以 uid 為 key
        # 會導致 KeyError。必須建立完整的 SUPERUSER 環境。
        env = api.Environment(request.env.cr, SUPERUSER_ID, {})
        Users = env['res.users']

        # 檢查是否已有 user；只有「share 且屬於同一個 partner」才可以直接
        # 重用——login 字串剛好相同不代表可以把 session 發給它，那可能是
        # 完全無關的帳號、甚至是內部（非 share）帳號（B-3：帳號接管防護）。
        # 撞到這種情況就改用 placeholder login 另建，不重用既有帳號。
        existing = Users.search([('login', '=', login)], limit=1)
        if existing:
            if existing.share and existing.partner_id.id == partner.id:
                return existing
            _logger.warning(
                'liff_redirect: login %s 已被%s帳號 %s(id=%s, partner=%s) 使用，'
                '改用 placeholder login 另建，避免把 session 發給無關帳號（B-3）',
                login, '非 share (內部)' if not existing.share else '其他 partner 的',
                existing.login, existing.id, existing.partner_id.id,
            )
            login = f'line_p{partner.id}_{secrets.token_hex(6)}@line.placeholder'

        # 產生隨機密碼（用戶不需要用密碼登入，都是透過 LIFF）
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

        try:
            portal_group = env.ref('base.group_portal')
            internal_group = env.ref('base.group_user')
            main_company = env['res.company'].search([], limit=1, order='id')
            # 先建立 user（SUPERUSER 預設會帶 internal group）
            user = Users.with_context(no_reset_password=True).create({
                'name': partner.name,
                'login': login,
                'password': password,
                'partner_id': partner.id,
                'company_id': main_company.id,
                'company_ids': [(6, 0, [main_company.id])],
            })
            # 再明確切換為 portal user（移除 internal + 加入 portal）
            user.write({'groups_id': [
                (3, internal_group.id),
                (4, portal_group.id),
            ]})
            _logger.info('建立 portal user: %s (partner: %s)', login, partner.name)
            return user
        except Exception:
            _logger.exception('建立 portal user 失敗: %s', login)
            return None

    def _get_custom_book_path(self):
        """讀取 line.liff.config.rebook_path 作為 'book' 的自訂目標。

        新·2：rebook_path 欄位的預設值是 /liff/redirect/book——如果照單全收，
        對還沒手動改過設定的客戶會造成無限重導（book → /liff/redirect/book
        → 這個 controller 自己 → target='book' → 又是同一個 rebook_path），
        所以把「以 /liff/redirect 開頭」視同未設定，回傳 None 讓呼叫端退回
        REDIRECT_TARGETS['book'] 的安全預設值。

        :return: 自訂路徑字串，或 None（代表沒有可用的自訂值）
        """
        Config = request.env['line.liff.config'].sudo()
        config = Config._get_default_config()
        path = (config.rebook_path or '').strip() if config else ''
        if is_safe_local_path(path) and not path.startswith('/liff/redirect'):
            return path
        return None

    def _get_redirect_url(self, target, kwargs):
        """取得 redirect 目標 URL

        :param target: target 字串
        :param kwargs: 額外參數
        :return: URL 字串
        """
        admin_targets = self._get_admin_targets()
        if target in admin_targets:
            return admin_targets[target]
        if not allowed_target(target):
            return '/my/home'
        # A booking nonce may only select the site-configured local resume route.
        # The appointment controller consumes it from the same server-side session
        # after LIFF establishes identity; no user-supplied return URL exists.
        booking_nonce = self._sanitize_booking_nonce(kwargs.get('booking_nonce'))
        resume_path, _booking_key = self._get_booking_resume()
        if target == 'book' and booking_nonce and resume_path:
            return f'{resume_path}?{urlencode({"booking_nonce": booking_nonce})}'

        # 'book' 可由 line.liff.config.rebook_path 覆寫，取不到才用
        # REDIRECT_TARGETS 裡的安全預設值（/my/home）。
        if target == 'book':
            custom_book = self._get_custom_book_path()
            if custom_book:
                return custom_book

        # 先查對照表
        url = self.REDIRECT_TARGETS.get(target)
        if url:
            return url

        # 嘗試解析 booking/<id> 格式
        if target.startswith('booking/'):
            try:
                booking_id = int(target.split('/')[1])
                return f'/my/ext-bookings/{booking_id}'
            except (ValueError, IndexError):
                pass

        # 支援直接路徑（portal + backend）
        if target.startswith(('my/', 'shop', 'appointment/', 'contactus',
                              'odoo/', 'web/', 'mail', 'discuss')):
            return f'/{target}'

        # 任何其他 / 分隔路徑也允許（避免誤擋合法頁面）
        if '/' in target and not target.startswith(('http', 'javascript', 'data:')):
            _logger.info('liff_redirect: 允許自訂路徑 target=%s', target)
            return f'/{target}'

        # 預設回首頁（不是登入頁，因為 session 已建立）
        _logger.warning('liff_redirect: 未知的 target=%s，導回首頁', target)
        return '/odoo'

