# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_audience_tag.py
# LINE Audience 分眾標籤 — Odoo tag + LINE Audience API 同步
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

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
            lambda u: u.is_follower and not u.is_blocked
            and u.notification_enabled and u.line_user_id
        ).mapped('line_user_id')
        if not user_ids:
            return self._notification('沒有可同步的用戶', 'warning')

        old_group_id = self.line_audience_group_id
        group_id = api.audience_create(
            description=f'Odoo: {self.name}',
            user_ids=user_ids,
        )
        if group_id:
            # 新的建立成功後才刪除舊的（LINE 不支援替換全部用戶）；
            # 若先刪除，create 失敗會讓 tag 指向一個已不存在的 audience。
            leftover = None
            if old_group_id:
                ok, status_code, body = api.audience_delete_ex(int(old_group_id))
                if not ok and status_code != 404:
                    leftover = (old_group_id, self._line_error_text(status_code, body))
                    _logger.warning('Audience 同步：舊名單 %s 未能從 LINE 刪除（%s）',
                                    old_group_id, leftover[1])
            self.write({'line_audience_group_id': str(group_id)})
            _logger.info('Audience 同步成功: %s → %s (%d users)',
                         self.name, group_id, len(user_ids))
            if leftover:
                # 新名單已生效；舊名單還在 LINE 上，必須讓操作者知道編號才清得掉
                return self._notification(
                    f'已同步 {len(user_ids)} 位用戶到 LINE Audience，但舊名單 {leftover[0]} '
                    f'未能從 LINE 刪除（{leftover[1]}），請稍後到 LINE 後台刪除。', 'warning')
            return self._notification(
                f'已同步 {len(user_ids)} 位用戶到 LINE Audience', 'success')

        return self._notification('同步失敗，請檢查 Access Token', 'danger')

    def action_delete_from_line(self):
        """從 LINE 刪除 Audience Group

        只有 LINE 真的刪掉才清 group id：失敗時照樣清掉的話，audience 留在 LINE
        上、Odoo 卻再也指不到它（跟 H-8 的圖文選單孤兒同一類）。
        """
        self.ensure_one()
        message = '已從 LINE 刪除'
        if self.line_audience_group_id:
            ok, status_code, body = self.env['line.api.service'].audience_delete_ex(
                int(self.line_audience_group_id))
            if status_code == 404:
                # LINE 上本來就沒有了：舊連結留著只會誤導，清掉即可
                message = 'LINE 上已不存在這份名單，已清除 Odoo 裡的連結'
            elif not ok:
                raise UserError(
                    f'從 LINE 刪除分眾名單失敗：{self._line_error_text(status_code, body)}。'
                    '名單仍保留在 LINE 上，Odoo 也保留它的編號，可以稍後再試一次。')
            self.write({'line_audience_group_id': False})
        return self._notification(message, 'success')

    @staticmethod
    def _line_error_text(status_code, body):
        """把 LINE 的錯誤回應（通常是 {"message": "..."}）轉成一句話"""
        message = ''
        if body:
            try:
                message = json.loads(body).get('message', '')
            except (ValueError, AttributeError, TypeError):
                message = body
        if not status_code:
            return f'無法連線到 LINE（{message or "網路錯誤"}）'
        return f'LINE 回應 {status_code}：{message}' if message else f'LINE 回應 {status_code}'

    def _notification(self, message, ntype):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'LINE Audience', 'message': message,
                       'type': ntype, 'sticky': False},
        }
