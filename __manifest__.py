# -*- coding: utf-8 -*-
# woow_line_bridge/__manifest__.py
{
    'name': 'WOOW LINE Bridge',
    'version': '18.0.2.0.0',
    'category': 'Marketing',
    'summary': 'LINE LIFF 整合層：通知、Rich Menu、LIFF 跳轉',
    'description': """
        WOOW LINE Bridge
        =================
        LINE LIFF 整合模組，提供：
        - LIFF → Portal 自動登入跳轉
        - LINE Flex Message 通知（灰階通用設計）
        - Rich Menu 管理
        - Webhook 事件處理
        - mail.notification 自動推播 hook
    """,
    'author': 'WOOWTECH',
    'website': 'https://woowtech.io',
    'license': 'LGPL-3',
    'depends': [
        'woow_line_base',
        'portal',
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        # 1. 安全性
        'security/line_security.xml',
        'security/ir.model.access.csv',
        # 2. 資料
        'data/ir_config_parameter.xml',
        'data/line_flex_templates.xml',
        'data/mail_template.xml',
        # 3. 視圖
        'views/liff_base.xml',
        'views/liff_news.xml',
        'views/liff_locations.xml',
        'views/assets.xml',
        'views/line_logs_views.xml',
        'views/line_richmenu_views.xml',
        'views/line_user_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/line_news_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'woow_line_bridge/static/src/js/liff_helper.js',
            'woow_line_bridge/static/src/css/liff.css',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
}
