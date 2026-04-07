# TommyTV Dashboard

## Prosjekt
- **URL**: https://tommytv.no (via Cloudflare Tunnel)
- **LAN**: http://nuc.tommy.tv:8880 (direkte)
- **Stack**: Statisk HTML + Nginx + Cloudflare Tunnel (Docker Compose)
- **Start**: `docker compose down && docker compose up -d`

## Filstruktur
- `index.html` — Hoveddashboard med e-post, VPN, offentlige tjenester og LAN-tjenester
- `status.html` — Status-side (LAN): Smarthus (Hue + Homey + Nanoleaf + Plejd + Yale + gardiner) + Infrastruktur (UniFi + speedtest + WiFi restart)
- `bookmarks.html` — Bokmerkeside med eksterne tjenester og lenker
- `heating.html` — Varme og sikkerhet (LAN): Gulvvarme, Mill-ovn, Yale-lås, temperaturer, batteristatus, printer
- `sparing.html` — Spareoversikt-side (portefølje, fordeling, anbefalinger)
- `photos.html` — Fotoside med Immich-integrasjon
- `tommy_skogstad_brand_guide.html` — Brand guide (visuell identitet, logo, farger, typografi) — standalone side uten header.js/footer.js
- `header.js` — Delt navigasjonskomponent (inkluderes av alle sider)
- `footer.js` — Delt footerkomponent (inkluderes av alle sider)
- `sparing-data.json` — Porteføljedata for sparesiden
- `sparing-anbefaling.json` — Investeringsanbefalinger for sparesiden
- `logo.svg` — SVG-tekstlogo med gradient (Tommy=blå gradient, TV=hvit)
- `nginx.conf` — Nginx-konfigurasjon
- `docker-compose.yml` — Cloudflared + Nginx + sparing-api, port 8880 eksponert for LAN
- `.env` — Cloudflare Tunnel-token (git-ignorert)

## Tjenester (Docker Compose)
- **nginx** — Serverer statiske filer, port 8880
- **cloudflared** — Cloudflare Tunnel til tommytv.no
- **sparing-api** — Python REST API for porteføljedata (port 8881), leser/skriver sparing-data.json

## Arkitektur
- Nginx serverer statiske filer, cloudflared kobler til Cloudflare Tunnel
- Port 8880 eksponert på host for direkte LAN-tilgang
- Alle HTML-filer må mountes som volumes i docker-compose.yml

## Immich-fotointegrasjon (photos.html)
- Bildefremvisning med Immich API (port 2283) via nginx-proxy (/immich-api/)
- Personsøk, favorittmarkering, zoom-til-ansikt, fullskjerm, skjuling av bilder

## Navigasjon
Hovednavigasjonen inneholder:
- **Offentlig** (alle): Dashboard, Bokmerker, Brand Guide
- **LAN** (kun lokalt): Status, Varme & Sikkerhet, Sparing, Bilder

## LAN-logikk
- Seksjoner med klasse `local-section` og `style="display: none;"` er skjult som standard
- JavaScript viser dem kun når `location.hostname !== 'tommytv.no'` (dvs. LAN-tilgang)
- På tommytv.no viser header.js en "LAN-versjon"-lenke i navigasjonen som peker til `http://nuc.tommy.tv:8880`
- På LAN vises i stedet ekstra navigasjonspunkter (Status, Varme & Sikkerhet, Sparing, Bilder)
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
Nginx bruker volume mounts, men restart sikrer at endringene blir plukket opp.
