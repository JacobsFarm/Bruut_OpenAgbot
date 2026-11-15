<script>
    // Tabblad Veldmissie: een missie uit openagbot-fieldsim (veldmissie.json) kiezen, starten en volgen op de
    // kaart, samen met de veiligheidskaart (kaart.json). De verboden gebieden van die kaart bewaakt de robot
    // altijd, ook bij handmatig rijden; dit tabblad laat ze zien en laat je de bestanden op de robot zetten.
    import { onMount, onDestroy } from 'svelte';
    import L from 'leaflet';
    import 'leaflet/dist/leaflet.css';
    import { fmt, fixInfo, postJson, noodstop } from '../lib/telemetry.js';

    // False zolang dit tabblad niet in beeld is (het blijft bestaan, zodat de kaart en je keuze blijven staan).
    export let actief = true;

    const POLL_MS = 300;
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
    const SOORT_KLEUR = { water: '#2979ff', weg: '#424242', dijk: '#a1887f', gebouw: '#d32f2f',
        verboden: '#ff1744', nest: '#ff9100', hek: '#8d6e63', gat: '#ff7043' };
    const SOORT_TEKST = { water: 'sloot + slootzone', weg: 'weg', dijk: 'dijk', gebouw: 'gebouw',
        verboden: 'verboden gebied', nest: 'nest', hek: 'hek', gat: 'gat in het veld' };
    const TYPE_KLEUR = { rondje: '#ffffff', baan: '#ffffff', bocht: '#FF9100', overgang: '#FF9100',
        transport: '#b388ff', doorgang: '#00e676', aanrijden: '#b388ff' };

    let kaartDiv;
    let kaart = null;
    let zoneLaag, missieLaag, spoorLaag, robotLaag;

    let live = null;
    let verbonden = true;
    let bezig = true;
    let timer = null;
    let volgen = false;
    let geplaatst = false;

    // Veiligheidskaart
    let veiligheidskaart = null;
    let kaartSleutel = null;
    let kaartMelding = '';

    // Missies
    let missies = [];
    let voortgang = {};
    let gekozen = '';
    let getekendeMissie = null;      // naam van de missie die op de kaart staat
    let segmentLijnen = [];          // per segment { lijn, type, status }
    let voortgangSleutel = null;
    let melding = '';
    let maxKmh = 0;                  // 0 = snelheden van de missie

    // Spoor
    let missieNr = null;
    let spoorLengte = 0;
    let spoorLijn = null;
    let spoorModus = null;
    let spoorLaatste = null;

    let robot = null;
    let robotHoek = null;
    let omtrek = null;
    let werktuigLijn = null;

    $: pos = live?.pos;
    $: m = live?.missie;
    $: gf = live?.geofence;
    $: heeftPositie = !!(pos && pos.lat && pos.lon);
    $: fix = fixInfo(pos?.fix);
    $: rijdt = m?.actief ?? false;
    $: if (kaart && actief) setTimeout(() => kaart?.invalidateSize(), 0);
    $: info = missies.find((x) => x.naam === gekozen);
    $: hervatbaar = !rijdt && gekozen && voortgang[gekozen];
    $: if (kaart && gekozen !== getekendeMissie) tekenMissie(gekozen);

    onMount(() => {
        kaart = L.map(kaartDiv, { center: [52.1, 5.3], zoom: 7, maxZoom: 22 });
        const lagen = {};
        for (const [naam, maak] of Object.entries(ONDERGRONDEN)) lagen[naam] = maak();
        let basis = 'Satelliet (Esri)';
        try {
            const bewaard = localStorage.getItem('veldkaart-ondergrond');
            if (bewaard && lagen[bewaard]) basis = bewaard;
        } catch (e) {}
        lagen[basis].addTo(kaart);
        L.control.layers(lagen, null, { position: 'topright' }).addTo(kaart);
        L.control.scale({ imperial: false, maxWidth: 150 }).addTo(kaart);
        kaart.on('baselayerchange', (e) => {
            try { localStorage.setItem('veldkaart-ondergrond', e.name); } catch (err) {}
        });
        kaart.createPane('zones').style.zIndex = 410;
        kaart.createPane('missie').style.zIndex = 430;
        kaart.createPane('spoor').style.zIndex = 450;
        kaart.createPane('robot').style.zIndex = 470;
        zoneLaag = L.layerGroup().addTo(kaart);
        missieLaag = L.layerGroup().addTo(kaart);
        spoorLaag = L.layerGroup().addTo(kaart);
        robotLaag = L.layerGroup().addTo(kaart);
        kaart.on('dragstart', () => { volgen = false; });
        haalKaart();
        haalMissies();
        tik();
    });

    onDestroy(() => {
        bezig = false;
        clearTimeout(timer);
        if (kaart) kaart.remove();
    });

    async function vraag(url, opties) {
        const res = await fetch(url, { cache: 'no-store', ...opties });
        let data = null;
        try { data = await res.json(); } catch (e) {}
        if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
        return data;
    }

    // ------------------------------------------------------------------
    //  Verversen
    // ------------------------------------------------------------------
    async function tik() {
        try {
            const data = await vraag(`/api/missie/live?spoor_vanaf=${spoorLengte}`);
            if (!bezig) return;
            verwerk(data);
            verbonden = true;
        } catch (e) {
            verbonden = false;
        }
        if (bezig) timer = setTimeout(tik, actief ? POLL_MS : 2000);
    }

    function verwerk(data) {
        const ms = data.missie;
        if (ms.missie_nr !== missieNr) {
            missieNr = ms.missie_nr;
            wisSpoor();
        }
        if (data.spoor.vanaf === spoorLengte) voegSpoorToe(data.spoor.punten);
        else if (data.spoor.vanaf === 0) { wisSpoor(); voegSpoorToe(data.spoor.punten); }
        // Rijdt er een missie (ook als die elders gestart is), dan staat die op de kaart.
        if (ms.actief && ms.naam && ms.naam !== gekozen) gekozen = ms.naam;
        // De kaart op de robot kan vervangen zijn (vanuit de sim): opnieuw ophalen.
        const sleutel = data.geofence?.kaart ? `${data.geofence.kaart.naam}|${data.geofence.kaart.gemaakt}` : '-';
        if (kaartSleutel !== null && sleutel !== kaartSleutel) haalKaart();
        kaartSleutel = sleutel;
        // Gestart of gestopt (ook van buitenaf): de bewaarde voortgang is dan veranderd.
        if (live && live.missie.actief !== ms.actief) setTimeout(haalMissies, 600);
        live = data;
        zetRobot(data.pos, data.geofence?.omtrek);
        kleurVoortgang();
    }

    // ------------------------------------------------------------------
    //  Veiligheidskaart (geofence)
    // ------------------------------------------------------------------
    async function haalKaart() {
        try {
            const data = await vraag('/api/kaart');
            veiligheidskaart = data.status === 'ok' ? data.kaart : null;
            tekenKaart();
        } catch (e) {
            kaartMelding = `Kaart ophalen mislukt: ${e.message}`;
        }
    }

    function tekenKaart() {
        zoneLaag.clearLayers();
        const k = veiligheidskaart;
        if (!k) return;
        if (k.werkgebied) {
            L.polygon(k.werkgebied, { pane: 'zones', color: '#ffffff', weight: 1.5, dashArray: '10 8', fill: false,
                                      interactive: false }).addTo(zoneLaag);
        }
        for (const v of k.velden || []) {
            L.polygon(v.grens, { pane: 'zones', color: '#c6ff00', weight: 1.5, opacity: 0.9, fillOpacity: 0.04 })
                .bindTooltip(`Veld ${v.naam || v.id}`, { sticky: true }).addTo(zoneLaag);
        }
        for (const z of k.verboden || []) {
            const kleur = SOORT_KLEUR[z.soort] || '#ff1744';
            const stop = z.actie !== 'mijden';
            const periode = z.van && z.tot ? ` (${z.van} t/m ${z.tot})` : '';
            L.polygon([z.polygon, ...(z.gaten || [])], {
                pane: 'zones', color: kleur, weight: stop ? 2 : 1, opacity: 0.95,
                fillColor: kleur, fillOpacity: stop ? 0.35 : 0.12, dashArray: stop ? null : '4 4',
            }).bindTooltip(`${SOORT_TEKST[z.soort] || z.soort}${z.naam && z.naam !== z.soort ? ' ' + z.naam : ''}${periode}: `
                + (stop ? 'hier stopt de robot' : 'alleen een waarschuwing'), { sticky: true }).addTo(zoneLaag);
        }
        for (const d of k.doorgangen || []) {
            L.polyline(d.lijn, { pane: 'zones', color: '#00e676', weight: 5, opacity: 0.9 })
                .bindTooltip(`Doorgang ${d.naam || d.soort} (${d.breedte_m} m)${d.bevestigen ? ', wacht op vrijgave' : ''}`,
                             { sticky: true }).addTo(zoneLaag);
        }
        if (!geplaatst && !getekendeMissie) heleKaart();
    }

    async function leesBestand(e) {
        const bestand = e.target.files?.[0];
        e.target.value = '';
        if (!bestand) return null;
        try {
            return { naam: bestand.name, data: JSON.parse(await bestand.text()) };
        } catch (err) {
            return { naam: bestand.name, fout: 'geen geldig JSON-bestand' };
        }
    }

    async function kaartKiezen(e) {
        const b = await leesBestand(e);
        if (!b) return;
        if (b.fout) { kaartMelding = `${b.naam}: ${b.fout}`; return; }
        try {
            const r = await vraag('/api/kaart', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                                                  body: JSON.stringify(b.data) });
            kaartMelding = `Kaart '${r.kaart.naam}' staat op de robot: ${r.kaart.stop_zones} gebieden waar hij stopt.`;
            await haalKaart();
            heleKaart();
        } catch (err) {
            kaartMelding = `${b.naam} geweigerd: ${err.message}`;
        }
    }

    async function kaartWissen() {
        if (!confirm('Kaart van de robot halen? Daarna is er geen geofence meer bij handmatig rijden.')) return;
        await vraag('/api/kaart', { method: 'DELETE' });
        kaartMelding = 'Kaart gewist: er is nu geen geofence.';
        await haalKaart();
    }

    async function overbruggen() {
        if (!confirm('Geofence 60 seconden overbruggen? Alleen om met de hand, langzaam, uit het gebied te rijden.')) return;
        await postJson('/api/geofence/overbruggen', {});
    }

    async function bewakingAan() {
        await vraag('/api/geofence/overbruggen', { method: 'DELETE' });
    }

    // ------------------------------------------------------------------
    //  Missies
    // ------------------------------------------------------------------
    async function haalMissies() {
        try {
            const data = await vraag('/api/missies');
            missies = data.missies;
            voortgang = data.voortgang || {};
            if (!gekozen && missies.length) gekozen = missies[0].naam;
            if (gekozen && !missies.some((x) => x.naam === gekozen)) gekozen = missies[0]?.naam || '';
        } catch (e) {
            melding = `Missies ophalen mislukt: ${e.message}`;
        }
    }

    async function missieKiezen(e) {
        const b = await leesBestand(e);
        if (!b) return;
        if (b.fout) { melding = `${b.naam}: ${b.fout}`; return; }
        const naam = b.naam.replace(/\.json$/i, '').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 60) || 'missie';
        try {
            await vraag(`/api/missies/${naam}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                                                 body: JSON.stringify(b.data) });
            melding = `Missie '${naam}' staat op de robot.`;
            getekendeMissie = null;
            await haalMissies();
            gekozen = naam;
        } catch (err) {
            melding = `${b.naam} geweigerd: ${err.message}`;
        }
    }

    async function missieWissen() {
        if (!gekozen || !confirm(`Missie '${gekozen}' van de robot halen?`)) return;
        try {
            await vraag(`/api/missies/${gekozen}`, { method: 'DELETE' });
            gekozen = '';
            await haalMissies();
        } catch (err) {
            melding = err.message;
        }
    }

    async function tekenMissie(naam) {
        getekendeMissie = naam;
        missieLaag.clearLayers();
        segmentLijnen = [];
        voortgangSleutel = null;
        if (!naam) return;
        let data;
        try {
            data = await vraag(`/api/missies/${naam}`);
        } catch (e) {
            melding = `Missie '${naam}' ophalen mislukt: ${e.message}`;
            return;
        }
        if (getekendeMissie !== naam) return;
        // Toegestaan gebied van de missie: daarbinnen blijft de robot tijdens deze missie.
        for (const t of data.geofence?.toegestaan || []) {
            L.polygon([t.polygon, ...(t.gaten || [])], { pane: 'missie', color: '#c6ff00', weight: 1.5, dashArray: '6 6',
                                                         fillOpacity: 0.05, interactive: false }).addTo(missieLaag);
        }
        const alle = [];
        for (const sg of data.segmenten) {
            L.polyline(sg.punten, { pane: 'missie', color: '#000000', weight: 5, opacity: 0.25, interactive: false })
                .addTo(missieLaag);
            const lijn = L.polyline(sg.punten, segmentStijl(sg.type, 'todo', sg.werktuig === 'omlaag'))
                .bindTooltip(`${sg.label}: ${sg.snelheid_kmh} km/h, werktuig ${sg.werktuig}`
                    + (sg.veilig === false ? ' - AFGEKEURD' : ''), { sticky: true })
                .addTo(missieLaag);
            segmentLijnen.push({ lijn, type: sg.type, omlaag: sg.werktuig === 'omlaag', status: 'todo',
                                 afgekeurd: sg.veilig === false });
            alle.push(...sg.punten);
        }
        const start = data.segmenten[0].punten[0];
        L.circleMarker(start, { pane: 'missie', radius: 7, color: '#ffffff', weight: 2, fillColor: '#2e7d32',
                                fillOpacity: 1 }).bindTooltip('Start van de missie').addTo(missieLaag);
        if (alle.length) {
            volgen = false;
            kaart.fitBounds(L.latLngBounds(alle), { padding: [25, 25], maxZoom: 21 });
            geplaatst = true;
        }
        kleurVoortgang();
    }

    function segmentStijl(type, status, omlaag) {
        const kleur = TYPE_KLEUR[type] || '#ffffff';
        if (status === 'afgekeurd') return { pane: 'missie', color: '#ff1744', weight: 4, opacity: 1, dashArray: null };
        if (status === 'nu') return { pane: 'missie', color: '#00E5FF', weight: 5, opacity: 1, dashArray: null };
        if (status === 'klaar') return { pane: 'missie', color: kleur, weight: 2, opacity: 0.3, dashArray: null };
        return { pane: 'missie', color: kleur, weight: 2, opacity: 0.95, dashArray: omlaag ? null : '6 6' };
    }

    function kleurVoortgang() {
        const zelfde = m && m.naam === getekendeMissie;
        const sleutel = zelfde ? `${m.segment}|${m.actief}|${m.state}` : '-';
        if (sleutel === voortgangSleutel) return;
        voortgangSleutel = sleutel;
        segmentLijnen.forEach((s, i) => {
            let status = 'todo';
            if (s.afgekeurd) status = 'afgekeurd';
            else if (zelfde && (m.state === 'KLAAR' || i < m.segment)) status = 'klaar';
            else if (zelfde && i === m.segment && m.actief) status = 'nu';
            if (status === s.status) return;
            s.status = status;
            s.lijn.setStyle(segmentStijl(s.type, status, s.omlaag));
        });
    }

    async function start(hervat) {
        if (!gekozen) return;
        melding = hervat ? 'Hervatten...' : 'Starten...';
        try {
            const r = await postJson('/api/missie/start', { naam: gekozen, hervat, max_kmh: maxKmh || null });
            melding = r.status === 'started' ? '' : (r.msg || 'Starten mislukt');
        } catch (e) {
            melding = 'Netwerkfout bij starten';
        }
        haalMissies();
    }

    async function stop() {
        // De noodstop stopt de missie net zo (de voortgang blijft bewaard) en probeert het vaker.
        if (!(await noodstop())) melding = 'Stoppen mislukt: de robot is niet bereikt!';
        setTimeout(haalMissies, 500);
    }

    async function vrijgeven() {
        const r = await postJson('/api/missie/vrijgeven');
        if (r.status !== 'vrijgegeven') melding = r.msg;
    }

    async function snelheidAanpassen() {
        try { await postJson('/api/missie/update', { max_kmh: maxKmh || null }); } catch (e) {}
    }

    // ------------------------------------------------------------------
    //  Spoor en robot
    // ------------------------------------------------------------------
    function wisSpoor() {
        spoorLaag?.clearLayers();
        spoorLijn = null; spoorModus = null; spoorLaatste = null; spoorLengte = 0;
    }

    // Punten [lat, lon, 1 = werktuig omlaag]: doorgetrokken waar gewerkt is, gestreept waar alleen gereden.
    function voegSpoorToe(punten) {
        let stuk = [];
        const schrijf = () => {
            if (spoorLijn && stuk.length) spoorLijn.setLatLngs(spoorLijn.getLatLngs().concat(stuk));
            stuk = [];
        };
        for (const [lat, lon, modus] of punten) {
            if (!spoorLijn || modus !== spoorModus) {
                schrijf();
                spoorLijn = L.polyline(spoorLaatste ? [spoorLaatste] : [], modus === 1
                    ? { pane: 'spoor', color: '#FFEA00', weight: 4, opacity: 0.95, interactive: false }
                    : { pane: 'spoor', color: '#FFEA00', weight: 2, opacity: 0.85, dashArray: '4 6', interactive: false })
                    .addTo(spoorLaag);
                spoorModus = modus;
            }
            stuk.push([lat, lon]);
            spoorLaatste = [lat, lon];
        }
        schrijf();
        spoorLengte += punten.length;
    }

    const robotIcoon = L.divIcon({
        className: 'robot-icoon',
        html: '<div class="robot-pijl"><svg viewBox="-12 -12 24 24" width="28" height="28">'
            + '<path d="M0,-10.5 L7.5,9 L0,5 L-7.5,9 Z"/></svg></div>',
        iconSize: [28, 28], iconAnchor: [14, 14],
    });

    function zetRobot(p, vorm) {
        if (!(p && p.lat && p.lon)) {
            robotLaag.clearLayers();
            robot = null; omtrek = null; werktuigLijn = null;
            return;
        }
        const plek = [p.lat, p.lon];
        if (robot) robot.setLatLng(plek);
        else robot = L.marker(plek, { pane: 'robot', icon: robotIcoon, interactive: false, keyboard: false }).addTo(robotLaag);
        const koers = p.heading || 0;
        robotHoek = robotHoek === null ? koers : robotHoek + ((((koers - robotHoek) % 360) + 540) % 360 - 180);
        const pijl = robot.getElement()?.firstElementChild;
        if (pijl) {
            pijl.style.transform = `rotate(${robotHoek}deg)`;
            pijl.className = `robot-pijl ${fixInfo(p.fix).kleur}`;
        }
        // De omtrek die de geofence bewaakt: robot plus marge, en de einden van het werktuig.
        const dicht = gf && (!gf.vooruit || !gf.achteruit);
        const kleur = dicht ? '#ff1744' : '#00E5FF';
        if (vorm?.robot) {
            if (omtrek) omtrek.setLatLngs(vorm.robot).setStyle({ color: kleur });
            else omtrek = L.polygon(vorm.robot, { pane: 'robot', color: kleur, weight: 2, fillOpacity: 0.1,
                                                  interactive: false }).addTo(robotLaag);
        }
        if (vorm?.werktuig) {
            if (werktuigLijn) werktuigLijn.setLatLngs(vorm.werktuig).setStyle({ color: kleur });
            else werktuigLijn = L.polyline(vorm.werktuig, { pane: 'robot', color: kleur, weight: 4, interactive: false })
                .addTo(robotLaag);
        } else if (werktuigLijn) {
            werktuigLijn.remove();
            werktuigLijn = null;
        }
        if (volgen) kaart.panTo(plek, { animate: true, duration: 0.25, easeLinearity: 1 });
        else if (!geplaatst) { kaart.setView(plek, 19); geplaatst = true; }
    }

    function wisselVolgen() {
        volgen = !volgen;
        if (volgen && heeftPositie) kaart.setView([pos.lat, pos.lon], Math.max(kaart.getZoom(), 19));
    }

    function heleKaart() {
        const punten = [];
        const k = veiligheidskaart;
        if (k?.werkgebied) punten.push(...k.werkgebied);
        for (const v of k?.velden || []) punten.push(...v.grens);
        for (const z of k?.verboden || []) punten.push(...z.polygon);
        if (!punten.length) return;
        volgen = false;
        kaart.fitBounds(L.latLngBounds(punten), { padding: [20, 20], maxZoom: 21 });
        geplaatst = true;
    }

    const statusKleur = { RIJDEN: 'groen', AANLOOP: 'blauw', KLAAR: 'groen', FOUT: 'rood',
        WACHT_OP_GNSS: 'oranje', WACHT_OP_VRIJGAVE: 'oranje' };
    const tijd = (min) => (min == null ? '–' : min >= 60 ? `${Math.floor(min / 60)} u ${Math.round(min % 60)} min` : `${Math.round(min)} min`);
</script>

<div class="pagina">
    <!-- Kaart -->
    <div class="kaartbalk">
        <button class:aan={volgen} on:click={wisselVolgen} disabled={!heeftPositie}>{volgen ? 'Volgt de robot' : 'Volg robot'}</button>
        <button on:click={() => tekenMissie(gekozen)} disabled={!gekozen}>Hele missie</button>
        <button on:click={heleKaart} disabled={!veiligheidskaart}>Hele kaart</button>
    </div>
    <div class="kaartvlak" bind:this={kaartDiv}></div>
    <div class="klein">
        {#if !verbonden}
            <span class="let-op">Geen verbinding met de robot</span>
        {:else if heeftPositie}
            <span class="stip {fix.kleur}"></span> {fix.tekst} · {fmt(pos.speed_kmh, 1)} km/h · koers {fmt(pos.heading, 0)}°
        {:else}
            <span class="let-op">Nog geen GPS-positie van de robot</span>
        {/if}
    </div>

    <!-- Missie -->
    <section class="paneel">
        <h3>Missie
            {#if m?.naam && (rijdt || m.state !== 'IDLE')}<span class="chip {statusKleur[m.state] ?? ''}">{m.state.replaceAll('_', ' ').toLowerCase()}</span>{/if}
        </h3>

        {#if m?.naam && m.naam === gekozen && m.totaal_m}
            <div class="voortgang"><div style="width:{m.procent}%"></div></div>
            <div class="klein stand">
                {fmt(m.s_m, 0)} van {fmt(m.totaal_m, 0)} m ({fmt(m.procent, 0)}%) · stuk {m.segment + 1}/{m.segmenten}: <b>{m.segment_label}</b>
                · nog {tijd(m.resterend_min)}
                {#if rijdt} · afwijking {fmt(m.afwijking_m * 100, 0)} cm · werktuig <b>{m.werktuig_omlaag ? 'OMLAAG' : 'omhoog'}</b>{/if}
            </div>
            <div class="melding {m.state === 'FOUT' ? 'rood' : m.state?.startsWith('WACHT') ? 'oranje' : ''}">{m.bericht}</div>
        {/if}

        <div class="knoppen start">
            {#if rijdt}
                {#if m.state === 'WACHT_OP_VRIJGAVE'}
                    <button class="primair groot" on:click={vrijgeven}>Vrijgeven: oversteken</button>
                {/if}
                <button class="gevaar groot" on:click={stop}>Stop missie</button>
            {:else}
                <button class="primair groot" on:click={() => start(false)} disabled={!info || info.fout || info.afgekeurd}>Start missie</button>
                {#if hervatbaar}
                    <button class="blauw groot" on:click={() => start(true)}>Hervat op {fmt(voortgang[gekozen].s_m, 0)} m</button>
                {/if}
            {/if}
        </div>
        {#if melding}<div class="melding rood">{melding}</div>{/if}

        <div class="veld">
            <select bind:value={gekozen} disabled={rijdt} aria-label="Missie op de robot">
                {#if !missies.length}<option value="">geen missies op de robot</option>{/if}
                {#each missies as x}
                    <option value={x.naam}>{x.naam}{x.velden?.length ? ` (${x.velden.join(', ')})` : ''}</option>
                {/each}
            </select>
        </div>
        {#if info}
            {#if info.fout}
                <div class="melding rood">Bestand onleesbaar: {info.fout}</div>
            {:else}
                <div class="klein stand">
                    {info.soort === 'boerderij' ? 'Boerderijmissie' : 'Veldmissie'} · {info.segmenten} stukken
                    {#if info.lengte_m} · {fmt(info.lengte_m / 1000, 2)} km{/if}
                    {#if info.tijd_min} · {tijd(info.tijd_min)}{/if}
                    {#if info.werkbreedte_m} · werkbreedte {info.werkbreedte_m} m{/if}
                    {#if info.gemaakt} · gemaakt {info.gemaakt.replace('T', ' ')}{/if}
                    {#if !info.geofence} · zonder eigen geofence{/if}
                </div>
                {#if info.afgekeurd}<div class="melding rood">Niet te rijden: {info.afgekeurd}.</div>{/if}
            {/if}
        {/if}

        <div class="veld">
            <label for="missie-max">Maximale snelheid <span class="waarde">{maxKmh ? `${fmt(maxKmh, 1)} km/h` : 'zoals in de missie'}</span></label>
            <input id="missie-max" type="range" min="0" max="6" step="0.5" bind:value={maxKmh} on:change={snelheidAanpassen} />
        </div>

        <div class="knoppen">
            <label class="knop">Missie laden
                <input type="file" accept=".json,application/json" on:change={missieKiezen} hidden />
            </label>
            <button on:click={missieWissen} disabled={!gekozen || rijdt}>Wissen</button>
        </div>
        <p class="klein voet">
            De robot moet binnen 30 m van het startpunt (of het hervatpunt) staan. Missie en kaart maak je in
            openagbot-fieldsim; die kan ze ook direct naar de robot sturen.
        </p>
    </section>

    <!-- Geofence -->
    <section class="paneel geofence" class:dicht={gf && (!gf.vooruit || !gf.achteruit)} class:overbrugd={gf?.overbrugd_s > 0}
             class:geen={gf && !gf.kaart && !gf.kaart_fout}>
        <h3>Geofence</h3>
        <div class="gf-tekst">
            {#if !gf}
                …
            {:else if gf.kaart_fout}
                <span class="let-op">{gf.kaart_fout}: de robot rijdt niet</span>
            {:else if gf.overbrugd_s > 0}
                OVERBRUGD, nog {fmt(gf.overbrugd_s, 0)} s (max {fmt(gf.max_kmh, 1)} km/h)
            {:else if !gf.vooruit || !gf.achteruit}
                {!gf.vooruit && !gf.achteruit ? 'Vooruit en achteruit dicht' : !gf.vooruit ? 'Vooruit dicht, achteruit vrij' : 'Achteruit dicht, vooruit vrij'}: {gf.reden}
            {:else if !gf.kaart}
                Geen kaart op de robot: buiten een missie is er geen bewaking
            {:else if gf.toestand === 'geen_positie'}
                Kaart '{gf.kaart.naam}', maar geen GNSS-positie: nu geen bewaking
            {:else}
                Actief: kaart '{gf.kaart.naam}', {gf.kaart.stop_zones} gebieden waar hij stopt{gf.missie_grenzen ? ' + grenzen van de missie' : ''}
            {/if}
        </div>
        {#if gf?.waarschuwing && gf.toestand !== 'geen_positie'}<div class="klein">Let op: {gf.waarschuwing}</div>{/if}
        {#if gf?.laatste_stop}
            <div class="klein">Laatste stop {gf.laatste_stop.tijd}: {gf.laatste_stop.reden} (bij {fmt(gf.laatste_stop.snelheid_kmh, 1)} km/h)</div>
        {/if}
        <div class="knoppen gf-knoppen">
            <label class="knop">Kaart laden
                <input type="file" accept=".json,application/json" on:change={kaartKiezen} hidden />
            </label>
            {#if gf?.kaart}<button on:click={kaartWissen}>Kaart wissen</button>{/if}
            {#if gf?.overbrugd_s > 0}
                <button class="primair" on:click={bewakingAan}>Bewaking weer aan</button>
            {:else if gf && (!gf.vooruit || !gf.achteruit)}
                <button class="oranje" on:click={overbruggen}>Overbruggen (60 s)</button>
            {/if}
        </div>
        {#if kaartMelding}<div class="klein">{kaartMelding}</div>{/if}
    </section>

    <div class="legenda">
        <span><i class="vlak" style="background:#2979ff"></i>sloot + slootzone</span>
        <span><i class="vlak" style="background:#ff1744"></i>verboden</span>
        <span><i class="vlak" style="background:#ff9100"></i>nest</span>
        <span><i class="lijn werk"></i>werken</span>
        <span><i class="lijn rij"></i>rijden (werktuig omhoog)</span>
        <span><i class="lijn nu"></i>nu bezig</span>
        <span><i class="lijn gereden"></i>gereden</span>
        <span><i class="lijn doorgang"></i>doorgang</span>
    </div>
</div>

<style>
    .stand { margin: 8px 0; }
    .start { margin: 10px 0 14px; }
    .melding { margin-bottom: 10px; }
    .voet { margin-top: 12px; }

    .geofence { border-left: 6px solid var(--groen); }
    .geofence.geen { border-left-color: var(--inkt2); }
    .geofence.dicht { border-left-color: var(--rood); background: var(--rood-vlak); }
    .geofence.overbrugd { border-left-color: var(--oranje); background: var(--oranje-vlak); }
    .gf-tekst { font-size: 15px; }
    .gf-knoppen { margin: 10px 0 6px; }

    .lijn.werk::after { border-top: 2px solid #ffffff; }
    .lijn.rij::after { border-top: 2px dashed #FF9100; }
    .lijn.nu::after { border-top: 4px solid #00E5FF; }
    .lijn.gereden::after { border-top: 4px solid #FFEA00; }
    .lijn.doorgang::after { border-top: 4px solid #00e676; }
</style>
