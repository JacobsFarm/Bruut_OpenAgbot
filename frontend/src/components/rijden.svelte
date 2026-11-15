<script>
    // Handmatig rijden met één duim: een stuurknuppel. Omhoog = vooruit, omlaag = achteruit,
    // opzij = sturen. Loslaten = stoppen. Zolang je de knuppel vasthoudt gaat er tien keer per
    // seconde een commando naar de robot; valt dat weg (wifi, scherm uit, ander tabblad), dan
    // remt hij zelf af (dodemansknop, manual_timeout_s in de config).
    import { onMount, onDestroy } from 'svelte';
    import { motors, status, postJson, fmt, grensOmlaag, bron, tril, schermAan } from '../lib/telemetry.js';

    const DODE_ZONE = 0.14;       // deel van de uitslag waarin de snelheid 0 blijft
    const STUUR_DODE_ZONE = 0.06;
    const ZEND_MS = 100;

    let vlak;                     // het raakvlak
    let x = 0, y = 0;             // uitslag van de knuppel, -1 .. 1 (y omhoog = vooruit)
    let vast = false;             // duim op de knuppel
    let toetsen = new Set();      // pijltjes / WASD op een toetsenbord
    let blokkade = null;          // waarom de robot het laatste commando weigerde
    let verbonden = true;

    // Grenzen uit de VESC-config van de backend.
    $: grenzen = $motors.data?.limits;
    $: maxVooruit = grensOmlaag(grenzen?.max_kmh ?? 4.6);
    $: maxAchteruit = grensOmlaag(grenzen?.max_reverse_kmh ?? 2.3);
    $: minKmh = grenzen?.min_kmh ?? 1.4;
    $: timeoutS = $motors.data?.drive?.manual_timeout_s ?? 1.5;

    // Hoe hard de knuppel op volle uitslag gaat. Laag beginnen: fijn manoeuvreren op het erf.
    let top = 3.0;
    try { top = parseFloat(localStorage.getItem('rijden-top')) || 3.0; } catch (e) { /* geen opslag */ }
    $: keuzes = [...new Set([Math.ceil(minKmh * 2) / 2, 2, 3, 4, maxVooruit].filter((k) => k >= minKmh && k <= maxVooruit))]
        .sort((a, b) => a - b);
    $: if (top > maxVooruit) top = maxVooruit;
    function kiesTop(k) {
        top = k;
        try { localStorage.setItem('rijden-top', String(k)); } catch (e) { /* geen opslag */ }
    }

    // Uitslag -> rijopdracht. Net voorbij de dode zone rijdt hij meteen op het minimum van
    // de VESC (langzamer bestaat niet); daarboven loopt het gelijkmatig op tot 'top'.
    // Sturen is rond het midden fijner dan aan de rand.
    function opdracht(px, py) {
        let kmh = 0;
        const uit = Math.abs(py);
        if (uit > DODE_ZONE) {
            const deel = (uit - DODE_ZONE) / (1 - DODE_ZONE);
            const grens = py > 0 ? top : Math.min(top, maxAchteruit);
            kmh = Math.sign(py) * (minKmh + Math.max(0, grens - minKmh) * deel);
        }
        let stuur = 0;
        const zij = Math.abs(px);
        if (zij > STUUR_DODE_ZONE) {
            stuur = Math.sign(px) * Math.pow((zij - STUUR_DODE_ZONE) / (1 - STUUR_DODE_ZONE), 1.5) * 100;
        }
        return { kmh: Math.round(kmh * 10) / 10, stuur: Math.round(stuur) };
    }
    $: doel = opdracht(x, y);

    // --- De knuppel ---
    function zet(e) {
        const r = vlak.getBoundingClientRect();
        const straal = r.width / 2 - 34;                       // de knop zelf is 68 px
        let dx = (e.clientX - (r.left + r.width / 2)) / straal;
        let dy = -(e.clientY - (r.top + r.height / 2)) / straal;
        const lengte = Math.hypot(dx, dy);
        if (lengte > 1) { dx /= lengte; dy /= lengte; }
        const wasStil = Math.abs(y) <= DODE_ZONE;
        x = dx; y = dy;
        if (wasStil && Math.abs(y) > DODE_ZONE) tril(12);      // voelbaar: nu gaat hij rijden
    }

    function pak(e) {
        if (e.button !== undefined && e.button !== 0) return;
        vlak.setPointerCapture(e.pointerId);
        vast = true;
        zet(e);
        zend();
    }

    function beweeg(e) {
        if (vast) zet(e);
    }

    function los() {
        if (!vast) return;
        vast = false;
        x = 0; y = 0;
        zendNul();
    }

    // --- Toetsenbord (desktop): pijltjes of WASD, spatie = stop ---
    function toets(e, neer) {
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
        const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
        const naam = { ArrowUp: 'op', w: 'op', ArrowDown: 'neer', s: 'neer', ArrowLeft: 'links', a: 'links',
                       ArrowRight: 'rechts', d: 'rechts' }[k];
        if (!naam) return;
        e.preventDefault();
        if (neer) toetsen.add(naam); else toetsen.delete(naam);
        if (vast) return;
        x = (toetsen.has('rechts') ? 1 : 0) - (toetsen.has('links') ? 1 : 0);
        y = (toetsen.has('op') ? 1 : 0) - (toetsen.has('neer') ? 1 : 0);
        if (toetsen.size) zend(); else zendNul();
    }
    const toetsNeer = (e) => toets(e, true);
    const toetsOp = (e) => toets(e, false);
    function focusWeg() {
        // Venster verliest de focus met een toets ingedrukt: 'keyup' komt dan nooit meer.
        if (toetsen.size && !vast) { toetsen = new Set(); x = 0; y = 0; zendNul(); }
    }

    // --- Verzenden: één verzoek tegelijk, altijd met de nieuwste stand ---
    let onderweg = false;
    let timer = null;

    async function zend() {
        clearTimeout(timer);
        if (onderweg) return;                  // het lopende verzoek plant de volgende
        const rijdt = vast || toetsen.size > 0;
        if (!rijdt) return;
        onderweg = true;
        const begin = performance.now();
        try {
            const d = opdracht(x, y);
            const antwoord = await postJson('/api/nav/manual_drive',
                { speed_kmh: d.kmh, steering_percentage: d.stuur, bron });
            verbonden = true;
            const was = blokkade;
            blokkade = antwoord.status === 'blocked' ? antwoord.msg : null;
            if (blokkade && !was) tril([60, 40, 60]);
        } catch (e) {
            verbonden = false;
        }
        onderweg = false;
        timer = setTimeout(zend, Math.max(0, ZEND_MS - (performance.now() - begin)));
    }

    // Loslaten: snelheid 0 en stuur recht, en dat net zo lang herhalen tot de robot het
    // bevestigd heeft. Lukt dat niet, dan stopt hij na timeoutS vanzelf.
    async function zendNul(poging = 0) {
        clearTimeout(timer);
        if (vast || toetsen.size) return;
        if (onderweg) { timer = setTimeout(() => zendNul(poging), 40); return; }
        onderweg = true;
        let gelukt = false;
        try {
            await postJson('/api/nav/manual_drive', { speed_kmh: 0, steering_percentage: 0, bron });
            gelukt = true;
            verbonden = true;
        } catch (e) {
            verbonden = false;
        }
        onderweg = false;
        if (!gelukt && poging < 6) timer = setTimeout(() => zendNul(poging + 1), 150);
    }

    onMount(() => {
        schermAan(true);
        window.addEventListener('keydown', toetsNeer);
        window.addEventListener('keyup', toetsOp);
        window.addEventListener('blur', focusWeg);
    });

    onDestroy(() => {
        schermAan(false);
        window.removeEventListener('keydown', toetsNeer);
        window.removeEventListener('keyup', toetsOp);
        window.removeEventListener('blur', focusWeg);
        clearTimeout(timer);
        // Weg van dit scherm is niet meer aan het stuur.
        if (vast || toetsen.size) {
            vast = false; toetsen = new Set();
            postJson('/api/nav/manual_drive', { speed_kmh: 0, steering_percentage: 0, bron }).catch(() => {});
        }
    });

    $: wielen = $motors.data?.wheels;
    $: rijopdracht = $motors.data?.drive;
    $: missieLoopt = $status.data && ($status.data.ab_active || $status.data.missie_actief || $status.data.navigator_active);
</script>

<div class="pagina rijden">
    <div class="live paneel">
        <div><span>GPS</span><b class="num">{fmt($status.data?.speed_kmh, 1)}</b><small>km/h</small></div>
        <div><span>Wielen L / R</span><b class="num">{fmt(wielen?.left?.speed_kmh, 1)} / {fmt(wielen?.right?.speed_kmh, 1)}</b><small>km/h</small></div>
        <div><span>Stuur</span><b class="num">{fmt(rijopdracht?.angle_degrees, 0)}°</b><small>midden</small></div>
    </div>

    {#if !verbonden}
        <div class="melding rood">Commando komt niet aan. De robot remt na {timeoutS} s vanzelf af.</div>
    {:else if blokkade}
        <div class="melding rood"><b>Rijden geweigerd:</b> {blokkade}</div>
    {:else if missieLoopt}
        <div class="melding oranje">Er rijdt een missie. Pak je de knuppel, dan stopt die en neem jij over.</div>
    {/if}

    <div class="bediening">
        <div class="vlak" class:vast bind:this={vlak}
             on:pointerdown|preventDefault={pak} on:pointermove={beweeg}
             on:pointerup={los} on:pointercancel={los} on:lostpointercapture={los}
             role="application" aria-label="Stuurknuppel: sleep omhoog voor vooruit, omlaag voor achteruit, opzij om te sturen">
            <span class="as vooruit">vooruit</span>
            <span class="as achteruit">achteruit</span>
            <span class="as links">links</span>
            <span class="as rechts">rechts</span>
            <div class="ring"></div>
            <div class="kruis h"></div>
            <div class="kruis v"></div>
            <div class="knop" class:rijdt={doel.kmh !== 0}
                 style="transform: translate(calc(-50% + {x * 50}cqw - {x * 34}px), calc(-50% - {y * 50}cqw + {y * 34}px))">
            </div>
        </div>

        <div class="zijkant">
            <div class="doel paneel">
                <div class="groot-getal">{fmt(Math.abs(doel.kmh), 1)}<small> km/h</small></div>
                <div class="richting" class:rijdt={doel.kmh !== 0}>
                    {doel.kmh > 0 ? 'vooruit' : doel.kmh < 0 ? 'achteruit' : 'stil'}
                    · {doel.stuur === 0 ? 'rechtuit' : `${Math.abs(doel.stuur)}% ${doel.stuur > 0 ? 'rechts' : 'links'}`}
                </div>
            </div>

            <div class="paneel">
                <h3>Snelheid op volle uitslag</h3>
                <div class="keuzes">
                    {#each keuzes as k}
                        <button class:primair={top === k} on:click={() => kiesTop(k)}>{fmt(k, 1)}</button>
                    {/each}
                </div>
                <p class="klein">km/h vooruit; achteruit hoogstens {fmt(maxAchteruit, 1)}. Langzamer dan
                    {fmt(minKmh, 1)} km/h kunnen de wielen niet draaien.</p>
            </div>

            <p class="klein uitleg">
                Loslaten = stoppen. Ook als de verbinding wegvalt of het scherm uitgaat remt hij
                binnen {timeoutS} s af. Op een toetsenbord: pijltjes of WASD.
            </p>
        </div>
    </div>
</div>

<style>
    .live { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 10px 12px; text-align: center; }
    .live div { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
    .live span { font-size: 12px; color: var(--inkt2); text-transform: uppercase; letter-spacing: 0.06em; }
    .live b { font-size: 21px; white-space: nowrap; }
    .live small { font-size: 12px; color: var(--inkt2); }

    .bediening { display: grid; gap: 12px; grid-template-columns: 1fr; justify-items: center; }
    .zijkant { display: flex; flex-direction: column; gap: 12px; width: 100%; }

    /* Het raakvlak: zo groot als past, vierkant, en niets erin scrollt of selecteert. */
    .vlak {
        position: relative;
        container-type: inline-size;
        width: min(100%, 56vh, 420px);
        width: min(100%, 56dvh, 420px);
        aspect-ratio: 1;
        border-radius: 50%;
        background: radial-gradient(circle at 50% 50%, var(--vlak) 0%, var(--vlak2) 70%);
        border: 2px solid var(--lijn);
        box-shadow: var(--schaduw), inset 0 0 0 10px var(--vlak);
        touch-action: none;
        user-select: none; -webkit-user-select: none;
        cursor: grab;
    }
    .vlak.vast { cursor: grabbing; border-color: var(--accent); }
    .ring { position: absolute; inset: 43%; border-radius: 50%; border: 2px dashed var(--lijn); }
    .kruis { position: absolute; background: var(--lijn); }
    .kruis.h { left: 12%; right: 12%; top: 50%; height: 1px; }
    .kruis.v { top: 12%; bottom: 12%; left: 50%; width: 1px; }
    .as { position: absolute; font-size: 12px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--inkt2); pointer-events: none; }
    .as.vooruit { top: 16px; left: 50%; transform: translateX(-50%); }
    .as.achteruit { bottom: 16px; left: 50%; transform: translateX(-50%); }
    .as.links { left: 14px; top: 50%; transform: translateY(-50%); }
    .as.rechts { right: 14px; top: 50%; transform: translateY(-50%); }
    .knop {
        position: absolute; left: 50%; top: 50%;
        width: 68px; height: 68px; border-radius: 50%;
        background: var(--inkt2);
        border: 4px solid var(--vlak);
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
        pointer-events: none;
    }
    .vlak:not(.vast) .knop { transition: transform 0.12s ease-out; }
    .knop.rijdt { background: var(--accent); }

    .doel { text-align: center; padding: 10px 14px; }
    .richting { font-size: 15px; color: var(--inkt2); font-weight: 600; }
    .richting.rijdt { color: var(--accent); }
    .keuzes { display: flex; gap: 6px; margin-bottom: 8px; }
    .keuzes button { flex: 1; padding: 8px 4px; font-variant-numeric: tabular-nums; }
    .uitleg { text-align: center; }

    /* Liggend of breed: knuppel rechts (rechterduim), getallen links. */
    @media (min-width: 720px), (orientation: landscape) {
        .bediening { grid-template-columns: minmax(0, 1fr) auto; align-items: center; }
        .zijkant { order: -1; }
        .vlak { width: min(46vw, 62vh, 420px); width: min(46vw, 62dvh, 420px); }
    }
    @media (orientation: landscape) and (max-height: 540px) {
        .rijden { padding-top: 8px; gap: 8px; }
        .live { display: none; }
        .uitleg { display: none; }
        .vlak { width: min(46vw, 74vh); width: min(46vw, 74dvh); }
    }
</style>
