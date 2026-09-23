import { readable } from 'svelte/store';

// Eén gedeelde poller per endpoint. Hij loopt alleen zolang er een component
// naar luistert, en houdt bij een netwerkhik de laatste gegevens vast: 'ok'
// zegt of de laatste poging lukte, 'updated' wanneer er voor het laatst
// verse data binnenkwam.
function poll(url, intervalMs) {
    return readable({ data: null, ok: false, updated: 0 }, (set) => {
        let actief = true;
        let timer = null;
        let laatste = { data: null, ok: false, updated: 0 };

        async function tik() {
            try {
                const res = await fetch(url, { cache: 'no-store' });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                laatste = { data: await res.json(), ok: true, updated: Date.now() };
            } catch (e) {
                laatste = { ...laatste, ok: false };
            }
            if (!actief) return;
            set(laatste);
            timer = setTimeout(tik, intervalMs);
        }

        tik();
        return () => {
            actief = false;
            clearTimeout(timer);
        };
    });
}

// GPS, navigatie en een kort overzicht van de aandrijving
export const status = poll('/api/status', 1000);
// Alles van de twee VESC's: wielen, accu, grenzen, fouten
export const motors = poll('/api/motors', 500);

export async function postJson(url, body) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body)
    });
    return res.json();
}

// Schuifgrenzen op één decimaal, naar binnen afgerond. Een schuif telt in
// stappen vanaf zijn minimum: met min 1.38 en step 0.1 kom je op 1.98 en
// 2.98 uit in plaats van 2.0 en 3.0. Naar binnen, zodat elke stand ook echt
// gereden kan worden.
export const grensOmhoog = (x) => Math.ceil(x * 10 - 1e-9) / 10;
export const grensOmlaag = (x) => Math.floor(x * 10 + 1e-9) / 10;

// Getal met vaste decimalen, of een streepje als het er (nog) niet is.
export function fmt(waarde, decimalen = 1) {
    if (waarde === null || waarde === undefined || Number.isNaN(Number(waarde))) return '–';
    return Number(waarde).toFixed(decimalen);
}

// GGA-fixkwaliteit als tekst plus kleur (groen/oranje/rood), voor het
// dashboard en de robot op de kaart.
export function fixInfo(fix) {
    if (fix === 4) return { tekst: 'RTK Fixed', kleur: 'groen' };
    if (fix === 5) return { tekst: 'RTK Float', kleur: 'oranje' };
    if (fix === 1 || fix === 2) return { tekst: 'Standaard GPS', kleur: 'oranje' };
    return { tekst: 'Geen fix', kleur: 'rood' };
}
