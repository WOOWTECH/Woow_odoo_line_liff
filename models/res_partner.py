# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/res_partner.py
# Bridge 擴充 res.partner：has_line_bound 計算欄位 + push_to_line 快捷方法
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # line_user_ids 已在 woow_line_base 定義，不重複宣告

    has_line_bound = fields.Boolean(
        string='已綁定 LINE',
        compute='_compute_has_line_bound',
        store=True,
        help='是否已綁定至少一個追蹤中的 LINE 帳號',
    )

    @api.depends('line_user_ids', 'line_user_ids.is_follower')
    def _compute_has_line_bound(self):
        # 也檢查 mail.guest 的 line_partner_id（livechat 綁定）
        has_guest_model = (
            'mail.guest' in self.env
            and hasattr(self.env['mail.guest'], 'line_partner_id')
        )
        guest_partner_ids = set()
        if has_guest_model and self.ids:
            guests = self.env['mail.guest'].sudo().search([
                ('line_partner_id', 'in', self.ids),
                ('line_user_id', '!=', False),
            ])
            guest_partner_ids = set(guests.mapped('line_partner_id').ids)

        for partner in self:
            via_line_user = bool(
                partner.line_user_ids.filtered(lambda lu: lu.is_follower)
            )
            via_guest = partner.id in guest_partner_ids
            partner.has_line_bound = via_line_user or via_guest

    def action_open_line_user(self):
        """Smart button：開啟此聯絡人的 LINE 用戶表單"""
        self.ensure_one()
        line_user = self.line_user_ids[:1]
        if line_user:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'line.user',
                'view_mode': 'form',
                'res_id': line_user.id,
                'target': 'current',
            }
        # 沒有 LINE 用戶：開 LINE 用戶列表（過濾此聯絡人）
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'line.user',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'target': 'current',
        }

    def push_to_line(self, msg_or_flex):
        """快捷方法：推播 LINE 通知給此聯絡人

        :param msg_or_flex: 字串（純文字）、dict（Flex Message）或 list（messages）
        :return: True/False
        """
        self.ensure_one()
        line_users = self.line_user_ids.filtered(
            lambda lu: lu.is_follower and not lu.is_blocked and lu.notification_enabled
        )
        if not line_users:
            return False

        if isinstance(msg_or_flex, str):
            messages = [{'type': 'text', 'text': msg_or_flex}]
        elif isinstance(msg_or_flex, dict):
            messages = [{
                'type': 'flex',
                'altText': msg_or_flex.get('altText', '通知'),
                'contents': msg_or_flex.get('contents', msg_or_flex),
            }]
        else:
            messages = msg_or_flex if isinstance(msg_or_flex, list) else []

        return bool(self.env['line.api.service'].push(line_users, messages))
