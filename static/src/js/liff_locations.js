/**
 * woow_line_bridge/static/src/js/liff_locations.js
 * 店家位置頁 JavaScript
 * Phase 3 補完 Google Maps 整合
 */
(function () {
    'use strict';

    // 目前為預留，Phase 3 補完地圖功能
    function onReady(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    onReady(function () {
        var mapEl = document.getElementById('liff-map');
        if (!mapEl) return;

        var lat = mapEl.getAttribute('data-lat');
        var lng = mapEl.getAttribute('data-lng');

        if (!lat || !lng) return;

        // Phase 3: 初始化 Google Maps 或使用靜態地圖
        // 目前使用 Google Maps Static API 預覽
        var placeholder = mapEl.querySelector('.liff-map-placeholder');
        if (placeholder) {
            placeholder.innerHTML = '<p style="text-align:center;padding:40px 0;color:#6B5B4E;">' +
                '📍 ' + lat + ', ' + lng +
                '<br><a href="https://www.google.com/maps?q=' + lat + ',' + lng +
                '" target="_blank" style="color:#B8956A;">在 Google 地圖中開啟</a></p>';
        }
    });

})();
