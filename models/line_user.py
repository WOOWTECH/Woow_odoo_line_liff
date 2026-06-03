# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_user.py
# LINE 用戶 Model：管理 LINE 用戶與 Odoo partner 的綁定關係
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class LineUser(models.Model):
    """LINE 用戶

    每個 LINE 用戶對應一筆記錄，透過 line_user_id (LINE UID) 唯一辨識。
    可綁定至 res.partner，實現 LINE ↔ Odoo 用戶對應。
    """
    _name = 'line.user'
    _description = 'LINE 用戶'
    _rec_name = 'display_name'
    _order = 'last_login desc, create_date desc'

    # ------------------------------------------------------------------
    # 基本資料（來自 LINE Profile）
    # ------------------------------------------------------------------
    line_user_id = fields.Char(
        string='LINE User ID',
        required=True,
        index=True,
        help='LINE 平台的 User ID（U 開頭的字串）',
    )
    display_name = fields.Char(
        string='顯示名稱',
        help='LINE 上的顯示名稱',
    )
    picture_url = fields.Char(
        string='頭像網址',
        help='LINE 用戶頭像圖片 URL',
    )
    status_message = fields.Char(
        string='狀態訊息',
        help='LINE 用戶的狀態訊息',
    )
    email = fields.Char(
        string='Email',
        help='LINE 用戶授權提供的 Email',
    )

    # ------------------------------------------------------------------
    # Odoo 關聯
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        'res.partner',
        string='聯絡人',
        ondelete='set null',
        index=True,
        help='對應的 Odoo 聯絡人',
    )

    # ------------------------------------------------------------------
    # 狀態欄位
    # ------------------------------------------------------------------
    is_follower = fields.Boolean(
        string='追蹤中',
        default=True,
        help='是否為 LINE OA 的追蹤者',
    )
    is_blocked = fields.Boolean(
        string='已封鎖',
        default=False,
        help='是否已被用戶封鎖',
    )
    notification_enabled = fields.Boolean(
        string='啟用通知',
        default=True,
        help='是否允許推播通知',
    )

    # ------------------------------------------------------------------
    # 時間戳記
    # ------------------------------------------------------------------
    follow_date = fields.Datetime(
        string='追蹤時間',
        help='首次加入好友的時間',
    )
    unfollow_date = fields.Datetime(
        string='取消追蹤時間',
        help='取消追蹤或封鎖的時間',
    )
    last_login = fields.Datetime(
        string='最後登入',
        help='最後一次透過 LIFF 登入的時間',
    )
    bound_at = fields.Datetime(
        string='綁定時間',
        help='與 Odoo partner 綁定的時間',
    )

    # ------------------------------------------------------------------
    # 偏好設定
    # ------------------------------------------------------------------
    preferred_lang = fields.Selection(
        selection=[
            ('zh_TW', '繁體中文'),
            ('en_US', 'English'),
            ('ja_JP', '日本語'),
        ],
        string='偏好語言',
        default='zh_TW',
    )

    # ------------------------------------------------------------------
    # 統計欄位
    # ------------------------------------------------------------------
    push_count = fields.Integer(
        string='推播次數',
        default=0,
        help='已推播訊息次數',
    )
    event_count = fields.Integer(
        string='事件次數',
        default=0,
        help='Webhook 事件次數',
    )

    # ------------------------------------------------------------------
    # 預留欄位（未來擴充，目前不啟用）
    # ------------------------------------------------------------------
    # 當 hr 模組安裝時才會有 hr.employee
    # employee_id = fields.Many2one(
    #     'hr.employee',
    #     string='員工',
    #     ondelete='set null',
    # )
    # 當 loyalty 模組安裝時才會有
    # loyalty_card_id = fields.Many2one(...)

    # ------------------------------------------------------------------
    # SQL Constraints
    # ------------------------------------------------------------------
    _sql_constraints = [
        (
            'line_user_id_unique',
            'UNIQUE(line_user_id)',
            'LINE User ID 必須唯一，此 LINE 用戶已存在！',
        ),
    ]

    # ------------------------------------------------------------------
    # 業務方法：推播
    # ------------------------------------------------------------------

    def push_text(self, text):
        """推播純文字訊息

        :param text: 訊息文字
        :return: 成功送出的 line.user id list
        """
        self.ensure_one()
        messages = [{'type': 'text', 'text': text}]
        return self.env['line.service'].push(self, messages)

    def push_messages(self, messages):
        """推播自訂訊息（可包含多則）

        :param messages: LINE message object list
        :return: 成功送出的 line.user id list
        """
        return self.env['line.service'].push(self, messages)

    def push_flex(self, alt_text, contents):
        """推播 Flex Message

        :param alt_text: 替代文字（裝置不支援 Flex 時顯示）
        :param contents: Flex Message 的 contents dict
        :return: 成功送出的 line.user id list
        """
        self.ensure_one()
        messages = [{
            'type': 'flex',
            'altText': alt_text,
            'contents': contents,
        }]
        return self.env['line.service'].push(self, messages)

    # ------------------------------------------------------------------
    # 業務方法：綁定 / 解綁
    # ------------------------------------------------------------------

    def bind_partner(self, partner_id):
        """綁定至 Odoo 聯絡人

        :param partner_id: res.partner 的 record ID
        """
        self.ensure_one()
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            _logger.warning('嘗試綁定不存在的 partner: %s', partner_id)
            return False

        self.write({
            'partner_id': partner_id,
            'bound_at': fields.Datetime.now(),
        })
        _logger.info(
            'LINE 用戶 %s 已綁定至 partner %s (%s)',
            self.line_user_id, partner.id, partner.name,
        )
        return True

    def unbind(self):
        """解除與 Odoo 聯絡人的綁定"""
        self.ensure_one()
        old_partner = self.partner_id
        self.write({
            'partner_id': False,
            'bound_at': False,
        })
        _logger.info(
            'LINE 用戶 %s 已解除與 partner %s 的綁定',
            self.line_user_id, old_partner.id if old_partner else 'N/A',
        )
        return True

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @api.model
    def find_by_line_uid(self, line_user_id):
        """根據 LINE User ID 查找記錄

        :param line_user_id: LINE 平台 User ID
        :return: line.user recordset（可能為空）
        """
        return self.sudo().search([('line_user_id', '=', line_user_id)], limit=1)

    @api.model
    def create_or_update_from_webhook(self, line_user_id, profile_data=None):
        """從 Webhook 事件建立或更新 LINE 用戶

        :param line_user_id: LINE User ID
        :param profile_data: dict，可包含 displayName, pictureUrl, statusMessage
        :return: line.user record
        """
        existing = self.find_by_line_uid(line_user_id)
        vals = {
            'line_user_id': line_user_id,
            'is_follower': True,
            'is_blocked': False,
        }

        if profile_data:
            if profile_data.get('displayName'):
                vals['display_name'] = profile_data['displayName']
            if profile_data.get('pictureUrl'):
                vals['picture_url'] = profile_data['pictureUrl']
            if profile_data.get('statusMessage'):
                vals['status_message'] = profile_data['statusMessage']
            if profile_data.get('email'):
                vals['email'] = profile_data['email']

        if existing:
            existing.sudo().write(vals)
            _logger.debug('更新 LINE 用戶: %s', line_user_id)
            return existing
        else:
            vals['follow_date'] = fields.Datetime.now()
            record = self.sudo().create(vals)
            _logger.info('建立新 LINE 用戶: %s', line_user_id)
            return record

    @api.model
    def create_or_update_from_liff(self, id_token_payload):
        """從 LIFF ID Token payload 建立或更新 LINE 用戶

        :param id_token_payload: LINE verify API 回傳的 payload dict
        :return: line.user record
        """
        line_uid = id_token_payload.get('sub')
        if not line_uid:
            _logger.error('ID Token payload 缺少 sub 欄位')
            return self.browse()  # 空 recordset

        existing = self.find_by_line_uid(line_uid)
        vals = {
            'line_user_id': line_uid,
            'last_login': fields.Datetime.now(),
        }

        name = id_token_payload.get('name')
        if name:
            vals['display_name'] = name

        picture = id_token_payload.get('picture')
        if picture:
            vals['picture_url'] = picture

        email = id_token_payload.get('email')
        if email:
            vals['email'] = email

        if existing:
            existing.sudo().write(vals)
            _logger.debug('LIFF 登入更新 LINE 用戶: %s', line_uid)
            return existing
        else:
            vals['follow_date'] = fields.Datetime.now()
            vals['is_follower'] = True
            record = self.sudo().create(vals)
            _logger.info('LIFF 登入建立新 LINE 用戶: %s', line_uid)
            return record
