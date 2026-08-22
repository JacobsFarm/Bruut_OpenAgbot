<script>
    import { onMount, onDestroy } from 'svelte';

    let linksVast = true;
    let rechtsVast = true;
    let stuurPercentage = 0.0;
    let snelheid = 0.0;

    // Live uitgelezen stand van de twee voorwielen
    let hoekLinks = null;
    let hoekRechts = null;
    let maxMiddenHoek = null;
    let verbonden = false;

    let statusTimer;

    // De schuif loopt van -100% tot +100% van de maximale MIDDENHOEK. De
    // wielen zelf staan daar in een Ackermann-verhouding omheen, dus het
    // binnenwiel komt hoger uit dan dit getal.
    $: middenHoek = maxMiddenHoek === null ? null : (stuurPercentage / 100.0) * maxMiddenHoek;
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
        } catch(e) {
            verbonden = false;
        }
    }

    onMount(() => {
        haalStatus();
        statusTimer = setInterval(haalStatus, 2000);
    });

    onDestroy(() => clearInterval(statusTimer));

    async function stuurCommando() {
        try {
            await fetch('/api/nav/manual_drive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed_kmh: snelheid, steering_percentage: stuurPercentage })
            });
        } catch(e) {}
    }

    async function zetVast(wheel, vast) {
        try {
            await fetch('/api/steering/enable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enable: vast, wheel: wheel })
            });
        } catch(e) {}
        haalStatus();
    }

    async function jog(wheel, delta) {
        try {
            await fetch('/api/steering/jog', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    left_delta:  wheel === 'right' ? 0 : delta,
                    right_delta: wheel === 'left'  ? 0 : delta
                })
            });
        } catch(e) {}
        haalStatus();
    }

    async function setZeroPoint(wheel) {
        const wat = wheel === 'left' ? "het LINKER voorwiel"
                  : wheel === 'right' ? "het RECHTER voorwiel"
                  : "BEIDE voorwielen";
        if (!confirm(`Weet je zeker dat ${wat} nu EXACT recht staat? Dit wordt het nieuwe nulpunt.`)) return;
        try {
            await fetch('/api/steering/zero', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ wheel: wheel })
            });
            stuurPercentage = 0.0;
            stuurCommando();
        } catch(e) {}
        haalStatus();
    }

    async function noodstop() {
        snelheid = 0.0;
        stuurPercentage = 0.0;
        try {
            await fetch('/api/stop', { method: 'POST' });
        } catch(e) {}
    }
</script>

<div class="motor-container">
    <button class="noodstop" on:click={noodstop}>NOODSTOP / STOP</button>

    <div class="kalibratie-box">
        <h3>Stuurmotoren Kalibratie</h3>

        {#if verbonden}
            <div class="stand">
                <span>Links <b>{hoekLinks.toFixed(2)}°</b></span>
                <span>Rechts <b>{hoekRechts.toFixed(2)}°</b></span>
            </div>
            {#if Math.abs(scheefstand) > 0.5}
                <p class="waarschuwing">
                    Wielen staan {Math.abs(scheefstand).toFixed(2)}° uit elkaar. Kalibreer ze
                    apart: zo blijft er spanning op de vooras staan.
                </p>
            {/if}
        {:else}
            <p class="waarschuwing">Geen verbinding met de stuur-Arduino.</p>
        {/if}

        <div class="wiel-rij">
            <span class="wiel-naam">Links</span>
            <button class="btn-toggle" class:is-vrij={!linksVast} on:click={() => zetVast('left', !linksVast)}>
                {linksVast ? "Zet Vrij" : "Zet Vast"}
            </button>
            <button class="btn-jog" on:click={() => jog('left', -1.0)}>-1°</button>
            <button class="btn-jog" on:click={() => jog('left', -0.1)}>-0.1°</button>
            <button class="btn-jog" on:click={() => jog('left', 0.1)}>+0.1°</button>
            <button class="btn-jog" on:click={() => jog('left', 1.0)}>+1°</button>
            <button class="btn-zero" on:click={() => setZeroPoint('left')}>Nulpunt</button>
        </div>

        <div class="wiel-rij">
            <span class="wiel-naam">Rechts</span>
            <button class="btn-toggle" class:is-vrij={!rechtsVast} on:click={() => zetVast('right', !rechtsVast)}>
                {rechtsVast ? "Zet Vrij" : "Zet Vast"}
            </button>
            <button class="btn-jog" on:click={() => jog('right', -1.0)}>-1°</button>
            <button class="btn-jog" on:click={() => jog('right', -0.1)}>-0.1°</button>
            <button class="btn-jog" on:click={() => jog('right', 0.1)}>+0.1°</button>
            <button class="btn-jog" on:click={() => jog('right', 1.0)}>+1°</button>
            <button class="btn-zero" on:click={() => setZeroPoint('right')}>Nulpunt</button>
        </div>

        <div class="btn-group">
            <button class="btn-toggle" on:click={() => zetVast(null, !(linksVast && rechtsVast))}>
                {linksVast && rechtsVast ? "Beide in Vrijloop" : "Beide Vastzetten"}
            </button>
            <button class="btn-zero" on:click={() => setZeroPoint(null)}>Zet Nulpunt Beide (0°)</button>
        </div>

        <p class="hint">
            De fijnafstelling (±0.1°) werkt alleen op een wiel dat vastgezet is.
            Zet een wiel op "Vrij" om het met de hand te draaien.
        </p>
    </div>

    <div class="slider-box">
        <div class="slider-container">
            <label>
                Snelheid: {snelheid.toFixed(1)} km/h
                <input type="range" min="0" max="7" step="0.1" bind:value={snelheid} on:input={stuurCommando}>
            </label>
        </div>

        <div class="slider-container">
            <label>
                Stuur (RC Uitslag): {stuurPercentage > 0 ? 'Rechts' : stuurPercentage < 0 ? 'Links' : 'Rechtuit'} {Math.abs(stuurPercentage).toFixed(0)}%
                {#if middenHoek !== null}
                    <span class="subtiel">({middenHoek.toFixed(1)}° middenhoek)</span>
                {/if}
                <input type="range" min="-100" max="100" step="1" bind:value={stuurPercentage} on:input={stuurCommando}>
            </label>
            <button class="center-btn" on:click={() => { stuurPercentage = 0; stuurCommando(); }}>Zet Stuur Recht</button>
        </div>
    </div>
</div>

<style>
    .motor-container { padding: 15px; font-family: sans-serif; }
    .noodstop { background: #d32f2f; color: white; padding: 20px; width: 100%; font-size: 24px; font-weight: bold; border: none; border-radius: 8px; margin-bottom: 20px; cursor: pointer; }
    .noodstop:active { background: #b71c1c; transform: translateY(2px); }

    .kalibratie-box { background: #2a2a2a; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    .stand { display: flex; justify-content: space-around; background: #333; padding: 12px; border-radius: 4px; margin-bottom: 10px; font-size: 1.2em; }
    .stand b { font-family: monospace; font-size: 1.1em; }
    .waarschuwing { background: #5d4037; color: #ffcc80; padding: 10px; border-radius: 4px; margin: 10px 0; }
    .hint { color: #9e9e9e; font-size: 0.9em; margin-top: 12px; }
    .subtiel { color: #9e9e9e; font-weight: normal; font-size: 0.85em; }

    .wiel-rij { display: flex; align-items: center; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
    .wiel-naam { width: 60px; font-weight: bold; font-size: 1.1em; }

    .btn-group { display: flex; flex-direction: column; gap: 10px; margin-top: 15px; }
    .btn-toggle { background: #ff9800; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; cursor: pointer; }
    .btn-zero { background: #03a9f4; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; cursor: pointer; }
    .btn-jog { background: #455a64; color: white; padding: 15px 10px; border: none; border-radius: 4px; font-weight: bold; font-size: 1em; cursor: pointer; flex: 1; min-width: 55px; }
    /* Een vrijgezet wiel kan met de hand draaien: duidelijk anders kleuren. */
    .btn-toggle.is-vrij { background: #7b1fa2; }
    .wiel-rij .btn-toggle, .wiel-rij .btn-zero { padding: 15px 12px; flex: 1; min-width: 70px; }

    .slider-box { background: #2a2a2a; color: white; padding: 15px; border-radius: 8px; text-align: center; }
    .slider-container { margin-bottom: 30px; background: #333; padding: 15px; border-radius: 8px; }
    label { display: block; margin-bottom: 15px; font-size: 1.2em; font-weight: bold; }
    input[type="range"] { width: 100%; height: 40px; cursor: pointer; }
    .center-btn { background: #607d8b; color: white; width: 100%; margin-top: 15px; padding: 15px; font-size: 1.1em; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; }
</style>
