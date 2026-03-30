/* Shared footer for all tommytv pages.
   Usage: <div id="site-footer"></div> + <script src="/footer.js"></script> */
(function() {
    var html = '<footer>' +
        '<div style="margin-bottom:1rem;">' +
            '<strong style="color:var(--white);">Tommy Skogstad</strong>' +
        '</div>' +
        '<div style="display:flex;justify-content:center;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem;">' +
            '<a href="tel:+4748061560" target="_blank" style="color:var(--blue4);text-decoration:none;">48 06 15 60</a>' +
            '<a href="mailto:tommyskogstad@gmail.com" target="_blank" style="color:var(--blue4);text-decoration:none;">tommyskogstad@gmail.com</a>' +
            '<a href="https://www.linkedin.com/in/tommy-skogstad-79b04864/" target="_blank" style="color:var(--blue5);text-decoration:none;">LinkedIn</a>' +
            '<a href="https://github.com/TommySkogstad" target="_blank" style="color:var(--blue5);text-decoration:none;">GitHub</a>' +
        '</div>' +
        '<div style="font-family:\'DM Mono\',monospace;font-size:0.7rem;letter-spacing:0.1em;color:var(--blue3);">' +
            'Ingeni\u00f8r Tommy Skogstad \u00b7 org.nr. 921 954 565 \u00b7 \u00a9 ' + new Date().getFullYear() +
        '</div>' +
    '</footer>';

    var el = document.getElementById('site-footer');
    if (el) el.innerHTML = html;
})();
