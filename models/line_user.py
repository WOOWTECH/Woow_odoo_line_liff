# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_user.py
# Bridge 擴充 line.user：加入 Rich Menu 關聯 + 推播快捷方法
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
