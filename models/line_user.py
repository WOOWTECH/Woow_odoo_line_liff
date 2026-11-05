# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_user.py
# Bridge 擴充 line.user：加入 Rich Menu 關聯 + 推播快捷方法
import logging
import time
from urllib.parse import urlencode

from odoo import SUPERUSER_ID, api, fields, models
from odoo.tools import consteq, email_normalize
from odoo.tools.misc import hmac as odoo_hmac

_logger = logging.getLogger(__name__)

# 以 LINE email 綁定既有聯絡人前，要先證明擁有該信箱（寄一次性確認連結）。
BIND_CONFIRM_SCOPE = 'woow_odoo_line_liff.bind_confirm'
BIND_CONFIRM_TTL = 30 * 60
BIND_CONFIRM_RESEND_INTERVAL = 10 * 60
BIND_CONFIRM_TOKEN_MAX_LEN = 200


def mask_email(email):
    """w***@example.com：讓本人認得、旁人看不出完整信箱。"""
    local, _sep, domain = (email or '').partition('@')
    if not local or not domain:
        return ''
    return f'{local[0]}***@{domain}'


class LineUserBridge(models.Model):
    _inherit = 'line.user'

    # LIFF 設定檔來源
    liff_config_id = fields.Many2one(
        'line.liff.config',
        string='LIFF 設定檔',
        ondelete='set null', index=True,
        help='此用戶來自的 LINE LIFF 設定檔',
    )

    # 分眾標籤
    audience_tag_ids = fields.Many2many(
        'line.audience.tag', 'line_audience_tag_user_rel',
        'user_id', 'tag_id', string='分眾標籤')

    # 以 email 綁定既有聯絡人的確認流程（見 _request_bind_confirmation）
    pending_bind_partner_id = fields.Many2one(
        'res.partner', string='待確認綁定聯絡人', ondelete='set null', copy=False,
        groups='woow_line_base.group_line_manager',
        help='LINE email 對應到這位既有聯絡人；收信確認後才會綁定')
    pending_bind_sent_at = fields.Datetime(
        '確認信寄出時間', copy=False, groups='woow_line_base.group_line_manager')

    # Rich Menu（richmenu model 從 base 搬到 bridge）
    current_richmenu_id = fields.Many2one(
        'line.richmenu',
        string='目前 Rich Menu',
        ondelete='set null',
    )

    # ------------------------------------------------------------------
    # Rich Menu 自動同步到 LINE
    # ------------------------------------------------------------------

    def write(self, vals):
        res = super().write(vals)
        if 'current_richmenu_id' in vals:
            for rec in self:
                rec._sync_richmenu_to_line()
        return res

    def _sync_richmenu_to_line(self):
        """當 current_richmenu_id 變更時，自動呼叫 LINE API 綁定/解綁"""
        self.ensure_one()
        if not self.line_user_id:
            return
        api = self.env['line.api.service'].sudo()
        if self.current_richmenu_id and self.current_richmenu_id.line_richmenu_id:
            success = api.richmenu_link_to_user(
                self.current_richmenu_id.line_richmenu_id,
                self.line_user_id,
            )
            if success:
                _logger.info('Rich Menu 已綁定: %s → %s',
                             self.display_name, self.current_richmenu_id.name)
            else:
                _logger.warning('Rich Menu 綁定失敗: %s', self.display_name)
        else:
            # 解除個人綁定 → 回到預設
            api.richmenu_unlink_from_user(self.line_user_id)
            _logger.info('Rich Menu 已解除: %s → 回到預設', self.display_name)

    # ------------------------------------------------------------------
    # 推播快捷方法（使用 line.api.service）
    # ------------------------------------------------------------------

    def action_push_test(self):
        """View 按鈕：發送測試訊息"""
        self.ensure_one()
        self.push_text('這是測試訊息')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'LINE', 'message': '已發送測試訊息', 'type': 'success', 'sticky': False},
        }

    def push_text(self, text):
        """推播純文字訊息"""
        self.ensure_one()
        messages = [self.env['line.api.service'].build_text_message(text)]
        return self.env['line.api.service'].push(self, messages)

    def push_messages(self, messages):
        """推播自訂訊息（可包含多則）"""
        return self.env['line.api.service'].push(self, messages)

    def push_flex(self, alt_text, contents):
        """推播 Flex Message"""
        self.ensure_one()
        messages = [{
            'type': 'flex',
            'altText': alt_text,
            'contents': contents,
        }]
        return self.env['line.api.service'].push(self, messages)

    # ------------------------------------------------------------------
    # UI 動作
    # ------------------------------------------------------------------

    def action_open_partner(self):
        """打開關聯的聯絡人表單"""
        self.ensure_one()
        if self.partner_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.partner',
                'res_id': self.partner_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return False

    # ------------------------------------------------------------------
    # 以 email 綁定既有聯絡人：先寄確認信，收信者確認後才綁定
    # ------------------------------------------------------------------
    # LINE 回傳的 email 沒有「已驗證屬於本人」的保證。對應到既有聯絡人時，
    # 確認連結寄到 Odoo 裡那位聯絡人的信箱（不是 LINE 給的值），能收信並按下確認，
    # 才證明是本人。token 以資料庫密鑰簽章，綁定 line.user、聯絡人與當時的 email，
    # 30 分鐘到期；聯絡人改了 email、或已改寄給別人，舊連結就失效。

    @api.model
    def _partner_for_line_email(self, email):
        """LINE email 對應到的既有聯絡人（精確比對正規化後的 email）。"""
        normalized = email_normalize(email or '')
        if not normalized:
            return self.env['res.partner']
        return self.env['res.partner'].sudo().search(
            [('email_normalized', '=', normalized)], limit=1)

    def _bind_confirmation_signature(self, partner, expires):
        self.ensure_one()
        message = '%s:%s:%s:%s:%s' % (
            self.id, self.line_user_id, partner.id,
            email_normalize(partner.email or '') or '', expires)
        return odoo_hmac(self.env(su=True), BIND_CONFIRM_SCOPE, message)

    def _make_bind_confirmation_token(self, partner, now=None):
        self.ensure_one()
        expires = int((now if now is not None else time.time()) + BIND_CONFIRM_TTL)
        return '%s.%s.%s.%s' % (
            self.id, partner.id, expires, self._bind_confirmation_signature(partner, expires))

    @api.model
    def _check_bind_confirmation_token(self, token, now=None):
        """驗證確認連結的 token。

        :return: (line.user, res.partner)；任何一項不符都回兩個空 recordset
        """
        empty = (self.browse(), self.env['res.partner'].browse())
        if not isinstance(token, str) or len(token) > BIND_CONFIRM_TOKEN_MAX_LEN:
            return empty
        parts = token.split('.')
        if len(parts) != 4 or not all(part.isdigit() for part in parts[:3]):
            return empty
        line_user_id, partner_id, expires = (int(part) for part in parts[:3])
        if expires < (now if now is not None else time.time()):
            return empty
        line_user = self.sudo().browse(line_user_id).exists()
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not line_user or not partner or not partner.email:
            return empty
        if not consteq(parts[3], line_user._bind_confirmation_signature(partner, expires)):
            return empty
        if line_user.pending_bind_partner_id != partner or self._is_staff_partner(partner):
            return empty
        if line_user._partner_bound_to_other_line_user(partner):
            return empty
        if line_user.partner_id and line_user.partner_id != partner:
            return empty
        return line_user, partner

    @api.model
    def _is_staff_partner(self, partner):
        """有內部（非 share）使用者的聯絡人：不走自助確認信，請店家處理。"""
        return bool(partner.sudo().with_context(active_test=False).user_ids.filtered(
            lambda user: not user.share))

    def _partner_bound_to_other_line_user(self, partner):
        """聯絡人已綁定另一個 LINE 帳號：不走自助確認信，請店家處理。"""
        self.ensure_one()
        return bool(partner.sudo().with_context(active_test=False).line_user_ids - self)

    def _request_bind_confirmation(self, partner):
        """寄確認連結到 partner 的信箱；10 分鐘內對同一位聯絡人不重寄。

        auth='none' 的路由沒有 uid，這裡自行改用 SUPERUSER 環境；呼叫端不必處理。

        :return: (sent, email_hint)。sent 為 False 代表沒寄出（員工聯絡人、寄信失敗），
                 畫面應請使用者聯絡店家；email_hint 是遮罩過的收件信箱
        """
        self.ensure_one()
        env = self.env if self.env.uid else api.Environment(self.env.cr, SUPERUSER_ID, {})
        line_user = self.with_env(env).sudo()
        partner = partner.with_env(env).sudo()
        email_hint = mask_email(email_normalize(partner.email or '') or '')
        if not partner.email or self._is_staff_partner(partner):
            _logger.info('LINE %s：email 對應到員工或無信箱的聯絡人 id=%s，不寄自助確認信',
                         line_user.line_user_id, partner.id)
            return False, email_hint
        if line_user._partner_bound_to_other_line_user(partner):
            _logger.info('LINE %s：聯絡人 id=%s 已綁定其他 LINE 帳號，不寄自助確認信',
                         line_user.line_user_id, partner.id)
            return False, email_hint
        now = fields.Datetime.now()
        recently_sent = (
            line_user.pending_bind_partner_id == partner
            and line_user.pending_bind_sent_at
            and (now - line_user.pending_bind_sent_at).total_seconds()
            < BIND_CONFIRM_RESEND_INTERVAL)
        if recently_sent:
            return True, email_hint
        line_user.write({'pending_bind_partner_id': partner.id, 'pending_bind_sent_at': now})
        token = line_user._make_bind_confirmation_token(partner)
        confirm_url = '%s/liff/bind/confirm?%s' % (
            line_user.get_base_url(), urlencode({'token': token}))
        body = env['ir.qweb']._render(
            'woow_odoo_line_liff.liff_bind_confirm_email', {
                'confirm_url': confirm_url,
                'line_name': line_user.display_name or '',
                'partner_name': partner.name or '',
                'ttl_minutes': BIND_CONFIRM_TTL // 60,
            })
        email_from = (env['ir.mail_server']._get_default_from_address()
                      or env.company.email_formatted)
        mail = env['mail.mail'].create({
            'subject': '確認綁定 LINE 帳號',
            'email_from': email_from,
            'email_to': partner.email,
            'body_html': body,
            'auto_delete': True,
        })
        mail.send(raise_exception=False)
        if mail.exists() and mail.state == 'exception':
            _logger.warning('LINE %s：綁定確認信寄送失敗（partner id=%s）',
                            line_user.line_user_id, partner.id)
            line_user.write({'pending_bind_partner_id': False, 'pending_bind_sent_at': False})
            return False, email_hint
        _logger.info('LINE %s：已寄綁定確認信給 partner id=%s',
                     line_user.line_user_id, partner.id)
        return True, email_hint

    def _confirm_pending_bind(self, partner):
        """收信者按下確認之後：綁定並清掉待確認狀態。"""
        self.ensure_one()
        line_user = self.sudo()
        if line_user._partner_bound_to_other_line_user(partner):
            line_user.write({'pending_bind_partner_id': False, 'pending_bind_sent_at': False})
            _logger.info('LINE %s：聯絡人 id=%s 已綁定其他 LINE 帳號，不綁定',
                         line_user.line_user_id, partner.id)
            return False
        line_user.bind_partner(partner.id)
        line_user.write({'pending_bind_partner_id': False, 'pending_bind_sent_at': False})
        _logger.info('LINE %s：信箱確認後綁定 partner id=%s', line_user.line_user_id, partner.id)
        return True
