# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/webhook.py
# LINE Webhook 接收端點
# 接收 LINE Platform 的 Webhook 事件，驗簽後處理
import json
import logging
import re

import psycopg2

from odoo import http
from odoo.http import request, Response

# 併發錯誤：讓它們往外傳播，讓 Odoo 的請求層重試整個 request，
# 而不是在這裡吞掉（吞掉會關閉 Odoo 內建的交易重試）。
_CONCURRENCY_ERRORS = (psycopg2.errors.SerializationFailure,
                       psycopg2.errors.LockNotAvailable)

# H-19：fed to a regex at match time. Caps worst-case backtracking input size
# even for a pattern that looked safe at save time.
_MAX_REGEX_MATCH_TEXT = 500

_logger = logging.getLogger(__name__)


class LineWebhookController(http.Controller):
    """LINE Webhook Controller

    接收 LINE Platform 的 Webhook 事件。
    安全原則：
    1. 必驗 X-Line-Signature
    2. 1 秒內回 200，業務邏輯不阻塞回應
    """

    @http.route(['/line/webhook', '/line/webhook/<int:config_id>'],
                type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def webhook(self, config_id=None, **kwargs):
        """LINE Webhook 主端點（支援 per-config routing）

        路由解析順序：
        1. line.liff.config（bridge 模式）
        2. im_livechat.channel（livechat 獨立模式）
        3. 全域 fallback
        """
        Config = request.env['line.liff.config'].sudo()
        config = None
        lc_channel = None
        channel_secret = None

        # 1) 嘗試 line.liff.config
        if config_id:
            config = Config.browse(config_id)
            if not config.exists() or not config.active:
                config = None
        if not config:
            config = Config._get_default_config()

        if config and config.messaging_channel_secret:
            channel_secret = config.messaging_channel_secret

        # 2) Fallback: 嘗試 im_livechat.channel（livechat 獨立模式）
        LivechatChannel = None if channel_secret else self._livechat_line_channels()
        if LivechatChannel is not None:
            if config_id:
                lc_channel = LivechatChannel.browse(config_id)
                if not lc_channel.exists() or not lc_channel.line_enabled:
                    lc_channel = None
            if not lc_channel:
                lc_channel = LivechatChannel.search(
                    [('line_enabled', '=', True)], limit=1)
            if lc_channel and lc_channel.line_channel_secret:
                channel_secret = lc_channel.line_channel_secret
                _logger.info('Webhook: 使用 LiveChat 頻道 %s 的憑證', lc_channel.name)

        body_bytes = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Line-Signature', '')

        # 驗證簽章
        api_service = request.env['line.api.service'].sudo()
        if channel_secret:
            if not api_service.verify_webhook_signature(
                    body_bytes, signature,
                    channel_secret=channel_secret):
                _logger.warning('Webhook 簽章驗證失敗')
                return Response('Invalid signature', status=403)
        elif not api_service.verify_webhook_signature(body_bytes, signature):
            _logger.warning('Webhook 簽章驗證失敗（無可用 secret）')
            return Response('Invalid signature', status=403)

        # 將 config 存到 request context 供後續 handler 使用
        request._line_config = config

        # 解析 JSON
        try:
            payload = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _logger.warning('Webhook payload 解析失敗')
            return Response('Invalid JSON', status=400)

        # 處理事件：每個 event 各自一個 savepoint，one bad event 不能拖垮
        # 同一個 delivery 裡其他 event 的效果。
        events = payload.get('events', [])
        for event in events:
            self._process_event(event)

        return Response('OK', status=200)

    def _process_event(self, event):
        """分派處理單一 Webhook 事件

        Log 建立 + handler 執行包在同一個 savepoint：成功就把 log 標記為
        processed，失敗就整個回滾（含 log 本身），然後在回滾*之後*另外補一筆
        帶 error_msg 的 log，讓錯誤不會隨著回滾一起消失。
        轉發到 LiveChat 是獨立的第二個 savepoint：無論上面 handler 成功與否都
        會執行，它自己的失敗也不能影響 handler 那一半已經確定的結果。
        併發類錯誤（serialization failure / lock not available）兩段都直接
        往外拋，讓 Odoo 重試整個 request。
        """
        event_type = event.get('type', '')
        source = event.get('source', {})
        line_uid = source.get('userId', '')

        try:
            with request.env.cr.savepoint():
                log = self._log_event(event, event_type, line_uid)
                handler = getattr(self, f'_handle_{event_type}', None)
                if handler:
                    handler(event, line_uid)
                else:
                    _logger.debug('未處理的事件類型: %s', event_type)
                log.write({'processed': True})
        except _CONCURRENCY_ERRORS:
            raise
        except Exception as exc:
            _logger.exception('Webhook 事件處理失敗: %s', event_type)
            self._log_event_error(event, event_type, line_uid, exc)

        try:
            with request.env.cr.savepoint():
                self._forward_to_livechat(event)
        except _CONCURRENCY_ERRORS:
            raise
        except Exception:
            _logger.warning('LiveChat 轉發失敗', exc_info=True)

    def _livechat_line_channels(self):
        """im_livechat.channel (sudo), or None if the LINE bridge fields are absent.

        `line_enabled` / `line_channel_secret` are added to im_livechat.channel
        by woow_odoo_livechat_line, which this module does not depend on. Stock
        im_livechat is often installed on its own (website_livechat pulls it
        in), so checking only that the model exists let the webhook read fields
        that are not there and crash with a 500.

        Returns None rather than an empty recordset because an empty recordset
        is falsy, and callers need to tell "unavailable" apart from "no rows".
        """
        if 'im_livechat.channel' not in request.env:
            return None
        Channel = request.env['im_livechat.channel'].sudo()
        if 'line_enabled' not in Channel._fields:
            return None
        return Channel

    def _forward_to_livechat(self, event):
        """轉發 webhook 事件到 LiveChat LINE 模組（如已安裝）

        解決路由衝突：bridge 的 /line/webhook/<int:config_id> 與
        livechat 的 /line/webhook/<int:channel_id> 共用同一模式，
        bridge 攔截所有請求。因此由 bridge 主動轉發。

        H-5：無論 liff 這邊的 handler 有沒有成功都要跑（呼叫端已經把這個方法
        跟 handler 放在不同的 savepoint 裡）。這裡不吞自己的例外——讓呼叫端
        的 savepoint 接手回滾，並在 WARNING 記錄失敗，而不是像以前一樣用
        debug（正式環境看不到）或直接 pass 掉 ImportError。
        """
        LivechatChannel = self._livechat_line_channels()
        if LivechatChannel is None:
            return
        # 檢查是否有啟用 LINE 的 LiveChat 頻道
        lc_channel = LivechatChannel.search([('line_enabled', '=', True)], limit=1)
        if not lc_channel:
            return
        # 動態載入 LiveChat 控制器（避免硬依賴）
        try:
            from odoo.addons.woow_odoo_livechat_line.controllers.webhook import (
                LineWebhookController as LCController,
            )
        except ImportError:
            return
        LCController()._process_event(event, lc_channel)

    def _event_log_vals(self, event, event_type, line_uid):
        """組出建立 line.event.log 所需的欄位值（不含 processed / error_msg）。

        回傳 (line_user, vals)。抽出來讓 _log_event（正常路徑）跟
        _log_event_error（savepoint 回滾後的錯誤補記）共用同一套邏輯。
        """
        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.find_by_line_uid(line_uid) if line_uid else LineUser

        message_type = False
        message = event.get('message', {})
        if message:
            msg_type = message.get('type', 'other')
            valid_types = ['text', 'image', 'video', 'audio', 'location', 'sticker', 'file']
            message_type = msg_type if msg_type in valid_types else 'other'

        text_content = message.get('text', '') if message.get('type') == 'text' else ''

        valid_event_types = [
            'follow', 'unfollow', 'message', 'postback', 'join', 'leave',
            'memberJoined', 'memberLeft', 'beacon', 'accountLink', 'things',
            'unsend', 'videoPlayComplete',
        ]
        log_event_type = event_type if event_type in valid_event_types else 'other'

        config = getattr(request, '_line_config', None)
        vals = {
            'config_id': config.id if config else False,
            'line_user_id': line_user.id if line_user else False,
            'event_type': log_event_type,
            'message_type': message_type,
            'raw_payload': json.dumps(event, ensure_ascii=False),
            'text_content': text_content[:255] if text_content else False,
        }
        return line_user, vals

    def _bump_event_count(self, line_user):
        """H-3：event_count + 1 是 SQL 層的原子 UPDATE，而不是 ORM 的
        read-modify-write（並發事件不會互相蓋掉彼此的計數）。"""
        if not line_user:
            return
        request.env.flush_all()
        request.env.cr.execute(
            'UPDATE line_user SET event_count = event_count + 1 WHERE id = %s',
            (line_user.id,),
        )
        line_user.invalidate_recordset(['event_count'])

    def _log_event(self, event, event_type, line_uid):
        """記錄 Webhook 事件到 line.event.log，回傳新建立的記錄。

        H-4：一開始 processed=False；呼叫端在 handler 成功後才把它設成 True。
        DB 層的例外（若有）會往外傳播，由呼叫端的 savepoint 接手。
        """
        EventLog = request.env['line.event.log'].sudo()
        line_user, vals = self._event_log_vals(event, event_type, line_uid)
        vals['processed'] = False
        log = EventLog.create(vals)
        self._bump_event_count(line_user)
        return log

    def _log_event_error(self, event, event_type, line_uid, exc):
        """H-3/H-4：這個事件的 savepoint 已經回滾（含它原本的 log 列），
        在回滾*之後*另外補一筆帶 error_msg 的記錄，讓錯誤不會被一起吞掉。
        只記錄例外類別與訊息，不記錄原始 payload/文字內容。
        """
        EventLog = request.env['line.event.log'].sudo()
        line_user, vals = self._event_log_vals(event, event_type, line_uid)
        vals['processed'] = False
        vals['error_msg'] = f'{type(exc).__name__}: {exc}'
        EventLog.create(vals)
        self._bump_event_count(line_user)

    # ------------------------------------------------------------------
    # 事件處理器
    # ------------------------------------------------------------------

    def _handle_follow(self, event, line_uid):
        """處理 follow 事件（加好友）"""
        if not line_uid:
            return

        _logger.info('收到 follow 事件: %s', line_uid)
        LineUser = request.env['line.user'].sudo()

        config = getattr(request, '_line_config', None)
        line_user = LineUser.create_or_update_from_webhook(
            line_uid,
            messaging_channel_id=config.messaging_channel_id if config else None,
            messaging_channel_name=config.name if config else None,
        )
        from odoo import fields as odoo_fields
        update_vals = {
            'is_follower': True,
            'is_blocked': False,
            'follow_date': line_user.follow_date or odoo_fields.Datetime.now(),
        }
        if config and hasattr(line_user, 'liff_config_id'):
            update_vals['liff_config_id'] = config.id
        line_user.write(update_vals)

        self._fetch_and_update_profile(line_user)

        # 推送歡迎訊息
        try:
            flex = request.env['line.flex.template'].sudo().build_welcome(
                display_name=line_user.display_name or '',
            )
            reply_token = event.get('replyToken')
            if reply_token:
                messages = [{
                    'type': 'flex',
                    'altText': f'歡迎來到{request.env["line.flex.template"].sudo()._get_shop_name()}',
                    'contents': flex,
                }]
                request.env['line.api.service'].sudo().reply(reply_token, messages)
            _logger.info('已發送歡迎訊息: %s', line_uid)
        except Exception:
            _logger.exception('發送歡迎訊息失敗: %s', line_uid)

    def _handle_unfollow(self, event, line_uid):
        """處理 unfollow 事件（封鎖/取消追蹤）"""
        if not line_uid:
            return

        _logger.info('收到 unfollow 事件: %s', line_uid)
        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.find_by_line_uid(line_uid)

        if line_user:
            from odoo import fields as odoo_fields
            line_user.write({
                'is_follower': False,
                'is_blocked': True,
                'unfollow_date': odoo_fields.Datetime.now(),
            })

    def _handle_message(self, event, line_uid):
        """處理 message 事件"""
        message = event.get('message', {})
        msg_type = message.get('type', '')
        text = message.get('text', '')

        if msg_type != 'text' or not text:
            return

        _logger.debug('收到文字訊息: user=%s, text=%s', line_uid, text[:50])

        reply_token = event.get('replyToken')
        if not reply_token:
            return

        api_service = request.env['line.api.service'].sudo()
        response_text = self._match_keyword(text.strip())

        if response_text:
            api_service.reply(reply_token, [{'type': 'text', 'text': response_text}])

    def _handle_postback(self, event, line_uid):
        """處理 postback 事件（來自 Rich Menu 或 Flex Message 按鈕）

        Postback data 格式：action=xxx&key=value&...
        支援的 action：
        - cancel_booking: 取消預約（需 appointment.booking 模型存在）
        - view_booking: 查看預約詳情（需 appointment.booking 模型存在）
        - rebook: 重新預約
        - navigate: Google Maps 導航
        - richmenu: Rich Menu 選單項目
        """
        data_str = event.get('postback', {}).get('data', '')
        reply_token = event.get('replyToken')
        _logger.info('收到 postback: user=%s, data=%s', line_uid, data_str)

        if not data_str or not reply_token:
            return

        params = {}
        for item in data_str.split('&'):
            if '=' in item:
                k, v = item.split('=', 1)
                params[k] = v

        action = params.get('action', '')
        handler = getattr(self, f'_postback_{action}', None)
        if handler:
            handler(event, line_uid, params, reply_token)
        else:
            _logger.debug('未處理的 postback action: %s', action)

    # ------------------------------------------------------------------
    # Postback 處理器
    # ------------------------------------------------------------------

    def _postback_cancel_booking(self, event, line_uid, params, reply_token):
        """取消預約（postback）— 需 appointment.booking 模型"""
        # 安全檢查：模型是否存在
        if 'appointment.booking' not in request.env:
            _logger.debug('appointment.booking 模型不存在，跳過 cancel_booking')
            return

        booking_id = params.get('booking_id')
        if not booking_id:
            return
        try:
            booking_id = int(booking_id)
        except ValueError:
            return

        Booking = request.env['appointment.booking'].sudo()
        booking = Booking.browse(booking_id)
        if not booking.exists() or booking.state != 'confirmed':
            request.env['line.api.service'].sudo().reply(reply_token, [{
                'type': 'text',
                'text': '此預約無法取消（可能已取消或不存在）',
            }])
            return

        if not self._verify_booking_ownership(line_uid, booking):
            return

        booking.with_context(skip_line_notification=True).action_cancel()

        flex = request.env['line.flex.template'].sudo().build_booking_cancelled(booking)
        request.env['line.api.service'].sudo().reply(reply_token, [{
            'type': 'flex',
            'altText': f'預約已取消 - {booking.name}',
            'contents': flex,
        }])

    def _postback_view_booking(self, event, line_uid, params, reply_token):
        """查看預約詳情（postback）— 需 appointment.booking 模型"""
        if 'appointment.booking' not in request.env:
            _logger.debug('appointment.booking 模型不存在，跳過 view_booking')
            return

        booking_id = params.get('booking_id')
        if not booking_id:
            return
        try:
            booking_id = int(booking_id)
        except ValueError:
            return

        Booking = request.env['appointment.booking'].sudo()
        booking = Booking.browse(booking_id)
        if not booking.exists():
            return

        # 擁有者驗證：確認此 LINE 用戶有權查看此預約
        if not self._verify_booking_ownership(line_uid, booking):
            _logger.warning('view_booking: LINE user %s not owner of booking %s', line_uid, booking_id)
            return

        flex = request.env['line.flex.template'].sudo().build_booking_confirmed(booking)
        request.env['line.api.service'].sudo().reply(reply_token, [{
            'type': 'flex',
            'altText': f'預約詳情 - {booking.name}',
            'contents': flex,
        }])

    def _postback_rebook(self, event, line_uid, params, reply_token):
        """重新預約（postback）"""
        config = getattr(request, '_line_config', None)
        ICP = request.env['ir.config_parameter'].sudo()
        base_url = ICP.get_param('web.base.url', '')
        rebook_path = (config.rebook_path if config and config.rebook_path
                        else ICP.get_param('woow_odoo_line_liff.rebook_path', '/liff/redirect/book'))
        rebook_url = f'{base_url}{rebook_path}'
        request.env['line.api.service'].sudo().reply(reply_token, [{
            'type': 'text',
            'text': f'請點擊連結重新預約：\n{rebook_url}',
        }])

    def _postback_navigate(self, event, line_uid, params, reply_token):
        """Google Maps 導航（postback）"""
        config = getattr(request, '_line_config', None)
        if config:
            lat, lng = config.shop_latitude or '', config.shop_longitude or ''
        else:
            ICP = request.env['ir.config_parameter'].sudo()
            lat = ICP.get_param('woow_odoo_line_liff.shop_latitude', '')
            lng = ICP.get_param('woow_odoo_line_liff.shop_longitude', '')
        if lat and lng:
            nav_url = f'https://www.google.com/maps/dir/?api=1&destination={lat},{lng}'
            request.env['line.api.service'].sudo().reply(reply_token, [{
                'type': 'text',
                'text': f'Google 地圖導航：\n{nav_url}',
            }])

    def _postback_richmenu(self, event, line_uid, params, reply_token):
        """Rich Menu 選單項目（postback）"""
        target = params.get('target', '')
        flex_tmpl = request.env['line.flex.template'].sudo()

        if target == 'contact':
            config = getattr(request, '_line_config', None)
            if config and config.richmenu_contact_text:
                reply_text = config.richmenu_contact_text
            else:
                ICP = request.env['ir.config_parameter'].sudo()
                reply_text = ICP.get_param('woow_odoo_line_liff.richmenu_contact_text', '歡迎直接傳訊息給我們，將由專人為您服務！')
            request.env['line.api.service'].sudo().reply(reply_token, [{
                'type': 'text',
                'text': reply_text,
            }])
            return

        target_labels = {
            'book': '立即預約',
            'my-bookings': '我的預約',
            'news': '最新消息',
            'locations': '店家位置',
        }
        label = target_labels.get(target, '立即預約')
        if target in ('news', 'locations'):
            url = flex_tmpl._liff_url(target)
        else:
            # Booking targets open through the member LIFF redirect bridge.
            # _liff_url() looks up one LIFF app per page name, and there is no
            # `liff_id_book`, so it fell back to /liff/book — a route that does
            # not exist, which handed the customer a 404.
            url = flex_tmpl._liff_redirect_url(
                target if target in target_labels else 'book')

        request.env['line.api.service'].sudo().reply(reply_token, [{
            'type': 'text',
            'text': f'請點擊連結前往{label}：\n{url}',
        }])

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _verify_booking_ownership(self, line_uid, booking):
        """驗證預約屬於此 LINE 用戶"""
        if not line_uid or not booking.partner_id:
            return False
        line_user = request.env['line.user'].sudo().find_by_line_uid(line_uid)
        if not line_user or not line_user.partner_id:
            return False
        return line_user.partner_id.id == booking.partner_id.id

    def _fetch_and_update_profile(self, line_user):
        """透過 LINE API 取得用戶 profile 並更新"""
        api_service = request.env['line.api.service'].sudo()
        profile = api_service.get_profile(line_user.line_user_id)
        if profile:
            line_user.write({
                'display_name': profile.get('displayName', line_user.display_name),
                'picture_url': profile.get('pictureUrl', line_user.picture_url),
                'status_message': profile.get('statusMessage', line_user.status_message),
            })

    def _match_keyword(self, text):
        """比對 DB 關鍵字規則並回覆"""
        from collections import defaultdict
        AutoReply = request.env['line.auto.reply'].sudo()
        rules = AutoReply.search([('active', '=', True)], order='sequence, id')
        text_lower = text.lower().strip()

        for rule in rules:
            kw = rule.keyword.lower().strip()
            matched = False
            if rule.match_type == 'contains':
                matched = kw in text_lower
            elif rule.match_type == 'exact':
                matched = kw == text_lower
            elif rule.match_type == 'regex':
                # H-19：@api.constrains 只擋得到「之後」新存的規則；存在較舊
                # 資料裡的危險 pattern 要在真的拿去跑 re.search 之前再擋一次。
                if not rule._is_safe_regex():
                    _logger.warning(
                        '略過不安全的正規表達式自動回覆規則 id=%s', rule.id)
                    continue
                try:
                    matched = bool(re.search(
                        rule.keyword, text[:_MAX_REGEX_MATCH_TEXT], re.IGNORECASE))
                except re.error:
                    continue

            if matched:
                config = getattr(request, '_line_config', None)
                if config:
                    ph = {
                        'shop_name': config.shop_name or '',
                        'shop_phone': config.shop_phone or '',
                        'shop_address': config.shop_address or '',
                        'shop_hours': config.shop_opening_hours or '',
                    }
                else:
                    ICP = request.env['ir.config_parameter'].sudo()
                    ph = {
                        'shop_name': ICP.get_param('woow_odoo_line_liff.shop_name', ''),
                        'shop_phone': ICP.get_param('woow_odoo_line_liff.shop_phone', ''),
                        'shop_address': ICP.get_param('woow_odoo_line_liff.shop_address', ''),
                        'shop_hours': ICP.get_param('woow_odoo_line_liff.shop_opening_hours', ''),
                    }
                placeholders = defaultdict(str, ph)
                try:
                    return rule.response_text.format_map(placeholders)
                except (KeyError, ValueError):
                    return rule.response_text
        return None
