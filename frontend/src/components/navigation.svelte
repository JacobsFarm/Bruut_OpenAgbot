<script>
    // Waypoint-route: punten inmeten op de plek waar de robot staat, en ze daarna afrijden.
    import { onMount } from 'svelte';
    import { motors, status, postJson, noodstop, fmt, fixInfo, grensOmhoog, grensOmlaag } from '../lib/telemetry.js';

    // Snelheidsbereik van de aandrijving (min/max eRPM in de VESC-config).
    $: minKmh = grensOmhoog($motors.data?.limits?.min_kmh ?? 0.5);
    $: maxKmh = grensOmlaag($motors.data?.limits?.max_kmh ?? 5.0);

    let melding = '';
    let waypoints = [];
    let nieuweNaam = '';
    let gekozen = null;           // uitgeklapt punt in de lijst

    let snelheid = 2.0;
    let lookahead = 1.5;

    $: s = $status.data;
    $: fix = fixInfo(s?.fix);
    $: heeftPositie = !!(s && s.lat && s.lon && s.fix > 0);
    $: actief = s?.navigator_active ?? false;
    // Waarom de robot wel of niet rijdt ("Wacht op GNSS-heading", "Eindbestemming bereikt").
    $: navBericht = s && (s.navigator_active || (s.nav_state && s.nav_state !== 'IDLE')) ? s.nav_message : '';

    async function haalWaypoints() {
        try {
            const res = await fetch('/api/waypoints');
            waypoints = await res.json();
        } catch (e) {
            melding = 'Waypoints ophalen mislukt (geen verbinding)';
        }
    }

    async function voegToe() {
        if (!heeftPositie) {
            melding = 'Geen GPS-positie: er valt geen punt in te meten.';
            return;
        }
        try {
            await postJson('/api/waypoints', { lat: s.lat, lon: s.lon, way_point_name: nieuweNaam.trim() });
            nieuweNaam = '';
            melding = fix.kleur === 'groen' ? '' : `Punt ingemeten met ${fix.tekst}: minder nauwkeurig dan RTK Fixed.`;
            await haalWaypoints();
        } catch (e) {
            melding = 'Punt toevoegen mislukt';
        }
    }

    async function wisAlles() {
        if (!confirm(`Alle ${waypoints.length} punten wissen?`)) return;
        try {
            await fetch('/api/waypoints', { method: 'DELETE' });
            gekozen = null;
            await haalWaypoints();
        } catch (e) {
            melding = 'Wissen mislukt';
        }
    }

    async function bijwerken() {
        try {
            await postJson('/api/nav/update_sliders', { target_speed_kmh: +snelheid, lookahead_distance: +lookahead });
        } catch (e) { /* bij de volgende start gaan ze alsnog mee */ }
    }

    async function rijNaar(wp) {
        melding = '';
        try {
            const data = await postJson('/api/nav/start_pure_pursuit_direct', {
                lat: wp.lat, lon: wp.lon, target_speed_kmh: +snelheid, lookahead_distance: +lookahead, gain: 1.0
            });
            if (data.status === 'error') melding = data.msg || 'Starten mislukt';
        } catch (e) {
            melding = 'Starten mislukt (geen verbinding)';
        }
    }

    async function startRoute() {
        if (!waypoints.length) {
            melding = 'Geen punten: meet er eerst een paar in.';
            return;
        }
        melding = '';
        try {
            const data = await postJson('/api/nav/start_pure_pursuit', {
                target_speed_kmh: +snelheid, lookahead_distance: +lookahead, gain: 1.0
            });
            if (data.status === 'error') melding = data.msg || 'Starten mislukt';
        } catch (e) {
            melding = 'Starten mislukt (geen verbinding)';
        }
    }

    async function stop() {
        if (!(await noodstop())) melding = 'Stoppen mislukt: de robot is niet bereikt!';
    }

    onMount(haalWaypoints);
</script>

<section class="paneel">
    <h3>Route afrijden <span class="chip {actief ? 'groen' : ''}">{actief ? 'rijdt' : 'gestopt'}</span></h3>
    {#if navBericht}<div class="melding {s.nav_state === 'FOUT' ? 'rood' : 'blauw'}">{navBericht}</div>{/if}
    {#if melding}<div class="melding oranje">{melding}</div>{/if}

    <div class="knoppen start">
        {#if actief}
            <button class="gevaar groot" on:click={stop}>Stop route</button>
        {:else}
            <button class="primair groot" on:click={startRoute} disabled={!waypoints.length}>
                Start route ({waypoints.length} {waypoints.length === 1 ? 'punt' : 'punten'})
            </button>
        {/if}
    </div>

    <div class="veld">
        <label for="route-snelheid">Snelheid <span class="waarde">{fmt(snelheid, 1)} km/h</span></label>
        <input id="route-snelheid" type="range" min={minKmh} max={maxKmh} step="0.1" bind:value={snelheid} on:change={bijwerken}>
    </div>
    <div class="veld">
        <label for="route-lookahead">Lookahead <span class="waarde">{fmt(lookahead, 1)} m (alleen bij pure pursuit)</span></label>
        <input id="route-lookahead" type="range" min="0.5" max="4.0" step="0.1" bind:value={lookahead} on:change={bijwerken}>
    </div>
</section>

<section class="paneel">
    <h3>Punten inmeten</h3>
    <div class="veld">
        <input type="text" placeholder="Naam van het punt (mag leeg)" bind:value={nieuweNaam}
               on:keydown={(e) => { if (e.key === 'Enter') voegToe(); }} />
    </div>
    <div class="knoppen">
        <button class="blauw" on:click={voegToe} disabled={!heeftPositie}>+ Punt op deze plek</button>
        <button on:click={wisAlles} disabled={!waypoints.length}>Wis alles</button>
    </div>
    <p class="klein plek">
        {#if heeftPositie}
            <span class="stip {fix.kleur}"></span> {fix.tekst} · {fmt(s.lat, 7)}, {fmt(s.lon, 7)}
        {:else}
            Nog geen GPS-positie van de robot.
        {/if}
    </p>
</section>

<section class="paneel">
    <h3>Route ({waypoints.length})</h3>
    {#if !waypoints.length}
        <p class="klein">Nog geen punten. Rijd naar het begin en meet het eerste punt in.</p>
    {:else}
        <ul>
            {#each waypoints as wp, i}
                <li>
                    <button class="punt" on:click={() => (gekozen = gekozen === i ? null : i)} aria-expanded={gekozen === i}>
                        <span class="nr">{i + 1}</span>
                        <span class="naam"><b>{wp.way_point_name || `punt ${i + 1}`}</b>
                            <small class="num">{wp.lat.toFixed(6)}, {wp.lon.toFixed(6)}</small></span>
                    </button>
                    {#if gekozen === i}
                        <div class="actie">
                            <button class="primair vol" on:click={() => rijNaar(wp)}>Rij alleen naar dit punt</button>
                        </div>
                    {/if}
                </li>
            {/each}
        </ul>
    {/if}
</section>

<style>
    .melding { margin-bottom: 10px; }
    .start { margin-bottom: 14px; }
    .plek { margin-top: 10px; display: flex; align-items: center; gap: 6px; }
    ul { list-style: none; margin: 0; padding: 0; }
    li { border-top: 1px solid var(--lijn); }
    li:first-child { border-top: none; }
    .punt { width: 100%; justify-content: flex-start; gap: 12px; background: none; border: none; padding: 8px 2px; text-align: left; border-radius: 0; }
    .nr { flex: none; width: 30px; height: 30px; border-radius: 50%; background: var(--vlak2); display: grid; place-items: center; font-size: 14px; font-variant-numeric: tabular-nums; }
    .naam { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
    .naam small { font-weight: 400; color: var(--inkt2); font-size: 13px; }
    .actie { padding: 0 0 10px 42px; }
</style>
