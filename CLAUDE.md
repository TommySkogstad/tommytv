# TommyTV Dashboard

## Prosjekt
- **URL**: https://tommytv.no (via Cloudflare Tunnel)
- **LAN**: http://nuc.tommy.tv:8880 (direkte)
- **Stack**: Statisk HTML + Nginx + Cloudflare Tunnel (Docker Compose)
- **Start**: `docker compose down && docker compose up -d`

## Filstruktur
- `public/` — Alle statiske filer servert av nginx (én katalog-mount, inode-immun)
  - `index.html` — Hoveddashboard med e-post, VPN, offentlige tjenester og LAN-tjenester
  - `status.html` — Status-side (LAN): Smarthus (Hue + Homey + Nanoleaf + Plejd + Yale + gardiner) + Infrastruktur (UniFi + speedtest + WiFi restart)
  - `bookmarks.html` — Bokmerkeside med eksterne tjenester og lenker
  - `heating.html` — Avviklet (homey-shs avviklet 2026-06-01)
  - `sparing.html` — Spareoversikt-side (portefølje, fordeling, anbefalinger)
  - `photos.html` — Videresendes til bilder.tommytv.no
  - `tommy_skogstad_brand_guide.html` — Brand guide (visuell identitet, logo, farger, typografi) — standalone side uten header.js/footer.js
  - `header.js` — Delt navigasjonskomponent (inkluderes av alle sider)
  - `footer.js` — Delt footerkomponent (inkluderes av alle sider)
  - `sparing-data.json` — Porteføljedata for sparesiden (leses/skrives av sparing-api)
  - `sparing-anbefaling.json` — Investeringsanbefalinger for sparesiden
  - `robots.txt` — SEO: instruksjoner til webcrawlere
  - `sitemap.xml` — SEO: sitemap for søkemotorer
  - `llms.txt` — GEO: maskinlesbar profilside for AI-søkemotorer
  - `icons/` — Ikonmappe
  - `dashboard.html` — Alternativt dashboard
  - `status-app.html` — Status-app side
  - `favicon.svg` — Nettstedets favicon (SVG)
  - `tommy_skogstad_favicon_16.svg` — Brand favicon 16px
  - `tommy_skogstad_favicon_32.svg` — Brand favicon 32px
  - `tommy_skogstad_logo_lys.svg` — Brand logo (lys variant)
  - `tommy_skogstad_logo_mork.svg` — Brand logo (mørk variant)
  - `logo.svg` — SVG-tekstlogo med gradient (Tommy=blå gradient, TV=hvit)
- `nginx.conf` — Nginx-konfigurasjon (git-crypt-kryptert)
- `docker-compose.yml` — Cloudflared + Nginx + sparing-api, port 8880 eksponert for LAN
- `.env` — Cloudflare Tunnel-token (git-ignorert, git-crypt-kryptert)

## Tjenester (Docker Compose)
- **nginx** — Serverer statiske filer, port 8880
- **cloudflared** — Cloudflare Tunnel til tommytv.no
- **sparing-api** — Python REST API for porteføljedata (port 8881), leser/skriver sparing-data.json
- **status-api** — Read-only JSON-API mot `~/status-data/status.db` (port 8882, proxy via nginx som `/status-api/`). Endepunkter: `/api/apps`, `/api/overview`, `/api/app/<slug>`, `/api/series/<slug>/<metric>`, `/api/shadow-modes`, `/api/job-metrics`, `/api/triage-24h?hours=<n>` (triage-classifier-resultater for siste n timer, default 24). Kilder: misc-scripts/status/

## Dashboard-tjenester (index.html)
Offentlige tjenester vist på dashboardet (seksjon "Offentlige tjenester"):
- **Biologportal** — portal.leienbiolog.no — Oppdragshåndtering for biologer
- **Sameiet HWA 6-8-10** — 6810.no — Beboerportal
- **Styreportal** — styreportal.leienbiolog.no — Multi-tenant styreportal
- **BilagBot** — bilag.tommytv.no — AI-drevet bilagsscanner
- **md2pdf** — md.tommytv.no
- **Stirling PDF** — pdf.tommytv.no
- **Ntfy** — ntfy.tommytv.no
- **Uptime Kuma** — uptime.tommytv.no
- **Speedtest** — speedtest.tommytv.no
- **Plex** — app.plex.tv
- **Smart Casual** — smart-casual.no — Norsk guide til kleskoder og herrekledning
- **Safekeeper** — github.com/TommySkogstad/safekeeper
- **Grunnmur** — github.com/TommySkogstad/grunnmur

## Arkitektur
- Nginx serverer statiske filer, cloudflared kobler til Cloudflare Tunnel
- Port 8880 eksponert på host for direkte LAN-tilgang
- `public/` mountes som katalog (ikke enkeltfiler) — inode-immun ved git pull/checkout

## Navigasjon
Navigasjonen har to varianter basert på `location.hostname`:
- **tommytv.no (offentlig)**: Hjem, Portefølje, Brand Guide
- **LAN (nuc.tommy.tv:8880)**: Dashboard, Brand Guide + Bokmerker, Status, Sparing, Bilder

## LAN-logikk
- Seksjoner med klasse `local-section` og `style="display: none;"` er skjult som standard
- JavaScript viser dem kun når `location.hostname !== 'tommytv.no'` (dvs. LAN-tilgang)
- På LAN vises andre navigasjonspunkter (Dashboard i stedet for Hjem/Portefølje) + ekstra LAN-lenker (Bokmerker, Status, Varme & Sikkerhet, Sparing, Bilder)
- bookmarks.html har samme LAN-logikk for seksjoner

## Legge til ny tjeneste (index.html)
Legg kortet i riktig seksjon. JavaScript sorterer alfabetisk automatisk.

### Offentlig tjeneste (synlig for alle):
```html
<a href="https://url.no" class="card" target="_blank">
    <h3><img src="https://url.no/favicon.ico" alt="">Navn</h3>
    <p>Kort beskrivelse av hva tjenesten gjør</p>
    <span class="url">url.no</span>
    <div>
        <span class="tech">Stack1</span>
        <span class="tech">Stack2</span>
    </div>
</a>
```

### LAN-tjeneste (kun synlig lokalt):
Legg kortet i seksjonen med klasse `local-section`. For ny LAN-seksjon:
```html
<section class="section local-section" style="display: none;">
    <div class="section-header">
        <h2>Seksjonsnavn</h2>
        <span class="badge badge-local">LAN</span>
    </div>
    <div class="grid">
        <!-- kort her -->
    </div>
</section>
```

## Legge til bokmerke (bookmarks.html)
Samme kort-format som over. LAN-bokmerker bruker `local-section`-klasse.
Bruk favicon fra tjenestens nettside: `<img src="https://tjeneste.com/favicon.ico" alt="">` i h3.

## Badges
- `badge-public` (grønn) — Offentlig tilgjengelig
- `badge-local` (blå) — Kun LAN

## Etter endringer
Restart containere: `docker compose down && docker compose up -d`
Katalog-mount (`public/`) er inode-immun — nginx leser endrede filer uten restart etter git pull.
