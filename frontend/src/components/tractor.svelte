<script>
    import { onMount } from 'svelte';

    let werkbreedte = 4.0;
    let veldlengte = 50.0;
    let snelheid = 3.0;
    let statusBericht = "Kies een A-B lijn";

    // Lijnvolging-tuning (lager = strakker/agressiever, hoger = soepeler)
    let lookahead = 2.5;
    let bochtSnelheid = 2.0;

    let opgeslagenLijnen = [];
    let geselecteerdeLijnIndex = -1;

    let lat_a = null;
    let lon_a = null;
    let lat_b = null;
    let lon_b = null;

    onMount(async () => {
        await haalLijnenOp();
    });

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
            lat_a = lijn.lat_a;
            lon_a = lijn.lon_a;
            lat_b = lijn.lat_b;
            lon_b = lijn.lon_b;
            statusBericht = `Lijn '${lijn.veldnaam}' geladen`;
        } else {
            lat_a = null;
            lat_b = null;
            statusBericht = "Kies een A-B lijn";
        }
    }

    async function startABMissie() {
        if (!lat_a || !lat_b) {
            statusBericht = "Fout: Geen A-B lijn geselecteerd!";
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
                    turn_speed_kmh: parseFloat(bochtSnelheid)
                })
            });
            const data = await res.json();
            if (data.status === "error") {
                statusBericht = "Fout: " + data.msg;
            } else {
                statusBericht = "A-B Missie Actief!";
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
        </div>

        <div class="config-box">
            <h3>2. Werk Instellingen</h3>
            <div class="slider-group">
                <label>
                    Werkbreedte: {werkbreedte.toFixed(1)}m
                    <input type="range" min="1.0" max="10.0" step="0.1" bind:value={werkbreedte}>
                </label>
            </div>

            <div class="slider-group">
                <label>
                    Veldlengte: {veldlengte.toFixed(0)}m
                    <input type="range" min="10" max="200" step="5" bind:value={veldlengte}>
                </label>
            </div>

            <div class="slider-group">
                <label>
                    Werksnelheid: {snelheid.toFixed(1)} km/h
                    <input type="range" min="0.5" max="7.0" step="0.1" bind:value={snelheid} on:change={updateLijnvolging}>
                </label>
            </div>
        </div>

        <div class="config-box">
            <h3>3. Lijnvolging (live)</h3>
            <p class="hint">Lager = strakker/agressiever volgen, hoger = soepeler. Werkt direct tijdens een lopende missie.</p>
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
    
    .actions { display: flex; flex-direction: column; gap: 15px; }
    .btn-start, .btn-stop { padding: 20px; font-size: 20px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; color: white; }
    .btn-start { background: #4caf50; }
    .btn-stop { background: #d32f2f; }
</style>