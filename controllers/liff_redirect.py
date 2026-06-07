# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/liff_redirect.py
# ★ LIFF → Portal 自動登入跳轉（整個整合的命脈）
# 流程：驗證 LINE ID Token → 找到/建立 portal user → session.authenticate → 302 redirect
import json
import logging
import secrets
import string

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


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
    }

    # ------------------------------------------------------------------
    # 共用認證邏輯（DRY：從 liff_redirect + liff_redirect_booking 提取）
    # ------------------------------------------------------------------

    def _authenticate_liff_user(self, **kwargs):
        """驗證 LIFF token 並建立 Odoo session

        從 POST body 或 kwargs 取得 id_token/access_token，
        驗證後建立/更新 LINE 用戶、確保 portal user、authenticate session。

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
        line_service = request.env['line.service'].sudo()
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
            _logger.warning('liff_redirect: 所有 token 驗證失敗')
            return None, request.redirect('/web/login?error=invalid_token')

        line_uid = payload.get('sub')
        if not line_uid:
            return None, request.redirect('/web/login?error=no_uid')

        # 建立或更新 LINE 用戶
        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.create_or_update_from_liff(payload)
        if not line_user:
            return None, request.redirect('/web/login?error=user_creation_failed')

        # 確保有對應的 portal user
        partner, user = self._ensure_portal_user(line_user, payload)
        if not user:
            return None, request.redirect('/web/login?error=login_failed')

        # 建立 session：Odoo 18 authenticate(db, credential_dict)
        db = request.env.cr.dbname
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        try:
            user.sudo().write({'password': temp_password})
            request.env.cr.flush()
            request.env.cr.commit()
            request.session.authenticate(db, {
                'login': user.login,
                'password': temp_password,
                'type': 'password',
            })
        except Exception:
            _logger.exception('liff_redirect: session.authenticate 失敗')
            return None, request.redirect('/web/login?error=login_failed')

        return user, None

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------

    @http.route(['/liff/redirect', '/liff/redirect/<string:target>'], type='http',
                auth='none', methods=['GET', 'POST'], website=False, csrf=False)
    def liff_redirect(self, target='book', **kwargs):
        """LIFF 自動登入跳轉端點

        GET: 返回中間頁，前端 JS 取得 ID Token 後 POST 回來
        POST: 驗證 ID Token，建立 session，302 redirect
        """
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(target)

        user, error = self._authenticate_liff_user(**kwargs)
        if error:
            return error

        redirect_url = self._get_redirect_url(target, kwargs)
        separator = '&' if '?' in redirect_url else '?'
        redirect_url = f'{redirect_url}{separator}liff=1'

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

        user, error = self._authenticate_liff_user(**kwargs)
        if error:
            return error

        redirect_url = f'/my/ext-bookings/{booking_id}?liff=1'
        return request.redirect(redirect_url)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _render_liff_bridge_page(self, target):
        """渲染 LIFF 中間頁（取得 ID Token 用）

        使用 auth='none' 所以不能用 request.render()，直接回 HTML。
        """
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')

        # 直接跳轉對照表（fallback）
        direct_urls = {
            'book': '/appointment/1/schedule',
            'my-bookings': '/my/ext-bookings',
            'profile': '/my/account',
        }

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loading...</title>
<style>body{{display:flex;align-items:center;justify-content:center;min-height:100vh;background:#F5F5F5;margin:0;}}
.s{{width:40px;height:40px;border:4px solid #E5E5E5;border-top-color:#333333;border-radius:50%;animation:r .8s linear infinite;margin:0 auto 16px;}}
@keyframes r{{to{{transform:rotate(360deg)}}}}</style></head>
<body><div style="text-align:center"><div class="s"></div>
<p id="st" style="color:#666666;font-family:sans-serif;font-size:14px;">正在登入中...</p></div>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
(function(){{
var liffId='{liff_id}',target='{target}';
var fallbacks={json.dumps(direct_urls)};
function fb(){{var u=fallbacks[target]||'/appointment/1/schedule';window.location.href=u;}}
if(!liffId||typeof liff==='undefined'){{fb();return;}}
liff.init({{liffId:liffId}}).then(function(){{
  if(!liff.isLoggedIn()){{fb();return;}}
  var t=null,a=null;
  try{{t=liff.getIDToken();}}catch(e){{}}
  try{{a=liff.getAccessToken();}}catch(e){{}}
  if(!t&&!a){{fb();return;}}
  var f=document.createElement('form');f.method='POST';f.action=window.location.pathname;
  if(t){{var i=document.createElement('input');i.type='hidden';i.name='id_token';i.value=t;f.appendChild(i);}}
  if(a){{var i2=document.createElement('input');i2.type='hidden';i2.name='access_token';i2.value=a;f.appendChild(i2);}}
  document.body.appendChild(f);f.submit();
}}).catch(function(){{fb();}});
}})();
</script></body></html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    def _ensure_portal_user(self, line_user, id_token_payload):
        """確保 LINE 用戶有對應的 portal user

        查找順序：
        1. line_user 已有 partner_id → 查 partner 的 user
        2. 用 email 查現有 partner
        3. 建立新 partner + portal user

        :param line_user: line.user record
        :param id_token_payload: LINE verify API 回傳的 payload
        :return: (partner, user) tuple
        """
        Partner = request.env['res.partner'].sudo()
        Users = request.env['res.users'].sudo()

        email = id_token_payload.get('email', '') or line_user.email or ''
        name = id_token_payload.get('name', '') or line_user.display_name or 'LINE User'

        # 情況 1：line_user 已綁定 partner
        if line_user.partner_id:
            partner = line_user.partner_id
            user = Users.search([('partner_id', '=', partner.id)], limit=1)
            if user:
                return partner, user
            # partner 存在但沒有 user，建立 portal user
            user = self._create_portal_user(partner, email)
            return partner, user

        # 情況 2：用 email 查現有 partner
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                line_user.bind_partner(partner.id)
                user = Users.search([('partner_id', '=', partner.id)], limit=1)
                if user:
                    return partner, user
                user = self._create_portal_user(partner, email)
                return partner, user

        # 情況 3：建立新 partner + portal user
        partner = Partner.create({
            'name': name,
            'email': email or f'line_{line_user.line_user_id}@line.placeholder',
            'image_1920': False,
        })
        line_user.bind_partner(partner.id)

        login_email = email or f'line_{line_user.line_user_id}@line.placeholder'
        user = self._create_portal_user(partner, login_email)
        return partner, user

    def _create_portal_user(self, partner, login):
        """建立 portal user

        :param partner: res.partner record
        :param login: 登入帳號（通常是 email）
        :return: res.users record
        """
        Users = request.env['res.users'].sudo()

        # 檢查是否已有 user
        existing = Users.search([('login', '=', login)], limit=1)
        if existing:
            return existing

        # 產生隨機密碼（用戶不需要用密碼登入，都是透過 LIFF）
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

        try:
            portal_group = request.env.ref('base.group_portal')
            user = Users.with_context(no_reset_password=True).create({
                'name': partner.name,
                'login': login,
                'password': password,
                'partner_id': partner.id,
                'groups_id': [(6, 0, [portal_group.id])],
            })
            _logger.info('建立 portal user: %s (partner: %s)', login, partner.name)
            return user
        except Exception:
            _logger.exception('建立 portal user 失敗: %s', login)
            return Users

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

        # 預設回登入頁
        _logger.warning('liff_redirect: 未知的 target=%s，導回登入頁', target)
        return '/web/login'
