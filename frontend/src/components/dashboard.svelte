<script>
    import { onMount } from 'svelte';

    let status = {
        lat: 0, lon: 0, fix: 0, hdop: 99.0, sats: 0,
        heading: 0, heading_bron: "geen", heading_geldig: false,
        positie_hz: 0, heading_hz: 0, checksum_fouten: 0, speed_kmh: 0
    };

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
        <h3>Positie (ZED-X20D)</h3>
        <p><strong>Latitude:</strong> {status.lat.toFixed(8)}</p>
        <p><strong>Longitude:</strong> {status.lon.toFixed(8)}</p>
        <p><strong>Kwaliteit (Fix):</strong> {getFixText(status.fix)}</p>
        <p><strong>HDOP:</strong> {status.hdop} &nbsp; <strong>Satellieten:</strong> {status.sats}</p>
        <p><strong>Snelheid:</strong> {(status.speed_kmh ?? 0).toFixed(2)} km/h</p>
    </div>

    <div class="card">
        <h3>Koers (2 antennes)</h3>
        <p>
            <strong>Richting:</strong> {(status.heading ?? 0).toFixed(2)}&deg;
            <span class="badge" class:goed={status.heading_geldig} class:fout={!status.heading_geldig}>
                {status.heading_bron}
            </span>
        </p>
        <p class="hint">
            Bron <em>THS</em> = ware neus-richting uit de twee antennes, ook bij stilstand.
            <em>VTG</em> = terugval op de rijrichting; die klopt niet tijdens slippen of draaien op de plek.
        </p>
    </div>

    <div class="card">
        <h3>Datastroom</h3>
        <p><strong>Positie:</strong> {status.positie_hz} Hz &nbsp; <strong>Koers:</strong> {status.heading_hz} Hz</p>
        <p><strong>Verminkte NMEA-zinnen:</strong> {status.checksum_fouten}</p>
        <p class="hint">Met de 25 Hz rover-config horen beide rond de 25 Hz te liggen.</p>
    </div>
</div>

<style>
    .card { background: white; padding: 15px; border-radius: 5px; border: 1px solid #ccc; margin-bottom: 15px; }
    .badge { padding: 2px 8px; border-radius: 10px; font-size: 0.85em; font-weight: bold; color: white; }
    .badge.goed { background: #2e7d32; }
    .badge.fout { background: #c62828; }
    .hint { font-size: 13px; color: #666; }
</style>