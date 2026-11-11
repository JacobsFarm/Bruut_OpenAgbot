<script>
    // Tabblad Veldmissie: een missie uit openagbot-fieldsim (veldmissie.json) kiezen, starten en volgen op de
    // kaart, samen met de veiligheidskaart (kaart.json). De verboden gebieden van die kaart bewaakt de robot
    // altijd, ook bij handmatig rijden; dit tabblad laat ze zien en laat je de bestanden op de robot zetten.
    import { onMount, onDestroy } from 'svelte';
    import L from 'leaflet';
    import 'leaflet/dist/leaflet.css';
    import { fmt, fixInfo, postJson } from '../lib/telemetry.js';

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
    $: actief = m?.actief ?? false;
    $: info = missies.find((x) => x.naam === gekozen);
    $: hervatbaar = !actief && gekozen && voortgang[gekozen];
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
        if (bezig) timer = setTimeout(tik, POLL_MS);
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
        try { await postJson('/api/missie/stop'); } catch (e) {}
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

    const tijd = (min) => (min == null ? '–' : min >= 60 ? `${Math.floor(min / 60)} u ${Math.round(min % 60)} min` : `${Math.round(min)} min`);
</script>

<div class="missie">
    <!-- Geofence -->
    <div class="kaartje geofence" class:dicht={gf && (!gf.vooruit || !gf.achteruit)} class:overbrugd={gf?.overbrugd_s > 0}
         class:geen={gf && !gf.kaart && !gf.kaart_fout}>
        <div class="kop">
            <b>Geofence</b>
            {#if !gf}
                <span>…</span>
            {:else if gf.kaart_fout}
                <span class="let-op">{gf.kaart_fout}: de robot rijdt niet</span>
            {:else if gf.overbrugd_s > 0}
                <span>OVERBRUGD, nog {fmt(gf.overbrugd_s, 0)} s (max {fmt(gf.max_kmh, 1)} km/h)</span>
            {:else if !gf.vooruit || !gf.achteruit}
                <span>{!gf.vooruit && !gf.achteruit ? 'Vooruit en achteruit dicht' : !gf.vooruit ? 'Vooruit dicht, achteruit vrij' : 'Achteruit dicht, vooruit vrij'}: {gf.reden}</span>
            {:else if !gf.kaart}
                <span>Geen kaart op de robot: buiten een missie is er geen bewaking</span>
            {:else if gf.toestand === 'geen_positie'}
                <span>Kaart '{gf.kaart.naam}', maar geen GNSS-positie: nu geen bewaking</span>
            {:else}
                <span>Actief: kaart '{gf.kaart.naam}', {gf.kaart.stop_zones} gebieden waar hij stopt{gf.missie_grenzen ? ' + grenzen van de missie' : ''}</span>
            {/if}
        </div>
        {#if gf?.waarschuwing && gf.toestand !== 'geen_positie'}<div class="klein">Let op: {gf.waarschuwing}</div>{/if}
        {#if gf?.laatste_stop}
            <div class="klein">Laatste stop {gf.laatste_stop.tijd}: {gf.laatste_stop.reden} (bij {fmt(gf.laatste_stop.snelheid_kmh, 1)} km/h)</div>
        {/if}
        <div class="rij">
            <label class="knop grijs">Kaart laden (kaart.json)
                <input type="file" accept=".json,application/json" on:change={kaartKiezen} hidden />
            </label>
            {#if gf?.kaart}<button class="grijs" on:click={kaartWissen}>Kaart wissen</button>{/if}
            {#if gf?.overbrugd_s > 0}
                <button class="groen" on:click={bewakingAan}>Bewaking weer aan</button>
            {:else if gf && (!gf.vooruit || !gf.achteruit)}
                <button class="oranje" on:click={overbruggen}>Overbruggen (60 s)</button>
            {/if}
        </div>
        {#if kaartMelding}<div class="klein">{kaartMelding}</div>{/if}
    </div>

    <!-- Kaart -->
    <div class="balk">
        <button class:aan={volgen} on:click={wisselVolgen} disabled={!heeftPositie}>{volgen ? 'Volgt de robot' : 'Volg robot'}</button>
        <button on:click={() => tekenMissie(gekozen)} disabled={!gekozen}>Hele missie</button>
        <button on:click={heleKaart} disabled={!veiligheidskaart}>Hele kaart</button>
    </div>
    <div class="kaart" bind:this={kaartDiv}></div>
    <div class="info">
        {#if !verbonden}
            <span class="let-op">Geen verbinding met de robot</span>
        {:else if heeftPositie}
            <span class="stip {fix.kleur}"></span>{fix.tekst} · {fmt(pos.speed_kmh, 1)} km/h · koers {fmt(pos.heading, 0)}°
        {:else}
            <span class="let-op">Nog geen GPS-positie van de robot</span>
        {/if}
    </div>
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

    <!-- Missie -->
    <div class="kaartje">
        <div class="kop"><b>Missie</b>
            {#if m?.naam && (actief || m.state !== 'IDLE')}<span class="status {m.state}">{m.state.replaceAll('_', ' ')}</span>{/if}
        </div>
        <div class="rij">
            <select bind:value={gekozen} disabled={actief}>
                {#if !missies.length}<option value="">geen missies op de robot</option>{/if}
                {#each missies as x}
                    <option value={x.naam}>{x.naam}{x.velden?.length ? ` (${x.velden.join(', ')})` : ''}</option>
                {/each}
            </select>
            <label class="knop grijs">Missie laden
                <input type="file" accept=".json,application/json" on:change={missieKiezen} hidden />
            </label>
            <button class="grijs" on:click={missieWissen} disabled={!gekozen || actief}>Wissen</button>
        </div>
        {#if info}
            {#if info.fout}
                <div class="let-op">Bestand onleesbaar: {info.fout}</div>
            {:else}
                <div class="klein">
                    {info.soort === 'boerderij' ? 'Boerderijmissie' : 'Veldmissie'} · {info.segmenten} stukken
                    {#if info.lengte_m} · {fmt(info.lengte_m / 1000, 2)} km{/if}
                    {#if info.tijd_min} · {tijd(info.tijd_min)}{/if}
                    {#if info.werkbreedte_m} · werkbreedte {info.werkbreedte_m} m{/if}
                    {#if info.gemaakt} · gemaakt {info.gemaakt.replace('T', ' ')}{/if}
                    {#if !info.geofence} · zonder eigen geofence{/if}
                </div>
                {#if info.afgekeurd}<div class="let-op">Niet te rijden: {info.afgekeurd}.</div>{/if}
            {/if}
        {/if}

        {#if m?.naam && m.naam === gekozen && m.totaal_m}
            <div class="voortgang"><div style="width:{m.procent}%"></div></div>
            <div class="klein">
                {fmt(m.s_m, 0)} van {fmt(m.totaal_m, 0)} m ({fmt(m.procent, 0)}%) · stuk {m.segment + 1}/{m.segmenten}: <b>{m.segment_label}</b>
                · nog {tijd(m.resterend_min)}
                {#if actief} · afwijking {fmt(m.afwijking_m * 100, 0)} cm · werktuig <b>{m.werktuig_omlaag ? 'OMLAAG' : 'omhoog'}</b>{/if}
            </div>
            <div class="bericht">{m.bericht}</div>
        {/if}

        <div class="rij">
            {#if actief}
                {#if m.state === 'WACHT_OP_VRIJGAVE'}
                    <button class="groen groot" on:click={vrijgeven}>Vrijgeven: oversteken</button>
                {/if}
                <button class="rood groot" on:click={stop}>STOP</button>
            {:else}
                <button class="groen groot" on:click={() => start(false)} disabled={!info || info.fout || info.afgekeurd}>Start missie</button>
                {#if hervatbaar}
                    <button class="blauw groot" on:click={() => start(true)}>Hervat op {fmt(voortgang[gekozen].s_m, 0)} m</button>
                {/if}
            {/if}
        </div>
        <label class="schuif">Maximale snelheid: <b>{maxKmh ? `${fmt(maxKmh, 1)} km/h` : 'zoals in de missie'}</b>
            <input type="range" min="0" max="6" step="0.5" bind:value={maxKmh} on:change={snelheidAanpassen} />
        </label>
        {#if melding}<div class="let-op">{melding}</div>{/if}
        <div class="klein grijs-tekst">
            De robot moet binnen 30 m van het startpunt (of het hervatpunt) staan. Missie en kaart maak je in
            openagbot-fieldsim; die kan ze ook direct naar de robot sturen.
        </div>
    </div>
</div>

<style>
    .missie { padding: 15px; }
    .kaartje { border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin-bottom: 12px; background: #fafafa; }
    .kaartje.geofence { border-left: 6px solid #2e7d32; }
    .kaartje.geofence.geen { border-left-color: #9e9e9e; }
    .kaartje.geofence.dicht { border-left-color: #c62828; background: #ffebee; }
    .kaartje.geofence.overbrugd { border-left-color: #ef6c00; background: #fff3e0; }
    .kop { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; font-size: 15px; margin-bottom: 6px; }
    .rij { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; align-items: center; }
    .rij select { flex: 1; min-width: 150px; padding: 10px; font-size: 15px; border-radius: 4px; border: 1px solid #bbb; }
    button, .knop { padding: 10px 14px; font-size: 14px; font-weight: bold; border: none; border-radius: 4px; color: white; cursor: pointer; display: inline-block; }
    button:disabled { opacity: 0.5; cursor: default; }
    .grijs { background: #607d8b; } .groen { background: #2e7d32; } .rood { background: #c62828; }
    .oranje { background: #ef6c00; } .blauw { background: #1565c0; }
    .groot { flex: 1; padding: 16px; font-size: 17px; }
    .klein { font-size: 13px; color: #444; margin-top: 5px; }
    .grijs-tekst { color: #777; }
    .bericht { font-size: 14px; margin-top: 4px; color: #222; }
    .let-op { color: #c62828; font-weight: bold; font-size: 14px; margin-top: 5px; }
    .status { font-size: 12px; font-weight: bold; padding: 2px 8px; border-radius: 10px; background: #607d8b; color: white; }
    .status.RIJDEN { background: #2e7d32; } .status.AANLOOP { background: #1565c0; } .status.KLAAR { background: #00838f; }
    .status.FOUT { background: #c62828; } .status.WACHT_OP_GNSS, .status.WACHT_OP_VRIJGAVE { background: #ef6c00; }
    .voortgang { height: 10px; background: #cfd8dc; border-radius: 5px; overflow: hidden; margin-top: 10px; }
    .voortgang div { height: 100%; background: #2e7d32; }
    .schuif { display: block; font-size: 14px; margin-top: 10px; color: #333; }
    .schuif input { width: 100%; }

    .balk { display: flex; gap: 8px; margin-bottom: 8px; }
    .balk button { flex: 1; background: #607d8b; }
    .balk button.aan { background: #00838f; }
    .kaart { height: 55vh; min-height: 320px; max-height: 640px; border-radius: 8px; border: 1px solid #ccc; background: #cfd8dc; }
    .info { font-size: 14px; color: #444; margin-top: 6px; }
    .stip { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
    .stip.groen { background: #00c853; } .stip.oranje { background: #ff9100; } .stip.rood { background: #d50000; }
    .legenda { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; color: #555; margin: 8px 0 12px; }
    .legenda span { display: inline-flex; align-items: center; gap: 5px; }
    .vlak { display: inline-block; width: 14px; height: 12px; border-radius: 3px; opacity: 0.75; }
    .lijn { position: relative; display: inline-block; width: 28px; height: 12px; background: #455a64; border-radius: 3px; }
    .lijn::after { content: ''; position: absolute; left: 3px; right: 3px; top: 50%; transform: translateY(-50%); border-top: 2px solid; }
    .lijn.werk::after { border-top: 2px solid #ffffff; }
    .lijn.rij::after { border-top: 2px dashed #FF9100; }
    .lijn.nu::after { border-top: 4px solid #00E5FF; }
    .lijn.gereden::after { border-top: 4px solid #FFEA00; }
    .lijn.doorgang::after { border-top: 4px solid #00e676; }

    :global(.robot-icoon) { background: none; border: none; }
    :global(.robot-pijl) { transition: transform 0.3s linear; filter: drop-shadow(0 0 2px rgba(0, 0, 0, 0.9)); }
    :global(.robot-pijl svg) { display: block; }
    :global(.robot-pijl path) { fill: currentColor; stroke: #ffffff; stroke-width: 1.6; stroke-linejoin: round; }
    :global(.robot-pijl.groen) { color: #00c853; }
    :global(.robot-pijl.oranje) { color: #ff9100; }
    :global(.robot-pijl.rood) { color: #d50000; }
</style>
