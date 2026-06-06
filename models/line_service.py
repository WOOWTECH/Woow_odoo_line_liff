# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_service.py
# LINE API 客戶端服務（AbstractModel）
# 負責：ID Token 驗證、Webhook 簽章驗證、推播 / multicast / broadcast / reply
import hashlib
import hmac
import base64
import json
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

# LINE API 端點
LINE_VERIFY_URL = 'https://api.line.me/oauth2/v2.1/verify'
LINE_PUSH_URL = 'https://api.line.me/v2/bot/message/push'
LINE_MULTICAST_URL = 'https://api.line.me/v2/bot/message/multicast'
LINE_BROADCAST_URL = 'https://api.line.me/v2/bot/message/broadcast'
LINE_REPLY_URL = 'https://api.line.me/v2/bot/message/reply'


class LineService(models.AbstractModel):
    """LINE API 客戶端服務

    所有對 LINE Platform API 的呼叫都集中在這個 AbstractModel，
    其他 model / controller 透過 self.env['line.service'] 取用。
    """
    _name = 'line.service'
    _description = 'LINE API 客戶端服務'

    # ------------------------------------------------------------------
    # 私有輔助方法：讀取設定
    # ------------------------------------------------------------------

    def _get_config(self, key, default=''):
        """從 ir.config_parameter 取得設定值

        :param key: 完整 key（需含 woow_line_bridge. 前綴）
        :param default: 找不到時的預設值
        :return: 設定值字串
        """
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def _get_login_channel_id(self):
        """取得 LINE Login Channel ID"""
        return self._get_config('woow_line_bridge.login_channel_id')

    def _get_login_channel_secret(self):
        """取得 LINE Login Channel Secret"""
        return self._get_config('woow_line_bridge.login_channel_secret')

    def _get_messaging_channel_id(self):
        """取得 Messaging API Channel ID"""
        return self._get_config('woow_line_bridge.messaging_channel_id')

    def _get_messaging_channel_secret(self):
        """取得 Messaging API Channel Secret"""
        return self._get_config('woow_line_bridge.messaging_channel_secret')

    def _get_access_token(self):
        """取得 Messaging API Channel Access Token"""
        return self._get_config('woow_line_bridge.messaging_access_token')

    def _get_auth_headers(self):
        """取得含 Bearer Token 的 HTTP 標頭"""
        token = self._get_access_token()
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }

    # ------------------------------------------------------------------
    # 公開方法：ID Token 驗證
    # ------------------------------------------------------------------

    def verify_id_token(self, id_token):
        """驗證 LINE Login 的 ID Token

        每次都呼叫 LINE verify API，不信任前端傳來的 payload。

        :param id_token: 前端 LIFF 取得的 ID Token
        :return: 驗證成功回傳 payload dict（含 sub, name, picture 等），
                 失敗回傳 None
        """
        channel_id = self._get_login_channel_id()
        if not channel_id:
            _logger.error('LINE Login Channel ID 未設定，無法驗證 ID Token')
            return None

        try:
            resp = requests.post(
                LINE_VERIFY_URL,
                data={
                    'id_token': id_token,
                    'client_id': channel_id,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                _logger.debug('LINE ID Token 驗證成功: sub=%s', payload.get('sub'))
                return payload

            _logger.warning(
                'LINE ID Token 驗證失敗: status=%s, body=%s',
                resp.status_code, resp.text,
            )
            return None

        except requests.RequestException:
            _logger.exception('LINE ID Token 驗證時發生網路錯誤')
            return None

    # ------------------------------------------------------------------
    # 公開方法：Access Token 驗證（ID Token 的備援方案）
    # ------------------------------------------------------------------

    def verify_access_token(self, access_token):
        """用 LIFF Access Token 取得使用者 profile

        當 liff.getIDToken() 回 null（openid scope 未開）時，
        用 liff.getAccessToken() 取得的 access token 呼叫 LINE Profile API，
        同樣可以取得 LINE UID、displayName、pictureUrl。

        :param access_token: LIFF 取得的 access token
        :return: 類似 ID Token payload 的 dict（含 sub, name, picture），
                 失敗回 None
        """
        if not access_token:
            return None

        try:
            # 先驗證 token 有效性
            verify_resp = requests.get(
                'https://api.line.me/oauth2/v2.1/verify',
                params={'access_token': access_token},
                timeout=10,
            )
            if verify_resp.status_code != 200:
                _logger.warning(
                    'Access Token 驗證失敗: status=%s, body=%s',
                    verify_resp.status_code, verify_resp.text,
                )
                return None

            # 用 access token 取得 profile
            profile_resp = requests.get(
                'https://api.line.me/v2/profile',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10,
            )
            if profile_resp.status_code != 200:
                _logger.warning(
                    'Access Token Profile 取得失敗: status=%s, body=%s',
                    profile_resp.status_code, profile_resp.text,
                )
                return None

            profile = profile_resp.json()
            # 轉換成類似 ID Token payload 的格式
            payload = {
                'sub': profile.get('userId', ''),
                'name': profile.get('displayName', ''),
                'picture': profile.get('pictureUrl', ''),
            }
            _logger.debug('Access Token 驗證成功: sub=%s', payload.get('sub'))
            return payload

        except requests.RequestException:
            _logger.exception('Access Token 驗證時發生網路錯誤')
            return None

    # ------------------------------------------------------------------
    # 公開方法：Webhook 簽章驗證
    # ------------------------------------------------------------------

    def verify_webhook_signature(self, body_bytes, signature_header):
        """驗證 LINE Webhook 的 X-Line-Signature

        使用 HMAC-SHA256 + hmac.compare_digest 安全比對。

        :param body_bytes: request body 的原始 bytes
        :param signature_header: HTTP header 中的 X-Line-Signature 值
        :return: True 表示簽章有效，False 表示無效
        """
        channel_secret = self._get_messaging_channel_secret()
        if not channel_secret:
            _logger.error('Messaging Channel Secret 未設定，無法驗證 Webhook 簽章')
            return False

        try:
            hash_value = hmac.new(
                channel_secret.encode('utf-8'),
                body_bytes,
                hashlib.sha256,
            ).digest()
            expected_signature = base64.b64encode(hash_value).decode('utf-8')
            return hmac.compare_digest(expected_signature, signature_header or '')
        except Exception:
            _logger.exception('Webhook 簽章驗證時發生錯誤')
            return False

    # ------------------------------------------------------------------
    # 公開方法：推播
    # ------------------------------------------------------------------

    def push(self, line_users, messages):
        """推播訊息給指定的 line.user recordset

        會自動跳過：
        - is_blocked = True
        - notification_enabled = False
        - is_follower = False

        每次推播都寫入 line.push.log。

        :param line_users: line.user recordset
        :param messages: LINE messages list (dict list)
        :return: 成功送出的 line.user id list
        """
        sent_ids = []
        access_token = self._get_access_token()
        if not access_token:
            _logger.error('Messaging Access Token 未設定，無法推播')
            return sent_ids

        headers = self._get_auth_headers()
        PushLog = self.env['line.push.log'].sudo()

        for lu in line_users:
            # 過濾不該推播的用戶
            if lu.is_blocked:
                _logger.debug('跳過已封鎖用戶: %s', lu.line_user_id)
                continue
            if not lu.notification_enabled:
                _logger.debug('跳過已關閉通知用戶: %s', lu.line_user_id)
                continue
            if not lu.is_follower:
                _logger.debug('跳過非追蹤用戶: %s', lu.line_user_id)
                continue

            payload = {
                'to': lu.line_user_id,
                'messages': messages,
            }

            try:
                resp = requests.post(
                    LINE_PUSH_URL,
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
                success = resp.status_code == 200

                # 寫入推播記錄
                PushLog.create({
                    'line_user_id': lu.id,
                    'messages': json.dumps(messages, ensure_ascii=False),
                    'status_code': resp.status_code,
                    'response_body': resp.text,
                    'success': success,
                })

                if success:
                    sent_ids.append(lu.id)
                    lu.sudo().write({'push_count': lu.push_count + 1})
                    _logger.debug('推播成功: %s', lu.line_user_id)
                else:
                    _logger.warning(
                        '推播失敗: user=%s, status=%s, body=%s',
                        lu.line_user_id, resp.status_code, resp.text,
                    )

            except requests.RequestException:
                _logger.exception('推播時發生網路錯誤: user=%s', lu.line_user_id)
                PushLog.create({
                    'line_user_id': lu.id,
                    'messages': json.dumps(messages, ensure_ascii=False),
                    'status_code': 0,
                    'response_body': 'RequestException',
                    'success': False,
                })

        return sent_ids

    def multicast(self, line_user_ids_list, messages):
        """群發訊息給多個 LINE User ID

        使用 LINE Multicast API（一次最多 500 人）。

        :param line_user_ids_list: LINE user ID 字串 list（非 recordset ID）
        :param messages: LINE messages list
        :return: True 成功 / False 失敗
        """
        access_token = self._get_access_token()
        if not access_token:
            _logger.error('Messaging Access Token 未設定，無法 multicast')
            return False

        if not line_user_ids_list:
            _logger.debug('multicast: 空的用戶列表，略過')
            return True

        headers = self._get_auth_headers()
        PushLog = self.env['line.push.log'].sudo()

        # LINE multicast 一次最多 500 人，分批送出
        batch_size = 500
        all_success = True

        for i in range(0, len(line_user_ids_list), batch_size):
            batch = line_user_ids_list[i:i + batch_size]
            payload = {
                'to': batch,
                'messages': messages,
            }

            try:
                resp = requests.post(
                    LINE_MULTICAST_URL,
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
                success = resp.status_code == 200

                # 記錄（multicast 不關聯單一用戶，line_user_id 留空）
                PushLog.create({
                    'messages': json.dumps(messages, ensure_ascii=False),
                    'status_code': resp.status_code,
                    'response_body': resp.text,
                    'success': success,
                })

                if not success:
                    _logger.warning(
                        'multicast 失敗: status=%s, body=%s',
                        resp.status_code, resp.text,
                    )
                    all_success = False

            except requests.RequestException:
                _logger.exception('multicast 時發生網路錯誤')
                PushLog.create({
                    'messages': json.dumps(messages, ensure_ascii=False),
                    'status_code': 0,
                    'response_body': 'RequestException',
                    'success': False,
                })
                all_success = False

        return all_success

    def broadcast(self, messages):
        """廣播訊息給所有好友

        使用 LINE Broadcast API。

        :param messages: LINE messages list
        :return: True 成功 / False 失敗
        """
        access_token = self._get_access_token()
        if not access_token:
            _logger.error('Messaging Access Token 未設定，無法 broadcast')
            return False

        headers = self._get_auth_headers()
        PushLog = self.env['line.push.log'].sudo()
        payload = {'messages': messages}

        try:
            resp = requests.post(
                LINE_BROADCAST_URL,
                headers=headers,
                json=payload,
                timeout=10,
            )
            success = resp.status_code == 200

            PushLog.create({
                'messages': json.dumps(messages, ensure_ascii=False),
                'status_code': resp.status_code,
                'response_body': resp.text,
                'success': success,
            })

            if not success:
                _logger.warning(
                    'broadcast 失敗: status=%s, body=%s',
                    resp.status_code, resp.text,
                )
            return success

        except requests.RequestException:
            _logger.exception('broadcast 時發生網路錯誤')
            PushLog.create({
                'messages': json.dumps(messages, ensure_ascii=False),
                'status_code': 0,
                'response_body': 'RequestException',
                'success': False,
            })
            return False

    def reply(self, reply_token, messages):
        """回覆訊息（使用 Reply Token）

        Reply Token 只能使用一次，且有時效限制。

        :param reply_token: LINE 事件中的 replyToken
        :param messages: LINE messages list
        :return: True 成功 / False 失敗
        """
        access_token = self._get_access_token()
        if not access_token:
            _logger.error('Messaging Access Token 未設定，無法 reply')
            return False

        headers = self._get_auth_headers()
        payload = {
            'replyToken': reply_token,
            'messages': messages,
        }

        try:
            resp = requests.post(
                LINE_REPLY_URL,
                headers=headers,
                json=payload,
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'reply 失敗: status=%s, body=%s',
                    resp.status_code, resp.text,
                )
            return resp.status_code == 200

        except requests.RequestException:
            _logger.exception('reply 時發生網路錯誤')
            return False
