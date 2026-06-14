<script>
    import { onMount } from 'svelte';

    let status = "Gestopt";
    let waypoints = [];

    // Naam voor het volgende toe te voegen waypoint
    let newWaypointName = "";

    // Bijhouden welk waypoint is aangeklikt om uit te klappen
    let selectedWp = null;
    
    // Autonome tuning parameters
    let targetSpeed = 2.0; 
    let lookaheadDistance = 1.5;
    let gain = 1.0;

    async function fetchWaypoints() {
        try {
            const res = await fetch('/api/waypoints');
            waypoints = await res.json();
        } catch (e) {
            status = "Netwerkfout";
        }
    }

    async function addWaypoint() {
        try {
            const statusRes = await fetch('/api/status');
            const gpsData = await statusRes.json();

            await fetch('/api/waypoints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: gpsData.lat,
                    lon: gpsData.lon,
                    way_point_name: newWaypointName.trim()
                })
            });
            newWaypointName = "";
            await fetchWaypoints();
        } catch (e) {
            status = "Fout bij toevoegen";
        }
    }

    async function clearWaypoints() {
        try {
            await fetch('/api/waypoints', { method: 'DELETE' });
            await fetchWaypoints();
            selectedWp = null; // Sluit menuutje als alles is gewist
        } catch (e) {
            status = "Fout bij wissen";
        }
    }

    async function updateSliders() {
        await fetch('/api/nav/update_sliders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_speed_kmh: parseFloat(targetSpeed),
                lookahead_distance: parseFloat(lookaheadDistance),
                gain: parseFloat(gain)
            })
        });
    }

    // --- Rij Direct (Rechte Lijn / Snappen) ---
    async function startDirectSpecific(wp) {
        status = "Starten Naar Punt (Rechte Lijn)...";
        try {
            const res = await fetch('/api/nav/start_point_to_point', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: wp.lat,
                    lon: wp.lon,
                    target_speed_kmh: parseFloat(targetSpeed),
                    gain: parseFloat(gain)
                })
            });
            const data = await res.json();
            status = data.status || "Onderweg (Rechte Lijn)";
        } catch (e) {
            status = "Fout bij starten";
        }
    }

    // --- NIEUW: Rij Direct via Pure Pursuit (Vloeiende bocht) ---
    async function startPurePursuitSpecific(wp) {
        status = "Starten Naar Punt (Pure Pursuit)...";
        try {
            const res = await fetch('/api/nav/start_pure_pursuit_direct', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: wp.lat,
                    lon: wp.lon,
                    target_speed_kmh: parseFloat(targetSpeed),
                    lookahead_distance: parseFloat(lookaheadDistance),
                    gain: parseFloat(gain)
                })
            });
            const data = await res.json();
            status = data.status || "Onderweg (Vloeiende Bocht)";
        } catch (e) {
            status = "Fout bij starten";
        }
    }

    // --- Start de volledige route ---
    async function startPurePursuit() {
        if (waypoints.length === 0) {
            status = "Geen waypoints geladen — voeg eerst punten toe";
            return;
        }
        status = "Starten Volledige Route...";
        try {
            const res = await fetch('/api/nav/start_pure_pursuit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_speed_kmh: parseFloat(targetSpeed),
                    lookahead_distance: parseFloat(lookaheadDistance),
                    gain: parseFloat(gain)
                })
            });
            const data = await res.json();
            // Toon de foutmelding van de server (bv. "Geen waypoints geladen")
            status = data.status === "error" ? ("Fout: " + (data.msg || "onbekend")) : (data.status || "Volledige Route Actief");
        } catch (e) {
            status = "Fout bij starten";
        }
    }

    async function stopNav() {
        status = "Stoppen...";
        try {
            const res = await fetch('/api/stop_nav', { method: 'POST' }); 
            const data = await res.json();
            status = data.status || "Gestopt";
        } catch (e) {
            status = "Fout bij stoppen";
        }
    }

    // Pollt live de navigatiestatus zodat zichtbaar is WAAROM de robot (niet) rijdt,
    // bv. "Wachten op RTK-fix" of "Eindbestemming bereikt".
    async function pollStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            if (data.navigator_active || (data.nav_state && data.nav_state !== "IDLE")) {
                status = data.nav_message || data.nav_state || status;
            }
        } catch (e) { /* netwerk-hik: status laten staan */ }
    }

    onMount(() => {
        fetchWaypoints();
        const interval = setInterval(pollStatus, 1000);
        return () => clearInterval(interval);
    });
</script>

<div class="nav-container">
    <h2>Route Navigatie</h2>
    <div class="status-box">Status: <strong>{status}</strong></div>

    <div class="sliders-box">
        <h3>Tuning Parameters</h3>
        <label>Snelheid ({targetSpeed} km/h)
            <input type="range" min="0.5" max="5.0" step="0.1" bind:value={targetSpeed} on:change={updateSliders}>
        </label>
        
        <label>Lookahead Afstand ({lookaheadDistance} m) <i>(Alleen Pure Pursuit)</i>
            <input type="range" min="0.5" max="4.0" step="0.1" bind:value={lookaheadDistance} on:change={updateSliders}>
        </label>

        <label>Strakheid / Gain ({gain})
            <input type="range" min="0.5" max="3.0" step="0.1" bind:value={gain} on:change={updateSliders}>
        </label>
    </div>

    <div class="add-box">
        <input
            class="naam-input"
            type="text"
            placeholder="Naam van het punt (optioneel)"
            bind:value={newWaypointName}
            on:keydown={(e) => { if (e.key === 'Enter') addWaypoint(); }} />
        <div class="controls">
            <button class="btn-add" on:click={addWaypoint}>📍 + Waypoint op Huidige Positie</button>
            <button class="btn-clear" on:click={clearWaypoints}>🗑️ Wis Alles</button>
        </div>
    </div>

    <div class="waypoints-list">
        <h3>Route ({waypoints.length} punten)</h3>
        <p class="instructie">Klik op een coördinaat in de lijst om acties te tonen</p>
        
        {#if waypoints.length === 0}
            <p>Geen punten. Loop naar het begin en voeg punten toe.</p>
        {:else}
            <ul>
                {#each waypoints as wp, i}
                    <li class="waypoint-item">
                        <div class="wp-header" 
                             role="button" 
                             tabindex="0" 
                             on:click={() => selectedWp = (selectedWp === i ? null : i)}
                             on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectedWp = (selectedWp === i ? null : i) }}>
                            <strong>{wp.way_point_name || `WP ${i}`}</strong>: {wp.lat.toFixed(6)}, {wp.lon.toFixed(6)}
                            <span class="pijl">{selectedWp === i ? '▲' : '▼'}</span>
                        </div>
                        
                        {#if selectedWp === i}
                            <div class="wp-actions">
                                <button class="btn-start-alt" on:click={() => startDirectSpecific(wp)}>🎯 Rechte Lijn (Direct)</button>
                                <button class="btn-start-bocht" on:click={() => startPurePursuitSpecific(wp)}>🌊 Vloeiend (Pure Pursuit)</button>
                            </div>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}
    </div>

    <div class="controls start-controls">
        <button class="btn-start" on:click={startPurePursuit}>🚀 Start Hele Route (Lijn Volgen)</button>
        <button class="btn-stop" on:click={stopNav}>🛑 STOP (Noodrem)</button>
    </div>
</div>

<style>
    .nav-container { background: #f4f4f9; padding: 20px; border-radius: 8px; text-align: center; }
    .status-box { background: #333; color: #fff; padding: 10px; border-radius: 4px; margin-bottom: 20px; }
    
    .sliders-box { background: #fff; padding: 15px; border-radius: 8px; border: 1px solid #ddd; margin-bottom: 20px; text-align: left; }
    .sliders-box label { display: block; margin-bottom: 15px; font-weight: bold; }
    .sliders-box input[type="range"] { width: 100%; margin-top: 5px; accent-color: #4CAF50; cursor: pointer; height: 30px;}
    
    .instructie { font-size: 13px; color: #666; margin-top: -10px; margin-bottom: 15px;}
    .waypoints-list { margin: 20px 0; text-align: left; background: #fff; padding: 15px; border-radius: 4px; border: 1px solid #ddd; }
    .waypoints-list ul { list-style-type: none; padding: 0; margin: 0; }
    
    .waypoint-item { border-bottom: 1px solid #eee; padding: 5px 0; }
    .wp-header { 
        padding: 12px; cursor: pointer; display: flex; justify-content: space-between; 
        background: #f9f9f9; border-radius: 4px; transition: background 0.2s; font-size: 15px;
    }
    .wp-header:hover { background: #e9e9e9; }
    .pijl { font-size: 12px; color: #888;}
    
    .wp-actions { padding: 10px; background: #f0f8ff; display: flex; gap: 10px; justify-content: center; border-radius: 0 0 4px 4px; border-top: 1px solid #ddd; }

    .add-box { margin-top: 15px; }
    .naam-input { width: 100%; box-sizing: border-box; padding: 12px; font-size: 15px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px; }
    .controls { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin-top: 15px; }
    .start-controls { margin-top: 30px; }
    
    button { padding: 12px 20px; font-size: 14px; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; color: white; flex: 1; }
    .btn-add { background: #007bff; flex: none;}
    .btn-clear { background: #6c757d; flex: none;}
    
    .btn-start { background: #28a745; padding: 15px; font-size: 16px; flex: none; width: 100%;}
    .btn-start-alt { background: #17a2b8; }
    .btn-start-bocht { background: #6f42c1; } /* Mooie paarse kleur voor Pure Pursuit variant */
    
    .btn-stop { background: #dc3545; width: 100%; flex: none; padding: 20px; font-size: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);}
    
    button:active { filter: brightness(80%); transform: translateY(2px);}
</style>