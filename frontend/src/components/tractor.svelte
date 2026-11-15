<script>
    import { onMount, onDestroy } from 'svelte';
    import { motors, status, noodstop as stopRobot, fmt, grensOmhoog, grensOmlaag } from '../lib/telemetry.js';
    import Veldkaart from './veldkaart.svelte';

    // False zolang dit tabblad niet in beeld is (het blijft bestaan, zodat je keuzes blijven staan).
    export let actief = true;

    // Snelheidsbereik van de aandrijving (min/max eRPM in de VESC-config).
    // Daarbuiten rijdt hij toch op de grens, dus de schuiven lopen niet verder.
    $: minKmh = grensOmhoog($motors.data?.limits?.min_kmh ?? 0.5);
    $: maxKmh = grensOmlaag($motors.data?.limits?.max_kmh ?? 7.0);

    let werkbreedte = 4.0;
    let veldlengte = 50.0;
    let snelheid = 3.0;
    let statusBericht = "Kies een A-B lijn";

    // Missieplan (komt uit data/ab_line.json, gemaakt met AB_mission_maker.py)
    let aantalBanen = 8;
    let banenOverslaan = 1;
    let kopakkerExtra = 2.0;
    let kant = "rechts";
    let baanVolgorde = [];
    // De ruwe json-regel, zodat je met een knop terug kunt naar de opgeslagen
    // waardes. Alles wat je hier verzet geldt alleen voor deze missie; het
    // bestand op de robot blijft ongemoeid.
    let gekozenLijn = null;
    let aangepast = false;

    // Lijnvolging-tuning (lager = strakker/agressiever, hoger = soepeler)
    let lookahead = 2.5;
    let bochtSnelheid = 2.0;

    let opgeslagenLijnen = [];
    let geselecteerdeLijnIndex = -1;

    let lat_a = null;
    let lon_a = null;
    let lat_b = null;
    let lon_b = null;

    // Live voortgang tijdens de missie, uit de gedeelde status
    $: s = $status.data;
    $: missieActief = s?.ab_active ?? false;
    $: liveBericht = missieActief ? s.ab_message : "";
    // Waarom de vorige missie stopte ("Gestopt - 1.20 m naast baan 3"), tot je een nieuwe start.
    $: stopReden = !missieActief && s?.ab_message?.startsWith('Gestopt -') ? s.ab_message : "";
    let timer = null;

    // Voorbeeld op de kaart: wat hij met deze instellingen gaat rijden. Alleen
    // zolang je een missie voorbereidt; na de start toont de kaart het plan van
    // de robot, en na afloop blijft dat staan tot je weer iets verzet.
    let voorbeeld = null;
    let voorbeeldJson = null;
    let voorbeeldNodig = false;
    let voorbeeldFout = "";
    let voorbeeldTimer = null;

    onMount(async () => {
        await haalLijnenOp();
        // Draait de robot intussen, of komt de GPS-fix binnen, dan kan de rijrichting
        // van de eerste baan omslaan: het voorbeeld af en toe verversen.
        timer = setInterval(() => { if (actief && voorbeeldNodig && !missieActief) haalVoorbeeldOp(); }, 3000);
    });

    onDestroy(() => {
        if (timer) clearInterval(timer);
        clearTimeout(voorbeeldTimer);
    });

    // Hetzelfde bericht voor de start en voor het voorbeeld op de kaart, zodat
    // de kaart precies laat zien wat er na 'Start' gereden wordt.
    function missieBericht() {
        return {
            work_width_m: werkbreedte,
            field_length_m: veldlengte,
            speed_kmh: snelheid,
            lat_a: lat_a, lon_a: lon_a,
            lat_b: lat_b, lon_b: lon_b,
            lookahead_m: parseFloat(lookahead),
            turn_speed_kmh: parseFloat(bochtSnelheid),
            swath_order: baanVolgorde.length ? baanVolgorde : null,
            aantal_banen: parseInt(aantalBanen),
            banen_overslaan: parseInt(banenOverslaan),
            kopakker_extra_m: parseFloat(kopakkerExtra),
            kant: kant
        };
    }

    function vernieuwVoorbeeld() {
        voorbeeldNodig = true;
        clearTimeout(voorbeeldTimer);
        voorbeeldTimer = setTimeout(haalVoorbeeldOp, 250);
    }

    async function haalVoorbeeldOp() {
        if (!voorbeeldNodig || missieActief || !lat_a || !lat_b || ontbrekend().length) return;
        try {
            const res = await fetch('/api/ab/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(missieBericht())
            });
            const data = await res.json();
            if (!voorbeeldNodig) return;     // intussen gestart
            if (res.ok && data.status === 'ok') {
                // Alleen vervangen als er echt iets anders is, anders tekent
                // de kaart elke paar seconden hetzelfde opnieuw.
                const json = JSON.stringify(data.plan);
                if (json !== voorbeeldJson) {
                    voorbeeldJson = json;
                    voorbeeld = data.plan;
                }
                voorbeeldFout = "";
            } else {
                voorbeeld = null;
                voorbeeldJson = null;
                voorbeeldFout = data.msg || `geen voorbeeld mogelijk (HTTP ${res.status})`;
            }
        } catch(e) {}
    }

    function wisVoorbeeld() {
        voorbeeldNodig = false;
        clearTimeout(voorbeeldTimer);
        voorbeeld = null;
        voorbeeldJson = null;
        voorbeeldFout = "";
    }

    function gewijzigd() {
        aangepast = true;
        vernieuwVoorbeeld();
    }

    // Zelfde algoritme als maak_baan_volgorde() in ab_navigator.py, zodat je
    // meteen ziet wat er straks gereden wordt als je hier iets verzet.
    function berekenVolgorde(aantal, overslaan) {
        const stap = Math.max(1, parseInt(overslaan) + 1);
        const volgorde = [];
        for (let start = 0; start < stap; start++) {
            const laag = [];
            for (let i = start; i < aantal; i += stap) laag.push(i);
            if (start % 2 === 1) laag.reverse();
            volgorde.push(...laag);
        }
        return volgorde;
    }

    // Verzet je het aantal banen of het overslaan, dan klopt de volgorde uit de
    // json niet meer; hier rekenen we hem opnieuw uit zodat scherm en robot
    // hetzelfde plan gebruiken.
    function hertelVolgorde() {
        // Het invulvakje laat ook onzin toe (leeg, of 5000 banen); hier vangen
        // we dat af zodat er geen kapot plan naar de robot gaat.
        aantalBanen = Math.min(500, Math.max(1, parseInt(aantalBanen) || 1));
        banenOverslaan = Math.min(9, Math.max(0, parseInt(banenOverslaan) || 0));
        baanVolgorde = berekenVolgorde(aantalBanen, banenOverslaan);
        gewijzigd();
    }

    // Een leeggemaakt invulvakje geeft null, en isNaN(null) is false - vandaar
    // dat we hier expliciet op null controleren.
    function isGetal(waarde) {
        return waarde !== null && waarde !== undefined && !isNaN(waarde);
    }

    function ontbrekend() {
        const velden = {
            "Werkbreedte": werkbreedte,
            "Baanlengte": veldlengte,
            "Werksnelheid": snelheid,
            "Aantal banen": aantalBanen,
            "Banen overslaan": banenOverslaan,
            "Kopakker doorrijden": kopakkerExtra
        };
        return Object.keys(velden).filter(n => !isGetal(velden[n]));
    }

    $: zijsprong = (isGetal(banenOverslaan) && isGetal(werkbreedte))
        ? ((banenOverslaan + 1) * werkbreedte).toFixed(1) : "?";

    // Zonder plan in de json valt hij terug op de oude werkwijze: baan na baan
    // (0,1,2,...) en de kopakker-instellingen uit de config.
    function pasPlanToe(lijn) {
        werkbreedte    = lijn.werkbreedte_m    ?? werkbreedte;
        veldlengte     = lijn.baanlengte_m     ?? veldlengte;
        aantalBanen    = lijn.aantal_banen     ?? aantalBanen;
        banenOverslaan = lijn.banen_overslaan  ?? banenOverslaan;
        kopakkerExtra  = lijn.kopakker_extra_m ?? kopakkerExtra;
        kant           = lijn.kant             ?? kant;
        snelheid       = lijn.werksnelheid_kmh ?? snelheid;
        bochtSnelheid  = lijn.bochtsnelheid_kmh ?? bochtSnelheid;
        baanVolgorde   = lijn.baan_volgorde    ?? [];
        aangepast = false;
    }

    // Alles terug naar wat er in de json staat, voor als je je verschoven hebt.
    function herstelUitJson() {
        if (!gekozenLijn) return;
        pasPlanToe(gekozenLijn);
        vernieuwVoorbeeld();
        statusBericht = `Waarden van '${gekozenLijn.veldnaam}' teruggezet uit de json`;
    }

    async function haalLijnenOp() {
        try {
            const res = await fetch('/api/ab_lijnen');
            opgeslagenLijnen = await res.json();
            statusBericht = "Lijst bijgewerkt";
        } catch(e) {
            statusBericht = "Fout bij laden van json";
        }
    }

    function selecteerLijn(e) {
        const idx = e.target.value;
        if (idx >= 0) {
            const lijn = opgeslagenLijnen[idx];
            gekozenLijn = lijn;
            lat_a = lijn.lat_a;
            lon_a = lijn.lon_a;
            lat_b = lijn.lat_b;
            lon_b = lijn.lon_b;
            pasPlanToe(lijn);
            vernieuwVoorbeeld();
            statusBericht = baanVolgorde.length
                ? `'${lijn.veldnaam}': ${baanVolgorde.length} banen x ${werkbreedte} m, ${veldlengte.toFixed(0)} m lang`
                : `Lijn '${lijn.veldnaam}' geladen (geen missieplan in de json)`;
        } else {
            gekozenLijn = null;
            lat_a = null;
            lat_b = null;
            baanVolgorde = [];
            aangepast = false;
            wisVoorbeeld();
            statusBericht = "Kies een A-B lijn";
        }
    }

    async function startABMissie() {
        if (!lat_a || !lat_b) {
            statusBericht = "Fout: Geen A-B lijn geselecteerd!";
            return;
        }
        const leeg = ontbrekend();
        if (leeg.length) {
            statusBericht = "Fout: nog niet ingevuld - " + leeg.join(", ");
            return;
        }
        try {
            statusBericht = "Missie starten...";
            const res = await fetch('/api/nav/start_ab', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(missieBericht())
            });
            const data = await res.json();
            // Ook een geweigerd verzoek (422) is geen start: dan heeft de
            // robot niets gedaan, al staat er geen status "error" in.
            if (!res.ok || data.status === "error") {
                statusBericht = "Fout: " + (data.msg || `de robot weigerde de opdracht (HTTP ${res.status})`);
            } else {
                wisVoorbeeld();     // vanaf nu toont de kaart het plan van de robot
                baanVolgorde = data.baan_volgorde || baanVolgorde;
                statusBericht = `A-B Missie actief: ${baanVolgorde.length} banen`;
            }
        } catch(e) {
            statusBericht = "Netwerkfout";
        }
    }

    // Live aanpassen tijdens (of voor) een missie zodat je snel waardes kunt proberen
    async function updateLijnvolging() {
        try {
            await fetch('/api/nav/update_ab_sliders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lookahead_m: parseFloat(lookahead),
                    target_speed_kmh: parseFloat(snelheid),
                    turn_speed_kmh: parseFloat(bochtSnelheid)
                })
            });
        } catch(e) {}
    }

    async function noodstop() {
        statusBericht = (await stopRobot()) ? "Gestopt" : "Stoppen mislukt: de robot is niet bereikt!";
    }
</script>

<div class="pagina">
    {#if missieActief}
        <div class="melding groen live">{liveBericht}</div>
    {:else if stopReden}
        <div class="melding rood">{stopReden}</div>
    {:else}
        <div class="melding blauw">{statusBericht}</div>
    {/if}

    <Veldkaart {voorbeeld} {actief} />
    {#if voorbeeldFout}
        <p class="klein">Kaart: {voorbeeldFout}</p>
    {/if}

    <!-- Starten en stoppen direct onder de kaart: daar kijk je naar. -->
    {#if missieActief}
        <button class="gevaar groot vol" on:click={noodstop}>Stop missie</button>
    {:else}
        <button class="primair groot vol" on:click={startABMissie} disabled={!lat_a || !lat_b}>
            {gekozenLijn ? 'Start: ' + gekozenLijn.veldnaam : 'Kies eerst een lijn'}
        </button>
    {/if}

    <details class="paneel" open>
        <summary>1. Lijn <small>{gekozenLijn ? gekozenLijn.veldnaam : 'geen gekozen'}</small></summary>
        <div class="veld">
            <select on:change={selecteerLijn} bind:value={geselecteerdeLijnIndex} disabled={missieActief} aria-label="Opgeslagen A-B lijn">
                <option value="-1">Kies een opgeslagen lijn</option>
                {#each opgeslagenLijnen as lijn, i}
                    <option value={i}>{lijn.veldnaam}</option>
                {/each}
            </select>
        </div>
        <button class="vol" on:click={haalLijnenOp}>Lijst opnieuw laden</button>
        {#if baanVolgorde.length}
            <p class="klein uitleg">
                Werkvolgorde: <b>{baanVolgorde.join(' - ')}</b>
                {#if aangepast}<span class="chip oranje">aangepast</span>{/if}<br>
                Kopakker {kopakkerExtra} m doorrijden, veld ligt {kant} van de lijn.
            </p>
            {#if aangepast}
                <button class="oranje vol" on:click={herstelUitJson}>Terug naar de waardes uit het bestand</button>
            {/if}
        {:else}
            <p class="klein uitleg">
                Geen missieplan in deze lijn. Maak er een met
                <code>Single_script_code/AB_mission_maker.py</code>, dan komen
                werkbreedte, baanlengte en werkvolgorde hier vanzelf te staan.
            </p>
        {/if}
    </details>

    <details class="paneel">
        <summary>2. Banen <small>{aantalBanen} x {werkbreedte} m, {fmt(veldlengte, 0)} m lang</small></summary>
        <p class="klein uitleg boven">
            De baanindeling, alleen te zetten <b>voor</b> de start. Wat je hier verzet geldt
            alleen voor deze missie; het bestand op de robot verandert niet.
        </p>

        <div class="veld">
            <label for="werkbreedte">Werkbreedte (m)</label>
            <div class="rij">
                <input id="werkbreedte" type="range" min="1.0" max="10.0" step="0.1"
                       bind:value={werkbreedte} on:change={gewijzigd}>
                <input type="number" inputmode="decimal" min="0.1" step="0.1" aria-label="Werkbreedte in meters"
                       bind:value={werkbreedte} on:change={gewijzigd}>
            </div>
        </div>

        <div class="veld">
            <label for="veldlengte">Baanlengte (m)</label>
            <div class="rij">
                <input id="veldlengte" type="range" min="10" max="400" step="1"
                       bind:value={veldlengte} on:change={gewijzigd}>
                <input type="number" inputmode="decimal" min="1" step="0.1" aria-label="Baanlengte in meters"
                       bind:value={veldlengte} on:change={gewijzigd}>
            </div>
        </div>

        <div class="veld">
            <label for="aantalBanen">Aantal banen</label>
            <div class="rij">
                <input id="aantalBanen" type="range" min="1" max="60" step="1"
                       bind:value={aantalBanen} on:change={hertelVolgorde}>
                <input type="number" inputmode="numeric" min="1" step="1" aria-label="Aantal banen"
                       bind:value={aantalBanen} on:change={hertelVolgorde}>
            </div>
        </div>

        <div class="veld">
            <label for="overslaan">Banen overslaan <span class="waarde">zijsprong {zijsprong} m</span></label>
            <div class="rij">
                <input id="overslaan" type="range" min="0" max="4" step="1"
                       bind:value={banenOverslaan} on:change={hertelVolgorde}>
                <input type="number" inputmode="numeric" min="0" max="9" step="1" aria-label="Banen overslaan"
                       bind:value={banenOverslaan} on:change={hertelVolgorde}>
            </div>
        </div>

        <div class="veld">
            <label for="kopakker">Kopakker doorrijden (m)</label>
            <div class="rij">
                <input id="kopakker" type="range" min="0.0" max="15.0" step="0.5"
                       bind:value={kopakkerExtra} on:change={gewijzigd}>
                <input type="number" inputmode="decimal" min="0" step="0.5" aria-label="Kopakker doorrijden in meters"
                       bind:value={kopakkerExtra} on:change={gewijzigd}>
            </div>
        </div>

        <div class="veld">
            <label for="kant">Het veld ligt</label>
            <select id="kant" bind:value={kant} on:change={gewijzigd}>
                <option value="rechts">rechts van de lijn A → B</option>
                <option value="links">links van de lijn A → B</option>
            </select>
        </div>
    </details>

    <details class="paneel" open={missieActief}>
        <summary>3. Rijden <small>{fmt(snelheid, 1)} km/h, bocht {fmt(bochtSnelheid, 1)} km/h</small></summary>
        <p class="klein uitleg boven">
            Deze drie werken direct, ook tijdens een lopende missie.
        </p>

        <div class="veld">
            <label for="snelheid">Werksnelheid <span class="waarde">{fmt(minKmh, 1)} – {fmt(maxKmh, 1)} km/h</span></label>
            <div class="rij">
                <input id="snelheid" type="range" min={minKmh} max={maxKmh} step="0.1"
                       bind:value={snelheid} on:change={updateLijnvolging}>
                <input type="number" inputmode="decimal" min="0" step="0.1" aria-label="Werksnelheid in km/h"
                       bind:value={snelheid} on:change={updateLijnvolging}>
            </div>
        </div>

        <div class="veld">
            <label for="bochtsnelheid">Bochtsnelheid <span class="waarde">{bochtSnelheid.toFixed(1)} km/h</span></label>
            <input id="bochtsnelheid" type="range" min={minKmh} max={maxKmh} step="0.1" bind:value={bochtSnelheid} on:change={updateLijnvolging}>
        </div>

        <div class="veld">
            <label for="lookahead">Lookahead <span class="waarde">{lookahead.toFixed(1)} m (alleen bij pure pursuit)</span></label>
            <input id="lookahead" type="range" min="0.5" max="6.0" step="0.1" bind:value={lookahead} on:change={updateLijnvolging}>
        </div>
    </details>
</div>

<style>
    .live { font-variant-numeric: tabular-nums; }
    .uitleg { margin-top: 10px; }
    .uitleg.boven { margin: 0 0 12px; }
    .uitleg + button { margin-top: 10px; }
    code { background: var(--vlak2); padding: 1px 4px; border-radius: 4px; font-size: 12.5px; overflow-wrap: anywhere; }
</style>
