<script>
    let modus = "HANDMATIG";
    
    async function wisselModus(nieuweModus) {
        modus = nieuweModus;
        
        if (modus === "AUTONOOM") {
            await fetch('/api/start_nav', { method: 'POST' });
        } else {
            await fetch('/api/stop_nav', { method: 'POST' });
        }
    }

    async function noodIngreep() {
        if (modus === "AUTONOOM") {
            modus = "HANDMATIG";
            await fetch('/api/stop', { method: 'POST' });
        }
    }
</script>

<div class="cockpit-layout">
    <div class="video-pane">
        <img src="/api/video_feed" alt="Live Camera">
    </div>

    <div class="control-pane">
        <h2>Huidige Modus: {modus}</h2>
        
        <div class="modus-knoppen">
            <button class:active={modus === "HANDMATIG"} on:click={() => wisselModus("HANDMATIG")}>
                Handmatig (RC)
            </button>
            <button class:active={modus === "AUTONOOM"} on:click={() => wisselModus("AUTONOOM")}>
                Start RTK Route
            </button>
        </div>

        {#if modus === "AUTONOOM"}
            <div class="rtk-status">
                <p>Navigeren naar Waypoints...</p>
                <button class="noodstop" on:click={noodIngreep}>🚨 NEEM BESTURING OVER</button>
            </div>
        {:else}
            <div class="manual-status">
                <p>Klaar voor toetsenbord/muis invoer.</p>
            </div>
        {/if}
    </div>
</div>