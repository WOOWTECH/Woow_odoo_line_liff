# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/liff_api.py
# LIFF AJAX API 端點
# 提供 LIFF 前端使用的 JSON API
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LiffApiController(http.Controller):
    """LIFF AJAX API Controller

    提供 LIFF 前端 JavaScript 呼叫的 JSON API。
    所有端點都是 auth='public'，但必須驗證 ID Token。
    """

    def _verify_and_get_line_user(self):
        """從 request 中取得並驗證 LINE 用戶

        讀取 Authorization header 或 POST body 中的 id_token。

        :return: (line_user, error_response) tuple
                 成功時 error_response 為 None，失敗時 line_user 為 None
        """
        id_token = None

        # 優先從 Authorization header 讀取
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            id_token = auth_header[7:]

        # 備用：從 POST body 讀取
        if not id_token:
            try:
                body = json.loads(request.httprequest.get_data(as_text=True))
                id_token = body.get('id_token', '')
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if not id_token:
            return None, Response(
                json.dumps({'error': 'missing_token', 'message': '缺少 ID Token'}),
                status=401, content_type='application/json',
            )

        # 驗證 ID Token
        line_service = request.env['line.api.service'].sudo()
        payload = line_service.verify_id_token(id_token)
        if not payload:
            return None, Response(
                json.dumps({'error': 'invalid_token', 'message': 'ID Token 驗證失敗'}),
                status=401, content_type='application/json',
            )

        line_uid = payload.get('sub')
        if not line_uid:
            return None, Response(
                json.dumps({'error': 'no_uid', 'message': '無法取得 LINE User ID'}),
                status=401, content_type='application/json',
            )

        # 取得或建立 LINE 用戶
        LineUser = request.env['line.user'].sudo()
        line_user = LineUser.create_or_update_from_liff(payload)
        if not line_user:
            return None, Response(
                json.dumps({'error': 'user_error', 'message': '無法建立用戶記錄'}),
                status=500, content_type='application/json',
            )

        return line_user, None

    # ------------------------------------------------------------------
    # API 端點
    # ------------------------------------------------------------------

    @http.route('/api/line/bind', type='http', auth='public',
                methods=['POST'], csrf=False)
    def api_bind(self, **kwargs):
        """綁定 LINE 用戶到 Odoo partner

        POST body:
        {
            "id_token": "...",
            "partner_id": 123  (可選，如果要指定綁定對象)
        }
        """
        line_user, error = self._verify_and_get_line_user()
        if error:
            return error

        # 如果已綁定，回傳現有綁定資訊
        if line_user.partner_id:
            return Response(
                json.dumps({
                    'status': 'already_bound',
                    'partner_id': line_user.partner_id.id,
                    'partner_name': line_user.partner_id.name,
                }, ensure_ascii=False),
                content_type='application/json',
            )

        # 嘗試綁定
        try:
            body = json.loads(request.httprequest.get_data(as_text=True))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}

        # 安全性：禁止指定任意 partner_id 綁定（防止帳號劫持）
        # 僅允許自動建立或 email 匹配綁定
        partner_id = None
            if success:
                return Response(
                    json.dumps({
                        'status': 'bound',
                        'partner_id': line_user.partner_id.id,
                        'partner_name': line_user.partner_id.name,
                    }, ensure_ascii=False),
                    content_type='application/json',
                )
            return Response(
                json.dumps({'error': 'bind_failed', 'message': '綁定失敗'}),
                status=400, content_type='application/json',
            )

        # 無指定 partner_id，自動建立
        email = line_user.email or ''
        name = line_user.display_name or 'LINE User'

        Partner = request.env['res.partner'].sudo()
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                line_user.bind_partner(partner.id)
                return Response(
                    json.dumps({
                        'status': 'bound',
                        'partner_id': partner.id,
                        'partner_name': partner.name,
                    }, ensure_ascii=False),
                    content_type='application/json',
                )

        partner = Partner.create({'name': name, 'email': email})
        line_user.bind_partner(partner.id)

        return Response(
            json.dumps({
                'status': 'created_and_bound',
                'partner_id': partner.id,
                'partner_name': partner.name,
            }, ensure_ascii=False),
            content_type='application/json',
        )

    @http.route('/api/line/me', type='http', auth='public',
                methods=['POST'], csrf=False)
    def api_me(self, **kwargs):
        """取得目前 LINE 用戶資訊

        POST body:
        {
            "id_token": "..."
        }
        """
        line_user, error = self._verify_and_get_line_user()
        if error:
            return error

        data = {
            'line_user_id': line_user.line_user_id,
            'display_name': line_user.display_name or '',
            'picture_url': line_user.picture_url or '',
            'email': line_user.email or '',
            'is_follower': line_user.is_follower,
            'notification_enabled': line_user.notification_enabled,
            'partner': None,
        }

        if line_user.partner_id:
            data['partner'] = {
                'id': line_user.partner_id.id,
                'name': line_user.partner_id.name,
                'email': line_user.partner_id.email or '',
                'phone': line_user.partner_id.phone or '',
                'has_line_bound': line_user.partner_id.has_line_bound,
            }

        return Response(
            json.dumps(data, ensure_ascii=False),
            content_type='application/json',
        )

    @http.route('/api/line/notification/toggle', type='http', auth='public',
                methods=['POST'], csrf=False)
    def api_toggle_notification(self, **kwargs):
        """切換 LINE 通知開關

        POST body:
        {
            "id_token": "...",
            "enabled": true/false
        }
        """
        line_user, error = self._verify_and_get_line_user()
        if error:
            return error

        try:
            body = json.loads(request.httprequest.get_data(as_text=True))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}

        enabled = body.get('enabled', True)
        line_user.write({'notification_enabled': bool(enabled)})

        return Response(
            json.dumps({
                'status': 'ok',
                'notification_enabled': line_user.notification_enabled,
            }),
            content_type='application/json',
        )
