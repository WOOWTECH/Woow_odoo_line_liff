# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_richmenu.py
# Rich Menu 管理 — 建立/上傳/綁定/刪除/Tab 切換
import base64
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LineRichMenu(models.Model):
    """LINE Rich Menu 管理"""
    _name = 'line.richmenu'
    _description = 'LINE Rich Menu'
    _order = 'sequence, id desc'

    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        ondelete='cascade',
        default=lambda self: self.env['line.liff.config']._get_default_config(),
        help='此 Rich Menu 屬於的 LINE 設定檔')
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

    def _line_error_message(self, status_code, body):
        """把 LINE 回傳的錯誤 body（通常是 {"message": "..."}）轉成訊息文字"""
        message = ''
        if body:
            try:
                message = json.loads(body).get('message', '')
            except (ValueError, AttributeError, TypeError):
                message = body
        return f'{message}（HTTP {status_code}）' if message else f'HTTP {status_code}'

    def _build_and_upload_to_line(self):
        """在 LINE 建立新選單並上傳圖片，回傳新的 richMenuId。

        H-7：不會動到 self 現有的 line_richmenu_id / state — 呼叫端決定新選單
        建好之後才切換過去，也才可以刪掉舊選單。失敗時清掉已建立的部份（若
        有），並拋出帶 LINE 實際錯誤訊息的 UserError。
        """
        if not self.area_ids:
            raise UserError('請至少定義一個觸按區域')
        if not self.image:
            raise UserError('請上傳選單圖片')

        api = self.env['line.api.service']

        # 建立
        menu_data = self._build_menu_data()
        richmenu_id, status_code, body = api.richmenu_create_ex(menu_data)
        if not richmenu_id:
            raise UserError(
                f'LINE Rich Menu 建立失敗：{self._line_error_message(status_code, body)}')

        # 上傳圖片
        image_data = base64.b64decode(self.image)
        content_type = 'image/png'
        if self.image_filename and self.image_filename.lower().endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'

        success = api.richmenu_upload_image(richmenu_id, image_data, content_type)
        if not success:
            # 清理已建立的 menu，不留半成品在 LINE 上
            api.richmenu_delete(richmenu_id)
            raise UserError('圖片上傳失敗，請確認圖片尺寸符合要求')

        return richmenu_id

    def _upload_success_notification(self, richmenu_id):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rich Menu',
                'message': f'已成功建立並上傳到 LINE（{richmenu_id}）',
                'type': 'success',
            },
        }

    def action_create_on_line(self):
        """建立 Rich Menu + 上傳圖片到 LINE"""
        self.ensure_one()
        richmenu_id = self._build_and_upload_to_line()
        self.write({
            'line_richmenu_id': richmenu_id,
            'state': 'uploaded',
        })
        _logger.info('Rich Menu 建立成功: %s → %s', self.name, richmenu_id)
        return self._upload_success_notification(richmenu_id)

    def action_reupload_to_line(self):
        """重新上傳 Rich Menu 到 LINE（先建好新的 → 成功後才刪舊的 → 重新綁定用戶）

        H-7：舊版先刪 LINE 上的選單再重建；重建失敗（tap area 不合法、圖片
        太大或比例不對）時 Odoo 會 rollback，但 LINE 上的刪除沒辦法復原——
        結果是所有好友都失去選單，Odoo 卻還顯示為啟用中。新順序：新選單建好
        （create → 上傳圖片 → 設預設/別名）才刪舊的；建立失敗就保留舊選單原
        封不動，並把 LINE 的實際錯誤訊息秀給使用者。
        """
        self.ensure_one()
        api = self.env['line.api.service']

        old_richmenu_id = self.line_richmenu_id
        was_default = self.is_default
        # 找出所有綁定此 Rich Menu 的用戶（reupload 後需要重新綁定）
        linked_users = self.env['line.user'].search([
            ('current_richmenu_id', '=', self.id),
            ('is_follower', '=', True),
            ('line_user_id', '!=', False),
        ])

        # 先建好新的；失敗會拋 UserError，這裡完全沒動到舊選單
        new_richmenu_id = self._build_and_upload_to_line()

        self.write({
            'line_richmenu_id': new_richmenu_id,
            'state': 'uploaded',
            'is_default': False,
        })

        # 如果之前是預設，自動重設為預設
        if was_default:
            self.action_set_as_default()

        # 重新綁定所有之前指定的用戶
        if linked_users:
            uids = linked_users.mapped('line_user_id')
            for i in range(0, len(uids), 500):
                batch = uids[i:i + 500]
                api.richmenu_link_to_users(new_richmenu_id, batch)
            _logger.info(
                'Rich Menu reupload: 重新綁定 %d 位用戶 → %s',
                len(uids), self.name)

        # 新選單已經生效，這時候才刪舊的
        if old_richmenu_id:
            api.richmenu_delete(old_richmenu_id)
            _logger.info('Rich Menu 已刪除舊版: %s', old_richmenu_id)

        return self._upload_success_notification(new_richmenu_id)

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

    def _delete_on_line_or_raise(self, richmenu_id):
        """刪除 LINE 上的 Rich Menu；200 或 404（已經不存在）視為成功。

        H-8：舊版把刪除結果丟掉，導致刪不掉的選單留在 LINE 上，佔掉
        1000 個選單的額度卻再也管不到。失敗時拋出 UserError，讓呼叫端保留
        記錄與其 LINE 連結不變。
        """
        api = self.env['line.api.service']
        ok, status_code, body = api.richmenu_delete_ex(richmenu_id)
        if ok or status_code == 404:
            return
        raise UserError(
            f'刪除 LINE Rich Menu 失敗：{self._line_error_message(status_code, body)}')

    def action_archive(self):
        """從 LINE 刪除並封存"""
        self.ensure_one()
        if self.line_richmenu_id:
            api = self.env['line.api.service']
            if self.is_default:
                api.richmenu_clear_default()
            self._delete_on_line_or_raise(self.line_richmenu_id)
        self.write({
            'state': 'archived',
            'is_default': False,
            'line_richmenu_id': False,
        })

    def unlink(self):
        """刪除前先刪 LINE 上的選單；刪不掉就整批拒絕，記錄與其 LINE 連結不變

        H-8：管理員原本可以直接刪除記錄，LINE 上的選單完全沒被清掉。
        """
        for menu in self:
            if menu.line_richmenu_id:
                menu._delete_on_line_or_raise(menu.line_richmenu_id)
        return super().unlink()

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

    # 統一值欄位：根據 action_type 填入對應內容
    action_value = fields.Char('值', help=(
        'URL → 完整網址\n'
        'Portal → 路徑如 /home、/book\n'
        '訊息 → 發送的文字\n'
        'Postback → data 字串\n'
        '日期選擇 → data 字串\n'
        '切換 Menu → 目標別名 ID\n'
        '複製文字 → 要複製的內容'
    ))
    action_mode = fields.Selection([
        ('date', '日期'), ('time', '時間'), ('datetime', '日期時間'),
    ], string='模式', default='date')

    # 舊欄位保留供向下相容（新記錄統一用 action_value）
    action_portal_path = fields.Char('Portal 路徑 (舊)')
    action_uri = fields.Char('URL (舊)')
    action_text = fields.Char('訊息文字 (舊)')
    action_data = fields.Char('Postback Data (舊)')
    action_richmenu_alias = fields.Char('Alias (舊)')
    action_clipboard_text = fields.Char('複製文字 (舊)')

    def _get_action_value(self):
        """取得動作值（優先 action_value，向下相容舊欄位）"""
        if self.action_value:
            return self.action_value
        mapping = {
            'uri': self.action_uri,
            'liff_portal': self.action_portal_path,
            'message': self.action_text,
            'postback': self.action_data,
            'datetimepicker': self.action_data,
            'richmenuswitch': self.action_richmenu_alias,
            'clipboard': self.action_clipboard_text,
        }
        return mapping.get(self.action_type) or ''

    def _build_action(self):
        """組裝 LINE action object"""
        action = {'type': self.action_type}
        if self.label:
            action['label'] = self.label
        val = self._get_action_value()

        if self.action_type == 'uri':
            action['uri'] = val or '#'
        elif self.action_type == 'liff_portal':
            action['type'] = 'uri'
            path = (val or '').lstrip('/')
            ICP = self.env['ir.config_parameter'].sudo()
            liff_id = ICP.get_param('woow_odoo_line_liff.liff_id_member', '')
            if liff_id:
                action['uri'] = f'https://liff.line.me/{liff_id}/{path}'
            else:
                base_url = ICP.get_param('web.base.url', '')
                action['uri'] = f'{base_url}/liff/redirect/{path}'
        elif self.action_type == 'message':
            action['text'] = val or ''
        elif self.action_type == 'postback':
            action['data'] = val or ''
        elif self.action_type == 'datetimepicker':
            action['data'] = val or 'datetime_select'
            action['mode'] = self.action_mode or 'date'
        elif self.action_type == 'richmenuswitch':
            action['richMenuAliasId'] = val or ''
            action['data'] = 'switch_menu'
        elif self.action_type == 'clipboard':
            action['clipboardText'] = val or ''

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
