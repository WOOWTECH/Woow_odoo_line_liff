/**
 * woow_line_bridge/static/src/js/liff_inject.js
 * LIFF 模式注入腳本
 * 偵測 ?liff=1 後隱藏 Odoo header/footer，讓既有 portal 頁面在 LINE 內看起來像 App
 * 同時確保 portal 頁面內的連結帶上 ?liff=1 參數
 */
(function () {
    'use strict';

    // 只在 LIFF 模式下執行
    var params = new URLSearchParams(window.location.search);
    if (params.get('liff') !== '1') return;

    // 等待 DOM 就緒
    function onReady(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    onReady(function () {
        // 標記 body class
        document.body.classList.add('liff-mode');
        document.documentElement.classList.add('liff-mode');

        // 隱藏 Odoo header/footer/navbar
        var selectors = [
            'header',
            'nav.navbar',
            '.o_main_navbar',
            'footer',
            '.o_portal_navbar',
            '#top_menu_container',
            '#oe_main_menu_navbar',
        ];

        selectors.forEach(function (sel) {
            var elements = document.querySelectorAll(sel);
            elements.forEach(function (el) {
                el.style.display = 'none';
            });
        });

        // 調整 main content 的 padding-top
        var mainContent = document.querySelector('#wrapwrap') ||
                          document.querySelector('.o_action_manager') ||
                          document.querySelector('main');
        if (mainContent) {
            mainContent.style.paddingTop = '0';
            mainContent.style.marginTop = '0';
        }

        // 為所有內部連結加上 ?liff=1 參數
        _appendLiffParam();

        // 監聽動態載入的內容
        var observer = new MutationObserver(function () {
            _appendLiffParam();
        });
        observer.observe(document.body, { childList: true, subtree: true });
    });

    /**
     * 為頁面上的內部連結加上 liff=1 參數
     */
    function _appendLiffParam() {
        var links = document.querySelectorAll('a[href]');
        links.forEach(function (link) {
            var href = link.getAttribute('href');
            if (!href) return;

            // 只處理內部連結（相對路徑或同 host）
            if (href.startsWith('http') && !href.includes(window.location.host)) return;
            if (href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) return;

            // 已有 liff 參數則跳過
            if (href.includes('liff=1')) return;

            // 加上 liff=1
            var separator = href.includes('?') ? '&' : '?';
            link.setAttribute('href', href + separator + 'liff=1');
        });

        // 也處理 form action
        var forms = document.querySelectorAll('form[action]');
        forms.forEach(function (form) {
            var action = form.getAttribute('action');
            if (!action) return;
            if (action.startsWith('http') && !action.includes(window.location.host)) return;
            if (action.includes('liff=1')) return;

            // 加入隱藏欄位
            var existing = form.querySelector('input[name="liff"]');
            if (!existing) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'liff';
                input.value = '1';
                form.appendChild(input);
            }
        });
    }

})();
