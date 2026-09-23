<script>
  import Dashboard from './components/dashboard.svelte';
  import Camera from './components/camera.svelte';
  import Navigation from './components/navigation.svelte';
  import Motor from './components/motor.svelte';
  import Tractor from './components/tractor.svelte';
  import { motors, postJson } from './lib/telemetry.js';

  let activeTab = 'dashboard';

  // Aandrijfproblemen horen op elk tabblad in beeld te staan: een missie die
  // stopt op een vastgelopen wiel zie je anders pas als je gaat zoeken.
  $: aandrijving = $motors.data;
  $: verbindingWeg = $motors.updated > 0 && !$motors.ok;

  async function vrijgeven() {
    try {
      await postJson('/api/motors/reset');
    } catch (e) {}
  }
</script>

<main class="container">
  <header>
    <h1>Bruut OpenAgbot</h1>
    <nav class="tabs">
      <button class:active={activeTab === 'dashboard'} on:click={() => activeTab = 'dashboard'}>Dashboard</button>
      <button class:active={activeTab === 'navigation'} on:click={() => activeTab = 'navigation'}>RTK Navigatie</button>
      <button class:active={activeTab === 'tractor'} on:click={() => activeTab = 'tractor'}>A-B Tractor</button>
      <button class:active={activeTab === 'motor'} on:click={() => activeTab = 'motor'}>Handmatig (RC)</button>
      <button class:active={activeTab === 'camera'} on:click={() => activeTab = 'camera'}>Camera & YOLO</button>
    </nav>
  </header>

  {#if verbindingWeg}
    <div class="banner grijs">Geen verbinding met de robot. De getoonde gegevens zijn verouderd.</div>
  {:else if aandrijving?.fault}
    <div class="banner rood">
      <span><b>Aandrijving staat stil:</b> {aandrijving.fault}</span>
      {#if aandrijving.fault_latched}
        <button class="banner-knop" on:click={vrijgeven}>Vrijgeven</button>
      {/if}
    </div>
  {/if}

  <section class="content">
    {#if activeTab === 'dashboard'}
      <Dashboard />
    {:else if activeTab === 'navigation'}
      <Navigation />
    {:else if activeTab === 'tractor'}
      <Tractor />
    {:else if activeTab === 'motor'}
      <Motor />
    {:else if activeTab === 'camera'}
      <Camera />
    {/if}
  </section>
</main>

<style>
  .container { max-width: 800px; margin: 0 auto; padding: 15px; font-family: sans-serif; color: #333; }
  header { margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
  .tabs { display: flex; overflow-x: auto; white-space: nowrap; gap: 5px; padding-bottom: 5px; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .tabs::-webkit-scrollbar { display: none; }
  button { padding: 10px 15px; border: none; background: #eee; cursor: pointer; border-radius: 4px; font-size: 16px; font-weight: bold; color: #555; }
  button.active { background: #4caf50; color: white; }
  .content { background: #fff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }

  .banner { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 15px; margin-bottom: 15px; border-radius: 6px; font-size: 15px; }
  .banner.rood { background: #c62828; color: white; }
  .banner.grijs { background: #616161; color: white; }
  .banner-knop { background: white; color: #c62828; flex: none; }
</style>
