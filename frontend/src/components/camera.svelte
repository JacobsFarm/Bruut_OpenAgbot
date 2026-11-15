<script>
    // Camerabeeld met de detecties van het model, en de laatst gevonden planten.
    import { onMount } from 'svelte';

    let weeds = [];
    let beeldFout = false;

    onMount(() => {
        const haal = async () => {
            if (document.hidden) return;
            try {
                const res = await fetch('/api/weeds');
                weeds = await res.json();
            } catch (e) { /* volgende keer */ }
        };
        haal();
        const interval = setInterval(haal, 2000);
        return () => clearInterval(interval);
    });
</script>

<section class="paneel beeld">
    <h3>Camera</h3>
    {#if beeldFout}
        <div class="melding oranje">Geen camerabeeld. De camera of het model is niet gestart (zie de log van de robot).</div>
    {:else}
        <img src="/api/video_feed" alt="Live camerabeeld met detecties" on:error={() => (beeldFout = true)} />
    {/if}
</section>

<section class="paneel">
    <h3>Laatste detecties ({weeds.length})</h3>
    {#if !weeds.length}
        <p class="klein">Nog niets gevonden.</p>
    {:else}
        <ul>
            {#each weeds.slice(0, 5) as weed}
                <li>
                    <div class="kop">
                        <b>{weed.class_name}</b>
                        <span class="chip groen">{(weed.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <div class="klein num">
                        {weed.gps_lat.toFixed(6)}, {weed.gps_lon.toFixed(6)} · zone {weed.zone}
                        ({weed.offset_meters > 0 ? '+' : ''}{weed.offset_meters} m) · {weed.time_readable}
                    </div>
                </li>
            {/each}
        </ul>
        {#if weeds.length > 5}
            <p class="klein">…en nog {weeds.length - 5} oudere, opgeslagen op de robot.</p>
        {/if}
    {/if}
</section>

<style>
    .beeld img { display: block; width: 100%; border-radius: var(--straal-klein); background: #000; aspect-ratio: 4 / 3; object-fit: contain; }
    ul { list-style: none; margin: 0; padding: 0; }
    li { border-top: 1px solid var(--lijn); padding: 9px 0; }
    li:first-child { border-top: none; padding-top: 0; }
    .kop { display: flex; justify-content: space-between; align-items: center; gap: 8px; text-transform: capitalize; }
</style>
