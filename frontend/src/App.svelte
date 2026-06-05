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
      <button class:active={activeTab === 'navigation'} on:click={() => activeTab = 'navigation'}>RTK Navigatie</button>
      <button class:active={activeTab === 'motor'} on:click={() => activeTab = 'motor'}>Handmatig (RC)</button>
      <button class:active={activeTab === 'camera'} on:click={() => activeTab = 'camera'}>Camera & YOLO</button>
    </nav>
  </header>

  <section class="content">
    {#if activeTab === 'dashboard'}
      <Dashboard />
    {:else if activeTab === 'navigation'}
      <Navigation />
    {:else if activeTab === 'motor'}
      <Motor />
    {:else if activeTab === 'camera'}
      <Camera />
    {/if}
  </section>
</main>

<style>
  .container { 
      max-width: 800px;
      margin: 0 auto; 
      padding: 15px; 
      font-family: sans-serif;
      color: #333; 
  }
  
  header { margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
  
  .tabs {
      display: flex;
      overflow-x: auto;
      white-space: nowrap;
      gap: 5px;
      padding-bottom: 5px;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
  }
  
  .tabs::-webkit-scrollbar { display: none; }

  .tabs button { 
      flex: 0 0 auto;
      padding: 12px 16px;
      font-size: 16px; 
      cursor: pointer; 
      border: 1px solid #ccc;
      background: #f9f9f9; 
      border-radius: 8px;
      font-weight: bold;
      transition: background 0.2s, color 0.2s;
  }
  .tabs button.active { background: #4CAF50; color: white; border-color: #4CAF50; }
  .content { border-radius: 5px; }
</style>