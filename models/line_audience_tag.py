# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_audience_tag.py
# LINE Audience 分眾標籤 — Odoo tag + LINE Audience API 同步
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineAudienceTag(models.Model):
    """LINE 分眾標籤

    管理用戶分群（VIP、新客、員工等），
    可同步到 LINE Audience API 用於 narrowcast 精準推播。
    """
    _name = 'line.audience.tag'
    _description = 'LINE 分眾標籤'
    _order = 'sequence, name'

    name = fields.Char('標籤名稱', required=True)
    color = fields.Integer('顏色', default=0)
    sequence = fields.Integer('排序', default=10)
    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        default=lambda self: self.env['line.liff.config']._get_default_config(),
    )
    line_audience_group_id = fields.Char(
        'LINE Audience Group ID', readonly=True,
        help='LINE 平台上的 audience group ID，同步時自動填入')
    user_ids = fields.Many2many(
        'line.user', 'line_audience_tag_user_rel',
        'tag_id', 'user_id', string='LINE 用戶')
    user_count = fields.Integer(
        '用戶數', compute='_compute_user_count', store=True)
    active = fields.Boolean('啟用', default=True)
    description = fields.Text('說明')

    @api.depends('user_ids')
    def _compute_user_count(self):
        for rec in self:
            rec.user_count = len(rec.user_ids)

    def action_sync_to_line(self):
        """同步標籤內的用戶到 LINE Audience Group"""
        self.ensure_one()
        api = self.env['line.api.service']
        user_ids = self.user_ids.filtered(
            lambda u: u.is_follower and u.line_user_id
        ).mapped('line_user_id')
        if not user_ids:
            return self._notification('沒有可同步的用戶', 'warning')

        if self.line_audience_group_id:
            # 已有 audience group → 刪除重建（LINE 不支援替換全部用戶）
            api.audience_delete(int(self.line_audience_group_id))

        group_id = api.audience_create(
            description=f'Odoo: {self.name}',
            user_ids=user_ids,
        )
        if group_id:
            self.write({'line_audience_group_id': str(group_id)})
            _logger.info('Audience 同步成功: %s → %s (%d users)',
                         self.name, group_id, len(user_ids))
            return self._notification(
                f'已同步 {len(user_ids)} 位用戶到 LINE Audience', 'success')

        return self._notification('同步失敗，請檢查 Access Token', 'danger')

    def action_delete_from_line(self):
        """從 LINE 刪除 Audience Group"""
        self.ensure_one()
        if self.line_audience_group_id:
            self.env['line.api.service'].audience_delete(
                int(self.line_audience_group_id))
            self.write({'line_audience_group_id': False})
        return self._notification('已從 LINE 刪除', 'success')

    def _notification(self, message, ntype):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'LINE Audience', 'message': message,
                       'type': ntype, 'sticky': False},
        }
