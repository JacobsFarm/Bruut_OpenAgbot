<script>
    import { onMount } from 'svelte';

    // --- KALIBRATIE STATE ---
    let stuurVast = true;
    let stuurStatus = "Vast (Enabled)";

    // --- SLIDER STATE ---
    let stuurRichting = 0.0; // -1.0 (links) tot 1.0 (rechts)
    let snelheid = 0.0;      // 0.0 tot 5.0 km/h

    // --- ANTI-SPAM GEHEUGEN ---
    let vorigeRichting = null;
    let vorigeSnelheid = null;

    let intervalId;

    // --- HARDWARE KALIBRATIE ---
    async function toggleStuur() {
        stuurVast = !stuurVast;
        try {
            await fetch('/api/steering/enable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enable: stuurVast })
            });
            stuurStatus = stuurVast ? "Vast (Enabled)" : "VRIJ (Kan met de hand draaien)";
        } catch(e) { console.error(e); }
    }

    async function setZeroPoint() {
        if (!confirm("Weet je zeker dat het wiel nu EXACT recht staat? Dit wordt het nieuwe nulpunt.")) return;
        try {
            await fetch('/api/steering/zero', { method: 'POST' });
            alert("Nulpunt gekalibreerd!");
        } catch(e) { console.error(e); }
    }

    // --- ZEND LOOP (10Hz) ---
    async function stuurNaarBackend() {
        // ANTI-SPAM: Check of er wel écht iets is veranderd sinds de vorige check!
        if (stuurRichting === vorigeRichting && snelheid === vorigeSnelheid) {
            return; // Zo niet? Doe dan lekker niks en stop met spammen!
        }

        // Sla de nieuwe waarden op in het geheugen
        vorigeRichting = stuurRichting;
        vorigeSnelheid = snelheid;

        try {
            await fetch('/api/nav/joystick', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    x: parseFloat(stuurRichting),
                    y: snelheid > 0 ? 1.0 : 0.0,
                    target_speed_kmh: parseFloat(snelheid)
                })
            });
        } catch(e) { console.error("RC Error", e); }
    }

    async function forceNoodstop() {
        snelheid = 0.0;
        stuurRichting = 0.0;
        await fetch('/api/stop', { method: 'POST' });
        
        // Forceer het opslaan door het geheugen even leeg te gooien
        vorigeSnelheid = null; 
        stuurNaarBackend(); 
    }

    function resetStuur() {
        stuurRichting = 0.0;
    }

    onMount(() => {
        // Start zendloop: checkt 10x per seconde (100ms) OF er iets is veranderd
        intervalId = setInterval(() => {
            stuurNaarBackend();
        }, 100);

        return () => clearInterval(intervalId);
    });
</script>

<div class="motor-pane">
    <button class="noodstop" on:click={forceNoodstop}>🛑 NOODSTOP 🛑</button>

    <div class="kalibratie-box">
        <h3>Stuur Kalibratie (Stappenmotor)</h3>
        <p>Status: <strong>{stuurStatus}</strong></p>
        <div class="btn-group">
            <button class="btn-toggle" on:click={toggleStuur}>
                {stuurVast ? "🔓 Vrijzetten (Handmatig)" : "🔒 Vastzetten (Motor)"}
            </button>
            <button class="btn-zero" on:click={setZeroPoint}>📍 Huidige Positie = 0° (Rechtuit)</button>
        </div>
    </div>

    <div class="slider-box">
        <h3>Handmatige Besturing</h3>

        <div class="slider-container">
            <label class="slider-label" for="snelheid-slider">Snelheid: {snelheid.toFixed(1)} km/h</label>
            <input id="snelheid-slider" type="range" min="0" max="5.0" step="0.1" bind:value={snelheid} class="speed-slider">
        </div>

        <div class="slider-container">
            <label class="slider-label" for="richting-slider">
                Richting: {stuurRichting > 0 ? "Rechts" : stuurRichting < 0 ? "Links" : "Rechtuit"} 
                ({(Math.abs(stuurRichting) * 100).toFixed(0)}%)
            </label>
            <input id="richting-slider" type="range" min="-1.0" max="1.0" step="0.05" bind:value={stuurRichting} class="steer-slider">
            <button class="btn-center" on:click={resetStuur}>⬇️ Zet Stuur Midden</button>
        </div>
    </div>
</div>

<style>
    .motor-pane { padding: 10px; color: #fff; background: #1a1a1a; border-radius: 8px; }

    .noodstop {
        background: #f44336; color: white; padding: 20px; width: 100%;
        font-size: 1.5em; font-weight: bold; border: none; border-radius: 5px;
        cursor: pointer; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .noodstop:active { background: #b71c1c; transform: translateY(2px); }

    .kalibratie-box { background: #2a2a2a; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    .btn-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
    .btn-toggle { background: #ff9800; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; }
    .btn-zero { background: #03a9f4; color: white; padding: 15px; border: none; border-radius: 4px; font-weight: bold; font-size: 1.1em; }

    .slider-box { background: #2a2a2a; padding: 15px; border-radius: 8px; text-align: center; }

    .slider-container { margin-bottom: 30px; background: #333; padding: 15px; border-radius: 8px; }
    .slider-label { display: block; margin-bottom: 15px; font-size: 1.2em; font-weight: bold; }

    /* Extra grote sliders voor gebruik op de telefoon/tablet */
    input[type="range"] {
        width: 100%; height: 45px;
        background: #444;
        border-radius: 20px;
        outline: none;
        cursor: pointer;
        margin-bottom: 15px;
    }

    .speed-slider { accent-color: #4CAF50; }
    .steer-slider { accent-color: #2196F3; }

    .btn-center { 
        background: #555; color: white; padding: 12px; border: none; 
        border-radius: 4px; font-weight: bold; cursor: pointer; 
        width: 100%; font-size: 1.1em; margin-top: 5px;
    }
    .btn-center:active { background: #777; }
</style>