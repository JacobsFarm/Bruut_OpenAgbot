<script>
  // De schil van de webinterface: bovenin altijd wat de robot doet (missie, GPS, accu, snelheid),
  // onderin de tabbladen en - op elk tabblad op dezelfde plek - de STOP-knop.
  import Dashboard from './components/dashboard.svelte';
  import Rijden from './components/rijden.svelte';
  import Tractor from './components/tractor.svelte';
  import Missie from './components/missie.svelte';
  import Meer from './components/meer.svelte';
  import Icoon from './components/Icoon.svelte';
  import { motors, status, postJson, noodstop, bezigheid, fixInfo, fmt, tril } from './lib/telemetry.js';

  const tabs = [
    ['status', 'Status', 'status'],
    ['rijden', 'Rijden', 'rijden'],
    ['banen', 'AB-lijn', 'banen'],
    ['missie', 'Missie', 'missie'],
    ['meer', 'Meer', 'meer'],
  ];

  let tab = 'status';
  try {
    const bewaard = sessionStorage.getItem('tab');
    if (tabs.some((t) => t[0] === bewaard)) tab = bewaard;
  } catch (e) { /* geen opslag */ }
  // De tabbladen met een kaart blijven bestaan als je even ergens anders kijkt:
  // je gekozen lijn, je instellingen en het kaartbeeld staan er dan nog.
  let bezocht = { [tab]: true };

  function kies(naam) {
    tab = naam;
    bezocht = { ...bezocht, [naam]: true };
    try { sessionStorage.setItem('tab', naam); } catch (e) { /* geen opslag */ }
  }

  $: s = $status.data;
  $: m = $motors.data;
  // Verbinding: weg zodra beide stromen haperen; 'nooit' zolang er nog niets binnen is.
  $: nooit = $status.updated === 0 && $motors.updated === 0;
  $: verbindingWeg = !nooit && !$status.ok && !$motors.ok;
  $: geenRobot = nooit && $status.pogingen > 1;
  $: doet = bezigheid(s, m);
  $: fix = fixInfo(s?.fix);
  $: accu = m?.battery;
  $: accuKleur = accu?.soc_pct == null ? '' : accu.soc_pct >= 40 ? 'groen' : accu.soc_pct >= 20 ? 'oranje' : 'rood';

  // Aandrijf- en stuurproblemen horen op elk tabblad in beeld te staan: een missie die
  // stopt op een vastgelopen wiel zie je anders pas als je gaat zoeken.
  $: fout = m?.fault;

  async function vrijgeven() {
    try { await postJson('/api/motors/reset'); } catch (e) { /* de balk blijft staan */ }
  }

  // Geofence (data/kaart.json): geldt bij elke manier van rijden, dus de
  // melding hoort ook op elk tabblad. Dicht = in die richting rijdt hij niet.
  $: geofence = s?.geofence;
  $: geofenceDicht = geofence && (!geofence.vooruit || !geofence.achteruit);

  async function overbruggen() {
    if (!confirm('Geofence 60 seconden overbruggen? Alleen om met de hand, langzaam, uit het gebied te rijden.')) return;
    try { await postJson('/api/geofence/overbruggen', {}); } catch (e) { /* de balk blijft staan */ }
  }

  async function bewakingAan() {
    try { await fetch('/api/geofence/overbruggen', { method: 'DELETE' }); } catch (e) { /* de balk blijft staan */ }
  }

  // STOP: op het indrukken, niet op het loslaten. De knop meldt terug of de robot
  // de stop bevestigd heeft; zo niet, dan zegt hij dat groot en duidelijk.
  let stopBezig = false;
  let stopMelding = null;       // { tekst, fout }
  let stopTimer;

  async function stop() {
    if (stopBezig) return;
    stopBezig = true;
    tril([40, 30, 40]);
    const gelukt = await noodstop();
    stopBezig = false;
    clearTimeout(stopTimer);
    stopMelding = gelukt
      ? { tekst: 'Gestopt', fout: false }
      : { tekst: 'Robot niet bereikt! Gebruik de noodstop op de machine.', fout: true };
    if (!gelukt) tril([200, 100, 200, 100, 200]);
    stopTimer = setTimeout(() => (stopMelding = null), gelukt ? 2500 : 8000);
  }
</script>

<div class="app">
  <header class="top">
    <button class="doet" on:click={() => kies('status')} aria-label="Naar het statusoverzicht">
      <span class="lamp {doet.toon}" class:knipper={doet.actief}></span>
      <span class="doet-tekst">
        <b>{verbindingWeg ? 'Geen verbinding' : doet.titel}</b>
        {#if doet.tekst && !verbindingWeg}<small>{doet.tekst}</small>{/if}
      </span>
    </button>
    <div class="meters">
      <span class="meter" title="GNSS: {fix.tekst}">
        <span class="stip {s ? fix.kleur : ''}"></span>{s ? fix.kort : '–'}
      </span>
      <span class="meter" title="Accu">
        <span class="stip {accuKleur}"></span>{accu?.soc_pct != null ? `${accu.soc_pct}%` : accu?.voltage_v != null ? `${fmt(accu.voltage_v, 0)} V` : '–'}
      </span>
      <span class="meter snelheid num"><b>{fmt(s?.speed_kmh, 1)}</b><small>km/h</small></span>
    </div>
  </header>

  <div class="balken" aria-live="assertive">
    {#if geenRobot}
      <div class="balk grijs">De robot antwoordt niet. Zit je op zijn wifi of hotspot?</div>
    {:else if verbindingWeg}
      <div class="balk grijs">Geen verbinding met de robot. De gegevens hieronder zijn verouderd.</div>
    {:else}
      {#if fout}
        <div class="balk rood">
          <span><b>Rijdt niet:</b> {fout}</span>
          {#if m.fault_latched}<button on:click={vrijgeven}>Vrijgeven</button>{/if}
        </div>
      {/if}
      {#if geofence?.overbrugd_s > 0}
        <div class="balk oranje">
          <span><b>Geofence overbrugd</b>, nog {Math.round(geofence.overbrugd_s)} s: alleen langzaam, met de hand.</span>
          <button on:click={bewakingAan}>Bewaking aan</button>
        </div>
      {:else if geofenceDicht}
        <div class="balk rood">
          <span><b>Geofence:</b> {geofence.reden}.
            {!geofence.vooruit && !geofence.achteruit ? 'Vooruit en achteruit dicht.'
              : !geofence.vooruit ? 'Vooruit dicht, achteruit kan nog.' : 'Achteruit dicht, vooruit kan nog.'}</span>
          <button on:click={overbruggen}>Overbruggen</button>
        </div>
      {/if}
    {/if}
  </div>

  <main class="inhoud">
    <!-- Status, Rijden en Meer worden opgebouwd als je ze opent. Rijden moet ook echt
         weg zijn als je het verlaat: wie niet op dat scherm zit, zit niet aan het stuur. -->
    {#if tab === 'status'}<div class="tabvlak"><Dashboard /></div>{/if}
    {#if tab === 'rijden'}<div class="tabvlak"><Rijden /></div>{/if}
    {#if bezocht.banen}<div class="tabvlak" hidden={tab !== 'banen'}><Tractor actief={tab === 'banen'} /></div>{/if}
    {#if bezocht.missie}<div class="tabvlak" hidden={tab !== 'missie'}><Missie actief={tab === 'missie'} /></div>{/if}
    {#if tab === 'meer'}<div class="tabvlak"><Meer /></div>{/if}

    {#if stopMelding}
      <div class="stopmelding" class:fout={stopMelding.fout} role="alert">{stopMelding.tekst}</div>
    {/if}
  </main>

  <nav class="onder">
    {#each tabs as [naam, label, icoon]}
      <button class="tab" class:actief={tab === naam} on:click={() => kies(naam)} aria-current={tab === naam ? 'page' : undefined}>
        <Icoon naam={icoon} maat={24} />
        <span>{label}</span>
      </button>
    {/each}
    <button class="stop" class:bezig={stopBezig} on:pointerdown|preventDefault={stop}
            on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') stop(); }} aria-label="Noodstop: alles stoppen">
      STOP
    </button>
  </nav>
</div>

<style>
  .app {
    height: 100vh;
    height: 100dvh;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto minmax(0, 1fr) auto;
    grid-template-areas: 'top' 'balken' 'inhoud' 'onder';
    background: var(--bg);
  }

  /* --- Bovenbalk: wat doet de robot, en de drie getallen die er altijd toe doen --- */
  .top {
    grid-area: top;
    display: flex; align-items: center; gap: 8px;
    padding: calc(6px + var(--boven)) calc(10px + var(--rechts)) 6px calc(6px + var(--links));
    background: var(--chrome); color: var(--chrome-inkt);
    min-height: 54px;
  }
  .doet {
    flex: 1; min-width: 0; min-height: 42px; padding: 2px 6px; gap: 10px;
    justify-content: flex-start; text-align: left;
    background: none; border: none; color: inherit;
  }
  .doet-tekst { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }
  .doet-tekst b { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .doet-tekst small { font-size: 12.5px; font-weight: 400; color: var(--chrome-stil); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lamp { width: 12px; height: 12px; border-radius: 50%; flex: none; background: var(--chrome-stil); }
  .lamp.groen { background: #4cd07a; box-shadow: 0 0 8px #4cd07a; }
  .lamp.blauw { background: #6ab0ff; box-shadow: 0 0 8px #6ab0ff; }
  .lamp.oranje { background: #ffab3d; box-shadow: 0 0 8px #ffab3d; }
  .lamp.rood { background: #ff6457; box-shadow: 0 0 8px #ff6457; }
  .lamp.knipper { animation: knipper 1.6s ease-in-out infinite; }
  @keyframes knipper { 50% { opacity: 0.45; } }

  .meters { display: flex; align-items: center; gap: 10px; flex: none; font-size: 13.5px; font-weight: 600; }
  .meter { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
  .meter .stip { background: var(--chrome-stil); }
  .meter .stip.groen { background: #4cd07a; }
  .meter .stip.oranje { background: #ffab3d; }
  .meter .stip.rood { background: #ff6457; }
  .snelheid { flex-direction: column; gap: 0; line-height: 1; min-width: 40px; align-items: flex-end; }
  .snelheid b { font-size: 19px; font-weight: 750; }
  .snelheid small { font-size: 10.5px; font-weight: 500; color: var(--chrome-stil); }

  /* --- Meldingen die op elk tabblad gelden --- */
  .balken { grid-area: balken; }
  .balk {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 9px calc(12px + var(--rechts)) 9px calc(12px + var(--links));
    font-size: 14.5px; line-height: 1.3; color: #fff;
  }
  .balk.rood { background: #b3261e; }
  .balk.oranje { background: #b35c00; }
  .balk.grijs { background: #4a5a50; }
  .balk button { flex: none; min-height: 40px; padding: 6px 12px; font-size: 14.5px; background: #fff; color: #1c1b1f; border: none; }

  /* --- Inhoud: elk tabblad heeft zijn eigen schuifpositie --- */
  .inhoud { grid-area: inhoud; position: relative; overflow: hidden; }
  .tabvlak {
    position: absolute; inset: 0; overflow-y: auto; overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
    padding-left: var(--links); padding-right: var(--rechts);
  }
  .tabvlak[hidden] { display: none; }

  .stopmelding {
    position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%);
    z-index: 2000; max-width: calc(100% - 24px);
    padding: 12px 18px; border-radius: 999px;
    background: #1c2a22; color: #fff; font-weight: 650; text-align: center;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
    animation: op 0.15s ease-out;
  }
  .stopmelding.fout { background: #b3261e; border-radius: 14px; font-size: 17px; }
  @keyframes op { from { opacity: 0; transform: translate(-50%, 8px); } }

  /* --- Onderbalk: tabbladen en STOP --- */
  .onder {
    grid-area: onder;
    display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)) 76px;
    background: var(--chrome); border-top: 1px solid var(--chrome-rand);
    padding: 0 var(--rechts) var(--onder) var(--links);
  }
  .tab {
    flex-direction: column; gap: 2px; min-height: 58px; padding: 6px 2px 5px;
    background: none; border: none; border-radius: 0;
    color: var(--chrome-stil); font-size: 11.5px; font-weight: 600;
  }
  .tab.actief { color: #7ee08a; box-shadow: inset 0 3px 0 #7ee08a; }
  .stop {
    margin: 5px 6px 5px 4px; min-height: 48px; padding: 0;
    background: var(--stop); border: none; border-bottom: 3px solid var(--stop-diep); border-radius: 12px;
    color: #fff; font-size: 17px; font-weight: 800; letter-spacing: 0.04em;
    touch-action: none;
  }
  .stop:active, .stop.bezig { background: var(--stop-diep); border-bottom-width: 1px; transform: translateY(2px); }

  /* --- Breed scherm of liggende telefoon: tabbladen als rail links, zodat de hoogte voor de inhoud blijft --- */
  @media (min-width: 900px), (orientation: landscape) and (max-height: 540px) {
    .app {
      grid-template-columns: 84px minmax(0, 1fr);
      grid-template-rows: auto auto minmax(0, 1fr);
      grid-template-areas: 'onder top' 'onder balken' 'onder inhoud';
    }
    .onder {
      grid-template-columns: 1fr; grid-auto-rows: min-content; align-content: start;
      border-top: none; border-right: 1px solid var(--chrome-rand);
      padding: calc(4px + var(--boven)) 0 calc(6px + var(--onder)) var(--links);
      overflow-y: auto;
    }
    .tab { min-height: 54px; }
    .tab.actief { box-shadow: inset 3px 0 0 #7ee08a; }
    .stop { margin: 8px 8px 0; min-height: 64px; }
  }
  @media (orientation: landscape) and (max-height: 540px) {
    .tab { min-height: 44px; font-size: 10.5px; padding: 3px 2px; }
    .stop { min-height: 52px; }
    .top { min-height: 44px; padding-top: calc(3px + var(--boven)); padding-bottom: 3px; }
  }
</style>
