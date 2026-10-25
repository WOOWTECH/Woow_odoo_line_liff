# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/__init__.py
# 載入順序：config → factory → template → bridge → user extensions → richmenu → logs → mail hook → partner → settings → news → auto_reply
from . import line_liff_config
from . import line_flex_factory
from . import line_flex_template
from . import line_bridge
from . import line_user
from . import line_richmenu
from . import line_event_log
from . import line_push_log
from . import mail_notification_line
from . import res_partner
from . import res_config_settings
from . import line_news
from . import line_auto_reply
from . import line_audience_tag
from . import line_insight_log
