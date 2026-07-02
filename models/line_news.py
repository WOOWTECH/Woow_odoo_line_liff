# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_news.py
# 最新消息 Model — 供 LIFF 頁面和 LINE 推播使用
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineNews(models.Model):
    """最新消息

    在後台撰寫文章，確認後可在 LIFF 新聞頁顯示，
    也可推播 Flex Message 給 LINE 好友。
    支援三種推播方式：Broadcast（全員）、Multicast（批量指定）、Push（逐一）。
    """
    _name = 'line.news'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '最新消息'
    _order = 'published_date desc, create_date desc'
    _rec_name = 'title'

    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        default=lambda self: self.env['line.liff.config']._get_default_config())
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
    is_published = fields.Boolean(
        string='已發佈', compute='_compute_is_published', store=True, index=True,
    )

    # ── 推播設定 ──
    push_method = fields.Selection([
        ('broadcast', '全員推播 (Broadcast)'),
        ('multicast', '指定推播 (Multicast)'),
        ('push', '個別推播 (Push)'),
        ('narrowcast', '精準推播 (Narrowcast)'),
    ], string='推播方式', default='broadcast',
        help='Broadcast: 發給所有好友（60次/小時）\n'
             'Multicast: 批量發給指定用戶（200次/秒，每次500人）\n'
             'Push: 逐一發給指定用戶（200次/秒）\n'
             'Narrowcast: 按分眾標籤精準推播（60次/小時）')
    push_target_ids = fields.Many2many(
        'line.user', string='推播對象',
        domain=[('is_follower', '=', True), ('is_blocked', '=', False)],
        help='Multicast / Push 模式的推播目標。留空則發給所有追蹤中的用戶。')
    push_audience_tag_ids = fields.Many2many(
        'line.audience.tag', string='分眾標籤',
        help='Narrowcast 模式的目標分眾群組')

    line_push_count = fields.Integer(string='LINE 推播次數', default=0)
    line_last_push = fields.Datetime(string='最近推播時間', readonly=True)
    line_last_push_method = fields.Char(string='最近推播方式', readonly=True)
    line_last_push_sent = fields.Integer(string='最近送達人數', readonly=True)
    quota_display = fields.Char(
        string='配額使用量', compute='_compute_quota_display')

    def _compute_quota_display(self):
        """即時查詢 LINE 配額"""
        api = self.env['line.api.service']
        cache = {}
        for rec in self:
            config = rec.config_id
            if not config:
                rec.quota_display = ''
                continue
            key = config.id
            if key not in cache:
                quota = api.get_quota() or {}
                consumption = api.get_quota_consumption() or {}
                total = quota.get('value', 0)
                used = consumption.get('totalUsage', 0)
                if total:
                    cache[key] = f'{used} / {total} 則（剩餘 {total - used}）'
                else:
                    cache[key] = f'已用 {used} 則（無上限）'
            rec.quota_display = cache[key]

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

    # ------------------------------------------------------------------
    # 推播
    # ------------------------------------------------------------------

    def action_push_to_line(self):
        """推播文章到 LINE 好友"""
        self.ensure_one()
        if self.state != 'published':
            return self._push_notification('請先發佈文章再推播', 'warning')

        try:
            flex = self.env['line.flex.template'].build_news_card(self)
            messages = [{
                'type': 'flex',
                'altText': f'最新消息 - {self.title}',
                'contents': flex,
            }]

            method = self.push_method or 'broadcast'
            success, sent_count, actual_method = self._execute_push(messages, method)

            if not success:
                return self._push_notification(
                    '推播失敗：LINE API 回傳錯誤，請檢查 Access Token 或改用 Multicast',
                    'danger')

            self.write({
                'line_push_count': self.line_push_count + 1,
                'line_last_push': fields.Datetime.now(),
                'line_last_push_method': actual_method,
                'line_last_push_sent': sent_count,
            })

            method_label = dict(self._fields['push_method'].selection).get(
                actual_method, actual_method)
            if sent_count:
                msg = f'已透過{method_label}推播給 {sent_count} 位好友（第 {self.line_push_count} 次）'
            else:
                msg = f'已透過{method_label}推播給所有好友（第 {self.line_push_count} 次）'

            return self._push_notification(msg, 'success')

        except Exception:
            _logger.exception('LINE 新聞推播失敗: %s', self.title)
            return self._push_notification('推播失敗，請查看系統日誌', 'danger')

    def _execute_push(self, messages, method):
        """執行推播，回傳 (success, sent_count, actual_method)

        Broadcast 失敗自動降級到 Multicast。
        """
        api = self.env['line.api.service']
        PushLog = self.env['line.push.log'].sudo()

        # ── Broadcast ──
        if method == 'broadcast':
            success = api.broadcast(messages)
            if success:
                self._log_broadcast(PushLog, messages, True)
                return True, 0, 'broadcast'
            # 降級到 multicast
            _logger.info('Broadcast 受限 (429)，自動降級到 Multicast: %s', self.title)
            method = 'multicast'

        # 取得推播目標
        targets = self._get_push_targets()
        if not targets:
            _logger.warning('推播無目標用戶: %s', self.title)
            return False, 0, method

        # ── Multicast ──
        if method == 'multicast':
            uids = [lu.line_user_id for lu in targets]
            success = api.multicast(uids, messages)
            self._log_multicast(PushLog, targets, messages, success)
            return success, len(uids) if success else 0, 'multicast'

        # ── Narrowcast（精準推播）──
        if method == 'narrowcast':
            recipient = None
            if self.push_audience_tag_ids:
                # 確保所有 tag 都已同步到 LINE
                for tag in self.push_audience_tag_ids:
                    if not tag.line_audience_group_id:
                        tag.action_sync_to_line()
                # 用第一個 tag 的 audience group（LINE narrowcast 一次只能指定一個）
                synced = self.push_audience_tag_ids.filtered('line_audience_group_id')
                if synced:
                    recipient = {
                        'type': 'audience',
                        'audienceGroupId': int(synced[0].line_audience_group_id),
                    }
            request_id = api.narrowcast(messages, recipient=recipient)
            if request_id:
                self._log_broadcast(PushLog, messages, True)
                return True, 0, 'narrowcast'
            return False, 0, 'narrowcast'

        # ── Push（逐一）──
        sent_ids = api.push(targets, messages)
        return len(sent_ids) > 0, len(sent_ids), 'push'

    def _get_push_targets(self):
        """取得推播目標 line.user recordset"""
        if self.push_target_ids:
            return self.push_target_ids.filtered(
                lambda lu: lu.is_follower and not lu.is_blocked and lu.notification_enabled)
        return self.env['line.user'].sudo().search([
            ('is_follower', '=', True),
            ('is_blocked', '=', False),
            ('notification_enabled', '=', True),
        ])

    def _log_broadcast(self, PushLog, messages, success):
        """記錄 broadcast 推播"""
        PushLog.create({
            'config_id': self.config_id.id if self.config_id else False,
            'messages': json.dumps(messages, ensure_ascii=False),
            'status_code': 200 if success else 429,
            'response_body': 'broadcast',
            'success': success,
        })

    def _log_multicast(self, PushLog, targets, messages, success):
        """記錄 multicast 推播"""
        PushLog.create({
            'config_id': self.config_id.id if self.config_id else False,
            'messages': json.dumps(messages, ensure_ascii=False),
            'status_code': 200 if success else 0,
            'response_body': f'multicast to {len(targets)} users',
            'success': success,
        })

    def _push_notification(self, message, ntype):
        """回傳 display_notification client action"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'LINE 推播',
                'message': message,
                'type': ntype,
                'sticky': ntype == 'danger',
            },
        }
