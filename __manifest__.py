# -*- coding: utf-8 -*-
# woow_line_bridge/__manifest__.py
# LINE 整合模組 - Odoo 18 CE
# 提供 LINE 用戶綁定、Webhook 接收、推播、LIFF 入口頁、事件 hook
{
    'name': 'WOOW LINE Bridge',
    'version': '18.0.1.0.0',
    'category': 'Marketing',
    'summary': 'LINE 平台整合層：用戶綁定、LIFF、推播、Webhook',
    'description': """
        WOOW LINE Bridge
        =================
        LINE 平台整合模組，提供：
        - LINE 用戶與 Odoo partner 綁定
        - LIFF 頁面（會員中心、最新消息、店家位置）
        - LIFF → Portal 自動登入跳轉
        - Webhook 事件處理（follow / unfollow / message）
        - LINE Messaging API 推播
        - 預約事件 LINE 通知 hook

        首個部署客戶：Mark Studio 馬克健身
    """,
    'author': 'WOOWTECH',
    'website': 'https://woowtech.io',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'website',
        'portal',
        'mail',
        'reservation_module',
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
        'data/ir_cron.xml',
        'data/line_flex_templates.xml',
        'data/markstudio_demo_data.xml',
        'data/mail_template.xml',
        # 3. 視圖
        'views/liff_base.xml',
        'views/liff_news.xml',
        'views/liff_locations.xml',
        'views/assets.xml',
        'views/line_logs_views.xml',
        'views/line_user_views.xml',
        'views/res_partner_views.xml',
        'views/appointment_booking_views.xml',
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
