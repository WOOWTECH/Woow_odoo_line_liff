# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_richmenu.py
# Rich Menu 管理 — 建立/上傳/綁定/刪除/Tab 切換
import base64
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LineRichMenu(models.Model):
    """LINE Rich Menu 管理"""
    _name = 'line.richmenu'
    _description = 'LINE Rich Menu'
    _order = 'sequence, id desc'

    name = fields.Char('名稱', required=True)
    sequence = fields.Integer('排序', default=10)
    chat_bar_text = fields.Char('底部按鈕文字', default='選單',
        help='聊天室底部顯示的文字')
    size = fields.Selection([
        ('full', '大 (2500×1686)'),
        ('compact', '小 (2500×843)'),
    ], string='尺寸', default='full', required=True)
    selected = fields.Boolean('預設展開', default=True,
        help='用戶打開聊天室時選單是否自動展開')
    image = fields.Binary('選單圖片', attachment=True)
    image_filename = fields.Char('圖片檔名')

    # LINE 平台資料
    line_richmenu_id = fields.Char('LINE Rich Menu ID', readonly=True, copy=False)
    is_default = fields.Boolean('預設選單', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', '草稿'),
        ('uploaded', '已上傳'),
        ('active', '啟用中'),
        ('archived', '已封存'),
    ], string='狀態', default='draft', readonly=True, copy=False)

    # 觸按區域
    area_ids = fields.One2many('line.richmenu.area', 'richmenu_id', string='觸按區域')
    # 別名（Tab 切換用）
    alias_ids = fields.One2many('line.richmenu.alias', 'richmenu_id', string='別名')

    # 統計
    linked_user_count = fields.Integer('綁定用戶數', compute='_compute_linked_user_count')

    @api.depends('line_richmenu_id')
    def _compute_linked_user_count(self):
        for menu in self:
            menu.linked_user_count = self.env['line.user'].sudo().search_count([
                ('current_richmenu_id', '=', menu.id),
            ]) if menu.id else 0

    # ------------------------------------------------------------------
    # 業務方法
    # ------------------------------------------------------------------

    def _get_size_dict(self):
        if self.size == 'full':
            return {'width': 2500, 'height': 1686}
        return {'width': 2500, 'height': 843}

    def _build_menu_data(self):
        """組裝 LINE Rich Menu API 的 JSON body"""
        areas = []
        for area in self.area_ids:
            action = area._build_action()
            areas.append({
                'bounds': {
                    'x': area.x, 'y': area.y,
                    'width': area.width, 'height': area.height,
                },
                'action': action,
            })

        return {
            'size': self._get_size_dict(),
            'selected': self.selected,
            'name': self.name,
            'chatBarText': self.chat_bar_text or '選單',
            'areas': areas,
        }

    def action_create_on_line(self):
        """建立 Rich Menu + 上傳圖片到 LINE"""
        self.ensure_one()
        if not self.area_ids:
            raise UserError('請至少定義一個觸按區域')
        if not self.image:
            raise UserError('請上傳選單圖片')

        api = self.env['line.api.service']

        # 建立
        menu_data = self._build_menu_data()
        richmenu_id = api.richmenu_create(menu_data)
        if not richmenu_id:
            raise UserError('LINE Rich Menu 建立失敗，請檢查 API 金鑰')

        # 上傳圖片
        image_data = base64.b64decode(self.image)
        content_type = 'image/png'
        if self.image_filename and self.image_filename.lower().endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'

        success = api.richmenu_upload_image(richmenu_id, image_data, content_type)
        if not success:
            # 清理已建立的 menu
            api.richmenu_delete(richmenu_id)
            raise UserError('圖片上傳失敗，請確認圖片尺寸符合要求')

        self.write({
            'line_richmenu_id': richmenu_id,
            'state': 'uploaded',
        })
        _logger.info('Rich Menu 建立成功: %s → %s', self.name, richmenu_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rich Menu',
                'message': f'已成功建立並上傳到 LINE（{richmenu_id}）',
                'type': 'success',
            },
        }

    def action_set_as_default(self):
        """設為所有用戶的預設選單"""
        self.ensure_one()
        if not self.line_richmenu_id:
            raise UserError('請先上傳到 LINE')

        api = self.env['line.api.service']

        # 取消其他預設
        for other in self.search([('is_default', '=', True), ('id', '!=', self.id)]):
            other.write({'is_default': False, 'state': 'uploaded'})

        success = api.richmenu_set_default(self.line_richmenu_id)
        if not success:
            raise UserError('設定預設 Rich Menu 失敗')

        self.write({'is_default': True, 'state': 'active'})

    def action_clear_default(self):
        """取消預設"""
        self.ensure_one()
        api = self.env['line.api.service']
        api.richmenu_clear_default()
        self.write({'is_default': False, 'state': 'uploaded'})

    def action_link_to_users(self):
        """綁定到選定的 LINE 用戶（打開選擇視窗）"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '選擇要綁定的 LINE 用戶',
            'res_model': 'line.user',
            'view_mode': 'list',
            'target': 'new',
            'context': {
                'default_current_richmenu_id': self.id,
                'richmenu_link_mode': True,
            },
        }

    def action_archive(self):
        """從 LINE 刪除並封存"""
        self.ensure_one()
        if self.line_richmenu_id:
            api = self.env['line.api.service']
            if self.is_default:
                api.richmenu_clear_default()
            api.richmenu_delete(self.line_richmenu_id)
        self.write({
            'state': 'archived',
            'is_default': False,
            'line_richmenu_id': False,
        })

    def action_preview(self):
        """綁定到管理員自己的 LINE 預覽"""
        self.ensure_one()
        if not self.line_richmenu_id:
            raise UserError('請先上傳到 LINE')
        # 取得管理員的 LINE User ID（從 ir.config_parameter）
        admin_uid = self.env['ir.config_parameter'].sudo().get_param(
            'woow_line_base.admin_line_user_id', '')
        if not admin_uid:
            raise UserError('請在設定中填入管理員的 LINE User ID')
        api = self.env['line.api.service']
        success = api.richmenu_link_to_user(self.line_richmenu_id, admin_uid)
        if success:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Rich Menu', 'message': '已綁定到您的 LINE 帳號，請查看', 'type': 'info'},
            }
        raise UserError('綁定失敗，請確認 LINE User ID 正確')


class LineRichMenuArea(models.Model):
    """Rich Menu 觸按區域"""
    _name = 'line.richmenu.area'
    _description = 'Rich Menu 觸按區域'
    _order = 'sequence'

    richmenu_id = fields.Many2one('line.richmenu', string='Rich Menu',
        required=True, ondelete='cascade')
    sequence = fields.Integer('排序', default=10)
    label = fields.Char('標籤', help='按鈕名稱（用於後台辨識）')

    # 座標
    x = fields.Integer('X', required=True, default=0)
    y = fields.Integer('Y', required=True, default=0)
    width = fields.Integer('寬', required=True, default=833)
    height = fields.Integer('高', required=True, default=843)

    # 動作
    action_type = fields.Selection([
        ('uri', '開啟 URL'),
        ('liff_portal', '開啟 Portal 頁面'),
        ('message', '傳送訊息'),
        ('postback', 'Postback'),
        ('datetimepicker', '日期選擇'),
        ('richmenuswitch', '切換 Rich Menu'),
        ('clipboard', '複製文字'),
    ], string='動作類型', required=True, default='uri')

    action_portal_path = fields.Char(
        'Portal 路徑', help='例如 /home、/book、/my-bookings、/profile')
    action_uri = fields.Char('URL')
    action_text = fields.Char('訊息文字')
    action_data = fields.Char('Postback Data')
    action_richmenu_alias = fields.Char('目標 Rich Menu Alias')
    action_clipboard_text = fields.Char('複製文字')
    action_mode = fields.Selection([
        ('date', '日期'), ('time', '時間'), ('datetime', '日期時間'),
    ], string='選擇器模式', default='date')

    def _get_portal_url(self):
        """組合 LIFF Portal URL"""
        path = (self.action_portal_path or '').lstrip('/')
        ICP = self.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')
        if liff_id:
            return f'https://liff.line.me/{liff_id}/{path}'
        base_url = ICP.get_param('web.base.url', '')
        return f'{base_url}/liff/redirect/{path}'

    def _build_action(self):
        """組裝 LINE action object"""
        action = {'type': self.action_type}
        if self.label:
            action['label'] = self.label

        if self.action_type == 'uri':
            action['uri'] = self.action_uri or '#'
        elif self.action_type == 'liff_portal':
            action['type'] = 'uri'
            action['uri'] = self._get_portal_url()
        elif self.action_type == 'message':
            action['text'] = self.action_text or ''
        elif self.action_type == 'postback':
            action['data'] = self.action_data or ''
        elif self.action_type == 'datetimepicker':
            action['data'] = self.action_data or 'datetime_select'
            action['mode'] = self.action_mode or 'date'
        elif self.action_type == 'richmenuswitch':
            action['richMenuAliasId'] = self.action_richmenu_alias or ''
            action['data'] = self.action_data or 'switch_menu'
        elif self.action_type == 'clipboard':
            action['clipboardText'] = self.action_clipboard_text or ''

        return action


class LineRichMenuAlias(models.Model):
    """Rich Menu 別名（Tab 切換用）"""
    _name = 'line.richmenu.alias'
    _description = 'Rich Menu 別名'

    alias_id = fields.Char('別名 ID', required=True, help='例如 tab-home, tab-service')
    richmenu_id = fields.Many2one('line.richmenu', string='Rich Menu', required=True,
        ondelete='cascade', domain="[('line_richmenu_id', '!=', False)]")
    line_alias_id = fields.Char('LINE Alias ID', readonly=True)

    _sql_constraints = [
        ('alias_id_unique', 'UNIQUE(alias_id)', '別名 ID 必須唯一'),
    ]

    def action_create_on_line(self):
        """建立/更新 Alias 到 LINE"""
        self.ensure_one()
        if not self.richmenu_id.line_richmenu_id:
            raise UserError('關聯的 Rich Menu 尚未上傳到 LINE')

        api = self.env['line.api.service']
        if self.line_alias_id:
            success = api.richmenu_update_alias(self.alias_id, self.richmenu_id.line_richmenu_id)
        else:
            success = api.richmenu_create_alias(self.alias_id, self.richmenu_id.line_richmenu_id)

        if success:
            self.write({'line_alias_id': self.alias_id})
        else:
            raise UserError('Alias 建立/更新失敗')
