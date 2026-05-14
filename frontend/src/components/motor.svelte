<script>
    import { onMount, onDestroy } from 'svelte';

    // --- STATE VARIABELEN ---
    let isGekoppeld = true; // Standaard op gekoppeld (net als in V5)
    
    // Gekoppelde waarden
    let gas = 700;      // 700 - 3100
    let stuur = 0;      // -100 - 100

    // Individuele DAC waarden
    let links = 700;
    let rechts = 700;

    // --- REKENFUNCTIES ---
    // Bereken het voltage voor weergave (zoals in DAC_test_versie_V5.py)
    $: voltLinks = (0.77 + ((links - 700) * (3.4 - 0.77) / (3100 - 700))).toFixed(2);
    $: voltRechts = (0.77 + ((rechts - 700) * (3.4 - 0.77) / (3100 - 700))).toFixed(2);

    // De mix-logica (Gas + Sturen -> Links & Rechts)
    function updateGekoppeld() {
        if (!isGekoppeld) return;

        let actief_gas = gas - 700;
        
        if (stuur < 0) { // Naar links
            let factor = 1.0 - (Math.abs(stuur) / 100.0);
            links = 700 + Math.round(actief_gas * factor);
            rechts = gas;
        } else if (stuur > 0) { // Naar rechts
            let factor = 1.0 - (stuur / 100.0);
            links = gas;
            rechts = 700 + Math.round(actief_gas * factor);
        } else { // Rechtdoor
            links = gas;
            rechts = gas;
        }
        
        stuurMotor();
    }

    // --- API COMMUNICATIE ---
    async function stuurMotor() {
        await fetch('/api/motor', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ links: parseInt(links), rechts: parseInt(rechts) })
        });
    }

    async function noodStop() {
        gas = 700;
        stuur = 0;
        links = 700;
        rechts = 700;
        await fetch('/api/stop', { method: 'POST' });
    }

    // --- TOETSENBORD LOGICA ---
    function handleKeydown(event) {
        // Voorkom dat het hele scherm scrollt als we pijltjes/spatie gebruiken
        if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ', 'Enter'].includes(event.key)) {
            event.preventDefault(); 
        }

        // Enter is ALTIJD Noodstop
        if (event.key === 'Enter') {
            noodStop();
            return;
        }

        // Overige toetsen werken alleen in gekoppelde modus
        if (!isGekoppeld) return;

        switch(event.key) {
            case 'ArrowUp':
                gas = Math.min(3100, gas + 50);
                updateGekoppeld();
                break;
            case 'ArrowDown':
                gas = Math.max(700, gas - 50);
                updateGekoppeld();
                break;
            case 'ArrowLeft':
                stuur = Math.max(-100, stuur - 10);
                updateGekoppeld();
                break;
            case 'ArrowRight':
                stuur = Math.min(100, stuur + 10);
                updateGekoppeld();
                break;
            case ' ': // Spatie = Stuur centreren
                stuur = 0;
                updateGekoppeld();
                break;
        }
    }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="motor-dashboard">
    <h2>Besturing (Muis & Toetsenbord)</h2>
    
    <button class="noodstop" on:click={noodStop}>
        🔴 NOODSTOP / Alles naar 0 (Druk op ENTER)
    </button>

    <div class="schakelaar-container">
        <label class="switch">
            <input type="checkbox" bind:checked={isGekoppeld} on:change={() => { if(isGekoppeld) updateGekoppeld(); }}>
            <span class="slider round"></span>
        </label>
        <span class="modus-text">
            {isGekoppeld ? "🟢 Gekoppelde Besturing (Gas/Stuur + Pijltjestoetsen)" : "⚪ Handmatige Besturing (Wielen apart)"}
        </span>
    </div>

    <hr>

    <div class="pane {isGekoppeld ? 'active-pane' : 'disabled-pane'}">
        <h3>Hoofdgas (Pijltje Omhoog / Omlaag)</h3>
        <input type="range" min="700" max="3100" class="gas-slider"
               bind:value={gas} on:input={updateGekoppeld} disabled={!isGekoppeld}>
        
        <h3>Sturen (Pijltjes L/R) - Spatie is Rechtdoor</h3>
        <input type="range" min="-100" max="100" class="stuur-slider"
               bind:value={stuur} on:input={updateGekoppeld} disabled={!isGekoppeld}>
    </div>

    <hr>

    <div class="pane {!isGekoppeld ? 'active-pane' : 'disabled-pane'}">
        <h3>Linker Wiel</h3>
        <p>DAC: <strong>{links}</strong> | Voltage: <strong>~{voltLinks}V</strong></p>
        <input type="range" min="700" max="3100" 
               bind:value={links} on:input={stuurMotor} disabled={isGekoppeld}>

        <h3>Rechter Wiel</h3>
        <p>DAC: <strong>{rechts}</strong> | Voltage: <strong>~{voltRechts}V</strong></p>
        <input type="range" min="700" max="3100" 
               bind:value={rechts} on:input={stuurMotor} disabled={isGekoppeld}>
    </div>
</div>

<style>
    .motor-dashboard { background: #1e1e1e; color: white; padding: 20px; border-radius: 8px; }
    
    .noodstop { 
        background: #d32f2f; color: white; padding: 20px; width: 100%; 
        font-size: 1.2em; font-weight: bold; border: none; border-radius: 5px; 
        cursor: pointer; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .noodstop:active { background: #b71c1c; transform: translateY(2px); }

    .pane { padding: 15px; border-radius: 5px; background: #2a2a2a; margin-bottom: 15px; transition: opacity 0.3s; }
    .active-pane { border: 2px solid #4CAF50; opacity: 1; }
    .disabled-pane { opacity: 0.4; pointer-events: none; }

    input[type=range] { width: 100%; height: 35px; margin-bottom: 15px; cursor: pointer;}
    .gas-slider { accent-color: #4CAF50; }
    .stuur-slider { accent-color: #ff9800; }

    /* Custom Switch CSS */
    .schakelaar-container { display: flex; align-items: center; gap: 15px; margin-bottom: 15px; font-weight: bold;}
    .switch { position: relative; display: inline-block; width: 60px; height: 34px; }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; }
    .slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; }
    input:checked + .slider { background-color: #4CAF50; }
    input:checked + .slider:before { transform: translateX(26px); }
    .slider.round { border-radius: 34px; }
    .slider.round:before { border-radius: 50%; }
</style>