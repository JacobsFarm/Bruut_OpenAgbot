<script>
  import Dashboard from './components/dashboard.svelte';
  import Camera from './components/camera.svelte';
  import Navigation from './components/navigation.svelte';
  import Motor from './components/motor.svelte';
  import Tractor from './components/tractor.svelte';

  let activeTab = 'dashboard';
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
</style>