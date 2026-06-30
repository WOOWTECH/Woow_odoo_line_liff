# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/__init__.py
# Controllers 載入順序很重要：
# 1. webhook（獨立，不依賴其他 controller）
# 2. liff_redirect（核心自動登入機制）
# 3. liff_pages（自建 LIFF 頁面）
# 4. liff_api（AJAX 端點）
from . import webhook
from . import liff_redirect
from . import liff_pages
from . import liff_api
