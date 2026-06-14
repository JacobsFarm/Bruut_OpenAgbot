<script>
    let stuurVast = true;
    let stuurStatus = "Vast (Enabled)";
    let stuurPercentage = 0.0;
    let snelheid = 0.0;

    async function stuurCommando() {
        try {
            await fetch('/api/nav/manual_drive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed_kmh: snelheid, steering_percentage: stuurPercentage })
            });
        } catch(e) {}
    }

    async function toggleStuur() {
        stuurVast = !stuurVast;
        try {
            await fetch('/api/steering/enable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enable: stuurVast })
            });
            stuurStatus = stuurVast ? "Vast (Enabled)" : "VRIJ (Kan met de hand draaien)";
        } catch(e) {}
    }

    async function setZeroPoint() {
        if (!confirm("Weet je zeker dat het wiel nu EXACT recht staat? Dit wordt het nieuwe nulpunt.")) return;
        try {
            await fetch('/api/steering/zero', { method: 'POST' });
            stuurPercentage = 0.0;
            stuurCommando();
        } catch(e) {}
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
        <h3>Stuurmotor Kalibratie</h3>
        <p>Status: {stuurStatus}</p>
        <div class="btn-group">
            <button class="btn-toggle" on:click={toggleStuur}>
                {stuurVast ? "Zet in Vrijloop" : "Zet Vast"}
            </button>
            <button class="btn-zero" on:click={setZeroPoint}>Zet Nulpunt (0°)</button>
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
                Stuur (RC Uitslag): {stuurPercentage > 0 ? 'Rechts' : stuurPercentage < 0 ? 'Links' : 'Rechtuit'} {Math.abs(stuurPercentage).toFixed(0)}%
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
    .btn-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
    .btn-toggle { background: #ff9800; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; cursor: pointer; }
    .btn-zero { background: #03a9f4; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; cursor: pointer; }
    
    .slider-box { background: #2a2a2a; color: white; padding: 15px; border-radius: 8px; text-align: center; }
    .slider-container { margin-bottom: 30px; background: #333; padding: 15px; border-radius: 8px; }
    label { display: block; margin-bottom: 15px; font-size: 1.2em; font-weight: bold; }
    input[type="range"] { width: 100%; height: 40px; cursor: pointer; }
    .center-btn { background: #607d8b; color: white; width: 100%; margin-top: 15px; padding: 15px; font-size: 1.1em; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; }
</style>