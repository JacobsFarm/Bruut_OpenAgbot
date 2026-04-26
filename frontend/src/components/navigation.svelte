<script>
    import { onMount } from 'svelte';

    let waypoints = [];
    let currentLat = 0;
    let currentLon = 0;

    onMount(() => {
        fetchWaypoints();
        const interval = setInterval(async () => {
            const res = await fetch('/api/status');
            const data = await res.json();
            currentLat = data.lat;
            currentLon = data.lon;
        }, 1000);
        return () => clearInterval(interval);
    });

    async function fetchWaypoints() {
        const res = await fetch('/api/waypoints');
        waypoints = await res.json();
    }

    async function addCurrentLocation() {
        await fetch('/api/waypoints', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat: currentLat, lon: currentLon })
        });
        fetchWaypoints();
    }

    async function clearWaypoints() {
        if(confirm("Weet je zeker dat je de route wilt wissen?")) {
            await fetch('/api/waypoints', { method: 'DELETE' });
            fetchWaypoints();
        }
    }
</script>

<div>
    <h2>Waypoints</h2>
    
    <div class="actions">
        <button class="add" on:click={addCurrentLocation}>📍 Huidige locatie opslaan als Waypoint</button>
        <button class="clear" on:click={clearWaypoints}>🗑️ Wis alle waypoints</button>
    </div>

    <h3>Opgeslagen Route ({waypoints.length} punten)</h3>
    <ol class="wp-list">
        {#each waypoints as wp}
            <li>Lat: {wp.lat.toFixed(7)} | Lon: {wp.lon.toFixed(7)}</li>
        {/each}
        {#if waypoints.length === 0}
            <p>Geen waypoints opgeslagen.</p>
        {/if}
    </ol>
</div>

<style>
    .actions { display: flex; gap: 10px; margin-bottom: 20px; }
    button { padding: 10px; border: none; border-radius: 4px; cursor: pointer; color: white; font-weight: bold;}
    .add { background: #2196F3; flex: 1; }
    .clear { background: #ff9800; }
    .wp-list li { background: white; padding: 10px; margin-bottom: 5px; border: 1px solid #ddd; }
</style>