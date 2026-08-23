<script>
    import { onMount, onDestroy } from 'svelte';

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

    // Live voortgang tijdens de missie
    let missieActief = false;
    let liveBericht = "";
    let timer = null;

    onMount(async () => {
        await haalLijnenOp();
        timer = setInterval(haalStatusOp, 1000);
    });

    onDestroy(() => {
        if (timer) clearInterval(timer);
    });

    async function haalStatusOp() {
        try {
            const res = await fetch('/api/status');
            const s = await res.json();
            missieActief = s.ab_active;
            liveBericht = s.ab_active
                ? `${s.ab_state} | ${s.ab_message} | baan ${s.ab_baan_nr}/${s.ab_totaal_banen}`
                : "";
        } catch(e) {}
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
        aangepast = true;
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
            statusBericht = baanVolgorde.length
                ? `'${lijn.veldnaam}': ${baanVolgorde.length} banen x ${werkbreedte} m, ${veldlengte.toFixed(0)} m lang`
                : `Lijn '${lijn.veldnaam}' geladen (geen missieplan in de json)`;
        } else {
            gekozenLijn = null;
            lat_a = null;
            lat_b = null;
            baanVolgorde = [];
            aangepast = false;
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
                body: JSON.stringify({
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
                })
            });
            const data = await res.json();
            if (data.status === "error") {
                statusBericht = "Fout: " + data.msg;
            } else {
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
        try {
            await fetch('/api/stop', { method: 'POST' });
            statusBericht = "Gestopt (Noodstop)";
        } catch(e) {}
    }
</script>

<div class="tractor-container">
    <h2>Landbouw (A-B Lijnen)</h2>
    <div class="status-box">{statusBericht}</div>
    {#if missieActief}
        <div class="live-box">{liveBericht}</div>
    {/if}

    <div class="grid-layout">
        <div class="config-box">
            <h3>1. Lijn Selecteren</h3>
            <select on:change={selecteerLijn} bind:value={geselecteerdeLijnIndex}>
                <option value="-1">-- Kies een opgeslagen lijn --</option>
                {#each opgeslagenLijnen as lijn, i}
                    <option value={i}>{lijn.veldnaam}</option>
                {/each}
            </select>
            <button class="btn-refresh" on:click={haalLijnenOp}>Herlaad JSON Lijst</button>
            {#if baanVolgorde.length}
                <p class="hint">
                    Werkvolgorde: <b>{baanVolgorde.join(' - ')}</b>
                    {#if aangepast}<span class="gewijzigd">aangepast</span>{/if}<br>
                    Kopakker {kopakkerExtra} m doorrijden, veld ligt {kant} van de lijn.
                </p>
                {#if aangepast}
                    <button class="btn-herstel" on:click={herstelUitJson}>
                        Terug naar de waardes uit de JSON
                    </button>
                {/if}
            {:else}
                <p class="hint">
                    Geen missieplan in deze lijn. Maak er een met
                    <code>Single_script_code/AB_mission_maker.py</code>, dan komen
                    werkbreedte, baanlengte en werkvolgorde hier vanzelf te staan.
                </p>
            {/if}
        </div>

        <div class="config-box">
            <h3>2. Werk Instellingen</h3>
            <p class="hint">
                De baanindeling, alleen te zetten <b>voor</b> de start. Deze
                waardes komen uit de JSON en mag je hier gerust verzetten: ze
                gelden alleen voor deze missie, het bestand op de robot verandert
                niet. Het invulvakje naast de schuif is er voor exacte waardes en
                voor buiten het schuifbereik.
            </p>

            <div class="slider-group">
                <label for="werkbreedte">Werkbreedte (m)</label>
                <div class="regel">
                    <input id="werkbreedte" type="range" min="1.0" max="10.0" step="0.1"
                           bind:value={werkbreedte} on:change={() => aangepast = true}>
                    <input class="getal" type="number" min="0.1" step="0.1"
                           bind:value={werkbreedte} on:change={() => aangepast = true}>
                </div>
            </div>

            <div class="slider-group">
                <label for="veldlengte">Baanlengte / veldlengte (m)</label>
                <div class="regel">
                    <input id="veldlengte" type="range" min="10" max="400" step="1"
                           bind:value={veldlengte} on:change={() => aangepast = true}>
                    <input class="getal" type="number" min="1" step="0.1"
                           bind:value={veldlengte} on:change={() => aangepast = true}>
                </div>
            </div>

            <div class="slider-group">
                <label for="aantalBanen">Aantal banen</label>
                <div class="regel">
                    <input id="aantalBanen" type="range" min="1" max="60" step="1"
                           bind:value={aantalBanen} on:change={hertelVolgorde}>
                    <input class="getal" type="number" min="1" step="1"
                           bind:value={aantalBanen} on:change={hertelVolgorde}>
                </div>
            </div>

            <div class="slider-group">
                <label for="overslaan">
                    Banen overslaan (zijsprong {zijsprong} m)
                </label>
                <div class="regel">
                    <input id="overslaan" type="range" min="0" max="4" step="1"
                           bind:value={banenOverslaan} on:change={hertelVolgorde}>
                    <input class="getal" type="number" min="0" max="9" step="1"
                           bind:value={banenOverslaan} on:change={hertelVolgorde}>
                </div>
            </div>

            <div class="slider-group">
                <label for="kopakker">Kopakker doorrijden (m)</label>
                <div class="regel">
                    <input id="kopakker" type="range" min="0.0" max="15.0" step="0.5"
                           bind:value={kopakkerExtra} on:change={() => aangepast = true}>
                    <input class="getal" type="number" min="0" step="0.5"
                           bind:value={kopakkerExtra} on:change={() => aangepast = true}>
                </div>
            </div>

            <div class="slider-group">
                <label for="kant">Veld ligt ... van de A-B lijn</label>
                <select id="kant" bind:value={kant} on:change={() => aangepast = true}>
                    <option value="rechts">rechts van de lijn</option>
                    <option value="links">links van de lijn</option>
                </select>
            </div>
        </div>

        <div class="config-box">
            <h3>3. Rijden &amp; lijnvolging (live)</h3>
            <p class="hint">
                Deze drie werken direct tijdens een lopende missie - je hoeft niet
                te stoppen. De baanindeling hierboven kan dat niet: die ligt bij
                het starten vast.
            </p>

            <div class="slider-group">
                <label for="snelheid">Werksnelheid (km/h)</label>
                <div class="regel">
                    <input id="snelheid" type="range" min="0.5" max="7.0" step="0.1"
                           bind:value={snelheid} on:change={updateLijnvolging}>
                    <input class="getal" type="number" min="0" step="0.1"
                           bind:value={snelheid} on:change={updateLijnvolging}>
                </div>
            </div>

            <div class="slider-group">
                <label>
                    Lookahead (strak ⟷ soepel): {lookahead.toFixed(1)} m
                    <input type="range" min="0.5" max="6.0" step="0.1" bind:value={lookahead} on:change={updateLijnvolging}>
                </label>
            </div>

            <div class="slider-group">
                <label>
                    Bochtsnelheid: {bochtSnelheid.toFixed(1)} km/h
                    <input type="range" min="0.5" max="5.0" step="0.1" bind:value={bochtSnelheid} on:change={updateLijnvolging}>
                </label>
            </div>
        </div>
    </div>

    <div class="actions">
        <button class="btn-start" on:click={startABMissie}>Start A-B Missie</button>
        <button class="btn-stop" on:click={noodstop}>STOP ALLES</button>
    </div>
</div>

<style>
    .tractor-container { padding: 15px; font-family: sans-serif; }
    .status-box { background: #e3f2fd; color: #1565c0; padding: 15px; border-radius: 4px; font-weight: bold; text-align: center; margin-bottom: 20px; font-size: 18px; }
    .live-box { background: #ede7f6; color: #4527a0; padding: 12px; border-radius: 4px; text-align: center; margin: -10px 0 20px; font-size: 15px; font-family: monospace; }
    code { background: #eceff1; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
    .grid-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
    @media (max-width: 600px) { .grid-layout { grid-template-columns: 1fr; } }
    
    .config-box { background: #f5f5f5; padding: 20px; border-radius: 8px; border: 1px solid #ddd; }
    h3 { margin-top: 0; border-bottom: 2px solid #ddd; padding-bottom: 10px; margin-bottom: 15px; }
    
    select { width: 100%; padding: 15px; font-size: 16px; margin-bottom: 15px; border-radius: 4px; border: 1px solid #ccc; background: white; }
    .btn-refresh { width: 100%; padding: 12px; background: #607d8b; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
    
    .hint { font-size: 13px; color: #666; margin-top: -5px; margin-bottom: 15px; }
    .slider-group { margin-bottom: 20px; }
    label { display: block; font-size: 14px; font-weight: bold; margin-bottom: 8px; }
    input[type="range"] { width: 100%; height: 30px; cursor: pointer; }

    /* Schuif plus invulvakje naast elkaar: de schuif om snel te zoeken, het
       vakje om een exacte waarde in te tikken of buiten het bereik te gaan. */
    .regel { display: flex; align-items: center; gap: 10px; }
    .regel input[type="range"] { flex: 1; min-width: 0; }
    .getal { width: 84px; padding: 8px; font-size: 15px; text-align: right; border: 1px solid #ccc; border-radius: 4px; }
    .gewijzigd { background: #ffe082; color: #6d4c00; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: bold; }
    .btn-herstel { width: 100%; padding: 10px; background: #ff8f00; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-top: 8px; }
    
    .actions { display: flex; flex-direction: column; gap: 15px; }
    .btn-start, .btn-stop { padding: 20px; font-size: 20px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; color: white; }
    .btn-start { background: #4caf50; }
    .btn-stop { background: #d32f2f; }
</style>