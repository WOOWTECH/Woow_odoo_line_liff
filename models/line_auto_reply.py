# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging
import re

_logger = logging.getLogger(__name__)


class LineAutoReply(models.Model):
    _name = 'line.auto.reply'
    _description = 'LINE 關鍵字自動回覆'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        ondelete='set null',
        help='指定設定檔專用規則（留空=全域規則）')
    name = fields.Char('名稱', required=True)
    keyword = fields.Char('關鍵字', required=True, help='比對的關鍵字或正規表達式')
    match_type = fields.Selection([
        ('contains', '包含'),
        ('exact', '完全比對'),
        ('regex', '正規表達式'),
    ], string='比對方式', default='contains', required=True)
    response_text = fields.Text(
        '回覆文字', required=True,
        help='可用佔位符：{shop_name}, {shop_phone}, {shop_address}, {shop_hours}',
    )
    active = fields.Boolean('啟用', default=True)
    sequence = fields.Integer('優先順序', default=10, help='數字越小優先度越高')
