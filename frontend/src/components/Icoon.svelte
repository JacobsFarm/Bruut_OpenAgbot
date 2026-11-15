<script>
    // Lijnpictogrammen, 24 x 24. Getekend als paden zodat er niets gedownload hoeft te worden.
    export let naam;
    export let maat = 24;

    const paden = {
        // Tabbladen
        status: 'M4 13a8 8 0 0 1 16 0M12 13l4-5M4 17h16',
        rijden: 'M12 3v4M12 17v4M3 12h4M17 12h4M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z',
        banen: 'M6 3v18M12 3v18M18 3v18M6 7l-2 2M12 17l2-2M18 7l-2 2',
        missie: 'M5 19c0-6 14-4 14-10a3 3 0 0 0-6 0M5 19a2 2 0 1 0 0-.01M19 5v0',
        meer: 'M5 12h.01M12 12h.01M19 12h.01',
        // Overig
        route: 'M12 21s-6-5.2-6-10a6 6 0 0 1 12 0c0 4.8-6 10-6 10ZM12 9v0',
        camera: 'M4 8h3l2-3h6l2 3h3v11H4ZM12 11a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z',
        sleutel: 'M14 6a4 4 0 0 0-5.2 5.2L4 16v4h4l4.8-4.8A4 4 0 0 0 18 10l-2.5 2.5-2-2L16 8a4 4 0 0 0-2-2Z',
        zon: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19',
        maan: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z',
        accu: 'M3 8h15v8H3ZM18 10.5h3v3h-3',
        gps: 'M12 2v3M12 19v3M2 12h3M19 12h3M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z',
        waarschuwing: 'M12 4 2.5 20h19ZM12 10v4.5M12 17.5v0',
        volg: 'M12 3 19 20l-7-4-7 4Z',
        veld: 'M4 4h16v16H4ZM4 9h16M4 15h16',
    };
</script>

<svg viewBox="0 0 24 24" width={maat} height={maat} fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d={paden[naam] ?? ''} />
</svg>

<style>
    svg { display: block; flex: none; }
</style>
