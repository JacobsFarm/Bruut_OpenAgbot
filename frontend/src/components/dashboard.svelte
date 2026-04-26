<script>
    import { onMount } from 'svelte';

    let status = { lat: 0, lon: 0, fix: 0, hdop: 99.0 };

    onMount(() => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch('/api/status');
                status = await res.json();
            } catch (err) {
                console.error("Kan GPS niet laden", err);
            }
        }, 1000);
        return () => clearInterval(interval);
    });

    function getFixText(fix) {
        if (fix === 4) return "RTK Fixed (Groen)";
        if (fix === 5) return "RTK Float (Oranje)";
        if (fix === 1 || fix === 2) return "Standaard GPS";
        return "Geen Fix";
    }
</script>

<div>
    <h2>Systeem Status</h2>
    <div class="card">
        <h3>GPS Informatie</h3>
        <p><strong>Latitude:</strong> {status.lat.toFixed(8)}</p>
        <p><strong>Longitude:</strong> {status.lon.toFixed(8)}</p>
        <p><strong>Kwaliteit (Fix):</strong> {getFixText(status.fix)}</p>
        <p><strong>HDOP:</strong> {status.hdop}</p>
    </div>
</div>

<style>
    .card { background: white; padding: 15px; border-radius: 5px; border: 1px solid #ccc; }
</style>