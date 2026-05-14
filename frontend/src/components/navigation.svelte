<script>
    import { onMount } from 'svelte';

    let status = "Gestopt";
    let waypoints = [];
    let baseSpeed = 1500;

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
                body: JSON.stringify({ lat: gpsData.lat, lon: gpsData.lon })
            });
            await fetchWaypoints();
        } catch (e) {
            status = "Fout bij toevoegen";
        }
    }

    async function clearWaypoints() {
        try {
            await fetch('/api/waypoints', { method: 'DELETE' });
            await fetchWaypoints();
        } catch (e) {
            status = "Fout bij wissen";
        }
    }

    async function startNav() {
        try {
            const res = await fetch('/api/start_nav', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ base_pwm: baseSpeed })
            });
            if (res.ok) {
                status = "Navigeren langs alle punten";
            } else {
                status = "Fout: Geen punten?";
            }
        } catch (e) {
            status = "Netwerkfout";
        }
    }

    async function navToPoint(wp) {
        try {
            const res = await fetch('/api/start_nav_direct', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lat: wp.lat, lon: wp.lon, base_pwm: baseSpeed })
            });
            if (res.ok) {
                status = `Navigeren naar specifiek punt`;
            }
        } catch (e) {
            status = "Netwerkfout bij direct navigeren";
        }
    }

    async function stopNav() {
        try {
            const res = await fetch('/api/stop_nav', { method: 'POST' });
            if (res.ok) {
                status = "Gestopt";
            }
        } catch (e) {
            status = "Netwerkfout";
        }
    }

    onMount(fetchWaypoints);
</script>

<div class="navigation-panel">
    <h2>Opgeslagen Punten & Navigatie</h2>
    <p>Huidige Status: <strong>{status}</strong></p>
    
    <div class="slider-container">
        <label for="speed">Basis Snelheid: {baseSpeed}</label>
        <input type="range" id="speed" min="700" max="3100" step="50" bind:value={baseSpeed} />
    </div>

    <div class="controls">
        <button class="btn-add" on:click={addWaypoint}>Huidige GPS Opslaan als Punt</button>
        <button class="btn-clear" on:click={clearWaypoints}>Wis Alle Punten</button>
    </div>

    <div class="waypoints-list">
        <h3>Kies een punt om naartoe te rijden:</h3>
        {#if waypoints.length === 0}
            <p>Je hebt nog geen punten opgeslagen.</p>
        {:else}
            <ul>
                {#each waypoints as wp, index}
                    <li>
                        <span>Punt {index + 1} (Lat: {wp.lat.toFixed(5)}, Lon: {wp.lon.toFixed(5)})</span>
                        <button class="btn-go" on:click={() => navToPoint(wp)}>Rijd Hierheen</button>
                    </li>
                {/each}
            </ul>
        {/if}
    </div>

    <div class="controls">
        <button class="btn-start" on:click={startNav}>Rijd Volledige Route (Alle punten)</button>
        <button class="btn-stop" on:click={stopNav}>Stop / Noodstop</button>
    </div>
</div>

<style>
    .navigation-panel {
        padding: 20px;
        border: 1px solid #ccc;
        border-radius: 8px;
        background: #f9f9f9;
        text-align: center;
        font-family: Arial, sans-serif;
    }
    .slider-container {
        margin: 20px 0;
        background: #fff;
        padding: 15px;
        border-radius: 4px;
        border: 1px solid #ddd;
    }
    .slider-container label {
        display: block;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .slider-container input[type="range"] {
        width: 80%;
        cursor: pointer;
    }
    .waypoints-list {
        margin: 20px 0;
        text-align: left;
        background: #fff;
        padding: 15px;
        border-radius: 4px;
        border: 1px solid #ddd;
    }
    .waypoints-list ul {
        list-style-type: none;
        padding: 0;
        margin: 0;
    }
    .waypoints-list li {
        padding: 10px 0;
        border-bottom: 1px solid #eee;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .waypoints-list li:last-child {
        border-bottom: none;
    }
    .controls {
        margin-top: 15px;
        display: flex;
        gap: 10px;
        justify-content: center;
        flex-wrap: wrap;
    }
    button {
        padding: 10px 20px;
        font-size: 14px;
        font-weight: bold;
        border: none;
        border-radius: 4px;
        cursor: pointer;
    }
    .btn-add {
        background-color: #007bff;
        color: white;
    }
    .btn-clear {
        background-color: #ffc107;
        color: black;
    }
    .btn-go {
        background-color: #17a2b8;
        color: white;
        padding: 8px 16px;
    }
    .btn-start {
        background-color: #28a745;
        color: white;
    }
    .btn-stop {
        background-color: #dc3545;
        color: white;
    }
    button:hover {
        opacity: 0.85;
    }
</style>