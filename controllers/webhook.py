# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/webhook.py
# LINE Webhook 接收端點
# 接收 LINE Platform 的 Webhook 事件，驗簽後非同步處理
# line.service → line.api.service (from woow_line_base)
# line.user, line.event.log (from woow_line_base)
import json
import logging

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
        """LINE Webhook 主端點

        LINE Platform 會將所有事件 POST 到這個 URL。
        """
        # 取得原始 body 與簽章
        body_bytes = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Line-Signature', '')

        # 驗證簽章
        line_service = request.env['line.api.service'].sudo()
        if not line_service.verify_webhook_signature(body_bytes, signature):
            _logger.warning('Webhook 簽章驗證失敗')
            return Response('Invalid signature', status=403)

        # 解析 JSON
        try:
            payload = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _logger.warning('Webhook payload 解析失敗')
            return Response('Invalid JSON', status=400)

        # 處理事件（不阻塞回應）
        events = payload.get('events', [])
        for event in events:
            try:
                self._process_event(event)
            except Exception:
                _logger.exception('Webhook 事件處理失敗: %s', event.get('type'))

        # 必須快速回 200
        return Response('OK', status=200)

    def _process_event(self, event):
        """分派處理單一 Webhook 事件

        :param event: LINE event dict
        """
        event_type = event.get('type', '')
        source = event.get('source', {})
        line_uid = source.get('userId', '')

        # 記錄事件
        self._log_event(event, event_type, line_uid)

        # 根據事件類型分派
        handler = getattr(self, f'_handle_{event_type}', None)
        if handler:
            handler(event, line_uid)
        else:
            _logger.debug('未處理的事件類型: %s', event_type)

    def _log_event(self, event, event_type, line_uid):
        """記錄 Webhook 事件到 line.event.log"""
        EventLog = request.env['line.event.log'].sudo()
        LineUser = request.env['line.user'].sudo()

        # 查找或略過 line_user
        line_user = LineUser.find_by_line_uid(line_uid) if line_uid else LineUser

        # 取得訊息類型
        message_type = False
        message = event.get('message', {})
        if message:
            msg_type = message.get('type', 'other')
            valid_types = ['text', 'image', 'video', 'audio', 'location', 'sticker', 'file']
            message_type = msg_type if msg_type in valid_types else 'other'

        # 取得文字內容
        text_content = message.get('text', '') if message.get('type') == 'text' else ''

        # 對應事件類型到 selection
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

            # 更新用戶事件計數
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

        # 建立或更新用戶
        line_user = LineUser.create_or_update_from_webhook(line_uid)
        line_user.write({
            'is_follower': True,
            'is_blocked': False,
            'follow_date': line_user.follow_date or request.env['line.user']._fields['follow_date'].default,
        })

        # 取得 profile（如果 webhook 沒附帶完整資訊）
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

        # 基本關鍵字回覆
        reply_token = event.get('replyToken')
        if not reply_token:
            return

        line_service = request.env['line.api.service'].sudo()
        response_text = self._match_keyword(text.strip())

        if response_text:
            line_service.reply(reply_token, [{'type': 'text', 'text': response_text}])

    def _handle_postback(self, event, line_uid):
        """處理 postback 事件（來自 Rich Menu 或 Flex Message 按鈕）"""
        data = event.get('postback', {}).get('data', '')
        _logger.debug('收到 postback: user=%s, data=%s', line_uid, data)
        # Phase 2 / 3 擴充

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _fetch_and_update_profile(self, line_user):
        """透過 LINE API 取得用戶 profile 並更新

        :param line_user: line.user record
        """
        import requests as http_requests

        access_token = request.env['line.api.service'].sudo()._get_access_token()
        if not access_token:
            return

        try:
            resp = http_requests.get(
                f'https://api.line.me/v2/bot/profile/{line_user.line_user_id}',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=5,
            )
            if resp.status_code == 200:
                profile = resp.json()
                line_user.write({
                    'display_name': profile.get('displayName', line_user.display_name),
                    'picture_url': profile.get('pictureUrl', line_user.picture_url),
                    'status_message': profile.get('statusMessage', line_user.status_message),
                })
        except Exception:
            _logger.exception('取得 LINE profile 失敗: %s', line_user.line_user_id)

    def _match_keyword(self, text):
        """比對關鍵字並回覆

        :param text: 用戶輸入的文字
        :return: 回覆文字，無比對回 None
        """
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_liff.shop_name', 'Mark Studio 馬克健身')
        shop_phone = ICP.get_param('woow_line_liff.shop_phone', '')
        shop_address = ICP.get_param('woow_line_liff.shop_address', '')

        keywords = {
            '預約': f'請點擊下方選單的「立即預約」，或直接前往我們的預約頁面 🙌',
            '電話': f'{shop_name} 電話：{shop_phone}' if shop_phone else f'請透過 LINE 與我們聯繫',
            '地址': f'{shop_name} 地址：{shop_address}' if shop_address else f'請透過 LINE 與我們聯繫',
            '營業時間': ICP.get_param('woow_line_liff.shop_opening_hours', '請透過 LINE 與我們聯繫'),
            '你好': f'您好！歡迎來到{shop_name} 😊\n有任何問題歡迎隨時詢問！',
            '哈囉': f'您好！歡迎來到{shop_name} 😊\n有任何問題歡迎隨時詢問！',
            'hi': f'您好！歡迎來到{shop_name} 😊\n有任何問題歡迎隨時詢問！',
            'hello': f'您好！歡迎來到{shop_name} 😊\n有任何問題歡迎隨時詢問！',
        }

        text_lower = text.lower()
        for keyword, response in keywords.items():
            if keyword in text_lower:
                return response

        return None
