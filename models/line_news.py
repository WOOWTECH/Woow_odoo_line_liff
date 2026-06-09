# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_news.py
# 最新消息 Model — 供 LIFF 頁面和 LINE 推播使用
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineNews(models.Model):
    """最新消息

    在後台撰寫文章，確認後可在 LIFF 新聞頁顯示，
    也可推播 Flex Message 給所有 LINE 好友（可重複推播）。
    """
    _name = 'line.news'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '最新消息'
    _order = 'published_date desc, create_date desc'
    _rec_name = 'title'

    title = fields.Char(string='標題', required=True)
    summary = fields.Text(string='摘要', help='在列表頁顯示的簡短摘要')
    body = fields.Html(string='內容', sanitize=True)
    image = fields.Binary(string='封面圖片', attachment=True)
    card_url = fields.Char(
        string='閱讀全文 URL',
        help='LINE Flex 卡片「閱讀全文」按鈕連結（建立時自動填入，可自行修改）',
    )
    published_date = fields.Date(string='發佈日期', default=fields.Date.today)
    author_id = fields.Many2one(
        'res.users', string='作者',
        default=lambda self: self.env.user,
    )
    state = fields.Selection([
        ('draft', '草稿'),
        ('published', '已發佈'),
    ], string='狀態', default='draft', required=True, tracking=True, index=True)
    # 保留 is_published 作為 computed 欄位以相容 LIFF 頁面查詢
    is_published = fields.Boolean(
        string='已發佈', compute='_compute_is_published', store=True, index=True,
    )
    line_push_count = fields.Integer(string='LINE 推播次數', default=0)
    line_last_push = fields.Datetime(string='最近推播時間', readonly=True)

    @api.depends('state')
    def _compute_is_published(self):
        for rec in self:
            rec.is_published = rec.state == 'published'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        for rec in records:
            if not rec.card_url:
                rec.card_url = f'{base_url}/liff/news?article_id={rec.id}'
        return records

    def action_publish(self):
        """確認發佈文章"""
        self.write({'state': 'published', 'published_date': fields.Date.today()})

    def action_draft(self):
        """退回草稿"""
        self.write({'state': 'draft'})

    def action_push_to_line(self):
        """推播文章到所有 LINE 好友（可重複推播）"""
        self.ensure_one()
        if self.state != 'published':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'LINE 推播',
                    'message': '請先發佈文章再推播',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        try:
            flex = self.env['line.flex.template'].build_news_card(self)
            success = self.env['line.api.service'].broadcast([{
                'type': 'flex',
                'altText': f'最新消息 - {self.title}',
                'contents': flex,
            }])
            if not success:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'LINE 推播',
                        'message': '推播失敗：LINE API 回傳錯誤，請檢查 Access Token',
                        'type': 'danger',
                    },
                }
            self.write({
                'line_push_count': self.line_push_count + 1,
                'line_last_push': fields.Datetime.now(),
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'LINE 推播',
                    'message': f'已推播給所有 LINE 好友（第 {self.line_push_count} 次）',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception:
            _logger.exception('LINE 新聞推播失敗: %s', self.title)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'LINE 推播',
                    'message': '推播失敗，請查看系統日誌',
                    'type': 'danger',
                    'sticky': False,
                },
            }
