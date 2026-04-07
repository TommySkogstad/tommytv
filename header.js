/* Shared header for all tommytv pages.
   Usage: <div id="site-header"></div> + <script src="/header.js"></script>
   Detects LAN vs public automatically. */
(function() {
    var isLAN = location.hostname !== 'tommytv.no';
    var path = location.pathname.replace(/\/$/, '') || '/';

    // Navigation items
    var publicNav = isLAN ? [
        { href: '/', label: 'Dashboard' },
        { href: '/tommy_skogstad_brand_guide.html', label: 'Brand Guide' },
    ] : [
        { href: '/', label: 'Hjem' },
        { href: '/dashboard.html', label: 'Portefølje' },
        { href: '/tommy_skogstad_brand_guide.html', label: 'Brand Guide' },
    ];

    var lanNav = [
        { href: '/bookmarks.html', label: 'Bokmerker' },
        { href: '/status.html', label: 'Status' },
        { href: '/heating.html', label: 'Varme & Sikkerhet' },
        { href: '/sparing.html', label: 'Sparing' },
        { href: '/photos.html', label: 'Bilder' },
    ];

    function isActive(href) {
        if (href === '/') return path === '/' || path === '/index.html';
        return path === href;
    }

    // Build nav links
    var navHTML = '';
    publicNav.forEach(function(item) {
        navHTML += '<a href="' + item.href + '"' + (isActive(item.href) ? ' class="active"' : '') + '>' + item.label + '</a>';
    });

    if (isLAN) {
        navHTML += '<span class="nav-sep"></span>';
        lanNav.forEach(function(item) {
            navHTML += '<a href="' + item.href + '"' + (isActive(item.href) ? ' class="active"' : '') + '>' + item.label + '</a>';
        });
    }

    var html = '<header>' +
        '<a href="/" style="text-decoration:none;color:inherit;">' +
            '<div class="header-brand">' +
                '<img src="/favicon.svg" alt="Tommy Skogstad">' +
                '<div class="header-brand-text">' +
                    '<div class="header-brand-name">Tommy Skogstad</div>' +
                    '<div class="header-brand-sep"></div>' +
                    '<div class="header-brand-sub">systemutvikling · automatisering · AI · drift</div>' +
                '</div>' +
            '</div>' +
        '</a>' +
        '<nav class="header-nav">' + navHTML + '</nav>' +
    '</header>';

    var el = document.getElementById('site-header');
    if (el) el.innerHTML = html;
})();
