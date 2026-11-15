<script>
    // Wat je minder vaak nodig hebt: de waypoint-route, de camera, het kalibreren van het stuur
    // en de weergave.
    import Navigation from './navigation.svelte';
    import Camera from './camera.svelte';
    import Kalibratie from './kalibratie.svelte';
    import Icoon from './Icoon.svelte';
    import { thema } from '../lib/telemetry.js';

    const delen = [
        ['route', 'Route', 'route'],
        ['camera', 'Camera', 'camera'],
        ['stuur', 'Stuur', 'sleutel'],
        ['weergave', 'Weergave', 'zon'],
    ];
    let deel = 'route';
    try {
        const bewaard = sessionStorage.getItem('meer');
        if (delen.some((d) => d[0] === bewaard)) deel = bewaard;
    } catch (e) { /* geen opslag */ }
    function kies(naam) {
        deel = naam;
        try { sessionStorage.setItem('meer', naam); } catch (e) { /* geen opslag */ }
    }
</script>

<div class="pagina">
    <div class="kiezer" role="tablist">
        {#each delen as [naam, label, icoon]}
            <button role="tab" aria-selected={deel === naam} class:actief={deel === naam} on:click={() => kies(naam)}>
                <Icoon naam={icoon} maat={20} /><span>{label}</span>
            </button>
        {/each}
    </div>

    {#if deel === 'route'}
        <Navigation />
    {:else if deel === 'camera'}
        <Camera />
    {:else if deel === 'stuur'}
        <Kalibratie />
    {:else}
        <section class="paneel">
            <h3>Weergave</h3>
            <div class="knoppen">
                <button class:primair={$thema === 'licht'} on:click={() => thema.set('licht')}>
                    <Icoon naam="zon" maat={20} /> Licht (in de zon)
                </button>
                <button class:primair={$thema === 'donker'} on:click={() => thema.set('donker')}>
                    <Icoon naam="maan" maat={20} /> Donker (schemer)
                </button>
            </div>
            <p class="klein tip">
                Zet deze pagina op je beginscherm (menu van de browser, "Toevoegen aan startscherm"):
                dan opent hij schermvullend, zonder adresbalk.
            </p>
        </section>
    {/if}
</div>

<style>
    .kiezer {
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
        background: var(--vlak); border: 1px solid var(--lijn); border-radius: var(--straal); padding: 4px;
    }
    .kiezer button {
        flex-direction: column; gap: 2px; min-height: 52px; padding: 6px 2px;
        background: none; border: none; color: var(--inkt2); font-size: 13px;
    }
    .kiezer button.actief { background: var(--accent); color: var(--accent-inkt); }
    .tip { margin-top: 12px; }
</style>
