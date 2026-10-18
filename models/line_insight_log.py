# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_insight_log.py
# LINE 統計紀錄 — 每日自動抓取送達/互動/好友數據
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

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

    _TOKYO_TZ = ZoneInfo('Asia/Tokyo')
    _MAX_BACKFILL_DATES = 31
    _MAX_BACKFILL_CONFIGS = 10
    _MAX_BACKFILL_REQUESTS = 100
    _FETCH_STATES = [
        ('unknown', 'Unknown / unverified'),
        ('ready', 'Ready'),
        ('unready', 'Unready'),
        ('out_of_service', 'Out of service'),
        ('error', 'Error'),
    ]

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

    # 抓取狀態。數值欄位只在對應 API 回傳 ready 時才更新；LINE 會省略
    # 零計數欄位，缺欄在 ready payload 中才是有效 0。非 ready 的列即使顯示
    # 舊值或預設 0，也不可當成該日有效統計。
    fetch_state = fields.Selection([
        ('unknown', 'Unknown / unverified'),
        ('ready', 'Ready'),
        ('partial', 'Partial'),
        ('unready', 'Unready'),
        ('out_of_service', 'Out of service'),
        ('error', 'Error'),
    ], string='抓取狀態', readonly=True, required=True, default='unknown', index=True)
    delivery_fetch_state = fields.Selection(
        _FETCH_STATES, string='送達抓取狀態', readonly=True,
        required=True, default='unknown')
    followers_fetch_state = fields.Selection(
        _FETCH_STATES, string='好友抓取狀態', readonly=True,
        required=True, default='unknown')
    last_fetch_attempt_at = fields.Datetime('最後嘗試時間', readonly=True)
    last_fetch_success_at = fields.Datetime(
        '最後完整成功時間', readonly=True,
        help='送達及好友兩個 Insight API 均回傳 ready 的時間。')
    fetch_error_summary = fields.Char(
        '抓取錯誤摘要', readonly=True, size=512,
        help='不含憑證或 API 原始回應內容的安全摘要。')

    _sql_constraints = [
        ('date_config_unique', 'UNIQUE(date, config_id)',
         '同一天同一設定檔只能有一筆統計'),
    ]

    def init(self):
        """Mark pre-status historical rows as explicitly unverified on module update.

        The static, parameterized update is an idempotent schema-data bridge for
        existing logs; all new rows receive these values through field defaults.
        """
        self.env.cr.execute(
            'UPDATE line_insight_log '
            'SET fetch_state = %s, delivery_fetch_state = %s, '
            'followers_fetch_state = %s '
            'WHERE fetch_state IS NULL OR delivery_fetch_state IS NULL '
            'OR followers_fetch_state IS NULL',
            ('unknown', 'unknown', 'unknown'),
        )

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

    @classmethod
    def _tokyo_today(cls):
        """Return today's calendar date for LINE Insight's Asia/Tokyo boundary."""
        return datetime.now(cls._TOKYO_TZ).date()

    @staticmethod
    def _ready_payload_values(payload, field_map):
        """Return validated non-negative integer values, or None for an invalid payload."""
        if not isinstance(payload, dict):
            return None
        values = {}
        for api_key, field_name in field_map.items():
            # LINE omits a zero metric from otherwise-ready delivery payloads.
            # Explicit nulls and malformed supplied values are still rejected.
            value = 0 if api_key not in payload else payload[api_key]
            # bool is an int subclass but is never a valid Insight count.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            values[field_name] = value
        return values

    @classmethod
    def _normalise_insight_response(cls, payload, field_map, label):
        """Classify a LINE Insight response without exposing its raw body.

        Only a ``status=ready`` payload can update metric fields. Missing metric
        keys in such a response mean valid zeroes; unready/out_of_service
        responses are deliberately not converted into zeroes.
        """
        if not isinstance(payload, dict):
            return 'error', {}, f'{label}: API request failed'

        status = payload.get('status')
        if status == 'ready':
            values = cls._ready_payload_values(payload, field_map)
            if values is not None:
                return 'ready', values, ''
            return 'error', {}, f'{label}: invalid ready payload'
        if status == 'unready':
            return 'unready', {}, f'{label}: API data is unready'
        if status == 'out_of_service':
            return 'out_of_service', {}, f'{label}: API is out of service'
        return 'error', {}, f'{label}: API returned an invalid status'

    @staticmethod
    def _combined_fetch_state(delivery_state, followers_state):
        if delivery_state == followers_state == 'ready':
            return 'ready'
        if 'ready' in (delivery_state, followers_state):
            return 'partial'
        if 'error' in (delivery_state, followers_state):
            return 'error'
        if 'out_of_service' in (delivery_state, followers_state):
            return 'out_of_service'
        return 'unready'

    def _call_insight_api(self, api, method_name, date_str, config, field_map, label):
        """Call one API endpoint and convert transport exceptions to a safe status."""
        try:
            payload = getattr(api, method_name)(
                date_str,
                channel_id=config.messaging_channel_id,
                channel_secret=config.messaging_channel_secret,
            )
        except Exception:  # The scheduler/backfill must continue with other dates/configs.
            _logger.exception('LINE Insight %s request failed: config_id=%s date=%s',
                              label, config.id, date_str)
            return 'error', {}, f'{label}: API request failed'
        return self._normalise_insight_response(payload, field_map, label)

    def _fetch_for_config(self, api, config, date_str, date_val):
        """Fetch and persist one config/date, preserving prior valid metrics on failure.

        The returned dict intentionally contains only scalar, XML-RPC/JSON-safe
        data and never credentials or raw LINE API content.
        """
        delivery_state, delivery_values, delivery_error = self._call_insight_api(
            api, 'get_insight_delivery', date_str, config,
            {
                'apiBroadcast': 'delivery_broadcast',
                'apiPush': 'delivery_push',
                'apiMulticast': 'delivery_multicast',
                'apiNarrowcast': 'delivery_narrowcast',
                'apiReply': 'delivery_reply',
            }, 'delivery')
        followers_state, followers_values, followers_error = self._call_insight_api(
            api, 'get_insight_followers', date_str, config,
            {
                'followers': 'followers',
                'targetedReaches': 'targeted_reaches',
                'blocks': 'blocks',
            }, 'followers')

        now = fields.Datetime.now()
        fetch_state = self._combined_fetch_state(delivery_state, followers_state)
        errors = [error for error in (delivery_error, followers_error) if error]
        vals = {
            'config_id': config.id,
            'date': date_val,
            'fetch_state': fetch_state,
            'delivery_fetch_state': delivery_state,
            'followers_fetch_state': followers_state,
            'last_fetch_attempt_at': now,
            'fetch_error_summary': '; '.join(errors)[:512] or False,
        }
        # Never write a failed endpoint's metrics: old successful values remain
        # intact, and a new non-ready record is clearly marked by fetch_state.
        if delivery_state == 'ready':
            vals.update(delivery_values)
        if followers_state == 'ready':
            vals.update(followers_values)
            # Config is a current dashboard summary. Historical backfills only
            # update their dated log and must not overwrite this current value.
            if date_val == self._tokyo_today() - timedelta(days=1):
                config.sudo().write({
                    'follower_count': followers_values['followers'],
                    'target_reach': followers_values['targeted_reaches'],
                    'blocked_count': followers_values['blocks'],
                    'follower_updated_at': now,
                })
        if fetch_state == 'ready':
            vals['last_fetch_success_at'] = now

        existing = self.sudo().search([
            ('config_id', '=', config.id),
            ('date', '=', date_val),
        ], limit=1)
        if existing:
            existing.write(vals)
            record = existing
        else:
            record = self.sudo().create(vals)

        summary = {
            'config_id': config.id,
            'date': fields.Date.to_string(date_val),
            'fetch_state': fetch_state,
            'delivery_fetch_state': delivery_state,
            'followers_fetch_state': followers_state,
            'updated': bool(delivery_values or followers_values),
            'error_summary': vals['fetch_error_summary'] or '',
            'record_id': record.id,
        }
        _logger.info('LINE Insight fetch: config_id=%s date=%s state=%s',
                     config.id, date_str, fetch_state)
        return summary

    @api.model
    def _cron_fetch_daily_insight(self):
        """排程任務：以 Asia/Tokyo 日期邊界抓取昨天的統計數據。"""
        yesterday_date = self._tokyo_today() - timedelta(days=1)
        yesterday = yesterday_date.strftime('%Y%m%d')
        configs = self.env['line.liff.config'].sudo().search([('active', '=', True)])
        api = self.env['line.api.service']

        for config in configs:
            try:
                self._fetch_for_config(api, config, yesterday, yesterday_date)
            except Exception:
                _logger.exception('LINE Insight fetch failed: config_id=%s date=%s',
                                  config.id, yesterday)

    @api.model
    def backfill_insight(self, dates, config_ids=None):
        """Fetch specified Insight dates for selected active configs.

        Public RPC interface (for controlled operator backfills):
        ``backfill_insight(['YYYY-MM-DD', ...], config_ids=[1, ...])``.
        It requires ``woow_line_base.group_line_manager``, accepts at most 31
        unique dates / 10 configs / 100 config-date requests, rejects future
        Asia/Tokyo dates, upserts by (config_id, date), and returns a list of
        scalar summaries.  No credentials are returned.
        """
        if not self.env.user.has_group('woow_line_base.group_line_manager'):
            raise AccessError('Only LINE managers may backfill LINE Insight data.')

        date_values = self._parse_backfill_dates(dates)
        configs = self._backfill_configs(config_ids)
        if len(date_values) * len(configs) > self._MAX_BACKFILL_REQUESTS:
            raise ValidationError(
                'Too many Insight backfill requests (maximum %d config-date pairs).'
                % self._MAX_BACKFILL_REQUESTS)

        api = self.env['line.api.service']
        summaries = []
        for config in configs:
            for date_val in date_values:
                date_str = date_val.strftime('%Y%m%d')
                try:
                    summaries.append(self._fetch_for_config(api, config, date_str, date_val))
                except Exception:
                    # Do not return exception text: third-party responses can contain
                    # sensitive information. Continue so callers get every other pair.
                    _logger.exception('LINE Insight backfill failed: config_id=%s date=%s',
                                      config.id, date_str)
                    summaries.append({
                        'config_id': config.id,
                        'date': fields.Date.to_string(date_val),
                        'fetch_state': 'error',
                        'delivery_fetch_state': 'error',
                        'followers_fetch_state': 'error',
                        'updated': False,
                        'error_summary': 'Insight persistence failed',
                        'record_id': False,
                    })
        return summaries

    @api.model
    def _parse_backfill_dates(self, dates):
        if not isinstance(dates, (list, tuple)) or not dates:
            raise ValidationError('dates must be a non-empty list of YYYY-MM-DD strings.')
        if len(dates) > self._MAX_BACKFILL_DATES:
            raise ValidationError('At most %d dates may be backfilled at once.' %
                                  self._MAX_BACKFILL_DATES)

        today = self._tokyo_today()
        result = []
        seen = set()
        for value in dates:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValidationError('Each date must use the YYYY-MM-DD format.')
            try:
                date_val = datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError as error:
                raise ValidationError('Each date must be a valid calendar date.') from error
            if date_val > today:
                raise ValidationError('Future Asia/Tokyo dates cannot be backfilled.')
            if date_val not in seen:
                seen.add(date_val)
                result.append(date_val)
        return result

    @api.model
    def _backfill_configs(self, config_ids):
        config_model = self.env['line.liff.config']
        if config_ids is None:
            configs = config_model.search([('active', '=', True)])
            if not configs:
                raise ValidationError('No active LINE configuration is available.')
            return configs

        if not isinstance(config_ids, (list, tuple)) or not config_ids:
            raise ValidationError('config_ids must be a non-empty list of active configuration IDs.')
        if len(config_ids) > self._MAX_BACKFILL_CONFIGS:
            raise ValidationError('At most %d configurations may be backfilled at once.' %
                                  self._MAX_BACKFILL_CONFIGS)
        if any(isinstance(config_id, bool) or not isinstance(config_id, int) or config_id <= 0
               for config_id in config_ids):
            raise ValidationError('config_ids must contain positive integer IDs.')

        requested_ids = list(dict.fromkeys(config_ids))
        configs = config_model.search([
            ('id', 'in', requested_ids),
            ('active', '=', True),
        ])
        if set(configs.ids) != set(requested_ids):
            raise ValidationError('Every requested LINE configuration must exist and be active.')
        return configs
