# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_news.py
# 最新消息 Model — 供 LIFF 頁面和 LINE 推播使用
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineNews(models.Model):
    """最新消息

    在後台撰寫文章，發佈後可在 LIFF 新聞頁顯示，
    也可推播 Flex Message 給所有 LINE 好友。
    """
    _name = 'line.news'
    _description = '最新消息'
    _order = 'published_date desc, create_date desc'
    _rec_name = 'title'

    title = fields.Char(string='標題', required=True)
    summary = fields.Text(string='摘要', help='在列表頁顯示的簡短摘要')
    body = fields.Html(string='內容', sanitize=True)
    image = fields.Binary(string='封面圖片', attachment=True)
    image_url = fields.Char(string='封面圖片 URL', help='外部圖片連結（優先於上傳圖片）')
    published_date = fields.Date(string='發佈日期', default=fields.Date.today)
    is_published = fields.Boolean(string='已發佈', default=False, index=True)
    author_id = fields.Many2one(
        'res.users', string='作者',
        default=lambda self: self.env.user,
    )
    line_push_sent = fields.Boolean(string='已推播 LINE', default=False)

    def action_publish(self):
        """發佈文章"""
        self.write({'is_published': True, 'published_date': fields.Date.today()})

    def action_unpublish(self):
        """取消發佈"""
        self.write({'is_published': False})

    def action_push_to_line(self):
        """推播文章到所有 LINE 好友"""
        self.ensure_one()
        if not self.is_published:
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
            self.env['line.service'].broadcast([{
                'type': 'flex',
                'altText': f'最新消息 - {self.title}',
                'contents': flex,
            }])
            self.write({'line_push_sent': True})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'LINE 推播',
                    'message': '已推播給所有 LINE 好友',
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
