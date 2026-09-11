# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
import logging
import re

_logger = logging.getLogger(__name__)

# H-19：一則訊息就能讓 worker 卡住的災難性回溯（ReDoS）。Python 的 re 沒有
# timeout，odoo:18 image 裡也沒有 regex 套件可以取代，所以用存檔時的靜態檢查
# 擋掉常見的危險寫法，並在比對時（含存檔前就已存在的舊資料）再檢查一次。
MAX_REGEX_PATTERN_LENGTH = 200

_BACKREFERENCE_RE = re.compile(r'\\[1-9]')
# (x+)+ / (x*)* / (x+)* 這類：一個簡單群組（不含更深層括號）裡已經有 +/*，
# 這個群組本身後面又接了 +/*/{ ——巢狀量詞，指數級回溯的典型形狀。
_NESTED_QUANTIFIER_RE = re.compile(r'\([^()]*[+*][^()]*\)\s*[+*{]')
# (x|xy)+ 這類：簡單群組裡有 | 交替，群組本身又被量詞包住。
_ALTERNATION_UNDER_QUANTIFIER_RE = re.compile(r'\([^()]*\|[^()]*\)\s*[+*{]')


def _validate_regex_pattern(pattern):
    """回傳錯誤訊息字串（不安全/無效），或 None（可以安全拿去 re.search）。"""
    if not pattern:
        return '正規表達式不可為空'
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        return f'正規表達式過長（超過 {MAX_REGEX_PATTERN_LENGTH} 字元）'
    try:
        re.compile(pattern)
    except re.error as exc:
        return f'正規表達式無效：{exc}'
    if _BACKREFERENCE_RE.search(pattern):
        return '正規表達式不可包含反向引用（如 \\1）'
    if _NESTED_QUANTIFIER_RE.search(pattern):
        return '正規表達式包含巢狀量詞（如 (x+)+），可能造成災難性回溯'
    if _ALTERNATION_UNDER_QUANTIFIER_RE.search(pattern):
        return '正規表達式包含量詞下的交替（如 (x|xy)+），可能造成災難性回溯'
    return None


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

    @api.constrains('keyword', 'match_type')
    def _check_regex_keyword(self):
        for rec in self:
            if rec.match_type != 'regex':
                continue
            error = _validate_regex_pattern(rec.keyword)
            if error:
                raise ValidationError(error)

    def _is_safe_regex(self):
        """給 webhook 在比對前再檢查一次，跳過存檔限制生效前就存在的舊資料。"""
        self.ensure_one()
        return _validate_regex_pattern(self.keyword) is None
