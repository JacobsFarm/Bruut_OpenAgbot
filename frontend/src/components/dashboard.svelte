<script>
    import { status, motors, fmt, fixInfo, bezigheid } from '../lib/telemetry.js';

    $: gps = $status.data;
    $: m = $motors.data;
    $: accu = m?.battery;
    $: links = m?.wheels?.left;
    $: rechts = m?.wheels?.right;
    $: doet = bezigheid(gps, m);

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

    $: fix = fixInfo(gps?.fix);
    // Diagnostiek van de ZED-X20D: gemeten rates, NTRIP en heading-bron.
    $: gnss = gps?.gnss;
    $: richting = gps?.rijrichting === 1 ? 'vooruit' : gps?.rijrichting === -1 ? 'achteruit' : 'stil / onbekend';
    $: headingTekst = !gps ? '–'
        : gps.heading_geldig ? (gps.heading_bron === 'VTG' ? 'VTG (noodval, geen THS)' : gps.heading_bron)
        : 'ongeldig';

    function ladingKleur(pct) {
        if (pct >= 40) return 'groen';
        if (pct >= 20) return 'oranje';
        return 'rood';
    }

    const heeft = (x) => x !== null && x !== undefined;

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

<div class="pagina">
    <section class="paneel nu {doet.toon}">
        <h3>Nu</h3>
        <div class="nu-titel">{doet.titel}</div>
        {#if doet.tekst}<div class="nu-tekst">{doet.tekst}</div>{/if}
    </section>

    <div class="raster2">
        <section class="paneel">
            <h3>Snelheid</h3>
            <div class="groot-getal">{fmt(gpsKmh, 1)}<small> km/h</small></div>
            <div class="klein onder-getal">echte snelheid (GPS)</div>
            <div class="regel"><span>Wielen</span><b>{fmt(wielKmh, 1)} km/h</b></div>
            {#if slip !== null}
                <div class="regel">
                    <span>Verschil wielen − GPS</span>
                    <b class:let-op={Math.abs(slip) > 15}>{slip > 0 ? '+' : ''}{fmt(slip, 0)} %</b>
                </div>
            {/if}
            <div class="regel"><span>Koers</span><b>{fmt(gps?.heading, 0)}°</b></div>
        </section>

        <section class="paneel">
            <h3>Accu</h3>
            <div class="groot-getal">
                {#if heeft(accu?.soc_pct)}{accu.soc_pct}<small> %</small>{:else}{fmt(accu?.voltage_v, 1)}<small> V</small>{/if}
            </div>
            {#if heeft(accu?.soc_pct)}
                <div class="voortgang lading"><div class={ladingKleur(accu.soc_pct)} style="width: {accu.soc_pct}%"></div></div>
                <div class="klein onder-getal">{fmt(accu.voltage_v, 1)} V · schatting uit de spanning</div>
            {:else}
                <div class="klein onder-getal">geen spanning van de VESC's</div>
            {/if}
            <div class="regel"><span>Stroom / vermogen</span><b>{fmt(accu?.current_a, 1)} A / {fmt(accu?.power_w, 0)} W</b></div>
            <div class="regel"><span>Verbruikt</span><b>{fmt(accu?.used_ah, 2)} Ah / {fmt(accu?.used_wh, 0)} Wh</b></div>
            <div class="regel"><span>Teruggeleverd</span><b>{fmt(accu?.regen_ah, 2)} Ah / {fmt(accu?.regen_wh, 0)} Wh</b></div>
            <div class="regel">
                <span>Netto van {fmt(accu?.capacity_wh, 0)} Wh</span>
                <b>{fmt(accu?.net_wh, 0)} Wh ({fmt(accu?.used_pct, 0)} %)</b>
            </div>
            <p class="klein voet">Verbruik telt vanaf het moment dat de VESC's spanning kregen.</p>
        </section>

        <section class="paneel">
            <h3>GNSS (ZED-X20D) <span class="chip {fix.kleur}">{fix.tekst}</span></h3>
            <div class="regel"><span>Latitude</span><b class="mono">{fmt(gps?.lat, 8)}</b></div>
            <div class="regel"><span>Longitude</span><b class="mono">{fmt(gps?.lon, 8)}</b></div>
            <div class="regel"><span>HDOP / satellieten</span><b>{fmt(gps?.hdop, 2)} / {gps?.sats ?? '–'}</b></div>
            <div class="regel">
                <span>Heading</span>
                <b class:let-op={gps && (!gps.heading_geldig || gps.heading_bron === 'VTG')}>{fmt(gps?.heading, 1)}° · {headingTekst}</b>
            </div>
            <div class="regel">
                <span>Positie / heading</span>
                <b class:let-op={gnss && (gnss.positie_hz < 20 || gnss.heading_hz < 20)}>{fmt(gnss?.positie_hz, 1)} / {fmt(gnss?.heading_hz, 1)} Hz</b>
            </div>
            <div class="regel"><span>Draaisnelheid</span><b>{fmt(gps?.draaisnelheid_dps, 1)} °/s</b></div>
            <div class="regel">
                <span>Rijrichting / slip</span>
                <b class:let-op={heeft(gps?.sliphoek_deg) && Math.abs(gps.sliphoek_deg) > 5}>
                    {richting}{heeft(gps?.sliphoek_deg) ? ` · ${fmt(gps.sliphoek_deg, 1)}°` : ''}
                </b>
            </div>
            <div class="regel">
                <span>Correcties (NTRIP)</span>
                <b class:let-op={gnss && gnss.ntrip_status !== 'verbonden'}>
                    {gnss?.ntrip_status ?? '–'}{heeft(gps?.correctie_leeftijd_s) ? ` · ${fmt(gps.correctie_leeftijd_s, 1)} s oud` : ''}
                </b>
            </div>
            <div class="regel">
                <span>Antennes</span>
                <b class:let-op={gps && gps.baseline_m === null}>
                    {#if heeft(gps?.baseline_m)}
                        {fmt(gps.baseline_m, 3)} m · {gps.antenne_hoogteverschil_m >= 0 ? '+' : ''}{fmt(gps.antenne_hoogteverschil_m * 100, 1)} cm · {gps.dah_oplossing}
                    {:else}
                        niet ontvangen ({gnss?.daheading_config ?? '–'})
                    {/if}
                </b>
            </div>
            {#if gnss?.ntrip_fout}
                <div class="melding rood">{gnss.ntrip_fout}</div>
            {/if}
        </section>

        <section class="paneel">
            <h3>Aandrijving en stuur</h3>
            {#if m?.fault}
                <div class="melding rood">{m.fault}</div>
            {:else if m}
                <div class="melding groen">Klaar om te rijden</div>
            {/if}
            {#each m?.warnings ?? [] as waarschuwing}
                <div class="melding oranje">{waarschuwing}</div>
            {/each}
            <div class="regel">
                <span>CAN ({m?.can?.channel ?? '–'})</span>
                <b class:let-op={m && !m.can.online}>{m ? (m.can.online ? 'open' : 'dicht') : '–'}</b>
            </div>
            <div class="regel">
                <span>Stuur-Arduino</span>
                <b class:let-op={m?.steering_fault}>{m ? (m.steering_fault ?? 'antwoordt') : '–'}</b>
            </div>
            <div class="regel"><span>Rijopdracht</span><b>{fmt(m?.drive?.target_kmh, 1)} km/h</b></div>
            <div class="regel"><span>Stuurhoek (midden)</span><b>{fmt(m?.drive?.angle_degrees, 1)}°</b></div>
            <div class="regel">
                <span>Bereik</span>
                <b>{fmt(m?.limits?.min_kmh, 1)} – {fmt(m?.limits?.max_kmh, 1)} km/h</b>
            </div>
        </section>

        <details class="paneel breed">
            <summary>Achterwielen (VESC) <small>{fmt(links?.speed_kmh, 1)} / {fmt(rechts?.speed_kmh, 1)} km/h</small></summary>
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
        </details>
    </div>
</div>

<style>
    .nu { border-left: 6px solid var(--inkt2); }
    .nu.groen { border-left-color: var(--groen); }
    .nu.blauw { border-left-color: var(--blauw); }
    .nu.oranje { border-left-color: var(--oranje); }
    .nu.rood { border-left-color: var(--rood); background: var(--rood-vlak); }
    .nu-titel { font-size: 22px; font-weight: 700; line-height: 1.2; }
    .nu-tekst { font-size: 15px; color: var(--inkt2); margin-top: 3px; overflow-wrap: anywhere; }
    .nu.rood .nu-tekst { color: var(--inkt); }

    .onder-getal { margin: 2px 0 10px; }
    .lading { margin-top: 8px; }
    .lading .groen { background: var(--groen); }
    .lading .oranje { background: var(--oranje); }
    .lading .rood { background: var(--rood); }
    .voet { margin-top: 8px; }
    .melding { margin-bottom: 8px; }
    .regel + .melding { margin-top: 8px; }

    table { width: 100%; border-collapse: collapse; font-size: 14.5px; font-variant-numeric: tabular-nums; }
    th, td { padding: 7px 4px; border-top: 1px solid var(--lijn); text-align: right; }
    th:first-child, td:first-child { text-align: left; color: var(--inkt2); }
    thead th { border-top: none; font-weight: 650; }
</style>
