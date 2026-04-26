<script>
    let modus = "HANDMATIG"; // of "AUTONOOM"
    
    // Functie om de robot te vertellen in welke modus hij zit
    async function wisselModus(nieuweModus) {
        modus = nieuweModus;
        await fetch('/api/set_modus', {
            method: 'POST',
            body: JSON.stringify({ modus: modus })
        });
    }

    // Als je handmatig stuurt (bijv. pijltjestoetsen), breek dan automatisch uit de RTK modus
    function noodIngreep() {
        if (modus === "AUTONOOM") {
            wisselModus("HANDMATIG");
            // Stuur direct stop-commando naar motor
            fetch('/api/stop', { method: 'POST' });
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
                <p>Navigeren naar Waypoint 3/10...</p>
                <p>Afstand: 4.2 meter</p>
                <button class="noodstop" on:click={noodIngreep}>🚨 NEEM BESTURING OVER</button>
            </div>
        {:else}
            <div class="manual-status">
                <p>Klaar voor toetsenbord/muis invoer.</p>
                </div>
        {/if}
    </div>
</div>