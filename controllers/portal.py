# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/portal.py
# Portal 優化：LINE 用戶密碼設定 + 個人資料只需 email
import logging

from odoo import _, http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class CustomerPortalLine(CustomerPortal):
    """Override portal controller for LINE user support.

    1. LINE 用戶可跳過舊密碼直接設定新密碼
    2. 個人資訊只有 name + email 必填
    3. Email 變更自動同步 login + 衝突檢查
    """

    # ── 密碼更改：LINE 用戶可跳過舊密碼 ──────────────────────

    def _is_line_user(self):
        """判斷當前登入用戶是否為 LINE 用戶"""
        partner = request.env.user.partner_id
        line_user = request.env['line.user'].sudo().search([
            ('partner_id', '=', partner.id),
        ], limit=1)
        return bool(line_user)

    def _update_password(self, old, new1, new2):
        """Override: LINE 用戶可以不填舊密碼"""
        is_line = self._is_line_user()

        # LINE 用戶且舊密碼為空 → 跳過舊密碼驗證
        if is_line and not old:
            if not new1:
                return {'errors': {'password': {'new1': _("You cannot leave any password empty.")}}}
            if new1 != new2:
                return {'errors': {'password': {'new2': _("The new password and its confirmation must be identical.")}}}

            try:
                request.env.user.sudo()._change_password(new1)
                new_token = request.env.user._compute_session_token(request.session.sid)
                request.session.session_token = new_token
            except Exception as e:
                return {'errors': {'password': str(e)}}

            _logger.info('LINE 用戶 %s 透過 Portal 設定了新密碼', request.env.user.login)
            return {'success': {'password': True}}

        return super()._update_password(old, new1, new2)

    # ── 個人資訊：只保留 name + email 必填 ───────────────────

    def _get_mandatory_fields(self):
        """Override: 只保留 name + email 為必填"""
        return ["name", "email"]

    def _get_optional_fields(self):
        """Override: 把原本必填的欄位改為選填，保留其他模組擴展的欄位"""
        parent_optional = super()._get_optional_fields()
        demoted = ["phone", "street", "city", "country_id"]
        for f in demoted:
            if f not in parent_optional:
                parent_optional.append(f)
        return parent_optional

    def details_form_validate(self, data, partner_creation=False):
        """Override: email 衝突檢查 + 移除 unknown field 錯誤"""
        error, error_message = super().details_form_validate(data, partner_creation)

        # 檢查 email 是否已被其他 user 的 login 佔用
        new_email = (data.get('email') or '').strip()
        if new_email:
            existing = request.env['res.users'].sudo().search([
                ('login', '=', new_email),
                ('id', '!=', request.env.user.id),
            ], limit=1)
            if existing:
                error['email'] = 'error'
                error_message.append(
                    _('此 Email 已被其他帳號使用，請使用其他 Email 地址。'))

        # 清除 unknown field 錯誤（account 等模組加的 hidden fields）
        if 'common' in error and 'Unknown field' in str(error.get('common', '')):
            del error['common']
            error_message = [m for m in error_message if 'Unknown field' not in m]
        return error, error_message

    # ── Email → Login 自動同步 ───────────────────────────────

    @http.route(['/my/account'], type='http', auth='user', website=True)
    def account(self, redirect=None, **post):
        """Override: email 變更後同步 login 並更新 session token"""
        old_email = request.env.user.partner_id.email
        response = super().account(redirect=redirect, **post)

        if request.httprequest.method == 'POST' and hasattr(response, 'status_code') and response.status_code in (302, 303):
            new_email = post.get('email', '').strip()
            if new_email and new_email != old_email:
                user = request.env.user.sudo()
                if user.login != new_email:
                    Users = request.env['res.users'].sudo()
                    conflict = Users.search([
                        ('login', '=', new_email),
                        ('id', '!=', user.id),
                    ], limit=1)
                    if conflict:
                        _logger.warning(
                            'Portal email→login 同步跳過: %s 已被 user %s (%s) 使用',
                            new_email, conflict.id, conflict.name)
                    else:
                        try:
                            user.write({'login': new_email})
                            request.env.flush_all()
                            request.env.registry.clear_cache()
                            new_token = request.env.user._compute_session_token(request.session.sid)
                            request.session.session_token = new_token
                            request.session.login = new_email
                            _logger.info('Portal email→login 同步: %s → %s', old_email, new_email)
                        except Exception:
                            _logger.exception('Portal email→login 同步失敗')

        return response
