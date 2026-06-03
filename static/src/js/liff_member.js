/**
 * woow_line_bridge/static/src/js/liff_member.js
 * 會員中心主入口頁 JavaScript
 * 初始化 LIFF → 取得 profile → 綁定按鈕事件
 */
(function () {
    'use strict';

    var liffId = window.__LIFF_ID__;
    if (!liffId) {
        console.warn('[LiffMember] LIFF ID 未設定');
        return;
    }

    // 等待 DOM 就緒
    function onReady(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    onReady(function () {
        initLiff();
        bindButtons();
    });

    function initLiff() {
        if (typeof liff === 'undefined') {
            console.error('[LiffMember] LIFF SDK 未載入');
            return;
        }

        liff.init({ liffId: liffId }).then(function () {
            if (!liff.isLoggedIn()) {
                // 在 LINE 內會自動登入，外部瀏覽器需手動
                if (!liff.isInClient()) {
                    console.log('[LiffMember] 非 LINE 環境，略過自動登入');
                }
                return;
            }

            // 更新使用者資訊
            liff.getProfile().then(function (profile) {
                updateUserUI(profile);
            }).catch(function (err) {
                console.error('[LiffMember] getProfile 失敗', err);
            });
        }).catch(function (err) {
            console.error('[LiffMember] LIFF init 失敗', err);
        });
    }

    function updateUserUI(profile) {
        // 更新頭像
        var avatarEl = document.getElementById('liff-user-avatar');
        if (avatarEl && profile.pictureUrl) {
            avatarEl.innerHTML = '<img src="' + profile.pictureUrl + '" ' +
                'alt="' + (profile.displayName || '') + '" ' +
                'style="width:48px;height:48px;border-radius:50%;object-fit:cover;" />';
        }

        // 更新問候語
        var greetingEl = document.getElementById('liff-user-greeting');
        if (greetingEl && profile.displayName) {
            greetingEl.textContent = profile.displayName + '，歡迎光臨';
        }
    }

    function bindButtons() {
        // 立即預約
        bindRedirectButton('btn-book', 'book');

        // 我的預約
        bindRedirectButton('btn-my-bookings', 'my-bookings');

        // 個人資料
        bindRedirectButton('btn-profile', 'profile');

        // 聯絡我們（直接在 LINE 中開啟對話）
        var contactBtn = document.getElementById('btn-contact');
        if (contactBtn) {
            contactBtn.addEventListener('click', function (e) {
                e.preventDefault();
                // 在 LINE 內直接回到聊天室
                if (typeof liff !== 'undefined' && liff.isInClient()) {
                    liff.closeWindow();
                }
            });
        }
    }

    function bindRedirectButton(elementId, target) {
        var btn = document.getElementById(elementId);
        if (!btn) return;

        btn.addEventListener('click', function (e) {
            e.preventDefault();

            if (typeof liff === 'undefined' || !liff.isLoggedIn()) {
                // 未登入，導向一般網頁
                window.location.href = '/liff/redirect/' + target;
                return;
            }

            // 已登入，取得 ID Token 後 POST
            var idToken;
            try {
                idToken = liff.getIDToken();
            } catch (err) {
                console.error('[LiffMember] getIDToken 失敗', err);
            }

            if (idToken) {
                // 建立隱藏 form POST
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = '/liff/redirect/' + target;

                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'id_token';
                input.value = idToken;
                form.appendChild(input);

                document.body.appendChild(form);
                form.submit();
            } else {
                // 無 ID Token，走 GET 流程
                window.location.href = '/liff/redirect/' + target;
            }
        });
    }

})();
