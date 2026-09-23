<script>
    import { status, motors, fmt } from '../lib/telemetry.js';

    $: gps = $status.data;
    $: m = $motors.data;
    $: accu = m?.battery;
    $: links = m?.wheels?.left;
    $: rechts = m?.wheels?.right;

    // De echte grondsnelheid komt van de GPS; de wielen zeggen hoe snel ze
    // draaien. Draaien ze duidelijk sneller dan de robot gaat, dan slipt hij -
    // of klopt de wielomtrek in de config niet.
    $: gpsKmh = gps ? gps.speed_kmh : null;
    $: wielKmh = (links?.online && rechts?.online)
        ? (Math.abs(links.speed_kmh) + Math.abs(rechts.speed_kmh)) / 2
        : null;
    $: slip = (wielKmh !== null && gpsKmh !== null && wielKmh >= 1.0)
        ? 100 * (wielKmh - gpsKmh) / wielKmh
        : null;

    function fixInfo(fix) {
        if (fix === 4) return { tekst: 'RTK Fixed', kleur: 'groen' };
        if (fix === 5) return { tekst: 'RTK Float', kleur: 'oranje' };
        if (fix === 1 || fix === 2) return { tekst: 'Standaard GPS', kleur: 'oranje' };
        return { tekst: 'Geen fix', kleur: 'rood' };
    }
    $: fix = fixInfo(gps?.fix);

    function ladingKleur(pct) {
        if (pct >= 50) return 'groen';
        if (pct >= 20) return 'oranje';
        return 'rood';
    }

    $: missie = gps?.ab_active ? `A-B: ${gps.ab_message}`
        : gps?.navigator_active ? `Route: ${gps.nav_message}`
        : 'Geen missie actief';

    // Per wiel dezelfde regels, links en rechts naast elkaar.
    const wielRegels = [
        ['Verbinding', (w) => w.online ? `ok (${w.age_ms} ms)` : 'geen data'],
        ['Gevraagd', (w) => `${fmt(w.speed_cmd_kmh, 2)} km/h`],
        ['Gemeten', (w) => `${fmt(w.speed_kmh, 2)} km/h`],
        ['eRPM', (w) => `${w.erpm_cmd} / ${w.erpm}`],
        ['Motorstroom', (w) => `${fmt(w.motor_current_a, 1)} A`],
        ['Accustroom', (w) => `${fmt(w.input_current_a, 1)} A`],
        ['Temp. FET', (w) => `${fmt(w.temp_fet_c, 0)} °C`],
        ['Motor (model)', (w) => `${fmt(w.motor_temp_model_c, 0)} °C`],
        ['Afgelegd', (w) => `${fmt(w.distance_m, 1)} m`],
        ['Verbruikt', (w) => `${fmt(w.watt_hours, 1)} Wh`],
        ['Foutcode', (w) => w.fault ?? '–'],
    ];
</script>

<div class="dashboard">
    <h2>Dashboard</h2>

    <div class="raster">
        <section class="kaart">
            <h3>Snelheid</h3>
            <div class="groot">{fmt(gpsKmh, 1)} <span class="eenheid">km/h</span></div>
            <div class="sub">echte snelheid (GPS)</div>
            <div class="regel"><span>Wielen</span><b>{fmt(wielKmh, 1)} km/h</b></div>
            {#if slip !== null}
                <div class="regel">
                    <span>Verschil wielen - GPS</span>
                    <b class:let-op={Math.abs(slip) > 15}>{slip > 0 ? '+' : ''}{fmt(slip, 0)} %</b>
                </div>
            {/if}
            <div class="regel"><span>Koers</span><b>{fmt(gps?.heading, 0)}°</b></div>
        </section>

        <section class="kaart">
            <h3>Accu</h3>
            <div class="groot">{fmt(accu?.voltage_v, 1)} <span class="eenheid">V</span></div>
            {#if accu?.soc_pct !== null && accu?.soc_pct !== undefined}
                <div class="balk"><div class="vulling {ladingKleur(accu.soc_pct)}" style="width: {accu.soc_pct}%"></div></div>
                <div class="sub">ca. {accu.soc_pct} % geladen (schatting uit de spanning)</div>
            {:else}
                <div class="sub">geen spanning van de VESC's</div>
            {/if}
            <div class="regel"><span>Stroom / vermogen</span><b>{fmt(accu?.current_a, 1)} A / {fmt(accu?.power_w, 0)} W</b></div>
            <div class="regel"><span>Verbruikt</span><b>{fmt(accu?.used_ah, 2)} Ah / {fmt(accu?.used_wh, 0)} Wh</b></div>
            <div class="regel"><span>Teruggeleverd</span><b>{fmt(accu?.regen_ah, 2)} Ah / {fmt(accu?.regen_wh, 0)} Wh</b></div>
            <div class="regel">
                <span>Netto van {fmt(accu?.capacity_wh, 0)} Wh</span>
                <b>{fmt(accu?.net_wh, 0)} Wh ({fmt(accu?.used_pct, 0)} %)</b>
            </div>
            <div class="klein">Verbruik telt vanaf het moment dat de VESC's spanning kregen.</div>
        </section>

        <section class="kaart">
            <h3>GPS</h3>
            <div class="badge {fix.kleur}">{fix.tekst}</div>
            <div class="regel"><span>Latitude</span><b class="mono">{fmt(gps?.lat, 8)}</b></div>
            <div class="regel"><span>Longitude</span><b class="mono">{fmt(gps?.lon, 8)}</b></div>
            <div class="regel"><span>HDOP</span><b>{fmt(gps?.hdop, 2)}</b></div>
            <div class="regel"><span>Missie</span><b class="rechts-uitlijnen">{missie}</b></div>
        </section>

        <section class="kaart">
            <h3>Aandrijving</h3>
            <div class="regel">
                <span>CAN ({m?.can?.channel ?? '–'})</span>
                <b class:let-op={m && !m.can.online}>{m ? (m.can.online ? 'open' : 'dicht') : '–'}</b>
            </div>
            <div class="regel"><span>Rijopdracht</span><b>{fmt(m?.drive?.target_kmh, 1)} km/h</b></div>
            <div class="regel"><span>Stuurhoek</span><b>{fmt(m?.drive?.angle_degrees, 1)}°</b></div>
            <div class="regel">
                <span>Bereik</span>
                <b>{fmt(m?.limits?.min_kmh, 1)} - {fmt(m?.limits?.max_kmh, 1)} km/h</b>
            </div>
            {#if m?.fault}
                <div class="melding rood">{m.fault}</div>
            {:else if m}
                <div class="melding groen">Klaar om te rijden</div>
            {/if}
            {#each m?.warnings ?? [] as waarschuwing}
                <div class="melding oranje">{waarschuwing}</div>
            {/each}
        </section>

        <section class="kaart breed">
            <h3>Achterwielen (VESC)</h3>
            <table>
                <thead>
                    <tr>
                        <th></th>
                        <th>Links{links ? ` (ID ${links.can_id})` : ''}</th>
                        <th>Rechts{rechts ? ` (ID ${rechts.can_id})` : ''}</th>
                    </tr>
                </thead>
                <tbody>
                    {#each wielRegels as [label, waarde]}
                        <tr>
                            <td>{label}</td>
                            <td>{links ? waarde(links) : '–'}</td>
                            <td>{rechts ? waarde(rechts) : '–'}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </section>
    </div>
</div>

<style>
    .dashboard { padding: 15px; }
    h2 { margin: 0 0 15px; }
    .raster { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    @media (max-width: 600px) { .raster { grid-template-columns: 1fr; } }

    .kaart { background: #f5f5f5; border: 1px solid #ddd; border-radius: 8px; padding: 15px; min-width: 0; }
    .kaart.breed { grid-column: 1 / -1; }
    h3 { margin: 0 0 10px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #666; }

    .groot { font-size: 44px; font-weight: 800; line-height: 1.1; color: #222; }
    .eenheid { font-size: 20px; font-weight: 600; color: #777; }
    .sub { color: #666; font-size: 13px; margin: 4px 0 10px; }
    .klein { color: #888; font-size: 12px; margin-top: 8px; }

    .regel { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border-top: 1px solid #e3e3e3; font-size: 15px; }
    .regel b { text-align: right; }
    .rechts-uitlijnen { overflow-wrap: anywhere; }
    .mono { font-family: monospace; }
    .let-op { color: #c62828; }

    .balk { background: #ddd; height: 14px; border-radius: 7px; overflow: hidden; }
    .vulling { height: 100%; transition: width 0.5s; }
    .vulling.groen { background: #43a047; }
    .vulling.oranje { background: #fb8c00; }
    .vulling.rood { background: #e53935; }

    .badge { display: inline-block; padding: 6px 12px; border-radius: 4px; font-weight: bold; color: white; margin-bottom: 8px; }
    .badge.groen { background: #43a047; }
    .badge.oranje { background: #fb8c00; }
    .badge.rood { background: #e53935; }

    .melding { padding: 8px 10px; border-radius: 4px; margin-top: 8px; font-size: 14px; }
    .melding.groen { background: #e8f5e9; color: #2e7d32; }
    .melding.oranje { background: #fff3e0; color: #e65100; }
    .melding.rood { background: #ffebee; color: #c62828; }

    table { width: 100%; border-collapse: collapse; font-size: 15px; }
    th, td { padding: 7px 6px; border-top: 1px solid #e3e3e3; text-align: right; }
    th:first-child, td:first-child { text-align: left; color: #555; }
    thead th { border-top: none; }
</style>
