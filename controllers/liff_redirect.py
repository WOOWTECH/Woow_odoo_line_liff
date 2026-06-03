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
    - booking/<id> → /appointment/booking/<id>/confirm
    """

    # 目標 URL 對照表
    REDIRECT_TARGETS = {
        'book': '/appointment/1/schedule',
        'my-bookings': '/my/ext-bookings',
        'profile': '/my/account',
    }

    @http.route('/liff/redirect/<string:target>', type='http', auth='public',
                methods=['GET', 'POST'], website=True, csrf=False)
    def liff_redirect(self, target, **kwargs):
        """LIFF 自動登入跳轉端點

        GET: 返回中間頁，前端 JS 取得 ID Token 後 POST 回來
        POST: 驗證 ID Token，建立 session，302 redirect
        """
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(target)

        # POST 處理：接受 id_token（優先）或 access_token（備援）
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
            return request.redirect('/liff/member?error=no_token')

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
            return request.redirect('/liff/member?error=invalid_token')

        line_uid = payload.get('sub')
        if not line_uid:
            return request.redirect('/liff/member?error=no_uid')

        # 建立或更新 LINE 用戶
        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.create_or_update_from_liff(payload)
        if not line_user:
            return request.redirect('/liff/member?error=user_creation_failed')

        # 確保有對應的 portal user
        partner, user = self._ensure_portal_user(line_user, payload)
        if not user:
            return request.redirect('/liff/member?error=login_failed')

        # 建立 session：設定一次性密碼後用正式 authenticate
        db = request.env.cr.dbname
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        try:
            user.sudo().write({'password': temp_password})
            request.session.authenticate(db, user.login, temp_password)
        except Exception:
            _logger.exception('liff_redirect: session.authenticate 失敗')
            return request.redirect('/liff/member?error=login_failed')

        # 決定 redirect 目標
        redirect_url = self._get_redirect_url(target, kwargs)
        separator = '&' if '?' in redirect_url else '?'
        redirect_url = f'{redirect_url}{separator}liff=1'

        _logger.info(
            'liff_redirect: LINE %s → user %s → %s',
            line_uid, user.login, redirect_url,
        )
        return request.redirect(redirect_url)

    @http.route('/liff/redirect/booking/<int:booking_id>', type='http',
                auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def liff_redirect_booking(self, booking_id, **kwargs):
        """LIFF 跳轉到特定預約詳情"""
        if request.httprequest.method == 'GET':
            return self._render_liff_bridge_page(f'booking/{booking_id}')

        # POST 處理（同上邏輯）
        id_token = kwargs.get('id_token', '')
        if not id_token:
            try:
                body = json.loads(request.httprequest.get_data(as_text=True))
                id_token = body.get('id_token', '')
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if not id_token:
            return request.redirect('/liff/member?error=no_token')

        line_service = request.env['line.service'].sudo()
        payload = line_service.verify_id_token(id_token)
        if not payload:
            return request.redirect('/liff/member?error=invalid_token')

        line_uid = payload.get('sub')
        if not line_uid:
            return request.redirect('/liff/member?error=no_uid')

        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.create_or_update_from_liff(payload)
        if not line_user:
            return request.redirect('/liff/member?error=user_creation_failed')

        partner, user = self._ensure_portal_user(line_user, payload)
        if not user:
            return request.redirect('/liff/member?error=login_failed')

        db = request.env.cr.dbname
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        try:
            user.sudo().write({'password': temp_password})
            request.session.authenticate(db, user.login, temp_password)
        except Exception:
            _logger.exception('liff_redirect_booking: session.authenticate 失敗')
            return request.redirect('/liff/member?error=login_failed')

        # 跳轉到預約詳情
        redirect_url = f'/my/ext-bookings/{booking_id}?liff=1'
        return request.redirect(redirect_url)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _render_liff_bridge_page(self, target):
        """渲染 LIFF 中間頁（取得 ID Token 用）

        這個頁面會載入 LIFF SDK，取得 ID Token 後 POST 回 redirect endpoint。
        """
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')

        return request.render('woow_line_bridge.liff_redirect_bridge', {
            'target': target,
            'liff_id': liff_id,
        })

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

        # 預設回會員中心
        _logger.warning('liff_redirect: 未知的 target=%s，導回會員中心', target)
        return '/liff/member'
