# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/liff_redirect.py
# ★ LIFF → Portal 自動登入跳轉（整個整合的命脈）
# 流程：驗證 LINE ID Token → 找到/建立 portal user → session.authenticate → 302 redirect
import json
import logging
import re
import secrets
import string

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)

# B-2：只接受安全字元的 target，避免任意字串（含 <script> breakout payload）
# 被當成合法 target 一路帶進 inline <script>。
_SAFE_TARGET_RE = re.compile(r'^[A-Za-z0-9_/-]{1,64}$')

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
    - book → /appointment/1/schedule
    - my-bookings → /my/ext-bookings
    - profile → /my/account
    - booking/<id> → /my/ext-bookings/<id>
    """

    # 目標 URL 對照表
    REDIRECT_TARGETS = {
        'book': '/appointment/1/schedule',
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

        if id_token:
            payload = line_service.verify_id_token(id_token)
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
                'var liffId=__LIFFID__;var target=__TARGET__;'
                "if(typeof liff==='undefined'||!liffId){window.location.href='/web/login?error=invalid_token';return;}"
                'liff.init({liffId:liffId}).then(function(){'
                'try{liff.logout();}catch(e){}'
                "liff.login({redirectUri:window.location.origin+'/liff/redirect/'+target});"
                "}).catch(function(){window.location.href='/web/login?error=invalid_token';});"
                '})();'
                '</script></body></html>'
            )
            safe_target = self._sanitize_target(target)
            html = html.replace(
                '__LIFFID__', _json_for_script(self._get_liff_id())
            ).replace('__TARGET__', _json_for_script(safe_target))
            return None, request.make_response(html, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Content-Security-Policy', _LIFF_BRIDGE_CSP),
            ])

        line_uid = payload.get('sub')
        if not line_uid:
            return None, request.redirect('/web/login?error=no_uid')

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
            return None, request.redirect('/web/login?error=login_failed')

        # Passwordless session：直接寫 session 狀態，跳過 res.users._check_credentials
        # 之前用 temp-password + authenticate 的做法在多 worker + ORM cache 場景下
        # 會偶發 AccessDenied（rewrite 的 hash 尚未反映到 authenticate 讀到的 cursor）。
        from odoo import api, SUPERUSER_ID
        try:
            # 讀出目標 user 需要的資料（用 SUPERUSER，因為 auth='none' 下 env.uid 為 None）
            su_env = api.Environment(request.env.cr, SUPERUSER_ID, {})
            fresh_user = su_env['res.users'].browse(user.id)
            if not fresh_user.exists() or not fresh_user.active:
                raise Exception('user missing or inactive')
            # 直接設 session state，並用 res.users._compute_session_token 產生合法 token
            request.session.uid = fresh_user.id
            request.session.login = fresh_user.login
            request.session.session_token = fresh_user._compute_session_token(request.session.sid)
            request.session.pre_login = fresh_user.login
            request.session.pre_uid = fresh_user.id
            # 更新 last login 紀錄（authenticate() 原本會做）
            # 用 SUPERUSER env 直接 create，帶上 create_uid 讓 login_date related 正確
            su_env['res.users.log'].create({'create_uid': fresh_user.id})
            request.env.cr.commit()
        except Exception:
            _logger.exception('liff_redirect: passwordless session 建立失敗')
            return None, request.redirect('/web/login?error=login_failed')

        return user, None

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------

    @http.route(['/liff/redirect', '/liff/redirect/<path:target>'], type='http',
                auth='none', methods=['GET', 'POST'], website=False, csrf=False)
    def liff_redirect(self, target='book', **kwargs):
        """LIFF 自動登入跳轉端點

        GET: 返回中間頁，前端 JS 取得 ID Token 後 POST 回來
        POST: 驗證 ID Token，建立 session，302 redirect
        """
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(target)

        user, error = self._authenticate_liff_user(target=target, **kwargs)
        if error:
            return error

        redirect_url = self._get_redirect_url(target, kwargs)

        _logger.info(
            'liff_redirect: LINE → user %s → %s',
            user.login, redirect_url,
        )
        return request.redirect(redirect_url)

    @http.route('/liff/redirect/booking/<int:booking_id>', type='http',
                auth='none', methods=['GET', 'POST'], website=False, csrf=False)
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

    def _render_liff_bridge_page(self, target):
        """渲染 LIFF 中間頁（取得 ID Token 用）

        使用 auth='none' 所以不能用 request.render()，直接回 HTML。
        Fast path: 若 Odoo session cookie 仍有效，直接 302 到目標，跳過 LIFF login。
        """
        # ---- Fast path：既有 Odoo session 仍有效就直接放行 ----
        # 用原始 target（跟 POST 成功後的 _get_redirect_url 一致），這裡只是
        # 302 的 Location，不會被內嵌進 HTML，不需要收窄到 B-2 的白名單。
        try:
            if request.session and request.session.uid:
                from odoo import api, SUPERUSER_ID
                su_env = api.Environment(request.env.cr, SUPERUSER_ID, {})
                u = su_env['res.users'].browse(request.session.uid)
                if u.exists() and u.active:
                    expected = u._compute_session_token(request.session.sid)
                    if expected and expected == request.session.session_token:
                        target_url = self._get_redirect_url(target, {})
                        _logger.info('liff bridge fast-path: uid=%s → %s', u.id, target_url)
                        return request.redirect(target_url)
        except Exception:
            _logger.exception('liff bridge fast-path 檢查失敗（fallback 到 LIFF 流程）')

        # B-2：從這裡開始 target 會被內嵌進下面的 inline <script>，先過白名單。
        target = self._sanitize_target(target)

        Config = request.env['line.liff.config'].sudo()
        config = Config._get_default_config()
        liff_id = config.liff_id_member if config else ''
        if not liff_id:
            ICP = request.env['ir.config_parameter'].sudo()
            liff_id = ICP.get_param('woow_odoo_line_liff.liff_id_member', '')

        # 直接跳轉對照表（fallback）
        direct_urls = {
            'book': '/appointment/1/schedule',
            'my-bookings': '/my/ext-bookings',
            'profile': '/my/account',
            'home': '/my/home',
            'orders': '/my/orders',
            'invoices': '/my/invoices',
        }

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
var fallbacks={json.dumps(direct_urls)};
var liffId={json.dumps(liff_id)};
var $st=document.getElementById('st');
var $er=document.getElementById('er');
var $sp=document.getElementById('sp');
function showErr(msg){{$sp.style.display='none';$st.textContent='登入失敗';$er.style.display='block';$er.textContent=msg;}}
var target=serverTarget;
if(target&&target!=='book'){{sessionStorage.setItem('liff_target',target);}}
else{{var saved=sessionStorage.getItem('liff_target');if(saved){{target=saved;}}}}
function fb(reason){{
  sessionStorage.removeItem('liff_target');
  if(reason){{showErr(reason);return;}}
  var u=fallbacks[target]||'/appointment/1/schedule';window.location.href=u;
}}
if(!liffId){{fb('LIFF ID 未設定');return;}}
if(typeof liff==='undefined'){{fb('LIFF SDK 載入失敗');return;}}
liff.init({{liffId:liffId}}).then(function(){{
  if(!liff.isLoggedIn()){{$st.textContent='正在跳轉 LINE 登入...';liff.login({{redirectUri:window.location.origin+'/liff/redirect/'+target}});return;}}
  $st.textContent='正在驗證身份...';
  var t=null,a=null;
  try{{t=liff.getIDToken();}}catch(e){{}}
  try{{a=liff.getAccessToken();}}catch(e){{}}
  if(!t&&!a){{fb('無法取得 LINE Token（ID Token 和 Access Token 皆為空）');return;}}
  sessionStorage.removeItem('liff_target');
  var f=document.createElement('form');f.method='POST';f.action='/liff/redirect/'+target;
  if(t){{var i=document.createElement('input');i.type='hidden';i.name='id_token';i.value=t;f.appendChild(i);}}
  if(a){{var i2=document.createElement('input');i2.type='hidden';i2.name='access_token';i2.value=a;f.appendChild(i2);}}
  document.body.appendChild(f);f.submit();
}}).catch(function(e){{fb('LIFF 初始化失敗: '+(e.message||e.code||JSON.stringify(e)));}});
}})();
</script></body></html>"""
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html'),
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

    def _get_redirect_url(self, target, kwargs):
        """取得 redirect 目標 URL

        :param target: target 字串
        :param kwargs: 額外參數
        :return: URL 字串
        """
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
