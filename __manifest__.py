# -*- coding: utf-8 -*-
# woow_odoo_line_liff/__manifest__.py
{
    'name': 'WOOW LINE Bridge',
    'version': '18.0.3.1.0',
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
        'data/line_auto_reply_data.xml',
        'data/line_flex_templates.xml',
        'data/mail_template.xml',
        'data/ir_cron.xml',
        # 3. 視圖
        'views/line_liff_config_views.xml',
        'views/line_logs_views.xml',
        'views/line_richmenu_views.xml',
        'views/line_user_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/line_news_views.xml',
        'views/line_auto_reply_views.xml',
        'views/line_audience_tag_views.xml',
        'views/line_insight_log_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'woow_odoo_line_liff/static/src/js/liff_helper.js',
            'woow_odoo_line_liff/static/src/css/liff.css',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
}
