<script>
  import Dashboard from './components/dashboard.svelte';
  import Camera from './components/camera.svelte';
  import Navigation from './components/navigation.svelte';
  import Motor from './components/motor.svelte';

  let activeTab = 'dashboard';
</script>

<main class="container">
  <header>
    <h1>Bruut OpenAgbot</h1>
    <nav class="tabs">
      <button class:active={activeTab === 'dashboard'} on:click={() => activeTab = 'dashboard'}>Dashboard</button>
      <button class:active={activeTab === 'camera'} on:click={() => activeTab = 'camera'}>Camera & YOLO</button>
      <button class:active={activeTab === 'navigation'} on:click={() => activeTab = 'navigation'}>RTK Navigatie</button>
      <button class:active={activeTab === 'motor'} on:click={() => activeTab = 'motor'}>Handmatige Motor</button>
    </nav>
  </header>

  <section class="content">
    {#if activeTab === 'dashboard'}
      <Dashboard />
    {:else if activeTab === 'camera'}
      <Camera />
    {:else if activeTab === 'navigation'}
      <Navigation />
    {:else if activeTab === 'motor'}
      <Motor />
    {/if}
  </section>
</main>

<style>
  /* Zorgt dat het netjes schaalt op mobiel */
  .container { 
      max-width: 800px; 
      margin: 0 auto; 
      padding: 15px; /* Iets minder padding voor mobiel */
      font-family: sans-serif; 
      color: #333; 
  }
  
  header { margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
  
  /* Mobiel-geoptimaliseerde Tabs */
  .tabs {
      display: flex;
      overflow-x: auto; /* Sta horizontaal swipen toe op mobiel */
      white-space: nowrap; /* Voorkom dat tekst afbreekt in de knop */
      gap: 5px; /* Ruimte tussen knoppen */
      padding-bottom: 5px;
      -webkit-overflow-scrolling: touch; /* Soepel swipen op iPhones */
      scrollbar-width: none; /* Verberg scrollbar in Firefox */
  }
  
  /* Verberg de lelijke scrollbar in Chrome/Safari */
  .tabs::-webkit-scrollbar { 
      display: none; 
  }

  .tabs button { 
      flex: 0 0 auto; /* Zorgt dat knoppen niet in elkaar gedrukt worden */
      padding: 12px 16px; /* Iets groter klik-oppervlak voor vingers */
      border: none; 
      background: #ddd; 
      cursor: pointer; 
      border-radius: 6px; 
      font-size: 14px;
  }
  
  .tabs button.active { 
      background: #4CAF50; 
      color: white; 
      font-weight: bold; 
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  }
  
  .content { 
      background: #f9f9f9; 
      padding: 15px; 
      border-radius: 8px; 
      box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
  }
</style>