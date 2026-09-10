# 部署限制（合約與 SOP 必須載明）

本文件記錄這套 LINE 模組**目前版本**在架構上的硬限制。這些不是 bug，是尚未實作
的能力——但如果客戶的期待超出這裡寫的範圍，就會在正式營運中出事，而且多半是靜默
出事。**簽約與導入前請逐項確認。**

最後更新：2026-09-10（部署前稽核修復後）

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

- **`match_type='regex'` 的自動回覆有 DoS 風險**：pattern 直接執行、無逾時、無長度
  上限，且位於 webhook 的同步請求內。一則精心構造的訊息即可吃滿 worker（實測
  `(a+)+b` 對 26 個 a 需 38.5 秒），匿名可觸發。**SOP：禁止使用 regex 類型。**
- **webhook 沒有冪等處理**：不檢查 `message.id` 與 `deliveryContext.isRedelivery`。
  請確認客戶的 LINE Console **未開啟** webhook redelivery，否則重送會造成重複訊息、
  重複附件、自動回覆重複觸發。
- **媒體下載沒有大小上限**且為同步：客戶傳送大型影片會造成 worker 記憶體暴衝與
  webhook 逾時。請告知客戶勿在 LINE 傳大檔。
- **`web.base.url.freeze` 必須設為 True**：否則任何管理員用不同 hostname 登入一次就會
  覆寫 `web.base.url`，之後所有 Flex 圖片與按鈕連結都會指向 LINE 連不到的位址
  （Flex 圖片強制 https，非 https 直接不顯示）。
- **出向音訊的長度是寫死的 60 秒**，與實際音檔長度無關。

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
