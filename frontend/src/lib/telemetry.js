import { readable, writable } from 'svelte/store';

// Eén gedeelde poller per endpoint. Hij loopt alleen zolang er een component
// naar luistert, en houdt bij een netwerkhik de laatste gegevens vast: 'ok'
// zegt of de laatste poging lukte, 'updated' wanneer er voor het laatst
// verse data binnenkwam. Staat het scherm uit of de browser op de
// achtergrond, dan pauzeert hij (scheelt accu en mobiele data) en haalt hij
// bij terugkomst meteen verse gegevens op.
function poll(url, intervalMs) {
    return readable({ data: null, ok: false, updated: 0, pogingen: 0 }, (set) => {
        let actief = true;
        let timer = null;
        let bezig = false;
        let laatste = { data: null, ok: false, updated: 0, pogingen: 0 };

        async function tik() {
            clearTimeout(timer);
            if (!actief || bezig) return;
            if (document.hidden) return;        // 'visibilitychange' start hem weer
            bezig = true;
            try {
                const res = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout?.(4000) });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                laatste = { data: await res.json(), ok: true, updated: Date.now(), pogingen: laatste.pogingen + 1 };
            } catch (e) {
                laatste = { ...laatste, ok: false, pogingen: laatste.pogingen + 1 };
            }
            bezig = false;
            if (!actief) return;
            set(laatste);
            timer = setTimeout(tik, intervalMs);
        }

        const zichtbaar = () => { if (!document.hidden) tik(); };
        document.addEventListener('visibilitychange', zichtbaar);
        tik();
        return () => {
            actief = false;
            clearTimeout(timer);
            document.removeEventListener('visibilitychange', zichtbaar);
        };
    });
}

// GPS, navigatie en een kort overzicht van de aandrijving
export const status = poll('/api/status', 500);
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

// Noodstop: stopt elke navigatie en zet de wielen stil. Probeert het een paar
// keer snel achter elkaar, want juist op het moment dat je stopt wil je niet
// afhangen van een enkel pakketje over een wankele wifi. Geeft true als de
// robot de stop bevestigd heeft.
export async function noodstop() {
    for (let poging = 0; poging < 4; poging++) {
        try {
            const res = await fetch('/api/stop', { method: 'POST', signal: AbortSignal.timeout?.(1500) });
            if (res.ok) return true;
        } catch (e) { /* opnieuw */ }
    }
    return false;
}

// Naam van dit apparaat / browservenster voor de handbediening: de robot laat
// één bestuurder tegelijk toe (zie Bestuurder in endpoints.py).
function maakBron() {
    const soort = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) ? 'telefoon' : 'computer';
    const nr = Math.random().toString(36).slice(2, 6);
    return `${soort}-${nr}`;
}
export const bron = maakBron();

// Kort trillen als bevestiging (Android; iOS doet niets). Nooit een fout.
export function tril(patroon = 15) {
    try { navigator.vibrate?.(patroon); } catch (e) { /* niet ondersteund */ }
}

// Scherm aan houden tijdens het rijden. Alleen beschikbaar op een beveiligde
// verbinding (https of localhost); op http://192.168... bestaat het niet en
// gebeurt er niets. Dooft het scherm dan toch, dan stopt de robot vanzelf op
// zijn dodemansknop.
let slot = null;
export async function schermAan(aan) {
    try {
        if (aan && !slot && navigator.wakeLock) {
            slot = await navigator.wakeLock.request('screen');
            slot.addEventListener('release', () => { slot = null; });
        } else if (!aan && slot) {
            await slot.release();
            slot = null;
        }
    } catch (e) { slot = null; }
}

// Thema: 'licht' voor in de zon, 'donker' voor de schemer. Zonder keuze
// volgt hij de instelling van de telefoon.
function beginThema() {
    try {
        const bewaard = localStorage.getItem('thema');
        if (bewaard === 'licht' || bewaard === 'donker') return bewaard;
    } catch (e) { /* geen opslag */ }
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'donker' : 'licht';
}
export const thema = writable(beginThema());
thema.subscribe((t) => {
    document.documentElement.dataset.thema = t;
    try { localStorage.setItem('thema', t); } catch (e) { /* geen opslag */ }
});

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
    if (fix === 4) return { tekst: 'RTK Fixed', kort: 'RTK', kleur: 'groen' };
    if (fix === 5) return { tekst: 'RTK Float', kort: 'Float', kleur: 'oranje' };
    if (fix === 2) return { tekst: 'DGPS', kort: 'DGPS', kleur: 'oranje' };
    if (fix === 1) return { tekst: 'Standaard GPS', kort: 'GPS', kleur: 'oranje' };
    if (fix === 6) return { tekst: 'Geschat', kort: 'Geschat', kleur: 'rood' };
    return { tekst: 'Geen fix', kort: 'Geen fix', kleur: 'rood' };
}

// Wat de robot nu doet, in één regel, uit /api/status (en /api/motors voor
// handmatig rijden). 'toon': groen = rijdt een missie, blauw = handmatig,
// oranje = wacht ergens op, rood = gestopt op een fout, grijs = staat stil.
export function bezigheid(s, m) {
    if (!s) return { titel: 'Verbinden…', tekst: '', toon: 'grijs', actief: false };
    if (s.missie_actief) {
        const wacht = s.missie_state?.startsWith('WACHT');
        return { titel: 'Veldmissie', tekst: s.missie_message, toon: wacht ? 'oranje' : 'groen', actief: true };
    }
    if (s.ab_active) {
        return { titel: `AB-lijn · baan ${s.ab_baan_nr}/${s.ab_totaal_banen}`, tekst: s.ab_message,
                 toon: 'groen', actief: true };
    }
    if (s.navigator_active) {
        return { titel: 'Route', tekst: s.nav_message, toon: s.nav_state === 'WACHT_OP_GNSS' ? 'oranje' : 'groen',
                 actief: true };
    }
    if (m?.drive && Math.abs(m.drive.target_kmh) > 0.05) {
        return { titel: 'Handmatig', tekst: `${fmt(m.drive.target_kmh, 1)} km/h`, toon: 'blauw', actief: true };
    }
    // Niets actief: laat zien waarom de laatste missie stopte, als dat een fout was.
    const fout = [s.missie_state === 'FOUT' && s.missie_message,
                  s.ab_message?.startsWith('Gestopt -') && s.ab_message,
                  s.nav_state === 'FOUT' && s.nav_message].find(Boolean);
    if (fout) return { titel: 'Gestopt', tekst: fout, toon: 'rood', actief: false };
    return { titel: 'Staat stil', tekst: '', toon: 'grijs', actief: false };
}
