# 部署限制（合約與 SOP 必須載明）

本文件記錄這套 LINE 模組**目前版本**在架構上的硬限制。這些不是 bug，是尚未實作
的能力——但如果客戶的期待超出這裡寫的範圍，就會在正式營運中出事，而且多半是靜默
出事。**簽約與導入前請逐項確認。**

最後更新：2026-09-12（18.0.3.2.5：通知卡片改中文摘要、LINE 聯絡人語言）

---

## 1. 一個 Odoo 資料庫只能接一個 LINE 官方帳號

**這是最重要的一條。**

`line.liff.config` 這個 model 看起來像 `pos.config` 那樣的多實體設計——它有
`company_id`、有 `sequence`、有 `active`、有獨立選單、還會為每一筆算出各自的
webhook URL，而空狀態的文案甚至寫著「建立您的第一個 LINE 設定檔／每個設定檔代表一個
LINE 官方帳號」。

**但送訊層完全沒有實作 per-config。** 所有對外呼叫（push、multicast、broadcast、
narrowcast、rich menu、reply）讀的都是同一組全域 `ir.config_parameter`，那組參數由
「最後被存檔的那一筆設定檔」決定。

如果同時存在兩筆啟用中的設定檔會發生什麼：

| 動作 | 結果 |
|---|---|
| `broadcast` / rich menu 設為預設 | **無條件對錯誤帳號的全體好友生效**，LINE 平台不會擋 |
| `push` / `multicast` | 多半回 400（userId 是 provider-scoped），吵但無害 |
| `reply`（自動回覆、歡迎訊息） | 拿 A 的 replyToken 配 B 的 token，被 LINE 拒絕；而 `reply()` 對非 200 **連 log 都不寫**，於是歡迎訊息與自動回覆靜默失效，Odoo 端每個指標都正常 |
| 稽核軌跡 | `line.push.log` 會記成設定檔 A，實際卻用了 B 的憑證——記錄會說謊 |

**目前的防護：** `line.liff.config` 上有一條 `@api.constrains('active')`，偵測到
第二筆啟用中的設定檔就 raise。也就是說系統現在會**擋住**你，而不是讓你靜默出事。
這是護欄，不是修復。

**合約與 SOP 應載明：** 每個 Odoo 實例只服務一個 LINE 官方帳號。客戶若有第二個
官方帳號（不同品牌、不同門市、測試帳號），需要**另一個 Odoo 實例**。

**要解除這個限制需要：** 把所有送訊呼叫端改走 `config._get_api_credentials()`
（該 helper 已定義但全 repo 零呼叫端），並保留 `line.richmenu.config_id` 為空時的
fallback，否則既有租戶升級後按任何 rich menu 按鈕都會壞。屬設計層工作。

---

## 2. 一個資料庫只能有一個啟用 LINE 的客服頻道

`woow_odoo_livechat_line` 的轉發邏輯用的是
`search([('line_enabled', '=', True)], limit=1)`，**不會**沿用 webhook URL 上已經
解析出來的那個頻道。

所以同一個官方帳號想做 sales / support 分流（兩個 `line_enabled=True` 的
`im_livechat.channel`）時，所有對話都會落到 id 最小的那一個，第二個團隊看不到任何
訊息，也不會有任何錯誤。

**SOP：** 一個資料庫只准一個 `line_enabled=True` 的客服頻道。

延伸問題：`/line/webhook/<int:id>` 這個路由同時是 `line.liff.config.id` 與
`im_livechat.channel.id` 的命名空間，兩個序列都從 1 開始，URL 無法區分。目前靠
bridge controller 主動轉發來繞過，且該路徑沒有任何測試覆蓋。

---

## 3. 多公司隔離尚未實作

`line.user`、`line.event.log`、`line.push.log`、`line.auto.reply` 這幾個 model
**沒有 `company_id` 欄位**，三個模組也沒有任何 `ir.rule`
（`security/line_security.xml` 是空檔）。

所以一個資料庫裝多家公司時，LINE 資料不分公司、全部混在一起。

**SOP：** 若客戶是多公司架構，合約需明確界定「LINE 整合只服務其中某一家」。
（現行的 puhsu 就是一個資料庫四家公司，只服務璞旭工程一家。）

---

## 4. 個人資料只進不出

目前沒有刪除機制、沒有匿名化方法、沒有保存期限 cron：

- `line.user` 存 display_name / picture_url / status_message / email，unfollow 只設
  旗標，刪除 partner 只是 `set null`，沒有 `active` 欄位也沒有 unlink override
- `line.event.log.raw_payload` 永久保存完整訊息全文與 token
- `line.push.log` 無限成長，逐字保存客戶姓名、預約項目、地址

**這是合約層要回答的問題：** 客戶若依個資法第 11 條或 GDPR Art. 17 要求刪除，
目前沒有任何機制可以履行。醫療、診所類客戶尤其需要事先講清楚。

---

## 5. 附件網址無法撤銷

客服在 Discuss 附加的檔案，會被呼叫 `generate_access_token()` 產生**永久有效、
免登入、可轉傳**的公開網址，然後送進 LINE。內部文件（報價單、合約、發票）一旦這樣送出
就無法收回。

**SOP：** 客服不得在 LINE 對話中附加既有的業務單據，只能上傳專為該次對話準備的檔案。

---

## 6. 其他需要在導入時說明的行為

- **`match_type='regex'` 的自動回覆仍不建議使用**：18.0.3.2.2 起存檔時會擋下常見的
  災難性寫法（巢狀量詞 `(x+)+`、量詞下的交替 `(x|xy)+`、反向引用、超過 200 字），
  比對時對舊資料再檢查一次，且只拿訊息前 500 字去比對。但這是靜態啟發式檢查，
  Python `re` 沒有逾時，**擋不住所有寫法**（例如多層括號 `((a+))+` 會漏網）。
  **SOP：優先用 contains / exact；非用 regex 不可時由我方審核 pattern。**
- **webhook 重送已冪等**（18.0.3.2.2）：同一個 `message.id` 在同一個對話裡只會建立
  一則訊息與一份附件（每個對話記住最近 200 個 id）。
- **客戶傳入的媒體有大小上限**（18.0.3.2.2）：預設 50 MB，可用
  `ir.config_parameter` 的 `woow_line_base.content_max_mb` 調整。超過上限的檔案不會
  下載，客服在 Discuss 看到的是「[Video - download failed]」這類提示，需請客戶改用
  其他方式提供。下載仍是同步執行，上限內的大檔仍會拖慢該次 webhook。
- **`web.base.url.freeze` 必須設為 True**：否則任何管理員用不同 hostname 登入一次就會
  覆寫 `web.base.url`，之後所有 Flex 圖片與按鈕連結都會指向 LINE 連不到的位址
  （Flex 圖片強制 https，非 https 直接不顯示）。（2026-09-10 五台皆已設定。）
- **出向音訊的長度是寫死的 60 秒**，與實際音檔長度無關。實機驗證：一段 1 分 9 秒的
  錄音，客戶端顯示為「1分鐘0秒」。要修需要音訊解析套件，目前不做。
- **出向影片的預覽圖是固定的灰底播放鍵**（`static/img/video_preview.png`），不是
  影片的第一格畫面。影片本身可以正常播放。
- **Broadcast 不會排除「關閉通知」的好友**（LINE 平台對全體好友發送，無法過濾），
  但 broadcast 因配額 429 降級成 multicast 時會排除他們——同一個按鈕的實際收件範圍
  隨配額狀態改變（H-15）。**SOP：尊重退訂的推播一律用 multicast / narrowcast。**

---

## 7. LINE 官方帳號後台（OA Manager）必須配合的設定

這幾項不在 Odoo 裡，Odoo 無法代設，**導入時要在 manager.line.biz 逐項確認**：

- **開 LINE 客服時，「回應設定 → 自動回應訊息」必須關閉**，Webhook 保持開啟。否則客戶
  每傳一則訊息，LINE 都會先自動回「很抱歉，本帳號無法個別回覆用戶的訊息」，與客服
  相矛盾。2026-09-10 實測 KomiBright、璞旭工程兩個帳號都還開著。
- **iPad 版 LINE 不顯示圖文選單（Rich Menu）**。只靠選單當入口的功能（預約、最新消息
  等）在 iPad 上找不到，需要另外提供入口：歡迎訊息內的連結、關鍵字自動回覆。
- **未認證的官方帳號**會在聊天室頂端對客戶顯示「尚未經過認證…若涉及個資收集、投資交易
  或金錢，請務必提高警覺」的警示橫幅。有收個資或金流的客戶建議申請認證。
- **預約按鈕的目的地是每個租戶自己設定的**：`line.liff.config.rebook_path`，未設定時
  安全預設為 `/my/home`（不再寫死 `/appointment/1/schedule`）。沒有設定檔的租戶
  （例如 evergreen）永遠走預設值。

---

## 8. 同一組 LINE 憑證存在三個地方

`ir.config_parameter`（`woow_line_base.*`）、`line.liff.config`、
`im_livechat.channel`（LINE 客服頻道）各存一份 Channel ID / Secret。**更換（rotate）
Channel Secret 或 Access Token 時三處都要改**，漏改其中一處會讓對應的功能（送訊、
LIFF 登入、客服轉發）靜默失效。合併成單一來源屬設計層工作，目前不做（B-8）。

---

## 升級注意事項

三個模組現在都有 `migrations/`。升級前仍請：

1. **先做可還原的資料庫備份**（`pg_dump -Fc`）。
2. 升級後**必須** `rollout restart`——`-u` 的「Registry changed, signaling through
   the database」不足以讓正在跑的 worker 換掉已載入的 Python 模組。
3. 檢查 `ir_model_data` 裡是否還有 `module='woow_line_bridge'` 的列（應為 0）。
   `18.0.3.2.1` 的 pre-migrate 會自動清理，但值得確認。
4. 確認 `woow_line_base.login_channel_id` 有值。`verify_access_token` 現在會比對
   `client_id` 且**取不到設定時 fail closed**，所以這個參數為空會讓 LIFF 的
   access-token 登入全數失敗。
5. **18.0.3.2.2 起三個模組要一起升級**：liff 的 Rich Menu 修復呼叫 base 新增的
   `richmenu_create_ex` / `richmenu_delete_ex`，只升 liff 不升 base 會在按
   「重新上傳」「封存」時出錯；livechat 在 `discuss_channel` 新增一個欄位
   （`line_processed_message_ids`），升級時會自動加欄位，不需要手動 migration。
6. 升級後 `line.event.log` 的「有錯誤」篩選器開始會有資料（以前永遠是空的）——
   這是修好了，不是出事了。
7. **18.0.3.2.3 的 base 與 liff 要一起升級**：liff 呼叫 base 新增的
   `audience_delete_ex` / `richmenu_upload_image_ex`。沒有資料庫結構變更。
8. 18.0.3.2.3 起 LIFF 免密碼登入會正確記在客人名下，客人的「最後登入」會更新；
   在這之前的 LIFF 登入紀錄作者都是 OdooBot，無法回溯補正。
9. 18.0.3.2.3 起圖文選單存檔時會檢查每一格都落在圖片內（全版 2500×1686、
   半版 2500×843）。升級前五台現有的 24 格都已確認在範圍內。
10. **請直接用 18.0.3.2.4，不要停在 18.0.3.2.3**：3.2.3 把 LINE 刪除分眾名單的
    成功回應（202）與「名單已不存在」（400 audience group not found）都當成失敗，
    按「從 LINE 刪除」一定顯示失敗、編號也清不掉。3.2.4 修正，base 與 liff 一起升。
11. **18.0.3.2.5 起自動通知卡片不再貼 email 內文**（H-17）：卡片改成單據的中文摘要
    ——行事曆「活動邀請 9/15（二）16:00」＋時間地點、報價單／銷售訂單＋金額、發票＋
    金額與付款期限，其他類型「您有一則新通知」＋單據名稱，一律附「查看詳情」。狀態變更
    照舊列出。**同仁在對話紀錄裡打的文字也不會再出現在卡片上**，客人要點「查看詳情」
    才看得到；想把文字直接送到客人 LINE，請用 LINE 客服（Discuss）。
12. **18.0.3.2.5 的 base 升級會更正 LINE 客人的聯絡人語言**：綁定 LINE、目前是
    en_US 的聯絡人改成 LINE 偏好語言（預設 zh_TW）；員工自己的聯絡人與偏好英文的
    客人不動。之後 Odoo 寄給這些客人的信件，有中文翻譯的就是中文。2026-09-12 盤點：
    只有 markstudio 受影響（5 位），其他四台都是 0。新建立的 LINE 聯絡人從此直接用
    LINE 偏好語言。
