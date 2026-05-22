<script>
    let links = 700;
    let rechts = 700;
    let lockPosition = false;
    let besturingsModus = 'sliders'; // Kan 'sliders' of 'joystick' zijn

    // Joystick variabelen
    let joystickBase;
    let joyX = 0; 
    let joyY = 0; 
    let isDragging = false;
    
    // NOG GROTER: Maximale uitslag vergroot naar 130 pixels
    const maxRadius = 130; 

    // --- COMMUNICATIE ---
    async function stuurCommand() {
        try {
            await fetch('/api/skidsteer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ links, rechts })
            });
        } catch (error) {
            console.error("Fout bij sturen skidsteer:", error);
        }
    }

    // --- ALGEMENE CONTROLES ---
    function toggleModus() {
        besturingsModus = besturingsModus === 'sliders' ? 'joystick' : 'sliders';
        forceerStop();
    }

    function forceerStop() {
        lockPosition = false;
        links = 700;
        rechts = 700;
        
        joyX = 0;
        joyY = 0;
        
        stuurCommand();
    }

    function releaseStop() {
        if (lockPosition) return;
        forceerStop();
    }

    // --- SLIDER LOGICA ---
    function handleSliderInput() {
        stuurCommand();
    }

    // --- JOYSTICK LOGICA ---
    function startJoystick(e) {
        if (e.target.hasPointerCapture) e.target.setPointerCapture(e.pointerId);
        isDragging = true;
        berekenJoystick(e);
    }

    function moveJoystick(e) {
        if (!isDragging) return;
        berekenJoystick(e);
    }

    function stopJoystick(e) {
        isDragging = false;
        if (e.target.hasPointerCapture) e.target.releasePointerCapture(e.pointerId);
        
        if (!lockPosition) {
            forceerStop();
        }
    }

    function berekenJoystick(e) {
        if (!joystickBase) return;
        const rect = joystickBase.getBoundingClientRect();
        
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        
        let dx = e.clientX - centerX;
        let dy = e.clientY - centerY;
        
        let distance = Math.sqrt(dx * dx + dy * dy);
        if (distance > maxRadius) {
            dx = (dx / distance) * maxRadius;
            dy = (dy / distance) * maxRadius;
        }
        
        joyX = dx;
        joyY = dy;
        
        let normX = dx / maxRadius;
        let normY = -dy / maxRadius; 
        
        if (normY < 0) {
            links = 700;
            rechts = 700;
        } else {
            let l = normY + normX;
            let r = normY - normX;
            
            l = Math.max(0, Math.min(1, l));
            r = Math.max(0, Math.min(1, r));
            
            links = 700 + Math.round(l * 2400);
            rechts = 700 + Math.round(r * 2400);
        }
        
        stuurCommand();
    }
</script>

<div class="skidsteer-container">
    <div class="header-controls">
        <h2>Handbediening</h2>
        <button class="modus-toggle" on:click={toggleModus}>
            🔄 Gebruik {besturingsModus === 'sliders' ? 'Joystick' : 'Sliders'}
        </button>
    </div>
    
    {#if lockPosition}
        <p class="status-waarschuwing">⚠️ Positie vergrendeld. De robot blijft doorrijden!</p>
    {:else}
        <p>Houd vast om te rijden. Laat los om te stoppen (Dodemansknop actief).</p>
    {/if}

    <div class="lock-option">
        <label for="lock-checkbox" class="checkbox-label">
            <input type="checkbox" id="lock-checkbox" bind:checked={lockPosition}>
            <span>Sliders/Joystick vasthouden bij loslaten (Lock)</span>
        </label>
    </div>

    {#if besturingsModus === 'sliders'}
        <div class="sliders-wrapper">
            <div class="slider-col">
                <label for="slider-links">Links: {links}</label>
                <input type="range" id="slider-links" min="700" max="3100" step="10" 
                       bind:value={links} 
                       on:input={handleSliderInput} 
                       on:touchend={releaseStop}
                       on:mouseup={releaseStop}
                       class="vertical-slider">
            </div>

            <div class="slider-col">
                <label for="slider-rechts">Rechts: {rechts}</label>
                <input type="range" id="slider-rechts" min="700" max="3100" step="10" 
                       bind:value={rechts} 
                       on:input={handleSliderInput} 
                       on:touchend={releaseStop}
                       on:mouseup={releaseStop}
                       class="vertical-slider">
            </div>
        </div>
    {/if}

    {#if besturingsModus === 'joystick'}
        <div class="joystick-wrapper">
            <div class="joystick-info">
                <span>Links: {links}</span>
                <span>Rechts: {rechts}</span>
            </div>
            <div class="joystick-base" bind:this={joystickBase}
                 on:pointerdown={startJoystick}
                 on:pointermove={moveJoystick}
                 on:pointerup={stopJoystick}
                 on:pointercancel={stopJoystick}
                 on:pointerleave={stopJoystick}
                 style="touch-action: none;">
                
                <div class="joystick-puck" 
                     style="transform: translate({joyX}px, {joyY}px)">
                </div>
            </div>
        </div>
    {/if}

    <button class="noodstop" on:click={forceerStop}>STOP / RESET</button>
</div>

<style>
    .skidsteer-container {
        text-align: center;
        user-select: none;
    }

    .header-controls {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
    }

    .modus-toggle {
        background-color: #2196F3;
        color: white;
        border: none;
        padding: 10px 20px;
        border-radius: 6px;
        font-weight: bold;
        cursor: pointer;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    .status-waarschuwing {
        color: #ff9800;
        font-weight: bold;
    }

    .lock-option {
        margin: 10px 0;
        padding: 10px;
        background-color: #eee;
        border-radius: 6px;
        display: inline-block;
    }

    .checkbox-label {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        font-size: 14px;
        font-weight: bold;
    }

    .sliders-wrapper {
        display: flex;
        justify-content: space-around;
        align-items: center;
        height: 300px;
        margin: 20px 0;
    }

    .slider-col {
        display: flex;
        flex-direction: column;
        align-items: center;
        height: 100%;
    }

    .slider-col label {
        display: block;
        margin-bottom: 10px;
        font-weight: bold;
    }

    .vertical-slider {
        -webkit-appearance: slider-vertical;
        writing-mode: bt-lr;
        width: 50px;
        height: 220px;
    }

    /* JOYSTICK STYLING */
    .joystick-wrapper {
        display: flex;
        flex-direction: column;
        align-items: center;
        margin: 20px 0;
        /* NOG GROTER: Wrapper hoogte is nu 400px zodat alles past */
        height: 400px; 
    }

    .joystick-info {
        display: flex;
        gap: 20px;
        margin-bottom: 15px;
        font-weight: bold;
    }

    .joystick-base {
        /* NOG GROTER: Basis is nu 280px breed en hoog (was 220px) */
        width: 280px;
        height: 280px;
        background-color: #ddd;
        border-radius: 50%;
        position: relative;
        display: flex;
        justify-content: center;
        align-items: center;
        box-shadow: inset 0 3px 6px rgba(0,0,0,0.2);
        cursor: crosshair;
    }

    .joystick-puck {
        /* NOG GROTER: Puck is nu 100px (was 80px) voor de ultieme duim-grip */
        width: 100px;
        height: 100px;
        background-color: #4CAF50;
        border-radius: 50%;
        position: absolute;
        box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        transition: transform 0.05s ease-out;
    }

    .noodstop {
        background-color: #f44336;
        color: white;
        padding: 15px 30px;
        font-size: 20px;
        border: none;
        border-radius: 8px;
        font-weight: bold;
        width: 100%;
        margin-top: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    
    .noodstop:active {
        background-color: #d32f2f;
    }
</style>