# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_user.py
# Bridge 擴充 line.user：加入 Rich Menu 關聯 + 推播快捷方法
from odoo import fields, models


class LineUserBridge(models.Model):
    _inherit = 'line.user'

    # Rich Menu（richmenu model 從 base 搬到 bridge）
    current_richmenu_id = fields.Many2one(
        'line.richmenu',
        string='目前 Rich Menu',
        ondelete='set null',
    )

    # ------------------------------------------------------------------
    # 推播快捷方法（使用 line.api.service）
    # ------------------------------------------------------------------

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
