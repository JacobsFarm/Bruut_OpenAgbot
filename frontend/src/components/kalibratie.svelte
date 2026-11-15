<script>
    // Nulpunt en vast/vrij van de twee stuurmotoren. Elk voorwiel heeft zijn eigen mechanische
    // nulpunt: staan ze niet exact gelijk, dan blijft er spanning op de vooras staan.
    import { onMount, onDestroy } from 'svelte';
    import { postJson, bron } from '../lib/telemetry.js';

    let linksVast = true;
    let rechtsVast = true;
    let hoekLinks = null;
    let hoekRechts = null;
    let maxMiddenHoek = null;
    let verbonden = false;
    let geladen = false;
    let timer;

    $: scheefstand = (hoekLinks === null || hoekRechts === null) ? null : hoekLinks - hoekRechts;

    async function haalStatus() {
        try {
            const res = await fetch('/api/steering/status');
            const data = await res.json();
            maxMiddenHoek = data.max_center_angle_degrees;
            const s = data.steering;
            if (s && s.position && s.enabled) {
                hoekLinks = s.position.left;
                hoekRechts = s.position.right;
                linksVast = s.enabled.left;
                rechtsVast = s.enabled.right;
                verbonden = true;
            } else {
                verbonden = false;
            }
        } catch (e) {
            verbonden = false;
        }
        geladen = true;
    }

    onMount(() => {
        haalStatus();
        timer = setInterval(haalStatus, 1500);
    });
    onDestroy(() => clearInterval(timer));

    async function zetVast(wheel, vast) {
        try { await postJson('/api/steering/enable', { enable: vast, wheel }); } catch (e) { /* status laat het zien */ }
        haalStatus();
    }

    async function jog(wheel, delta) {
        try {
            await postJson('/api/steering/jog', {
                left_delta: wheel === 'right' ? 0 : delta,
                right_delta: wheel === 'left' ? 0 : delta
            });
        } catch (e) { /* status laat het zien */ }
        haalStatus();
    }

    async function setZeroPoint(wheel) {
        const wat = wheel === 'left' ? 'het LINKER voorwiel'
                  : wheel === 'right' ? 'het RECHTER voorwiel'
                  : 'BEIDE voorwielen';
        if (!confirm(`Weet je zeker dat ${wat} nu EXACT recht staat? Dit wordt het nieuwe nulpunt.`)) return;
        try {
            await postJson('/api/steering/zero', { wheel });
            // Stuur op 0 zetten: het doel van de firmware is nu het nieuwe nulpunt.
            await postJson('/api/nav/manual_drive', { speed_kmh: 0, steering_percentage: 0, bron });
        } catch (e) { /* status laat het zien */ }
        haalStatus();
    }

    const wielen = [['left', 'Links'], ['right', 'Rechts']];
</script>

<section class="paneel">
    <h3>Stuurmotoren kalibreren</h3>

    {#if verbonden}
        <div class="stand">
            <div><span>Links</span><b class="num">{hoekLinks.toFixed(2)}°</b></div>
            <div><span>Rechts</span><b class="num">{hoekRechts.toFixed(2)}°</b></div>
        </div>
        {#if Math.abs(scheefstand) > 0.5}
            <div class="melding oranje">
                Wielen staan {Math.abs(scheefstand).toFixed(2)}° uit elkaar. Kalibreer ze apart:
                zo blijft er spanning op de vooras staan.
            </div>
        {/if}
    {:else if geladen}
        <div class="melding rood">Geen verbinding met de stuur-Arduino.</div>
    {/if}

    {#each wielen as [wiel, naam]}
        {@const vast = wiel === 'left' ? linksVast : rechtsVast}
        <div class="wiel">
            <div class="wielkop">
                <b>{naam}</b>
                <span class="chip {vast ? 'groen' : 'oranje'}">{vast ? 'vast' : 'vrij: met de hand te draaien'}</span>
            </div>
            <div class="jog">
                <button on:click={() => jog(wiel, -1.0)} disabled={!vast}>−1°</button>
                <button on:click={() => jog(wiel, -0.1)} disabled={!vast}>−0,1°</button>
                <button on:click={() => jog(wiel, 0.1)} disabled={!vast}>+0,1°</button>
                <button on:click={() => jog(wiel, 1.0)} disabled={!vast}>+1°</button>
            </div>
            <div class="knoppen">
                <button class:oranje={vast} on:click={() => zetVast(wiel, !vast)}>{vast ? 'Zet vrij' : 'Zet vast'}</button>
                <button class="blauw" on:click={() => setZeroPoint(wiel)}>Dit is recht (nulpunt)</button>
            </div>
        </div>
    {/each}

    <div class="knoppen beide">
        <button on:click={() => zetVast(null, !(linksVast && rechtsVast))}>
            {linksVast && rechtsVast ? 'Beide vrij zetten' : 'Beide vastzetten'}
        </button>
        <button class="blauw" on:click={() => setZeroPoint(null)}>Nulpunt beide</button>
    </div>

    <p class="klein">
        Bijstellen (±) werkt alleen op een wiel dat vast staat. Zet een wiel vrij om het met de
        hand te draaien{maxMiddenHoek ? `; de grootste stuurhoek van het midden is ${maxMiddenHoek.toFixed(1)}°` : ''}.
    </p>
</section>

<style>
    .stand { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
    .stand div { background: var(--vlak2); border-radius: var(--straal-klein); padding: 10px; text-align: center; display: flex; flex-direction: column; }
    .stand span { font-size: 12.5px; color: var(--inkt2); }
    .stand b { font-size: 24px; }
    .wiel { border-top: 1px solid var(--lijn); padding: 12px 0; display: flex; flex-direction: column; gap: 8px; }
    .wielkop { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .jog { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
    .jog button { padding: 8px 2px; font-variant-numeric: tabular-nums; }
    .beide { border-top: 1px solid var(--lijn); padding-top: 12px; margin-bottom: 10px; }
    .melding { margin-bottom: 10px; }
</style>
