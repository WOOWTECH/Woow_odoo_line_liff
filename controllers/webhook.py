# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/webhook.py
# LINE Webhook 接收端點
# 接收 LINE Platform 的 Webhook 事件，驗簽後處理
import json
import logging
import re

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LineWebhookController(http.Controller):
    """LINE Webhook Controller

    接收 LINE Platform 的 Webhook 事件。
    安全原則：
    1. 必驗 X-Line-Signature
    2. 1 秒內回 200，業務邏輯不阻塞回應
    """

    @http.route('/line/webhook', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def webhook(self, **kwargs):
        """LINE Webhook 主端點"""
        body_bytes = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Line-Signature', '')

        # 驗證簽章
        api_service = request.env['line.api.service'].sudo()
        if not api_service.verify_webhook_signature(body_bytes, signature):
            _logger.warning('Webhook 簽章驗證失敗')
            return Response('Invalid signature', status=403)

        # 解析 JSON
        try:
            payload = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _logger.warning('Webhook payload 解析失敗')
            return Response('Invalid JSON', status=400)

        # 處理事件
        events = payload.get('events', [])
        for event in events:
            try:
                self._process_event(event)
            except Exception:
                _logger.exception('Webhook 事件處理失敗: %s', event.get('type'))

        return Response('OK', status=200)

    def _process_event(self, event):
        """分派處理單一 Webhook 事件"""
        event_type = event.get('type', '')
        source = event.get('source', {})
        line_uid = source.get('userId', '')

        self._log_event(event, event_type, line_uid)

        handler = getattr(self, f'_handle_{event_type}', None)
        if handler:
            handler(event, line_uid)
        else:
            _logger.debug('未處理的事件類型: %s', event_type)

    def _log_event(self, event, event_type, line_uid):
        """記錄 Webhook 事件到 line.event.log"""
        EventLog = request.env['line.event.log'].sudo()
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

        try:
            EventLog.create({
                'line_user_id': line_user.id if line_user else False,
                'event_type': log_event_type,
                'message_type': message_type,
                'raw_payload': json.dumps(event, ensure_ascii=False),
                'text_content': text_content[:255] if text_content else False,
                'processed': True,
            })

            if line_user:
                line_user.write({'event_count': line_user.event_count + 1})
        except Exception:
            _logger.exception('記錄 Webhook 事件失敗')

    # ------------------------------------------------------------------
    # 事件處理器
    # ------------------------------------------------------------------

    def _handle_follow(self, event, line_uid):
        """處理 follow 事件（加好友）"""
        if not line_uid:
            return

        _logger.info('收到 follow 事件: %s', line_uid)
        LineUser = request.env['line.user'].sudo()

        line_user = LineUser.create_or_update_from_webhook(line_uid)
        from odoo import fields as odoo_fields
        line_user.write({
            'is_follower': True,
            'is_blocked': False,
            'follow_date': line_user.follow_date or odoo_fields.Datetime.now(),
        })

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
        ICP = request.env['ir.config_parameter'].sudo()
        base_url = ICP.get_param('web.base.url', '')
        rebook_path = ICP.get_param('woow_line_bridge.rebook_path', '/liff/redirect/book')
        rebook_url = f'{base_url}{rebook_path}'
        request.env['line.api.service'].sudo().reply(reply_token, [{
            'type': 'text',
            'text': f'請點擊連結重新預約：\n{rebook_url}',
        }])

    def _postback_navigate(self, event, line_uid, params, reply_token):
        """Google Maps 導航（postback）"""
        ICP = request.env['ir.config_parameter'].sudo()
        lat = ICP.get_param('woow_line_bridge.shop_latitude', '')
        lng = ICP.get_param('woow_line_bridge.shop_longitude', '')
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
            ICP = request.env['ir.config_parameter'].sudo()
            reply_text = ICP.get_param('woow_line_bridge.richmenu_contact_text', '歡迎直接傳訊息給我們，將由專人為您服務！')
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
        page = target if target in ('news', 'locations') else 'book'
        url = flex_tmpl._liff_url(page)

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
                try:
                    matched = bool(re.search(rule.keyword, text, re.IGNORECASE))
                except re.error:
                    continue

            if matched:
                ICP = request.env['ir.config_parameter'].sudo()
                placeholders = defaultdict(str, {
                    'shop_name': ICP.get_param('woow_line_bridge.shop_name', ''),
                    'shop_phone': ICP.get_param('woow_line_bridge.shop_phone', ''),
                    'shop_address': ICP.get_param('woow_line_bridge.shop_address', ''),
                    'shop_hours': ICP.get_param('woow_line_bridge.shop_opening_hours', ''),
                })
                try:
                    return rule.response_text.format_map(placeholders)
                except (KeyError, ValueError):
                    return rule.response_text
        return None
