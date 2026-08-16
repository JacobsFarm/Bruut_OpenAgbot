<script>
    import { onMount, onDestroy } from 'svelte';

    let snelheid = 0.0;
    let draaien = 0.0;          // -100% = linksom, +100% = rechtsom
    let statusTekst = "Stilstand";

    // Live terugkoppeling van de aandrijving
    let dacLinks = 700;
    let dacRechts = 700;
    let snelheidLinks = 0.0;
    let snelheidRechts = 0.0;

    let hartslag = null;
    let statusPoll = null;

    async function stuurCommando() {
        try {
            const res = await fetch('/api/nav/manual_drive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed_kmh: snelheid, turn_percentage: draaien })
            });
            const data = await res.json();
            verwerkStatus(data);
        } catch(e) {}
    }

    async function pivot(richting) {
        snelheid = 0.0;
        draaien = richting;
        try {
            const res = await fetch('/api/nav/pivot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ turn_percentage: richting })
            });
            const data = await res.json();
            verwerkStatus(data);
        } catch(e) {}
    }

    function verwerkStatus(data) {
        if (!data) return;
        if (data.dac_links !== undefined) dacLinks = data.dac_links;
        if (data.dac_rechts !== undefined) dacRechts = data.dac_rechts;
        if (data.speed_links_mps !== undefined) snelheidLinks = data.speed_links_mps;
        if (data.speed_rechts_mps !== undefined) snelheidRechts = data.speed_rechts_mps;

        if (data.watchdog) {
            statusTekst = "GESTOPT: geen commando ontvangen (watchdog)";
        } else if (snelheidLinks <= 0 && snelheidRechts <= 0) {
            statusTekst = "Stilstand";
        } else if (snelheidLinks <= 0 || snelheidRechts <= 0) {
            statusTekst = "Pivot om stilstaand wiel";
        } else {
            statusTekst = Math.abs(snelheidLinks - snelheidRechts) < 0.02
                ? "Rechtuit" : (snelheidLinks > snelheidRechts ? "Bocht naar rechts" : "Bocht naar links");
        }
    }

    async function noodstop() {
        snelheid = 0.0;
        draaien = 0.0;
        try {
            await fetch('/api/stop', { method: 'POST' });
            statusTekst = "NOODSTOP";
        } catch(e) {}
    }

    // De backend heeft een watchdog: blijft er langer dan command_timeout_sec
    // een commando uit, dan stopt de robot uit zichzelf. Zolang we willen
    // rijden sturen we daarom een hartslag, zodat een vastgelopen browser of
    // weggevallen wifi de robot niet door laat rijden.
    onMount(() => {
        hartslag = setInterval(() => {
            if (snelheid !== 0 || draaien !== 0) stuurCommando();
        }, 500);

        statusPoll = setInterval(async () => {
            try {
                const res = await fetch('/api/status');
                verwerkStatus(await res.json());
            } catch(e) {}
        }, 1000);
    });

    onDestroy(() => {
        if (hartslag) clearInterval(hartslag);
        if (statusPoll) clearInterval(statusPoll);
    });
</script>

<div class="motor-container">
    <button class="noodstop" on:click={noodstop}>NOODSTOP / STOP</button>

    <div class="status-box">
        <h3>Aandrijving (Skid Steer)</h3>
        <p class="status-tekst">{statusTekst}</p>
        <div class="wielen">
            <div class="wiel">
                <span class="wiel-titel">LINKS</span>
                <span class="wiel-waarde">{snelheidLinks.toFixed(2)} m/s</span>
                <span class="wiel-dac">DAC {dacLinks}</span>
            </div>
            <div class="wiel">
                <span class="wiel-titel">RECHTS</span>
                <span class="wiel-waarde">{snelheidRechts.toFixed(2)} m/s</span>
                <span class="wiel-dac">DAC {dacRechts}</span>
            </div>
        </div>
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
                Draaien: {draaien > 0 ? 'Rechts' : draaien < 0 ? 'Links' : 'Rechtuit'} {Math.abs(draaien).toFixed(0)}%
                <input type="range" min="-100" max="100" step="1" bind:value={draaien} on:input={stuurCommando}>
            </label>
            <button class="center-btn" on:click={() => { draaien = 0; stuurCommando(); }}>Zet Rechtuit</button>
        </div>

        <div class="pivot-box">
            <p class="hint">
                Draaien op de plek: het binnenwiel staat stil en de robot draait
                daaromheen. Achteruit kan deze aandrijving niet, dus hij schuift
                daarbij een klein stukje vooruit.
            </p>
            <div class="btn-group">
                <button class="btn-pivot" on:click={() => pivot(-60)}>&#8634; Draai Linksom</button>
                <button class="btn-pivot" on:click={() => pivot(60)}>Draai Rechtsom &#8635;</button>
            </div>
        </div>
    </div>
</div>

<style>
    .motor-container { padding: 15px; font-family: sans-serif; }
    .noodstop { background: #d32f2f; color: white; padding: 20px; width: 100%; font-size: 24px; font-weight: bold; border: none; border-radius: 8px; margin-bottom: 20px; cursor: pointer; }
    .noodstop:active { background: #b71c1c; transform: translateY(2px); }

    .status-box { background: #2a2a2a; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    .status-box h3 { margin: 0 0 10px 0; }
    .status-tekst { margin: 0 0 15px 0; font-size: 1.1em; color: #8bc34a; font-weight: bold; }
    .wielen { display: flex; gap: 15px; }
    .wiel { flex: 1; background: #333; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 4px; text-align: center; }
    .wiel-titel { font-size: 0.8em; color: #999; letter-spacing: 1px; }
    .wiel-waarde { font-size: 1.4em; font-weight: bold; }
    .wiel-dac { font-size: 0.85em; color: #999; }

    .slider-box { background: #2a2a2a; color: white; padding: 15px; border-radius: 8px; text-align: center; }
    .slider-container { margin-bottom: 30px; background: #333; padding: 15px; border-radius: 8px; }
    label { display: block; margin-bottom: 15px; font-size: 1.2em; font-weight: bold; }
    input[type="range"] { width: 100%; height: 40px; cursor: pointer; }
    .center-btn { background: #607d8b; color: white; width: 100%; margin-top: 15px; padding: 15px; font-size: 1.1em; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; }

    .pivot-box { background: #333; padding: 15px; border-radius: 8px; }
    .hint { font-size: 13px; color: #aaa; margin: 0 0 12px 0; text-align: left; }
    .btn-group { display: flex; gap: 10px; }
    .btn-pivot { flex: 1; background: #ff9800; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.05em; cursor: pointer; }
</style>
