<script>
    import { onMount } from 'svelte';

    let weeds = [];

    // Haal elke 2 seconden de nieuwste detecties op
    onMount(() => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch('/api/weeds');
                weeds = await res.json();
            } catch (e) { console.error(e); }
        }, 2000);
        return () => clearInterval(interval);
    });
</script>

<div>
    <h2>Live Vision Stream (Met Trigger Lijn)</h2>
    
    <div class="video-container">
        <img src="/api/video_feed" alt="RTSP YOLO Stream" />
    </div>

    <h3>Recente Detecties ({weeds.length})</h3>
    <ul class="weed-list">
        {#each weeds.slice(0, 5) as weed}
            <li>
                <div class="weed-header">
                    <strong>🌿 {weed.class_name.toUpperCase()}</strong> 
                    <span class="conf">{(weed.confidence * 100).toFixed(0)}% Match</span>
                </div>
                <div class="weed-details">
                    <p>📍 <strong>GPS:</strong> {weed.gps_lat.toFixed(6)}, {weed.gps_lon.toFixed(6)}</p>
                    <p>🎯 <strong>Positie:</strong> Zone {weed.zone} (Offset: {weed.offset_meters > 0 ? '+' : ''}{weed.offset_meters}m)</p>
                    <p>🕒 <strong>Tijd:</strong> {weed.time_readable}</p>
                </div>
            </li>
        {/each}
        {#if weeds.length === 0}
            <p>Nog geen onkruid gedetecteerd...</p>
        {:else if weeds.length > 5}
            <p class="more-text">...en nog {weeds.length - 5} oudere detecties (opgeslagen op schijf).</p>
        {/if}
    </ul>
</div>

<style>
    .video-container img { 
        width: 100%; 
        max-width: 640px; 
        border-radius: 8px; 
        border: 3px solid #333; 
    }
    
    .weed-list { list-style: none; padding: 0; }
    
    .weed-list li { 
        background: white; 
        padding: 12px; 
        margin-bottom: 10px; 
        border-left: 5px solid #4CAF50; /* Groene rand */
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    
    .weed-header {
        display: flex;
        justify-content: space-between;
        font-size: 1.1em;
        margin-bottom: 8px;
        border-bottom: 1px solid #eee;
        padding-bottom: 4px;
    }
    
    .conf {
        background: #e8f5e9;
        color: #2e7d32;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.85em;
        font-weight: bold;
    }
    
    .weed-details p {
        margin: 4px 0;
        font-size: 0.9em;
        color: #555;
    }

    .more-text {
        font-style: italic;
        color: #777;
        margin-top: 10px;
    }
</style>