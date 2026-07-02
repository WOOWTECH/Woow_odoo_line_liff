# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_insight_log.py
# LINE 統計紀錄 — 每日自動抓取送達/互動/好友數據
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineInsightLog(models.Model):
    """LINE 統計紀錄

    每日一筆，記錄訊息送達數、互動率、好友增減。
    由 ir.cron 每日凌晨自動抓取 LINE Insight API。
    """
    _name = 'line.insight.log'
    _description = 'LINE 統計紀錄'
    _order = 'date desc'
    _rec_name = 'date'

    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        required=True, ondelete='cascade', index=True)
    date = fields.Date('日期', required=True, index=True)

    # 送達統計
    delivery_broadcast = fields.Integer('Broadcast 送達')
    delivery_push = fields.Integer('Push 送達')
    delivery_multicast = fields.Integer('Multicast 送達')
    delivery_narrowcast = fields.Integer('Narrowcast 送達')
    delivery_reply = fields.Integer('Reply 送達')
    delivery_total = fields.Integer(
        '總送達', compute='_compute_delivery_total', store=True)

    # 好友統計
    followers = fields.Integer('好友數')
    targeted_reaches = fields.Integer('可觸及人數')
    blocks = fields.Integer('封鎖數')

    # 互動統計（聚合）
    impressions = fields.Integer('曝光數')
    clicks = fields.Integer('點擊數')
    click_rate = fields.Float('點擊率 (%)', digits=(5, 2))

    _sql_constraints = [
        ('date_config_unique', 'UNIQUE(date, config_id)',
         '同一天同一設定檔只能有一筆統計'),
    ]

    @api.depends('delivery_broadcast', 'delivery_push', 'delivery_multicast',
                 'delivery_narrowcast', 'delivery_reply')
    def _compute_delivery_total(self):
        for rec in self:
            rec.delivery_total = (
                (rec.delivery_broadcast or 0) +
                (rec.delivery_push or 0) +
                (rec.delivery_multicast or 0) +
                (rec.delivery_narrowcast or 0) +
                (rec.delivery_reply or 0)
            )

    @api.model
    def _cron_fetch_daily_insight(self):
        """排程任務：抓取昨天的統計數據"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        yesterday_date = (datetime.now() - timedelta(days=1)).date()
        configs = self.env['line.liff.config'].sudo().search([('active', '=', True)])
        api = self.env['line.api.service']

        for config in configs:
            try:
                self._fetch_for_config(api, config, yesterday, yesterday_date)
            except Exception:
                _logger.exception('統計抓取失敗: config=%s', config.name)

    def _fetch_for_config(self, api, config, date_str, date_val):
        """抓取特定 config 的統計"""
        ch_id = config.messaging_channel_id
        ch_secret = config.messaging_channel_secret

        # 送達統計
        delivery = api.get_insight_delivery(
            date_str, channel_id=ch_id, channel_secret=ch_secret)
        vals = {
            'config_id': config.id,
            'date': date_val,
        }
        if delivery and delivery.get('status') == 'ready':
            vals.update({
                'delivery_broadcast': delivery.get('broadcast', 0),
                'delivery_push': delivery.get('pushing', 0),
                'delivery_multicast': delivery.get('multicast', 0),
                'delivery_narrowcast': delivery.get('narrowcast', 0),
                'delivery_reply': delivery.get('reply', 0),
            })

        # 好友統計
        followers = api.get_insight_followers(
            date_str, channel_id=ch_id, channel_secret=ch_secret)
        if followers and followers.get('status') == 'ready':
            vals.update({
                'followers': followers.get('followers', 0),
                'targeted_reaches': followers.get('targetedReaches', 0),
                'blocks': followers.get('blocks', 0),
            })
            # 同步到 config
            config.sudo().write({
                'follower_count': followers.get('followers', 0),
                'target_reach': followers.get('targetedReaches', 0),
                'blocked_count': followers.get('blocks', 0),
                'follower_updated_at': fields.Datetime.now(),
            })

        # 建立或更新記錄
        existing = self.sudo().search([
            ('config_id', '=', config.id),
            ('date', '=', date_val),
        ], limit=1)
        if existing:
            existing.write(vals)
        else:
            self.sudo().create(vals)

        _logger.info('統計抓取完成: %s %s', config.name, date_str)
