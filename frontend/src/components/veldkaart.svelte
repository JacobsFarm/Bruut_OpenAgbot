<script>
    import { onMount, onDestroy } from 'svelte';
    import L from 'leaflet';
    import 'leaflet/dist/leaflet.css';
    import { fmt, fixInfo } from '../lib/telemetry.js';

    // Plan voor instellingen die nog niet rijden (uit het tabblad A-B Tractor).
    // Loopt er een missie, dan toont de kaart altijd het plan van de robot zelf.
    export let voorbeeld = null;

    // Zo vaak vragen we positie, voortgang en nieuw spoor op. De GPS levert
    // 10 Hz; bij 3 km/h schuift de robot per verversing zo'n 25 cm op.
    const POLL_MS = 300;
    // Baannummers pas tonen als de banen zoveel pixels uit elkaar liggen;
    // verder uitgezoomd lopen ze door elkaar heen.
    const LABELS_VANAF_PX = 16;

    // Satelliet eerst, net als de folium-kaarten uit Single_script_code. Zonder
    // internet blijft de ondergrond grijs, maar banen, spoor en robot staan er wel.
    const ONDERGRONDEN = {
        'Satelliet (Esri)': () => L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            { maxZoom: 22, maxNativeZoom: 19, attribution: 'Luchtfoto &copy; Esri' }),
        'Luchtfoto NL (PDOK)': () => L.tileLayer(
            'https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:3857/{z}/{x}/{y}.jpeg',
            { maxZoom: 22, maxNativeZoom: 21, attribution: 'Luchtfoto &copy; PDOK' }),
        'Wegenkaart (OSM)': () => L.tileLayer(
            'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            { maxZoom: 22, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap' }),
    };
    const STANDAARD_ONDERGROND = 'Satelliet (Esri)';

    let kaartDiv;
    let kaart = null;
    let planLaag, labelLaag, spoorLaag;

    let live = null;             // laatste antwoord van /api/ab/live
    let verbonden = true;
    let missiePlan = null;       // plan van de lopende of laatste missie
    let planVersie = -1;
    let planOphalen = false;
    let volgen = false;
    let geplaatst = false;       // stond het kaartbeeld al eens ergens op gericht?

    // Het gereden spoor, een lijn per stuk baan of bocht
    let missieNr = null;
    let spoorLengte = 0;
    let spoorLijn = null;
    let spoorModus = null;
    let spoorLaatste = null;

    // Wat er nu op de kaart staat
    let getekend = null;
    let banen = [];              // per baan: { lijn, label, nr, koers, status }
    let bochten = [];            // per bocht: { lijn, omega, status }
    let veldSleutel = null;
    let voortgangSleutel = null;

    let robot = null;
    let robotHoek = null;        // doorlopende hoek, zodat de pijl nooit de lange weg om draait

    let bezig = true;
    let timer = null;

    $: actief = live?.ab?.actief ?? false;
    $: toonPlan = actief ? missiePlan : (voorbeeld || missiePlan);
    $: if (kaart) tekenPlan(toonPlan);

    $: pos = live?.pos;
    $: heeftPositie = !!(pos && pos.lat && pos.lon);
    $: fix = fixInfo(pos?.fix);
    $: bron = !toonPlan ? ''
        : toonPlan === voorbeeld ? 'Voorbeeld met de instellingen hieronder'
        : actief ? 'Plan van de lopende missie'
        : 'Plan van de laatste missie';
    $: eersteBaan = !toonPlan ? ''
        : (toonPlan.eerste_richting === 'A->B' ? 'A → B' : 'B → A')
        + (!toonPlan.richting_bekend ? ' (aangenomen: de robot heeft nog geen GPS-fix)'
           : toonPlan === voorbeeld ? ' (volgt uit de richting waarin de robot nu staat)' : '');

    onMount(() => {
        kaart = L.map(kaartDiv, { center: [52.1, 5.3], zoom: 7, maxZoom: 22 });

        const ondergronden = {};
        for (const [naam, maak] of Object.entries(ONDERGRONDEN)) ondergronden[naam] = maak();
        let gekozen = STANDAARD_ONDERGROND;
        try {
            const bewaard = localStorage.getItem('veldkaart-ondergrond');
            if (bewaard && ondergronden[bewaard]) gekozen = bewaard;
        } catch (e) {}
        ondergronden[gekozen].addTo(kaart);
        L.control.layers(ondergronden, null, { position: 'topright' }).addTo(kaart);
        L.control.scale({ imperial: false, maxWidth: 150 }).addTo(kaart);
        kaart.on('baselayerchange', (e) => {
            try { localStorage.setItem('veldkaart-ondergrond', e.name); } catch (err) {}
        });

        // Het spoor in een eigen laag boven het plan: tekenen we het plan
        // opnieuw, dan komt het anders over het gereden spoor heen te liggen.
        kaart.createPane('spoor').style.zIndex = 450;
        planLaag = L.layerGroup().addTo(kaart);
        spoorLaag = L.layerGroup().addTo(kaart);
        labelLaag = L.layerGroup();

        kaart.on('zoomend', toonLabels);
        kaart.on('dragstart', () => { volgen = false; });
        toonLabels();
        tik();
    });

    onDestroy(() => {
        bezig = false;
        clearTimeout(timer);
        if (kaart) kaart.remove();
    });

    // ------------------------------------------------------------------
    //  Verversen
    // ------------------------------------------------------------------
    async function tik() {
        try {
            const res = await fetch(`/api/ab/live?spoor_vanaf=${spoorLengte}`, { cache: 'no-store' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (!bezig) return;
            verwerk(data);
            verbonden = true;
        } catch (e) {
            verbonden = false;
        }
        if (bezig) timer = setTimeout(tik, POLL_MS);
    }

    function verwerk(data) {
        const ab = data.ab;
        // Nieuwe missie: het oude spoor hoort daar niet bij.
        if (ab.missie_nr !== missieNr) {
            missieNr = ab.missie_nr;
            wisSpoor();
        }
        if (data.spoor.vanaf === spoorLengte) {
            voegSpoorToe(data.spoor.punten);
        } else if (data.spoor.vanaf === 0) {
            // De backend is opnieuw gestart: alles opnieuw tekenen.
            wisSpoor();
            voegSpoorToe(data.spoor.punten);
        }
        // Anders sluit dit stuk niet aan; de volgende keer vragen we vanaf het goede punt.

        if (ab.plan_versie !== planVersie) haalPlanOp(ab.plan_versie);
        live = data;
        zetRobot(data.pos);
        kleurVoortgang();
    }

    async function haalPlanOp(versie) {
        if (planOphalen) return;
        planOphalen = true;
        try {
            const res = await fetch('/api/ab/plan', { cache: 'no-store' });
            const data = await res.json();
            if (data.status === 'ok') {
                missiePlan = data.plan;
                planVersie = data.plan.versie;
            } else {
                missiePlan = null;
                planVersie = versie;
            }
        } catch (e) {
            // volgende tik opnieuw
        } finally {
            planOphalen = false;
        }
    }

    // ------------------------------------------------------------------
    //  Het plan: banen, bochten, veld, A en B
    // ------------------------------------------------------------------
    function baanStijl(status) {
        if (status === 'nu') return { color: '#00E5FF', weight: 5, opacity: 1, dashArray: null };
        if (status === 'klaar') return { color: '#ffffff', weight: 2, opacity: 0.35, dashArray: null };
        return { color: '#ffffff', weight: 2, opacity: 0.95, dashArray: '8 8' };
    }

    function bochtStijl(omega, status) {
        const kleur = omega ? '#FF1744' : '#FF9100';
        if (status === 'nu') return { color: kleur, weight: 4, opacity: 1, dashArray: null };
        if (status === 'klaar') return { color: kleur, weight: 2, opacity: 0.3, dashArray: null };
        return { color: kleur, weight: 2, opacity: 0.9, dashArray: '6 6' };
    }

    // Volgnummer in de werkvolgorde, met een pijltje in de rijrichting.
    function baanIcoon(nr, koers, status) {
        return L.divIcon({
            className: 'baan-icoon',
            html: `<div class="baan-label ${status}"><div class="baan-pijl" style="transform: rotate(${koers}deg)"></div><span>${nr}</span></div>`,
            iconSize: [26, 26],
            iconAnchor: [13, 13],
        });
    }

    function letterPunt(plek, letter, uitleg) {
        L.marker(plek, {
            icon: L.divIcon({ className: `kaart-punt punt-${letter.toLowerCase()}`, html: letter,
                              iconSize: [22, 22], iconAnchor: [11, 11] }),
            title: uitleg,
            keyboard: false,
        }).addTo(planLaag);
    }

    function tekenPlan(plan) {
        if (plan === getekend) return;
        getekend = plan;
        planLaag.clearLayers();
        labelLaag.clearLayers();
        banen = [];
        bochten = [];
        voortgangSleutel = null;
        if (!plan) return;

        // Het gewas, zodat je ziet waar het veld ligt en waar de kopakkers beginnen.
        L.polygon(plan.veld, {
            color: '#ffffff', weight: 1, opacity: 0.7, fillColor: '#ffffff', fillOpacity: 0.07,
            interactive: false,
        }).addTo(planLaag);

        plan.bochten.forEach((b, i) => {
            const omega = b.soort.startsWith('omega');
            const lijn = L.polyline(b.pad, bochtStijl(omega, 'todo'))
                .bindTooltip(`Bocht ${i + 1}: baan ${b.van} → ${b.naar} (${b.soort})`, { sticky: true })
                .addTo(planLaag);
            bochten.push({ lijn, omega, status: 'todo' });
        });

        plan.banen.forEach((b, i) => {
            // Donkere onderlijn: witte streepjes alleen zie je op een lichte ondergrond niet.
            L.polyline(b.pad, { color: '#000000', weight: 5, opacity: 0.3, interactive: false }).addTo(planLaag);
            const lijn = L.polyline(b.pad, baanStijl('todo'))
                .bindTooltip(`Baan ${b.baan}, als ${i + 1}e gereden`, { sticky: true })
                .addTo(planLaag);
            // Buurbanen niet op dezelfde hoogte, anders liggen de nummers
            // bij een smalle werkbreedte over elkaar.
            const t = b.baan % 2 === 0 ? 0.4 : 0.6;
            const plek = [b.pad[0][0] + t * (b.pad[1][0] - b.pad[0][0]),
                          b.pad[0][1] + t * (b.pad[1][1] - b.pad[0][1])];
            const label = L.marker(plek, {
                icon: baanIcoon(i + 1, b.koers, 'todo'), interactive: false, keyboard: false,
            }).addTo(labelLaag);
            banen.push({ lijn, label, nr: i + 1, koers: b.koers, status: 'todo' });
        });

        letterPunt(plan.a, 'A', 'A: begin van de AB-lijn');
        if (plan.b) letterPunt(plan.b, 'B', 'B: zoals ingemeten');

        // Alleen bij een ander veld opnieuw inzoomen: een nieuwe planversie
        // (bv. de rijrichting die bij de start bekend wordt) laat het beeld staan.
        const sleutel = JSON.stringify(plan.veld);
        if (sleutel !== veldSleutel) {
            veldSleutel = sleutel;
            heelVeld();
        }
        toonLabels();
        kleurVoortgang();
    }

    // Voortgang uit de werkvolgorde. order_index is de baan die nu (of het
    // laatst) gereden wordt; tijdens de bocht daarna is die baan al klaar.
    function baanStatus(i, ab) {
        if (!ab) return 'todo';
        if (ab.voltooid || i < ab.order_index) return 'klaar';
        if (i === ab.order_index && ab.actief) return ab.state === 'TURNING' ? 'klaar' : 'nu';
        return 'todo';
    }

    function bochtStatus(i, ab) {
        if (!ab) return 'todo';
        if (ab.voltooid || i < ab.order_index) return 'klaar';
        if (i === ab.order_index && ab.actief && ab.state === 'TURNING') return 'nu';
        return 'todo';
    }

    function kleurVoortgang() {
        // Een voorbeeld heeft geen voortgang; alleen het plan van de missie zelf.
        const ab = getekend && getekend === missiePlan ? live?.ab : null;
        const sleutel = ab ? `${ab.actief}|${ab.order_index}|${ab.state}|${ab.voltooid}` : '-';
        if (sleutel === voortgangSleutel) return;
        voortgangSleutel = sleutel;
        banen.forEach((b, i) => {
            const status = baanStatus(i, ab);
            if (status === b.status) return;
            b.status = status;
            b.lijn.setStyle(baanStijl(status));
            b.label.setIcon(baanIcoon(b.nr, b.koers, status));
        });
        bochten.forEach((b, i) => {
            const status = bochtStatus(i, ab);
            if (status === b.status) return;
            b.status = status;
            b.lijn.setStyle(bochtStijl(b.omega, status));
        });
    }

    function toonLabels() {
        let zichtbaar = false;
        if (getekend) {
            // Meters per pixel in Web Mercator op de breedtegraad van het veld
            const mPerPx = 156543.034 * Math.cos(getekend.a[0] * Math.PI / 180) / 2 ** kaart.getZoom();
            zichtbaar = getekend.werkbreedte_m / mPerPx >= LABELS_VANAF_PX;
        }
        if (zichtbaar && !kaart.hasLayer(labelLaag)) labelLaag.addTo(kaart);
        if (!zichtbaar && kaart.hasLayer(labelLaag)) kaart.removeLayer(labelLaag);
    }

    function heelVeld() {
        if (!getekend) return;
        const punten = [...getekend.veld];
        for (const b of getekend.banen) punten.push(...b.pad);
        for (const b of getekend.bochten) punten.push(...b.pad);
        volgen = false;
        kaart.fitBounds(L.latLngBounds(punten), { padding: [25, 25], maxZoom: 21 });
        geplaatst = true;
    }

    // ------------------------------------------------------------------
    //  Het gereden spoor
    // ------------------------------------------------------------------
    function spoorStijl(modus) {
        return modus === 1
            ? { pane: 'spoor', color: '#FFEA00', weight: 2, opacity: 0.85, dashArray: '4 6', interactive: false }
            : { pane: 'spoor', color: '#FFEA00', weight: 4, opacity: 0.95, interactive: false };
    }

    function wisSpoor() {
        spoorLaag.clearLayers();
        spoorLijn = null;
        spoorModus = null;
        spoorLaatste = null;
        spoorLengte = 0;
    }

    // Punten [lat, lon, 0 = baan / 1 = bocht]. Per aanroep een keer
    // setLatLngs per lijn: met een punt tegelijk wordt bijladen na een
    // herstart van de pagina (duizenden punten) traag.
    function voegSpoorToe(punten) {
        let stuk = [];
        const schrijf = () => {
            if (spoorLijn && stuk.length) spoorLijn.setLatLngs(spoorLijn.getLatLngs().concat(stuk));
            stuk = [];
        };
        for (const [lat, lon, modus] of punten) {
            if (!spoorLijn || modus !== spoorModus) {
                schrijf();
                // De nieuwe lijn begint op het laatste punt van de vorige: geen gat.
                spoorLijn = L.polyline(spoorLaatste ? [spoorLaatste] : [], spoorStijl(modus)).addTo(spoorLaag);
                spoorModus = modus;
            }
            stuk.push([lat, lon]);
            spoorLaatste = [lat, lon];
        }
        schrijf();
        spoorLengte += punten.length;
    }

    // ------------------------------------------------------------------
    //  De robot
    // ------------------------------------------------------------------
    const robotIcoon = L.divIcon({
        className: 'robot-icoon',
        html: '<div class="robot-pijl"><svg viewBox="-12 -12 24 24" width="32" height="32">'
            + '<path d="M0,-10.5 L7.5,9 L0,5 L-7.5,9 Z"/></svg></div>',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
    });

    function zetRobot(p) {
        // lat 0.0 betekent: nog geen positie van de GPS
        if (!(p && p.lat && p.lon)) {
            if (robot) {
                robot.remove();
                robot = null;
            }
            return;
        }
        const plek = [p.lat, p.lon];
        if (robot) {
            robot.setLatLng(plek);
        } else {
            robot = L.marker(plek, { icon: robotIcoon, interactive: false, keyboard: false, zIndexOffset: 1000 })
                .addTo(kaart);
        }
        // Van 359 naar 1 graad is 2 graden rechtsom, niet 358 terug.
        const koers = p.heading || 0;
        robotHoek = robotHoek === null
            ? koers
            : robotHoek + ((((koers - robotHoek) % 360) + 540) % 360 - 180);
        const pijl = robot.getElement()?.firstElementChild;
        if (pijl) {
            pijl.style.transform = `rotate(${robotHoek}deg)`;
            pijl.className = `robot-pijl ${fixInfo(p.fix).kleur}`;
        }

        if (volgen) {
            kaart.panTo(plek, { animate: true, duration: 0.25, easeLinearity: 1 });
        } else if (!geplaatst && !getekend) {
            // Nog geen plan: dan is de robot zelf het beginpunt.
            kaart.setView(plek, 19);
            geplaatst = true;
        }
    }

    function wisselVolgen() {
        volgen = !volgen;
        if (volgen && heeftPositie) kaart.setView([pos.lat, pos.lon], Math.max(kaart.getZoom(), 19));
    }
</script>

<div class="veldkaart">
    <div class="balk">
        <button class:aan={volgen} on:click={wisselVolgen} disabled={!heeftPositie}>
            {volgen ? 'Volgt de robot' : 'Volg robot'}
        </button>
        <button on:click={heelVeld} disabled={!toonPlan}>Heel veld</button>
    </div>

    <div class="kaart" bind:this={kaartDiv}></div>

    <div class="info">
        {#if !verbonden}
            <span class="let-op">Geen verbinding met de robot</span>
        {:else if heeftPositie}
            <span class="stip {fix.kleur}"></span>
            {fix.tekst} · {fmt(pos.speed_kmh, 1)} km/h · koers {fmt(pos.heading, 0)}°
        {:else}
            <span class="let-op">Nog geen GPS-positie van de robot</span>
        {/if}
    </div>
    {#if toonPlan}
        <div class="info">{bron}. Eerste baan {eersteBaan}.</div>
    {/if}

    <div class="legenda">
        <span><i class="lijn gepland"></i>gepland</span>
        <span><i class="lijn nu"></i>nu bezig</span>
        <span><i class="lijn gereden"></i>gereden</span>
        <span><i class="lijn bocht"></i>kopakkerbocht</span>
        <span><i class="lijn omega"></i>omega-bocht</span>
        <span><i class="mini-robot">▲</i>robot, kleur = GPS-fix</span>
    </div>
</div>

<style>
    .veldkaart { margin-bottom: 20px; }
    .balk { display: flex; gap: 8px; margin-bottom: 8px; }
    .balk button { flex: 1; padding: 11px; font-size: 15px; font-weight: bold; border: none; border-radius: 4px; background: #607d8b; color: white; cursor: pointer; }
    .balk button.aan { background: #00838f; }
    .balk button:disabled { opacity: 0.5; cursor: default; }

    .kaart { height: 55vh; min-height: 320px; max-height: 640px; border-radius: 8px; border: 1px solid #ccc; background: #cfd8dc; }

    .info { font-size: 14px; color: #444; margin-top: 6px; }
    .let-op { color: #c62828; font-weight: bold; }
    .stip { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 2px; }
    .stip.groen { background: #00c853; }
    .stip.oranje { background: #ff9100; }
    .stip.rood { background: #d50000; }

    .legenda { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; color: #555; margin-top: 8px; }
    .legenda span { display: inline-flex; align-items: center; gap: 5px; }
    /* Op een donker vlakje, zoals op de luchtfoto: wit gestreept zie je anders niet. */
    .lijn { position: relative; display: inline-block; width: 28px; height: 12px; background: #455a64; border-radius: 3px; }
    .lijn::after { content: ''; position: absolute; left: 3px; right: 3px; top: 50%; transform: translateY(-50%); border-top: 2px solid; }
    .lijn.gepland::after { border-top: 2px dashed #ffffff; }
    .lijn.nu::after { border-top: 4px solid #00E5FF; }
    .lijn.gereden::after { border-top: 4px solid #FFEA00; }
    .lijn.bocht::after { border-top: 2px dashed #FF9100; }
    .lijn.omega::after { border-top: 2px dashed #FF1744; }
    .mini-robot { font-style: normal; color: #00c853; text-shadow: 0 0 2px #000; }

    /* Onderstaande elementen maakt Leaflet zelf aan, dus buiten Sveltes scope. */
    :global(.robot-icoon), :global(.baan-icoon) { background: none; border: none; }
    :global(.robot-pijl) { width: 32px; height: 32px; transition: transform 0.3s linear; filter: drop-shadow(0 0 2px rgba(0, 0, 0, 0.9)); }
    :global(.robot-pijl svg) { display: block; }
    :global(.robot-pijl path) { fill: currentColor; stroke: #ffffff; stroke-width: 1.6; stroke-linejoin: round; }
    :global(.robot-pijl.groen) { color: #00c853; }
    :global(.robot-pijl.oranje) { color: #ff9100; }
    :global(.robot-pijl.rood) { color: #d50000; }

    :global(.baan-label) { --kleur: #1565c0; position: relative; width: 26px; height: 26px; }
    :global(.baan-label.nu) { --kleur: #00838f; }
    :global(.baan-label.klaar) { --kleur: #78909c; opacity: 0.85; }
    :global(.baan-pijl) { position: absolute; inset: -9px; }
    :global(.baan-pijl::before) { content: ''; position: absolute; top: 0; left: 50%; margin-left: -6px; border-left: 6px solid transparent; border-right: 6px solid transparent; border-bottom: 9px solid var(--kleur); }
    :global(.baan-label span) { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--kleur); color: #ffffff; border: 2px solid #ffffff; font: bold 12px sans-serif; }

    :global(.kaart-punt) { display: flex; align-items: center; justify-content: center; border-radius: 50%; border: 2px solid #ffffff; color: #ffffff; font: bold 12px sans-serif; box-shadow: 0 0 3px rgba(0, 0, 0, 0.8); }
    :global(.kaart-punt.punt-a) { background: #2e7d32; }
    :global(.kaart-punt.punt-b) { background: #c62828; }
</style>
