# WOOW LINE Bridge (`woow_odoo_line_liff`)

> **The bridge module** of a 3-module LINE integration suite for Odoo 18.
> Provides LIFF auto-login, Rich Menu management, News push, Audience tags, Insight stats, Webhook event processing, Flex notifications, and auto-push hooks.

| Field | Value |
|-------|-------|
| **Technical Name** | `woow_odoo_line_liff` |
| **Version** | `18.0.3.0.0` |
| **Category** | Marketing |
| **Author** | WOOWTECH |
| **Website** | https://woowtech.io |
| **License** | LGPL-3 |
| **Application** | Yes |
| **Dependencies** | `woow_line_base`, `portal`, `mail` |
| **External Python** | `requests`, `pytz` |

---

## Quick Start

Get from zero to sending your first LINE message from Odoo in 5 steps:

**Step 1 -- Install modules**

```
Settings -> Apps -> Update Apps List
Search and install: woow_line_base, then woow_odoo_line_liff
```

**Step 2 -- Create a LINE config record**

```
LINE menu -> Configuration -> LINE Configs -> Create
```

This creates a `line.liff.config` record that holds all credentials for one LINE Official Account.

**Step 3 -- Fill credentials from LINE Developers Console**

Log into [LINE Developers Console](https://developers.line.biz/) and copy:

| Field in Odoo | Where to find in LINE Console |
|---------------|-------------------------------|
| Messaging Channel ID | Messaging API > Channel settings > Basic settings > Channel ID |
| Messaging Channel Secret | Messaging API > Channel settings > Basic settings > Channel secret |
| Messaging Access Token | Messaging API > Channel settings > Messaging API > Channel access token (long-lived) |
| Login Channel ID | LINE Login > Channel settings > Basic settings > Channel ID |
| Login Channel Secret | LINE Login > Channel settings > Basic settings > Channel secret |

**Step 4 -- Test broadcast from Odoo Shell**

Open Odoo shell (`odoo-bin shell -d <dbname>`) and send a test message:

```python
config = env['line.liff.config']._get_default_config()
api = env['line.api.service']
api.broadcast([{'type': 'text', 'text': 'Hello from Odoo!'}])
env.cr.commit()
```

If successful, all followers of your LINE Official Account will receive "Hello from Odoo!".

**Step 5 -- Set up LIFF app for portal auto-login**

1. In LINE Developers Console, create a LIFF app under your LINE Login channel:
   - Size: `Full`
   - Endpoint URL: `https://<your-odoo-domain>/liff/redirect`
2. Copy the LIFF ID (e.g. `1234567890-abcDefGh`) into the `liff_id_member` field of your config record.
3. In the LINE Developers Console, set the Webhook URL to `https://<your-odoo-domain>/line/webhook/<config_id>` and enable webhook events.
4. Users who open the LIFF URL from LINE will be auto-logged into the Odoo portal.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Suite Context](#module-suite-context)
3. [File Structure](#file-structure)
4. [Models Reference](#models-reference)
   - [line.liff.config](#1-lineliffconfig--multi-instance-settings)
   - [line.richmenu + area + alias](#2-linerichmenu--linerichmenualias--linerichmenuarea)
   - [line.news](#3-linenews--news-push-system)
   - [line.audience.tag](#4-lineaudiencetag--audience-tags)
   - [line.insight.log](#5-lineinsightlog--insight-statistics)
   - [line.auto.reply](#6-lineautoreply--keyword-auto-reply)
   - [line.flex.template](#7-lineflextemplate--flex-message-templates)
   - [line.flex.factory](#8-lineflexfactory--generic-flex-factory)
   - [line.bridge](#9-linebridge--bridge-hub)
   - [line.user (extension)](#10-lineuser-extension)
   - [mail.notification (override)](#11-mailnotification-override--auto-push-hook)
   - [res.partner (extension)](#12-respartner-extension)
   - [res.config.settings (extension)](#13-resconfigsettings-extension)
   - [line.event.log](#14-lineeventlog--webhook-event-log)
   - [line.push.log](#15-linepushlog--push-log)
5. [Controllers Reference](#controllers-reference)
   - [liff_redirect.py -- LIFF Auto-Login](#liff_redirectpy--liff-auto-login-critical-path)
   - [webhook.py -- LINE Webhook](#webhookpy--line-webhook)
   - [liff_api.py -- AJAX Endpoints](#liff_apipy--ajax-endpoints)
   - [liff_pages.py -- LIFF Pages](#liff_pagespy--liff-pages)
6. [Webhook Route Conflict & LiveChat Coexistence](#webhook-route-conflict--livechat-coexistence)
7. [LiveChat Forwarding Edge Cases](#livechat-forwarding-edge-cases)
8. [Static Assets](#static-assets)
9. [Security](#security)
10. [Security Analysis -- Threat Model](#security-analysis--threat-model)
11. [Cron Jobs](#cron-jobs)
12. [Data Files](#data-files)
13. [Flow Diagrams](#flow-diagrams)
    - [LIFF Login Flow](#liff-login-flow)
    - [Rich Menu Lifecycle](#rich-menu-lifecycle)
    - [News Push Flow](#news-push-flow)
    - [Webhook Event Handling](#webhook-event-handling)
    - [Auto-Push Hook Flow](#auto-push-hook-flow)
14. [Installation & Configuration Checklist](#installation--configuration-checklist)
15. [Local Development & Testing](#local-development--testing)
16. [For AI Agents](#for-ai-agents)

---

## Architecture Overview

```
+---------------------------+     +----------------------------+     +----------------------------+
|     woow_line_base        |     |   woow_odoo_line_liff      |     | woow_odoo_livechat_line    |
|   (Core / Foundation)     |     |      (THIS MODULE)         |     |    (LiveChat Bridge)       |
|                           |     |                            |     |                            |
| - line.api.service        |<----|  - line.liff.config        |     | - im_livechat.channel ext  |
|   (HTTP client)           |     |  - line.richmenu           |---->| - mail.guest ext           |
| - line.user (base)        |     |  - line.news               |     | - Webhook forwarder        |
| - ir.config_parameter     |     |  - line.audience.tag       |     +----------------------------+
|   (credential store)      |     |  - line.insight.log        |
| - group_line_manager      |     |  - line.auto.reply         |
| - group_line_user         |     |  - line.flex.template      |
+---------------------------+     |  - line.flex.factory       |
                                  |  - line.bridge             |
                                  |  - mail.notification hook  |
                                  |  - res.partner ext         |
                                  |  - LIFF controllers (4)    |
                                  +----------------------------+
```

### Model Relationship Diagram

```
line.liff.config (1)
 |
 |-- (1:N) line.richmenu
 |           |-- (1:N) line.richmenu.area
 |           |-- (1:N) line.richmenu.alias
 |
 |-- (1:N) line.news
 |           |-- (M:N) line.user          (push_target_ids)
 |           |-- (M:N) line.audience.tag  (push_audience_tag_ids)
 |
 |-- (1:N) line.insight.log
 |
 |-- (1:N) line.auto.reply
 |
 |-- (1:N) line.event.log
 |
 |-- (1:N) line.push.log
 |
 +-- (1:N) line.user (liff_config_id)
              |-- (M:1) res.partner
              |-- (M:1) line.richmenu   (current_richmenu_id)
              |-- (M:N) line.audience.tag

line.bridge (AbstractModel) ---------> line.api.service (from woow_line_base)
line.flex.template (AbstractModel)
line.flex.factory (AbstractModel)
mail.notification (inherit) ---------> line.flex.factory --> line.api.service
res.partner (inherit) ---------------> line.user --> line.api.service
res.config.settings (inherit) -------> line.liff.config (related fields)
```

---

## Module Suite Context

This module is the **second layer** in a 3-module LINE integration stack:

| # | Module | Role |
|---|--------|------|
| 1 | `woow_line_base` | **Core**: LINE API HTTP client (`line.api.service`), `line.user` base model, credential storage in `ir.config_parameter`, security groups |
| 2 | **`woow_odoo_line_liff`** (this) | **Bridge**: LIFF login, Rich Menu, News push, Audience tags, Insights, Webhook, Flex templates, auto-push hook |
| 3 | `woow_odoo_livechat_line` | **LiveChat**: LINE-to-Odoo LiveChat bridge, `mail.guest` extension, real-time messaging |

---

## File Structure

```
woow_odoo_line_liff/
|-- __init__.py
|-- __manifest__.py
|
|-- controllers/
|   |-- __init__.py
|   |-- liff_redirect.py          # LIFF auto-login (critical path)
|   |-- webhook.py                # LINE Webhook receiver
|   |-- liff_api.py               # AJAX JSON endpoints
|   |-- liff_pages.py             # Self-contained LIFF pages
|
|-- data/
|   |-- automated_action_template.xml   # Reference template (NOT auto-loaded)
|   |-- ir_config_parameter.xml         # System parameter defaults
|   |-- ir_cron.xml                     # Daily insight cron
|   |-- line_auto_reply_data.xml        # Seed auto-reply rules
|   |-- line_flex_templates.xml         # Reserved for data-driven templates
|   |-- mail_template.xml               # Reserved for email templates
|
|-- models/
|   |-- __init__.py
|   |-- line_liff_config.py       # Multi-instance config (POS-style)
|   |-- line_flex_factory.py      # Generic Flex builder
|   |-- line_flex_template.py     # Domain-specific Flex templates
|   |-- line_bridge.py            # Business event hub (AbstractModel)
|   |-- line_user.py              # line.user extension (Rich Menu + push)
|   |-- line_richmenu.py          # Rich Menu + Area + Alias
|   |-- line_event_log.py         # Webhook event log
|   |-- line_push_log.py          # Push log
|   |-- mail_notification_line.py # Auto-push hook on mail.notification
|   |-- res_partner.py            # has_line_bound + push_to_line
|   |-- res_config_settings.py    # Settings UI (POS-style config picker)
|   |-- line_news.py              # News articles + push
|   |-- line_auto_reply.py        # Keyword auto-reply rules
|   |-- line_audience_tag.py      # Audience segmentation tags
|   |-- line_insight_log.py       # Daily insight stats + cron
|
|-- security/
|   |-- ir.model.access.csv       # ACL rules
|   |-- line_security.xml         # Reserved (groups in woow_line_base)
|
|-- static/
|   |-- description/
|   |   |-- icon.png
|   |   |-- line_icon.png
|   |-- src/
|       |-- css/
|       |   |-- liff.css           # LIFF page styles
|       |-- js/
|           |-- liff_helper.js     # WoowLiff global helper
|           |-- liff_locations.js  # Leaflet map integration
|
|-- tests/
|   |-- __init__.py
|   |-- test_flex_template.py     # Flex structure validation
|   |-- test_line_service.py      # LINE API service tests
|   |-- test_webhook.py           # Webhook signature tests
|
|-- views/
    |-- assets.xml
    |-- liff_base.xml
    |-- liff_locations.xml
    |-- liff_news.xml
    |-- line_audience_tag_views.xml
    |-- line_auto_reply_views.xml
    |-- line_insight_log_views.xml
    |-- line_liff_config_views.xml
    |-- line_logs_views.xml
    |-- line_news_views.xml
    |-- line_richmenu_views.xml
    |-- line_user_views.xml
    |-- menus.xml
    |-- res_config_settings_views.xml
    |-- res_partner_views.xml
```

---

## Models Reference

### 1. `line.liff.config` -- Multi-Instance Settings

**Purpose**: One record per LINE Official Account. POS-style multi-tenant architecture where each record holds the full credential set, LIFF IDs, shop info, and behavioral settings. Automatically syncs to `ir.config_parameter` on create/write so that `line.api.service` (from `woow_line_base`) can read credentials from system parameters.

**File**: `models/line_liff_config.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char | Display name, e.g. "Mark Studio LINE" |
| `sequence` | Integer | Sort order (default 10) |
| `active` | Boolean | Active flag (default True) |
| `company_id` | Many2one(`res.company`) | Company (default current) |
| `messaging_channel_id` | Char | LINE Messaging API Channel ID |
| `messaging_channel_secret` | Char | Messaging Channel Secret |
| `messaging_access_token` | Char | Messaging Access Token (long-lived) |
| `login_channel_id` | Char | LINE Login Channel ID (for LIFF token verification) |
| `login_channel_secret` | Char | Login Channel Secret |
| `liff_id_member` | Char | LIFF ID for Portal login redirect |
| `liff_id_news` | Char | LIFF ID for news page |
| `liff_id_locations` | Char | LIFF ID for store locations page |
| `shop_name` | Char | Store name |
| `shop_address` | Char | Store address |
| `shop_phone` | Char | Store phone |
| `shop_latitude` | Char | Latitude |
| `shop_longitude` | Char | Longitude |
| `shop_opening_hours` | Char | Opening hours text |
| `auto_line_notify` | Boolean | Enable auto LINE push on tracked changes |
| `admin_line_user_id` | Char | Admin LINE User ID for Rich Menu preview |
| `rebook_path` | Char | Re-booking redirect path (default `/liff/redirect/book`) |
| `richmenu_contact_text` | Text | Reply text for "contact" Rich Menu button |
| `follower_count` | Integer | Synced follower count (readonly) |
| `target_reach` | Integer | Targetable reach count (readonly) |
| `blocked_count` | Integer | Blocked user count (readonly) |
| `follower_updated_at` | Datetime | Last stats sync time (readonly) |
| `webhook_url` | Char | Computed: `{base_url}/line/webhook/{id}` |
| `liff_endpoint_news` | Char | Computed: `{base_url}/liff/news` |
| `liff_endpoint_locations` | Char | Computed: `{base_url}/liff/locations` |

#### Key Methods

| Method | Description |
|--------|-------------|
| `_sync_to_system_params()` | Writes all `_SYNC_FIELDS` to `ir.config_parameter` |
| `_get_api_credentials()` | Returns `(channel_id, channel_secret, access_token)` tuple |
| `_get_default_config()` | Returns the first active config record (single-instance compat) |
| `_get_config_by_liff_id(liff_id)` | Reverse-lookup config from any LIFF ID |

#### `_SYNC_FIELDS` Mapping

The following config fields are synced to `ir.config_parameter` keys:

```python
_SYNC_FIELDS = {
    'messaging_channel_id':    'woow_line_base.messaging_channel_id',
    'messaging_channel_secret':'woow_line_base.messaging_channel_secret',
    'messaging_access_token':  'woow_line_base.messaging_access_token',
    'login_channel_id':        'woow_line_base.login_channel_id',
    'login_channel_secret':    'woow_line_base.login_channel_secret',
    'liff_id_member':          'woow_odoo_line_liff.liff_id_member',
    'liff_id_news':            'woow_odoo_line_liff.liff_id_news',
    'liff_id_locations':       'woow_odoo_line_liff.liff_id_locations',
    'shop_name':               'woow_odoo_line_liff.shop_name',
    'shop_address':            'woow_odoo_line_liff.shop_address',
    'shop_phone':              'woow_odoo_line_liff.shop_phone',
    'shop_latitude':           'woow_odoo_line_liff.shop_latitude',
    'shop_longitude':          'woow_odoo_line_liff.shop_longitude',
    'shop_opening_hours':      'woow_odoo_line_liff.shop_opening_hours',
    'rebook_path':             'woow_odoo_line_liff.rebook_path',
    'richmenu_contact_text':   'woow_odoo_line_liff.richmenu_contact_text',
}
```

---

### 2. `line.richmenu` + `line.richmenu.alias` + `line.richmenu.area`

**Purpose**: Full lifecycle management for LINE Rich Menus: create, upload image, set default, link to individual users, reupload, archive.

**File**: `models/line_richmenu.py`

#### `line.richmenu` Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Owning config |
| `name` | Char | Menu name (required) |
| `sequence` | Integer | Sort order |
| `chat_bar_text` | Char | Text shown on chat bar button (default "選單") |
| `size` | Selection | `full` (2500x1686) or `compact` (2500x843) |
| `selected` | Boolean | Auto-expand when user opens chat |
| `image` | Binary | Menu image (attachment) |
| `image_filename` | Char | Original filename |
| `line_richmenu_id` | Char | LINE Platform Rich Menu ID (readonly) |
| `is_default` | Boolean | Whether this is the default menu (readonly) |
| `state` | Selection | `draft` / `uploaded` / `active` / `archived` |
| `area_ids` | One2many | Tap areas |
| `alias_ids` | One2many | Tab-switching aliases |
| `linked_user_count` | Integer | Computed: count of linked users |

#### `line.richmenu` Methods

| Method | Description |
|--------|-------------|
| `action_create_on_line()` | Build menu JSON, call `richmenu_create()`, upload image |
| `action_reupload_to_line()` | Delete old on LINE, create new, re-apply default if needed |
| `action_set_as_default()` | Set as default for all users, unset others |
| `action_clear_default()` | Remove default status |
| `action_link_to_users()` | Open user selection wizard for per-user assignment |
| `action_archive()` | Delete from LINE and set state to archived |
| `action_preview()` | Link menu to admin's LINE account for preview |

#### `line.richmenu.area` Fields

| Field | Type | Description |
|-------|------|-------------|
| `richmenu_id` | Many2one | Parent Rich Menu |
| `sequence` | Integer | Sort order |
| `label` | Char | Button label (backend reference) |
| `x`, `y`, `width`, `height` | Integer | Tap area bounds in pixels |
| `action_type` | Selection | One of 7 action types (see below) |
| `action_value` | Char | Unified value field (new records) |
| `action_mode` | Selection | `date`/`time`/`datetime` (for datetimepicker) |

**7 Action Types**:

| Type | `action_value` contains | LINE action |
|------|------------------------|-------------|
| `uri` | Full URL | `{ "type": "uri", "uri": "..." }` |
| `liff_portal` | Portal path (e.g. `/home`, `/book`) | Converts to `https://liff.line.me/{liff_id}/{path}` |
| `message` | Text to send | `{ "type": "message", "text": "..." }` |
| `postback` | Data string | `{ "type": "postback", "data": "..." }` |
| `datetimepicker` | Data string | `{ "type": "datetimepicker", "mode": "...", "data": "..." }` |
| `richmenuswitch` | Target alias ID | `{ "type": "richmenuswitch", "richMenuAliasId": "..." }` |
| `clipboard` | Text to copy | `{ "type": "clipboard", "clipboardText": "..." }` |

#### `line.richmenu.alias` Fields

| Field | Type | Description |
|-------|------|-------------|
| `alias_id` | Char | Unique alias ID (e.g. `tab-home`, `tab-service`) |
| `richmenu_id` | Many2one | Target Rich Menu (must have `line_richmenu_id`) |
| `line_alias_id` | Char | LINE-side alias ID (readonly) |

---

### 3. `line.news` -- News Push System

**Purpose**: Publish news articles displayed in the LIFF news page and push as Flex Message cards to LINE followers. Supports 4 push methods with automatic broadcast-to-multicast degradation.

**File**: `models/line_news.py`

**Inherits**: `mail.thread`, `mail.activity.mixin`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Config |
| `title` | Char | Article title (required) |
| `summary` | Text | Short summary for list view |
| `body` | Html | Full article content |
| `image` | Binary | Cover image |
| `card_url` | Char | "Read more" URL in Flex card (auto-generated) |
| `published_date` | Date | Publish date |
| `author_id` | Many2one(`res.users`) | Author |
| `state` | Selection | `draft` / `published` |
| `is_published` | Boolean | Computed from state |
| `push_method` | Selection | `broadcast` / `multicast` / `push` / `narrowcast` |
| `push_target_ids` | Many2many(`line.user`) | Target users for multicast/push |
| `push_audience_tag_ids` | Many2many(`line.audience.tag`) | Tags for narrowcast |
| `line_push_count` | Integer | Total push count |
| `line_last_push` | Datetime | Last push time |
| `line_last_push_method` | Char | Actual method used |
| `line_last_push_sent` | Integer | Number of recipients |
| `quota_display` | Char | Computed: real-time LINE quota usage |

#### Key Methods

| Method | Description |
|--------|-------------|
| `action_publish()` | Set state to `published` |
| `action_draft()` | Revert to draft |
| `action_push_to_line()` | Build Flex card and push via selected method |
| `_execute_push(messages, method)` | Execute push; returns `(success, sent_count, actual_method)` |
| `_get_push_targets()` | Get target `line.user` recordset (explicit or all followers) |

#### Push Methods

| Method | API | Rate Limit | Fallback |
|--------|-----|-----------|----------|
| `broadcast` | `/v2/bot/message/broadcast` | 60/hour | Auto-degrades to `multicast` on 429 |
| `multicast` | `/v2/bot/message/multicast` | 200/sec, 500 users/batch | -- |
| `push` | `/v2/bot/message/push` | 200/sec, per-user | -- |
| `narrowcast` | `/v2/bot/message/narrowcast` | 60/hour | Requires audience group |

---

### 4. `line.audience.tag` -- Audience Tags

**Purpose**: Segment LINE users into groups (VIP, new customer, staff, etc.) and sync to LINE Audience API for narrowcast targeting.

**File**: `models/line_audience_tag.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char | Tag name (required) |
| `color` | Integer | Odoo color index |
| `sequence` | Integer | Sort order |
| `config_id` | Many2one(`line.liff.config`) | Config |
| `line_audience_group_id` | Char | LINE Audience Group ID (readonly) |
| `user_ids` | Many2many(`line.user`) | Tagged users |
| `user_count` | Integer | Computed from `user_ids` |
| `active` | Boolean | Active flag |
| `description` | Text | Description |

#### Key Methods

| Method | Description |
|--------|-------------|
| `action_sync_to_line()` | Delete existing LINE Audience Group + recreate with current user list |
| `action_delete_from_line()` | Delete from LINE without removing Odoo tag |

**Sync Strategy**: LINE Audience API does not support replacing all users in a group. The module uses a **delete + recreate** strategy every time sync is triggered.

---

### 5. `line.insight.log` -- Insight Statistics

**Purpose**: Daily statistics from LINE Insight API. One record per config per day.

**File**: `models/line_insight_log.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Config (required) |
| `date` | Date | Stats date (required) |
| `delivery_broadcast` | Integer | Broadcast delivery count |
| `delivery_push` | Integer | Push delivery count |
| `delivery_multicast` | Integer | Multicast delivery count |
| `delivery_narrowcast` | Integer | Narrowcast delivery count |
| `delivery_reply` | Integer | Reply delivery count |
| `delivery_total` | Integer | Computed sum of all delivery types |
| `followers` | Integer | Follower count |
| `targeted_reaches` | Integer | Targetable reach count |
| `blocks` | Integer | Blocked count |
| `impressions` | Integer | Impression count |
| `clicks` | Integer | Click count |
| `click_rate` | Float | Click rate percentage |

**SQL Constraint**: `UNIQUE(date, config_id)` -- one record per day per config.

#### Key Methods

| Method | Description |
|--------|-------------|
| `_cron_fetch_daily_insight()` | Cron entry point: fetches yesterday's stats for all active configs |
| `_fetch_for_config(api, config, date_str, date_val)` | Fetch delivery + follower stats, create/update log, sync to config |

---

### 6. `line.auto.reply` -- Keyword Auto-Reply

**Purpose**: Automatic keyword-matching reply rules for incoming text messages via webhook.

**File**: `models/line_auto_reply.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Scoped config (null = global rule) |
| `name` | Char | Rule name |
| `keyword` | Char | Match keyword or regex pattern |
| `match_type` | Selection | `contains` / `exact` / `regex` |
| `response_text` | Text | Reply text with placeholder support |
| `active` | Boolean | Active flag |
| `sequence` | Integer | Priority (lower = higher priority) |

#### Placeholders

| Placeholder | Source |
|-------------|--------|
| `{shop_name}` | `config.shop_name` or ICP |
| `{shop_phone}` | `config.shop_phone` or ICP |
| `{shop_address}` | `config.shop_address` or ICP |
| `{shop_hours}` | `config.shop_opening_hours` or ICP |

---

### 7. `line.flex.template` -- Flex Message Templates

**Purpose**: AbstractModel that provides domain-specific Flex Message builders. All Flex templates follow a **grayscale design** with semantic status color accents.

**File**: `models/line_flex_template.py`

#### Color Palette

| Constant | Hex | Usage |
|----------|-----|-------|
| `CLR_BLACK` | `#1A1A1A` | Main title text |
| `CLR_DARK` | `#333333` | Body text, primary button background |
| `CLR_MID` | `#666666` | Secondary text |
| `CLR_LABEL` | `#999999` | Labels, timestamps |
| `CLR_BORDER` | `#E5E5E5` | Separators |
| `CLR_BG` | `#F5F5F5` | Header background |
| `CLR_WHITE` | `#FFFFFF` | Card background |
| `STATUS_SUCCESS` | `#22C55E` | Confirmed, completed, approved |
| `STATUS_ERROR` | `#EF4444` | Cancelled, failed, rejected |
| `STATUS_WARNING` | `#F59E0B` | Pending, waiting, payment required |
| `STATUS_INFO` | `#3B82F6` | Notification, update, welcome |

#### Template Methods

| Method | Accent Color | Purpose |
|--------|-------------|---------|
| `build_welcome(display_name)` | INFO (blue) | Follow event welcome message |
| `build_booking_confirmed(booking)` | SUCCESS (green) | Booking confirmation |
| `build_booking_cancelled(booking, reason)` | ERROR (red) | Booking cancellation |
| `build_booking_reminder(booking, hours_before)` | INFO (blue) | Upcoming booking reminder |
| `build_booking_payment_required(booking, payment_url)` | WARNING (orange) | Payment pending |
| `build_news_card(news)` | INFO (blue) | News article push card |

#### Helper Methods

| Method | Description |
|--------|-------------|
| `_get_base_url()` | Get Odoo `web.base.url` |
| `_get_shop_name()` | Get shop name from ICP |
| `_liff_redirect_url(target)` | Build `https://liff.line.me/{id}/{target}` URL |
| `_liff_url(page)` | Build LIFF URL for a page name |
| `_format_booking_dt(booking)` | Format booking datetime to Taiwan timezone `(date_str, time_str)` |
| `_info_row(label, value)` | Build horizontal label-value Flex row |
| `_booking_header(title, status_color)` | Build header with 4px accent strip |

---

### 8. `line.flex.factory` -- Generic Flex Factory

**Purpose**: AbstractModel that provides a generic, model-agnostic Flex Message builder. Any module can call `env['line.flex.factory'].build_notification(...)` without knowing the specific template.

**File**: `models/line_flex_factory.py`

#### Key Methods

| Method | Description |
|--------|-------------|
| `build_notification(event_type, title, subtitle, info_rows, buttons, timestamp)` | Build a grayscale Flex bubble with semantic accent |
| `build_tracking_notification(message, partner)` | Build Flex from `mail.message` tracking values; returns `(flex, alt_text)` |

#### `build_notification()` Parameters

```python
factory = env['line.flex.factory']
flex = factory.build_notification(
    event_type='success',        # 'success' | 'error' | 'warning' | 'info'
    title='Booking Confirmed',   # Header text
    subtitle='APT00003',         # Secondary text
    info_rows=[                  # (label, value) tuples
        ('Service', 'Professional Massage'),
        ('Time', '2026/06/07 14:30'),
    ],
    buttons=[                    # Action buttons
        {'label': 'View Details', 'uri': 'https://...'},
        {'label': 'Cancel', 'postback': 'action=cancel&id=3'},
    ],
    timestamp='2026/06/07 14:30',  # Optional
)
```

#### `build_tracking_notification()` Logic

1. Extracts tracking values from `mail.message.tracking_value_ids`
2. Auto-detects `event_type` from new values (e.g. "confirmed" -> success, "cancelled" -> error)
3. Falls back to stripping HTML from `message.body` if no tracking values
4. Returns `(None, None)` if no content to show

---

### 9. `line.bridge` -- Bridge Hub

**Purpose**: AbstractModel serving as the centralized LINE notification hub. Business modules should push through bridge methods instead of calling `line.api.service` directly.

**File**: `models/line_bridge.py`

#### Methods

| Method | Parameters | Description |
|--------|-----------|-------------|
| `notify_partner(partner, msg_or_flex)` | `partner`: res.partner record; `msg_or_flex`: str, dict, or list | Push notification to a partner's LINE users |
| `notify_group(xml_id, msg_or_flex)` | `xml_id`: group XML ID (e.g. `base.group_user`) | Push to all partners in a security group |
| `_get_line_users_for_partner(partner)` | `partner`: res.partner | Get active, non-blocked LINE users for a partner |

#### `msg_or_flex` Parameter Types

- **`str`**: Sent as plain text message
- **`dict`**: Wrapped as Flex Message (expects `contents` or raw Flex dict)
- **`list`**: Sent as-is (raw LINE messages array)

---

### 10. `line.user` Extension

**Purpose**: Extends `line.user` (from `woow_line_base`) with Rich Menu assignment, audience tags, and push convenience methods.

**File**: `models/line_user.py`

#### Added Fields

| Field | Type | Description |
|-------|------|-------------|
| `liff_config_id` | Many2one(`line.liff.config`) | Source LIFF config |
| `audience_tag_ids` | Many2many(`line.audience.tag`) | Audience tags |
| `current_richmenu_id` | Many2one(`line.richmenu`) | Currently assigned Rich Menu |

#### Rich Menu Auto-Sync

The `write()` method is overridden: when `current_richmenu_id` changes, `_sync_richmenu_to_line()` automatically calls the LINE API to link/unlink the menu for that user.

#### Push Methods

| Method | Description |
|--------|-------------|
| `push_text(text)` | Push plain text message |
| `push_messages(messages)` | Push custom messages list |
| `push_flex(alt_text, contents)` | Push Flex Message |
| `action_push_test()` | View button: send test message |

---

### 11. `mail.notification` Override -- Auto-Push Hook

**Purpose**: Hooks into `mail.notification.create()` to automatically push LINE Flex Messages when tracked field changes generate notifications for partners with bound LINE users.

**File**: `models/mail_notification_line.py`

#### How It Works

1. `create()` is overridden with `@api.model_create_multi`
2. Checks `skip_line_notification` context flag (skip if True)
3. Checks `woow_line_base.auto_line_notify` system parameter (must be `True`/`true`/`1`)
4. For each notification targeting a partner with LINE users:
   - Uses `line.flex.factory.build_tracking_notification()` to build Flex from `mail.message`
   - Pushes via `line.api.service.push()`
5. Entire push logic is wrapped in try/except -- failures never block `mail.notification` creation

#### Control Flags

| Flag | Type | Description |
|------|------|-------------|
| `woow_line_base.auto_line_notify` | ir.config_parameter | Master on/off switch |
| `skip_line_notification` | Context key | Per-call skip (e.g. during booking cancel from webhook) |

---

### 12. `res.partner` Extension

**Purpose**: Adds LINE binding status and a convenience push method to `res.partner`.

**File**: `models/res_partner.py`

#### Added Fields

| Field | Type | Description |
|-------|------|-------------|
| `has_line_bound` | Boolean (computed, stored) | True if partner has at least one active LINE user or `mail.guest` with `line_partner_id` |

#### Methods

| Method | Description |
|--------|-------------|
| `action_open_line_user()` | Smart button: opens LINE user form or list |
| `push_to_line(msg_or_flex)` | Push to this partner's LINE users (str/dict/list) |

---

### 13. `res.config.settings` Extension

**Purpose**: POS-style config picker in Settings. Selects a `line.liff.config` record and exposes all its fields as `related` fields for inline editing.

**File**: `models/res_config_settings.py`

All fields are `related` to `line_liff_config_id.<field_name>` with `readonly=False`, allowing direct editing from the Settings page.

---

### 14. `line.event.log` -- Webhook Event Log

**Purpose**: Audit trail of all received LINE webhook events.

**File**: `models/line_event_log.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Config |
| `line_user_id` | Many2one(`line.user`) | Triggering user |
| `event_type` | Selection | `follow`, `unfollow`, `message`, `postback`, `join`, `leave`, etc. (13 types) |
| `message_type` | Selection | `text`, `image`, `video`, `audio`, `location`, `sticker`, `file`, `other` |
| `raw_payload` | Text | Full webhook event JSON |
| `text_content` | Char | Text content (for text messages, truncated to 255 chars) |
| `processed` | Boolean | Whether business logic processed this event |
| `error_msg` | Text | Error message if processing failed |

---

### 15. `line.push.log` -- Push Log

**Purpose**: Audit trail of all outgoing LINE push operations.

**File**: `models/line_push_log.py`

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | Many2one(`line.liff.config`) | Config |
| `line_user_id` | Many2one(`line.user`) | Target user (null for broadcast/multicast) |
| `messages` | Text | Messages JSON |
| `status_code` | Integer | HTTP response status code |
| `response_body` | Text | Response body |
| `success` | Boolean | Whether push succeeded (HTTP 200) |

---

## Controllers Reference

### `liff_redirect.py` -- LIFF Auto-Login (Critical Path)

**File**: `controllers/liff_redirect.py`

This is the most critical controller -- it enables seamless authentication from LINE to Odoo Portal.

#### Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/liff/redirect` | GET/POST | `none` | Main LIFF login endpoint |
| `/liff/redirect/<path:target>` | GET/POST | `none` | Parametric redirect target |
| `/liff/redirect/booking/<int:booking_id>` | GET/POST | `none` | Direct booking detail redirect |

#### Redirect Targets

| Target | Portal URL |
|--------|-----------|
| `book` | `/appointment/1/schedule` |
| `my-bookings` | `/my/ext-bookings` |
| `profile` | `/my/account` |
| `home` | `/my/home` |
| `orders` | `/my/orders` |
| `invoices` | `/my/invoices` |
| `booking/<id>` | `/my/ext-bookings/<id>` |
| `my/*`, `shop*`, `appointment/*`, `contactus` | `/<target>` (pass-through) |

#### Authentication Flow

See [LIFF Login Flow](#liff-login-flow) for the full diagram.

#### Key Internal Methods

| Method | Description |
|--------|-------------|
| `_authenticate_liff_user(**kwargs)` | Verify token, create/update LINE user, ensure portal user, authenticate session |
| `_render_liff_bridge_page(target)` | Render inline HTML bridge page with embedded LIFF SDK |
| `_ensure_portal_user(line_user, payload)` | Find or create portal user (3-step lookup: existing partner -> email match -> create new) |
| `_create_portal_user(partner, login)` | Create portal user with random password, assign portal group |
| `_get_redirect_url(target, kwargs)` | Resolve target to actual URL |

---

### `webhook.py` -- LINE Webhook

**File**: `controllers/webhook.py`

#### Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/line/webhook` | POST | `public` | Global webhook endpoint |
| `/line/webhook/<int:config_id>` | POST | `public` | Per-config webhook endpoint |

#### Credential Resolution Order

1. `line.liff.config` by `config_id` or default
2. `im_livechat.channel` fallback (if installed and `line_enabled`)
3. Global `ir.config_parameter` fallback

#### Event Handlers

| Event | Handler | Action |
|-------|---------|--------|
| `follow` | `_handle_follow()` | Create/update line.user, set `is_follower=True`, send welcome Flex |
| `unfollow` | `_handle_unfollow()` | Set `is_follower=False`, `is_blocked=True` |
| `message` (text) | `_handle_message()` | Match keyword rules, reply if matched |
| `postback` | `_handle_postback()` | Parse `action=xxx&key=value`, dispatch to handler |

#### Postback Actions

| Action | Handler | Description |
|--------|---------|-------------|
| `cancel_booking` | `_postback_cancel_booking()` | Cancel booking (with ownership verification) |
| `view_booking` | `_postback_view_booking()` | Show booking Flex card |
| `rebook` | `_postback_rebook()` | Send rebooking URL |
| `navigate` | `_postback_navigate()` | Send Google Maps navigation URL |
| `richmenu` | `_postback_richmenu()` | Handle Rich Menu button targets |

#### LiveChat Forwarding

After processing each event, the webhook controller calls `_forward_to_livechat()` which dynamically imports `woow_odoo_livechat_line` (if installed) and forwards the event. This resolves the route conflict where both bridge and livechat share the `/line/webhook/<int:id>` pattern.

---

### `liff_api.py` -- AJAX Endpoints

**File**: `controllers/liff_api.py`

All endpoints authenticate via ID Token (in `Authorization: Bearer <token>` header or POST body).

| Route | Method | Description | Response |
|-------|--------|-------------|----------|
| `/api/line/bind` | POST | Bind LINE user to partner (auto-create if needed) | `{ status, partner_id, partner_name }` |
| `/api/line/me` | POST | Get current LINE user info + partner data | `{ line_user_id, display_name, partner, ... }` |
| `/api/line/notification/toggle` | POST | Toggle notification enabled/disabled | `{ status, notification_enabled }` |

#### Security Note

The `/api/line/bind` endpoint does **not** allow arbitrary `partner_id` binding (to prevent account hijacking). It only performs auto-creation or email-based matching.

---

### `liff_pages.py` -- LIFF Pages

**File**: `controllers/liff_pages.py`

Self-contained LIFF pages rendered as inline HTML (no dependency on website templates).

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/liff/news` | GET | `none` | News list/article page (supports `?article_id=N`) |
| `/liff/news/image/<int:news_id>` | GET | `none` | Public news cover image (LINE-spec: HTTPS, max 1024x1024) |
| `/liff/locations` | GET | `none` | Store location with Leaflet/OpenStreetMap map |
| `/liff/clear-session` | GET | `none` | Clear broken session and redirect (recovery endpoint) |
| `/liff/debug` | GET | `public` | LIFF SDK diagnostics page |

---

## Webhook Route Conflict & LiveChat Coexistence

When both `woow_odoo_line_liff` (this module) and `woow_odoo_livechat_line` are installed, they share the same `/line/webhook/<int:config_id>` URL pattern. This section explains how the conflict is resolved.

### Route Ownership

The **bridge module** (`woow_odoo_line_liff`) owns the webhook route. Its `LineWebhookBridge` controller in `controllers/webhook.py` registers `/line/webhook` and `/line/webhook/<int:config_id>` and handles all incoming webhook events.

The **livechat module** (`woow_odoo_livechat_line`) does **not** register a competing route when the bridge module is installed. Instead, the bridge module forwards events to the livechat module programmatically.

### Forwarding Mechanism

After processing each webhook event (follow, message, postback, etc.), the bridge controller calls its `_forward_to_livechat()` method:

```python
def _forward_to_livechat(self, event, config=None):
    try:
        from odoo.addons.woow_odoo_livechat_line.controllers.webhook import LineWebhookController
        livechat_ctrl = LineWebhookController()
        livechat_ctrl._handle_event_from_bridge(event, config)
    except ImportError:
        pass  # livechat module not installed -- silently skip
```

This means:
- The bridge module **always processes webhook events first** (logging, follow/unfollow, auto-reply, postback handling).
- The livechat module is invoked **second**, receiving the same event for real-time chat processing.
- If the livechat module is not installed, the `ImportError` is caught silently and the bridge handles everything standalone.

### Standalone vs. Coexistence Mode

| Mode | Installed Modules | Webhook Behavior |
|------|-------------------|------------------|
| **Standalone** | `woow_line_base` + `woow_odoo_line_liff` | Bridge handles all events directly; no forwarding |
| **Coexistence** | All three modules | Bridge handles events first, then forwards to livechat |
| **LiveChat only** | `woow_line_base` + `woow_odoo_livechat_line` | LiveChat module registers its own webhook route (no conflict) |

### Configuration

No additional configuration is needed. The bridge module auto-detects whether the livechat module is installed at runtime via the dynamic import. There is no manifest dependency between the two modules.

---

## LiveChat Forwarding Edge Cases

The dynamic import pattern used for livechat forwarding has several edge cases that developers should be aware of.

### ImportError Is Caught Silently

The `_forward_to_livechat()` method wraps the import in `try/except ImportError`. This means:
- If `woow_odoo_livechat_line` is **uninstalled** while the server is running, forwarding silently stops.
- If the livechat module has a **broken import** (e.g. missing dependency), the error is swallowed. Check server logs if livechat events are not being processed.
- To verify forwarding is active, check `line.event.log` for events with `processed=True` and look for corresponding livechat sessions.

### Route Registration Order

Odoo loads controllers in module dependency order. Since `woow_odoo_line_liff` does not depend on `woow_odoo_livechat_line` (and vice versa), their load order is non-deterministic. The bridge module avoids route conflicts by:
1. Registering the canonical `/line/webhook/<int:config_id>` route in its own controller.
2. Using dynamic import (not controller inheritance) to invoke the livechat handler.

If both modules independently register the same route pattern, Odoo's routing layer picks the **last loaded** controller. The bridge module's forwarding pattern avoids this ambiguity entirely.

### Error Containment Between Modules

Errors in the livechat handler do **not** propagate back to the bridge webhook response. The forwarding call is wrapped in its own `try/except`:
- If the livechat handler raises an exception, the bridge still returns HTTP 200 to LINE (as required by the LINE Platform).
- The error is logged via `_logger.exception()` but does not affect event logging, auto-reply, or postback handling in the bridge module.
- This isolation ensures that a bug in the livechat module cannot break core webhook processing.

---

## Static Assets

### `js/liff_helper.js`

Global `WoowLiff` object providing LIFF SDK wrapper functions:

| Function | Description |
|----------|-------------|
| `WoowLiff.init(liffId)` | Initialize LIFF SDK |
| `WoowLiff.ensureLogin()` | Redirect to LINE Login if not logged in |
| `WoowLiff.getIdToken()` | Get ID Token (with error handling) |
| `WoowLiff.getProfile()` | Get user profile |
| `WoowLiff.apiCall(url, data)` | POST to backend with ID Token auth |
| `WoowLiff.redirectTo(target)` | Submit hidden form to `/liff/redirect/<target>` |
| `WoowLiff.close()` | Close LIFF window (in LINE app only) |
| `WoowLiff.isInLine()` | Check if running inside LINE app |
| `WoowLiff.isLiffMode()` | Check if URL has `?liff=1` parameter |

### `js/liff_locations.js`

Leaflet map initialization for the store locations page:
- Reads `data-lat`, `data-lng`, `data-name` from `#liff-map` element
- Uses custom brand-colored marker icon (`#B8956A`)
- Falls back to Google Maps link if Leaflet fails to load

### `css/liff.css`

LIFF page component styles including:
- `.liff-container` -- Base container with warm-tone background (`#FAF6F2`)
- `.liff-page-header` -- Sticky header with back button
- `.liff-btn`, `.liff-btn-primary`, `.liff-btn-secondary`, `.liff-btn-line` -- Button variants
- `.liff-spinner` -- Loading animation
- `.liff-news-*` -- News list and detail page components
- `.liff-location-*` -- Location page and map components

Registered in `web.assets_frontend` bundle.

---

## Security

### Access Control Groups

Groups are defined in `woow_line_base`:
- `group_line_manager` (`woow_line_base.group_line_manager`): Full CRUD on all LINE models
- `group_line_user` (`woow_line_base.group_line_user`): Read-only access

### ACL Rules (`ir.model.access.csv`)

| Model | Group | Read | Write | Create | Delete |
|-------|-------|------|-------|--------|--------|
| `line.liff.config` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.event.log` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.push.log` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.richmenu` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.richmenu.area` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.richmenu.alias` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.news` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.news` | `base.group_public` | 1 | 0 | 0 | 0 |
| `line.auto.reply` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.audience.tag` | `group_line_manager` | 1 | 1 | 1 | 1 |
| `line.insight.log` | `group_line_manager` | 1 | 1 | 1 | 1 |

### Webhook Security

- **HMAC-SHA256**: All webhook requests are validated against `X-Line-Signature` using the channel secret
- **Config validation**: Channel secret is resolved from `line.liff.config` -> `im_livechat.channel` -> global parameter
- Invalid signatures return HTTP 403

---

## Security Analysis -- Threat Model

This section details specific security risks in the LIFF authentication and webhook flows, along with the mitigations implemented in this module.

### LIFF ID Token Replay Prevention

The LIFF login flow accepts a LINE ID Token (JWT) and verifies it via `POST https://api.line.me/oauth2/v2.1/verify`. The token includes an `exp` (expiration) claim.

**Risk**: A stolen ID Token could be replayed to authenticate as another user until the token expires.

**Mitigations**:
- The LINE verify endpoint rejects expired tokens (tokens are short-lived, typically 5-10 minutes).
- The ID Token is submitted via **POST body** (not URL query parameters), reducing exposure in browser history, referrer headers, and server access logs.
- The LIFF bridge page extracts the token client-side and immediately POSTs it; the token is never persisted in `localStorage` or cookies.
- After successful authentication, an Odoo session cookie is issued -- the ID Token is not reused for subsequent requests.

**Remaining risk**: Within the token's validity window (before `exp`), a man-in-the-middle on the client device could replay the token. HTTPS mitigates network-level interception.

### Email Claim Binding Attack

When a LINE user authenticates via LIFF, the `_ensure_portal_user()` method attempts to match the LINE user to an existing Odoo partner by email. This creates a potential account takeover vector.

**Risk**: A LINE user who sets their LINE profile email to `admin@company.com` (or any existing partner's email) would be automatically bound to that partner's portal account.

**Mitigations**:
- The `_ensure_portal_user()` lookup order prioritizes the existing `line_user.partner_id` binding. If the LINE user is already bound, the email match step is skipped entirely.
- For new LINE users, the email match creates a **binding** between the LINE user and the existing partner but does not grant elevated privileges -- portal users have limited access.
- Odoo's `group_portal` provides read-only access to the partner's own records. An attacker would see the target's portal data (orders, invoices) but cannot modify backend records.

**Recommendation for high-security deployments**: Override `_ensure_portal_user()` to require manual approval before binding a new LINE user to an existing partner with email match. Add an `email_verified` flag or use LINE's email scope verification status.

### Token Transmission Security

**Risk**: If the ID Token were transmitted as a URL query parameter (e.g. `GET /liff/redirect?id_token=xxx`), it would appear in server access logs, browser history, and potentially in `Referer` headers sent to third-party resources.

**Mitigation**: The LIFF bridge page uses a **hidden form POST** to submit the ID Token:
```html
<form method="POST" action="/liff/redirect/{target}">
    <input type="hidden" name="id_token" value="..." />
</form>
```
POST body data does not appear in URL logs or referrer headers.

### AJAX Endpoint Authentication

The `/api/line/*` endpoints (`liff_api.py`) do not use Odoo's session-based authentication. Instead, each request must include a valid LINE ID Token.

| Endpoint | Auth Method | Token Location |
|----------|------------|----------------|
| `/api/line/bind` | ID Token | `Authorization: Bearer <token>` or POST body `id_token` field |
| `/api/line/me` | ID Token | Same |
| `/api/line/notification/toggle` | ID Token | Same |

**Risk**: These endpoints use `auth='none'`, meaning Odoo does not enforce session authentication. If the ID Token validation is bypassed (e.g. due to a bug in `line.api.service.verify_id_token()`), the endpoints become unauthenticated.

**Mitigation**: The ID Token is verified on every request via the LINE platform's verify API. The verify call is not cached -- each request triggers a fresh HTTP call to `api.line.me`. This adds latency but ensures tokens cannot be used after expiration.

### Summary of Security Boundaries

| Boundary | Protection | Weakness |
|----------|-----------|----------|
| Webhook ingress | HMAC-SHA256 signature | None (standard LINE security) |
| LIFF token transmission | POST body (not URL) | Token valid until `exp` claim |
| LIFF token verification | LINE verify API (per-request) | Adds ~100ms latency per call |
| Email-based partner binding | Lookup order prioritizes existing binding | New users matched by email without verification |
| AJAX endpoints | ID Token required per request | `auth='none'` bypasses Odoo session layer |

---

## Cron Jobs

| Name | Model | Method | Interval | Description |
|------|-------|--------|----------|-------------|
| LINE: 每日統計抓取 | `line.insight.log` | `_cron_fetch_daily_insight()` | Daily | Fetches yesterday's delivery and follower stats from LINE Insight API for all active configs |

**Note on `numbercall`**: The cron XML uses `<field name="numbercall">-1</field>`. In Odoo 18, the `numbercall` field is deprecated -- `-1` means "run forever" but the field is ignored by the scheduler. The cron will run based solely on `interval_number` and `interval_type`.

---

## Data Files

### `ir_config_parameter.xml`

Default system parameters (all `noupdate="1"`):

| Key | Default | Description |
|-----|---------|-------------|
| `woow_line_base.auto_line_notify` | `False` | Auto-push master switch |
| `woow_line_base.admin_line_user_id` | (empty) | Admin LINE User ID |
| `woow_odoo_line_liff.liff_id_member` | (empty) | LIFF ID for member/portal |
| `woow_odoo_line_liff.liff_id_news` | (empty) | LIFF ID for news |
| `woow_odoo_line_liff.liff_id_locations` | (empty) | LIFF ID for locations |
| `woow_odoo_line_liff.shop_*` | (empty) | Shop info fields |
| `woow_odoo_line_liff.rebook_path` | `/liff/redirect/book` | Rebooking path |
| `woow_odoo_line_liff.richmenu_contact_text` | 歡迎直接傳訊息... | Contact reply text |

### `line_auto_reply_data.xml`

8 seed auto-reply rules:

| Keyword | Match Type | Response |
|---------|-----------|----------|
| 預約 | contains | Guide to booking menu |
| 電話 | contains | `{shop_name} 電話：{shop_phone}` |
| 地址 | contains | `{shop_name} 地址：{shop_address}` |
| 營業時間 | contains | `{shop_name} 營業時間：{shop_hours}` |
| 你好 | contains | Welcome greeting |
| 哈囉 | contains | Welcome greeting |
| hi | exact | Welcome greeting |
| hello | exact | Welcome greeting |

### `automated_action_template.xml`

**Not auto-loaded** (not in `__manifest__.py` data). Serves as a reference template for creating Automated Actions in the Odoo backend GUI. Contains:

- Booking confirmation detail card (Python code template)
- Generic module template (sales orders, tasks, etc.)
- Full `line.flex.factory.build_notification()` API reference

---

## Flow Diagrams

### LIFF Login Flow

```
User taps Rich Menu button in LINE
       |
       v
LINE opens LIFF URL:
  https://liff.line.me/{liff_id}/book
       |
       v
GET /liff/redirect/book
  Returns inline HTML bridge page
  with embedded LIFF SDK
       |
       v
[Browser: liff.init()]
       |
       +-- Not logged in? --> liff.login() --> LINE Login --> redirect back
       |
       v
[Browser: liff.getIDToken()]
       |
       v
Hidden form POST to /liff/redirect/book
  body: { id_token: "..." }
       |
       v
[Server: _authenticate_liff_user()]
  1. Extract id_token from POST body
  2. line.api.service.verify_id_token(id_token)
     POST https://api.line.me/oauth2/v2.1/verify
     Returns: { sub: "Uxxxx", name: "...", email: "..." }
  3. line.user.create_or_update_from_liff(payload)
  4. _ensure_portal_user(line_user, payload)
     a. line_user has partner? -> find user for partner
     b. email match? -> bind to existing partner
     c. Create new partner + portal user
  5. Generate random temp password
  6. request.session.authenticate(db, {login, password})
       |
       v
302 Redirect to /appointment/1/schedule
  (User is now logged into Odoo Portal)
```

### Rich Menu Lifecycle

```
[Odoo Backend: line.richmenu form]
       |
  1. Define areas (line.richmenu.area)
  2. Upload image
       |
       v
action_create_on_line()
  1. _build_menu_data() --> JSON with size, areas, actions
  2. line.api.service.richmenu_create(data) --> richmenu_id
  3. line.api.service.richmenu_upload_image(id, bytes, type)
  4. state = 'uploaded'
       |
       v
action_set_as_default()
  1. Unset other defaults
  2. richmenu_set_default(richmenu_id)
  3. state = 'active'
       |
       v
[Per-user assignment]
  line.user.write({'current_richmenu_id': menu.id})
    --> _sync_richmenu_to_line()
    --> richmenu_link_to_user(menu_id, user_id)
       |
       v
action_reupload_to_line()
  1. richmenu_delete(old_id)
  2. action_create_on_line() (new ID)
  3. If was default: action_set_as_default()
       |
       v
action_archive()
  1. richmenu_clear_default() (if default)
  2. richmenu_delete(id)
  3. state = 'archived'
```

### News Push Flow

```
[Odoo Backend: line.news form]
       |
  action_publish() --> state = 'published'
       |
  Select push_method:
  broadcast / multicast / push / narrowcast
       |
  Select targets (multicast/push) or tags (narrowcast)
       |
       v
action_push_to_line()
  1. Build Flex: line.flex.template.build_news_card(news)
     - Hero image (if news.image exists)
     - Title + summary
     - "閱讀全文" button -> card_url
  2. _execute_push(messages, method)
       |
       +-- broadcast:
       |     api.broadcast(messages)
       |     Success? --> return (True, 0, 'broadcast')
       |     429? --> auto-degrade to multicast
       |
       +-- multicast:
       |     targets = _get_push_targets() --> line.user recordset
       |     api.multicast(uids, messages)
       |     --> log to line.push.log
       |
       +-- narrowcast:
       |     Sync tags to LINE Audience Group
       |     api.narrowcast(messages, recipient={audienceGroupId})
       |
       +-- push:
             api.push(targets, messages) (per-user)
       |
       v
  Update: line_push_count++, line_last_push, line_last_push_method
  Display notification with result
```

### Webhook Event Handling

```
LINE Platform --> POST /line/webhook/<config_id>
       |
       v
[Credential Resolution]
  1. line.liff.config by config_id (or default)
  2. im_livechat.channel fallback
  3. Global ir.config_parameter
       |
       v
[Signature Verification]
  HMAC-SHA256(channel_secret, body) == X-Line-Signature?
  No --> 403
       |
       v
[Parse JSON]
  Invalid? --> 400
       |
       v
[For each event:]
  1. _log_event() --> create line.event.log
  2. Dispatch to _handle_{event_type}()
       |
       +-- follow:
       |     Create/update line.user (is_follower=True)
       |     Fetch profile from LINE API
       |     Reply with welcome Flex Message
       |
       +-- unfollow:
       |     Set is_follower=False, is_blocked=True
       |
       +-- message (text):
       |     _match_keyword(text)
       |     If matched: reply with response_text (with placeholders)
       |
       +-- postback:
       |     Parse data: "action=cancel_booking&booking_id=3"
       |     Dispatch to _postback_{action}()
       |       cancel_booking: verify ownership, cancel, reply Flex
       |       view_booking: verify ownership, reply Flex
       |       rebook: reply with rebooking URL
       |       navigate: reply with Google Maps URL
       |       richmenu: reply with LIFF URL for target
       |
  3. _forward_to_livechat(event)
     Dynamically import livechat controller (if installed)
       |
       v
Response: 200 OK
```

### Auto-Push Hook Flow

```
[Any Odoo model with mail.thread tracking]
  e.g., appointment.booking state changed
       |
       v
mail.message created with tracking_value_ids
       |
       v
mail.notification.create() triggered
       |
       v
[MailNotificationLine.create() override]
  1. Check context: skip_line_notification? --> skip
  2. Check ICP: woow_line_base.auto_line_notify == True? --> continue
  3. For each notification:
     a. notification_type in ('inbox', 'email')? --> continue
     b. Partner has LINE users? --> continue
     c. line.flex.factory.build_tracking_notification(message)
        - Extract tracking values: field_desc, old_value -> new_value
        - Auto-detect event_type from new_value text
        - Build grayscale Flex with semantic accent
     d. line.api.service.push(line_users, [flex_message])
       |
       v
[Original mail.notification records returned unaffected]
  (Push failures are logged but never block notification creation)
```

---

## Installation & Configuration Checklist

### Prerequisites

- [ ] Odoo 18 Community or Enterprise
- [ ] `woow_line_base` module installed and configured
- [ ] LINE Developers Console account with:
  - [ ] Messaging API channel (Channel ID, Secret, Access Token)
  - [ ] LINE Login channel (Channel ID, Secret)
  - [ ] LIFF apps created (member, news, locations)
- [ ] Python packages: `requests`, `pytz` (usually pre-installed)

### Installation Steps

1. [ ] Place module in Odoo addons path
2. [ ] Update apps list: Settings -> Apps -> Update Apps List
3. [ ] Install `woow_odoo_line_liff`

### Configuration Steps

1. [ ] Navigate to LINE menu in Odoo backend
2. [ ] Create a `line.liff.config` record:
   - [ ] Fill Messaging API credentials (Channel ID, Secret, Access Token)
   - [ ] Fill LINE Login credentials (Channel ID, Secret)
   - [ ] Fill LIFF IDs (member, news, locations)
   - [ ] Fill shop info (name, address, phone, lat/lng, hours)
3. [ ] Set Webhook URL in LINE Developers Console:
   - URL shown in config form: `{base_url}/line/webhook/{config_id}`
   - Enable webhook events: Follow, Unfollow, Message, Postback
4. [ ] Create LIFF apps in LINE Developers Console:
   - Type: Full (for member portal) or Tall (for news/locations)
   - Endpoint URL: `{base_url}/liff/redirect` (member), `{base_url}/liff/news`, `{base_url}/liff/locations`
5. [ ] Create and upload Rich Menu:
   - Design image (2500x1686 or 2500x843)
   - Define tap areas with actions
   - Upload and set as default
6. [ ] Enable auto-push (optional):
   - Settings -> LINE -> Enable "自動 LINE 推播"
   - Or set `woow_line_base.auto_line_notify` = `True` in System Parameters
7. [ ] Verify webhook: Send a follow event from LINE and check `line.event.log`

---

## For AI Agents

This section provides programmatic guidance for AI agents interacting with this module.

### How to Push Messages Programmatically

#### Simple Text Push to a Partner

```python
partner = env['res.partner'].browse(partner_id)
partner.push_to_line('Hello from Odoo!')
```

#### Flex Message Push to a Partner

```python
factory = env['line.flex.factory']
flex = factory.build_notification(
    event_type='success',
    title='Order Confirmed',
    subtitle='SO0042',
    info_rows=[('Amount', 'NT$ 1,500'), ('Delivery', '2026/07/05')],
    buttons=[{'label': 'View Order', 'uri': 'https://liff.line.me/LIFF_ID/orders'}],
)
partner.push_to_line(flex)
```

#### Push via Bridge Hub

```python
bridge = env['line.bridge']
# To a specific partner
bridge.notify_partner(partner, 'Important notification')
# To all internal users
bridge.notify_group('base.group_user', flex_dict)
```

#### Push to Specific LINE Users

```python
line_users = env['line.user'].search([('audience_tag_ids.name', '=', 'VIP')])
line_users.push_text('VIP exclusive offer!')
# Or with Flex
line_users.push_flex('Notification', flex_contents)
```

#### Broadcast News

```python
news = env['line.news'].create({
    'title': 'Summer Sale',
    'summary': '50% off all services',
    'body': '<p>Details here...</p>',
    'state': 'published',
    'push_method': 'broadcast',
})
news.action_push_to_line()
```

### How to Create and Manage Rich Menus

```python
Config = env['line.liff.config']
config = Config._get_default_config()

# Create menu
menu = env['line.richmenu'].create({
    'config_id': config.id,
    'name': 'Main Menu',
    'size': 'full',
    'chat_bar_text': 'Menu',
    'image': base64_encoded_image,
})

# Add tap areas
env['line.richmenu.area'].create({
    'richmenu_id': menu.id,
    'label': 'Book Now',
    'x': 0, 'y': 0, 'width': 833, 'height': 843,
    'action_type': 'liff_portal',
    'action_value': 'book',
})

# Upload to LINE and set as default
menu.action_create_on_line()
menu.action_set_as_default()

# Assign to specific user
line_user = env['line.user'].search([('line_user_id', '=', 'Uxxxx')])
line_user.write({'current_richmenu_id': menu.id})  # auto-syncs to LINE

# Reupload after changes
menu.action_reupload_to_line()
```

### How to Set Up Audience Tags and Narrowcast

```python
# Create tag
tag = env['line.audience.tag'].create({
    'name': 'VIP Customers',
    'description': 'High-value repeat customers',
})

# Add users
vip_users = env['line.user'].search([('partner_id.customer_rank', '>', 5)])
tag.write({'user_ids': [(6, 0, vip_users.ids)]})

# Sync to LINE Audience
tag.action_sync_to_line()

# Create and push narrowcast news
news = env['line.news'].create({
    'title': 'VIP Exclusive',
    'summary': 'Special offer for VIPs',
    'state': 'published',
    'push_method': 'narrowcast',
    'push_audience_tag_ids': [(6, 0, [tag.id])],
})
news.action_push_to_line()
```

### LIFF Login Flow Internals

**Critical path**: The LIFF login flow involves several moving parts that must all work correctly:

1. **LIFF SDK initialization**: The bridge page loads the LIFF SDK from `https://static.line-scdn.net/liff/edge/2/sdk.js` and calls `liff.init({liffId})`.

2. **Token acquisition**: After login, the page extracts both ID Token (`liff.getIDToken()`) and Access Token (`liff.getAccessToken()`) as fallback.

3. **Server-side verification**: ID Token is verified via `POST https://api.line.me/oauth2/v2.1/verify`. Access Token fallback uses `GET https://api.line.me/oauth2/v2.1/verify?access_token=...`.

4. **User creation**: `line.user.create_or_update_from_liff()` (from `woow_line_base`) handles idempotent user creation.

5. **Portal user provisioning**: The `_ensure_portal_user()` method follows a strict lookup order:
   - Existing `line_user.partner_id` -> find user for that partner
   - Email match -> bind LINE user to existing partner
   - Create new partner + portal user with random password

6. **Session authentication**: Uses `request.session.authenticate(db, credential_dict)` -- Odoo 18's dict-based authentication.

7. **SUPERUSER context**: The controller uses `auth='none'`, so `request.env.uid` is None. All ORM operations use `api.Environment(cr, SUPERUSER_ID, ...)` to avoid cache KeyError issues. The `active_test=False` context is used to handle cases where OdooBot (uid=1) may be inactive.

### Webhook Event Routing

The webhook controller resolves credentials in this priority:

1. `config_id` URL parameter -> `line.liff.config` record
2. Default active `line.liff.config`
3. `im_livechat.channel` with `line_enabled=True` (soft dependency)
4. Global `ir.config_parameter` (via `line.api.service`)

After processing, events are **forwarded** to the livechat module via dynamic import:
```python
from odoo.addons.woow_odoo_livechat_line.controllers.webhook import LineWebhookController
```
This is wrapped in `try/except ImportError` for graceful degradation.

### Config Sync Mechanism

The `line.liff.config` model acts as the **single source of truth** for all LINE credentials and settings. On every `create()` or `write()` that touches `_SYNC_FIELDS`, values are copied to `ir.config_parameter`. This design allows:

- `line.api.service` (from `woow_line_base`) to read credentials from system parameters without a hard dependency on this module
- Multiple configs to coexist (though only one syncs to global parameters at a time)
- Settings UI to edit config fields via `related` fields

### Error Handling Patterns

1. **Auto-push hook**: Wrapped in double try/except. Inner exception logs per-notification failures. Outer exception ensures `mail.notification.create()` always succeeds.

2. **Broadcast 429 degradation**: When `api.broadcast()` fails (rate limited), the push automatically falls back to `api.multicast()` using all follower user IDs.

3. **Rich Menu reupload**: `action_reupload_to_line()` remembers `was_default` state, deletes the old menu, creates a new one, and re-applies default if needed.

4. **LIFF token fallback**: Both ID Token and Access Token are attempted. If ID Token verification fails, Access Token is tried as backup.

5. **Webhook processing**: Each event is processed independently in a try/except block. One failing event does not block others. The response is always 200 OK (as required by LINE Platform).

### Important Gotchas

1. **Broadcast 429 auto-degradation**: When broadcast fails with HTTP 429 (rate limited), the code silently falls back to multicast. The `line_last_push_method` field records the **actual** method used, which may differ from the selected `push_method`.

2. **Token caching**: `line.api.service` (from `woow_line_base`) may cache tokens. After rotating credentials in `line.liff.config`, the system parameters are updated immediately, but cached tokens in running workers may persist until the next request cycle.

3. **`numbercall` deprecated in Odoo 18**: The cron XML uses `<field name="numbercall">-1</field>`. In Odoo 18, this field is deprecated and ignored by the scheduler. The cron runs indefinitely based on `interval_number` and `interval_type` alone. Do not rely on `numbercall` for limiting cron executions.

4. **`auth='none'` in LIFF controllers**: The LIFF redirect controller uses `auth='none'` because the user is not yet authenticated. This means `request.env.uid` is None, and standard ORM operations will fail. Always use `sudo()` or construct a `SUPERUSER_ID` environment.

5. **Audience tag sync strategy**: LINE Audience API does not support full member replacement. The module uses **delete + recreate** on every sync. This means the `line_audience_group_id` changes on each sync, and any external references to the old ID become invalid.

6. **LINE image requirements**: News cover images served via `/liff/news/image/<id>` are processed to max 1024x1024 pixels. LINE Flex Message images require HTTPS URLs; the code explicitly replaces `http://` with `https://`.

7. **Portal user password**: LIFF login generates a random 32-char password for each portal user. The password changes on every LIFF login session. Users cannot use password-based login; they must always authenticate via LIFF.

8. **LiveChat webhook forwarding**: The bridge module's `/line/webhook/<int:config_id>` route captures all integer-parameterized webhook URLs. If `woow_odoo_livechat_line` is installed, its webhook events are forwarded via dynamic import, not via separate routes.

9. **`skip_line_notification` context**: When performing operations from webhook postback handlers (e.g. cancelling a booking), always pass `context={'skip_line_notification': True}` to prevent recursive push loops.

10. **Flex Message `altText`**: LINE requires `altText` for Flex Messages (shown in push notifications and non-supported clients). Always provide meaningful `altText` -- it is the only text visible in notification banners.

---

## Cross-Module Method Dependencies

| This module calls | woow_line_base method | Context |
|-------------------|-----------------------|---------|
| Webhook controller | `verify_webhook_signature()` | Every incoming POST |
| Webhook controller | `reply()` | Follow welcome, auto-reply |
| Webhook controller | `get_profile()` | Follow event |
| Webhook controller | `line.user.create_or_update_from_webhook()` | Follow/message events |
| LIFF controller | `verify_id_token()` / `verify_access_token()` | LIFF login |
| LIFF controller | `line.user.create_or_update_from_liff()` | LIFF login |
| News push | `push()` / `broadcast()` / `multicast()` / `narrowcast()` | News push action |
| Rich Menu | `richmenu_create/upload/set_default/delete/link_*` | Rich Menu lifecycle |
| Auto-push hook | `push()` | mail.notification override |
| Audience sync | `audience_create()` / `audience_delete()` | Tag sync |
| Insight cron | `get_insight_delivery()` / `get_insight_followers()` | Daily stats |
| Quota display | `get_quota()` / `get_quota_consumption()` | News form computed field |

### Methods Exposed by This Module (for downstream modules)

| Model | Method | Purpose | Used by |
|-------|--------|---------|---------|
| `line.bridge` | `notify_partner(partner, msg_or_flex)` | Push notification to a partner's LINE users | Any business module |
| `line.bridge` | `notify_group(xml_id, msg_or_flex)` | Push to all users in a security group | Any business module |
| `line.flex.factory` | `build_notification(event_type, title, ...)` | Build a generic Flex Message | Any business module |
| `line.flex.factory` | `build_tracking_notification(message, partner)` | Build Flex from mail.message tracking | `mail.notification` hook |
| `line.flex.template` | `build_welcome()`, `build_news_card()`, etc. | Domain-specific Flex templates | Webhook handler, news push |
| `res.partner` | `push_to_line(msg_or_flex)` | Convenience method on partner | Any business module |
| `line.liff.config` | `_get_default_config()` | Get the default LINE config | Any module needing credentials |
| `line.liff.config` | `_get_api_credentials()` | Returns (channel_id, secret, token) | `line.api.service` callers |

---

## Local Development & Testing

### Exposing Local Odoo for Webhook Testing

```bash
# Option 1: ngrok
ngrok http 8069
# Copy HTTPS URL → set as webhook in LINE Console

# Option 2: Cloudflare Tunnel
cloudflared tunnel --url http://localhost:8069

# Update Odoo system parameter
Settings → Technical → Parameters → System Parameters
  web.base.url = https://your-tunnel-url.com
```

### Running Tests

```bash
# All tests
odoo-bin -d testdb -i woow_odoo_line_liff --test-enable --stop-after-init

# Specific test
odoo-bin -d testdb --test-tags=/woow_odoo_line_liff -k test_flex_template

# With verbose logging
odoo-bin -d testdb -i woow_odoo_line_liff --test-enable --stop-after-init --log-level=test
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| LIFF redirect loops infinitely | `web.base.url` is HTTP | Set to HTTPS in system parameters |
| LIFF login fails with "Invalid ID token" | Login channel ID mismatch | Verify `login_channel_id` matches the LIFF app's channel |
| Webhook returns 200 but no events logged | Signature verification failed | Check `messaging_channel_secret` matches LINE Console |
| Rich Menu image not showing | Image not uploaded after create | Call `action_create_on_line()` — it uploads automatically |
| Broadcast fails silently | HTTP 429 rate limit | Check `line_last_push_method` — it may have auto-degraded to multicast |
| News push shows 0 sent | No followers with `is_follower=True` | Check LINE user records; run webhook follow test |
| Audience sync fails | LINE returns 401 | Re-issue access token in LINE Console |
| Auto-push not triggering | `auto_line_notify` is False | Enable in Settings → LINE → Configuration |
| Portal user can't log in with password | LIFF generates random password | By design — users authenticate via LIFF only |
| Flex Message shows only altText | Client doesn't support Flex | Expected on desktop LINE or old versions |
