# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/portal.py
# Portal 優化：LINE 用戶密碼設定 + 個人資料只需 email
import logging
import time

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

    # B-3b：免舊密碼改密碼 / 改 email 連帶改 login，這兩個都是敏感動作，
    # 只在「剛透過 LIFF 免密碼登入」的有效期內開放，視窗過了就跟一般
    # portal 使用者一樣走正常規則（要填舊密碼、email 變更不會動 login）。
    _LIFF_FRESH_WINDOW = 15 * 60  # 15 分鐘

    # ── 密碼更改：LINE 用戶可跳過舊密碼 ──────────────────────

    def _is_line_user(self):
        """判斷目前這個 session 是否為「剛透過 LIFF 免密碼登入」的
        share 使用者（B-3b）。

        原本只檢查「這個 partner 有沒有 line.user 記錄」，但那沒辦法
        證明『這次』登入真的是透過 LIFF 來的——同一個 partner 完全可能
        是用一般密碼登入的（或 session 是用其他方式取得的）。改成看
        session 裡的時間戳：這個戳記只會在 _authenticate_liff_user()
        免密碼登入成功那一刻被寫入，比對 line.user 記錄更精確，也把
        風險視窗收斂到剛登入後的 15 分鐘內。同時要求 share=True，
        內部使用者一律不適用（B-3 的守門邏輯已經盡量擋住內部帳號被
        免密碼登入，這裡再加一層保險）。
        """
        user = request.env.user
        if not user.share:
            return False
        authed_at = getattr(request.session, 'liff_authenticated_at', None)
        if not authed_at:
            return False
        try:
            return (time.time() - float(authed_at)) <= self._LIFF_FRESH_WINDOW
        except (TypeError, ValueError):
            return False

    def _notify_account_change(self, user, subject, body):
        """B-3b：改密碼 / 改 login 後留下痕跡。優先用 partner 的 chatter
        留言（mail.thread 內建，不需要額外的 mail template），寄不出去
        不影響主流程。
        """
        try:
            partner = user.partner_id
            if partner:
                partner.sudo().message_post(body=body, subject=subject)
        except Exception:
            _logger.exception('B-3b: 帳號異動通知寄送失敗（不影響主流程）: user=%s', user.login)

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

            user = request.env.user
            _logger.info('LINE 用戶 %s 透過 Portal 設定了新密碼', user.login)
            self._notify_account_change(
                user, _('密碼變更通知'),
                _('您的 Portal 密碼剛剛被變更。若非您本人操作，請立即聯絡我們。'),
            )
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
        """Override: email 變更後同步 login 並更新 session token

        B-3b：這個自動同步只在 _is_line_user()（share + 剛透過 LIFF
        免密碼登入）時才做。這個功能原本就是為了「LINE 用戶把
        line_<uid>@line.placeholder 換成真實 email 後 login 也要跟著換」
        這個情境設計的，不是給一般 portal 使用者用的通用行為；不限制的話，
        任何人只要能取得一個 share 使用者的 session（不論是不是這次
        LIFF 認證來的），就能透過改 email 連帶接管對方的 login，把
        B-3 的暫時性冒用放大成永久接管。
        """
        old_email = request.env.user.partner_id.email
        response = super().account(redirect=redirect, **post)

        if request.httprequest.method == 'POST' and hasattr(response, 'status_code') and response.status_code in (302, 303):
            new_email = post.get('email', '').strip()
            if new_email and new_email != old_email:
                if not self._is_line_user():
                    _logger.info(
                        'Portal email→login 同步略過（非剛透過 LIFF 認證的 share '
                        '使用者）: user=%s, email %s → %s',
                        request.env.user.login, old_email, new_email)
                else:
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
                                old_login = user.login
                                user.write({'login': new_email})
                                request.env.flush_all()
                                request.env.registry.clear_cache()
                                new_token = request.env.user._compute_session_token(request.session.sid)
                                request.session.session_token = new_token
                                request.session.login = new_email
                                _logger.info(
                                    'Portal email→login 同步: %s → %s (user id=%s)',
                                    old_login, new_email, user.id)
                                self._notify_account_change(
                                    user, _('登入帳號變更通知'),
                                    _('您的登入帳號已由 %(old)s 變更為 %(new)s。'
                                      '若非您本人操作，請立即聯絡我們。',
                                      old=old_login, new=new_email),
                                )
                            except Exception:
                                _logger.exception('Portal email→login 同步失敗')

        return response
