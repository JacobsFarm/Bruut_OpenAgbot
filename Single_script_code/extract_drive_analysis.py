"""
Aandrijving en accu uit de ritlog: trekkracht, elektrisch vermogen, verbruik, spanningsval.

Leest data/logs/rit_*.csv (de VESC-kolommen die de app per regel meeschrijft)
en maakt per rit:
  <naam>_aandrijving.html rapport met kerngetallen (gemiddeld vermogen, Wh/km,
                          bereik), bevindingen, tabellen per wiel, per modus,
                          per snelheid en per 30 s, uitleg, en de grafieken
  <naam>_aandrijving.png 8 grafieken: snelheid en duty, trekkracht per wiel,
                          accuspanning en -stroom, elektrisch vermogen
                          per wiel, spanningsval (interne weerstand),
                          kracht tegen snelheid, temperaturen, verbruik en lading
en drukt een samenvatting af.

De TREKKRACHT wordt NIET gemeten maar uitgerekend uit de motorstroom:
    koppel motor = 1.5 x poolparen x lambda x I_q
    kracht wiel  = koppel motor x overbrenging x rendement kast / straal band
  - lambda (flux linkage, Wb) komt uit de log zelf: bij middelhoog toerental en
    weinig stroom geldt  lambda = (duty x Accu_V / wortel 3) / (hoeksnelheid
    elektrisch). Dat geeft per rit nagenoeg hetzelfde (1 nov 2026: 0,064 Wb).
    Weet je hem uit de VESC Tool (Motor Setup Wizard), geef hem dan op met --lambda.
  - rendement van de kast staat op 0,9 (gokje, wijzigen met --kast-rendement).
Het is dus een goede schatting, geen meting. IJken kan met een trekproef: een
weegschaal of kracht-meter tussen robot en een vaste paal, wiel op vast
toerental, dan stroom en kracht vergelijken.

De fabrikant geeft 50 kgf trekkracht per hubmotor (490 N, setup/information/
Specs hardware/specs_hub_motor.json); die staat als lijn in de grafiek.

Gebruik (vanuit de hoofdmap van het project):
    python Single_script_code/aandrijving_analyse.py                      # nieuwste rit
    python Single_script_code/aandrijving_analyse.py data/logs/rit_AB_Missie_20261101_180045.csv
    python Single_script_code/aandrijving_analyse.py --alle               # alle ritten
    python Single_script_code/aandrijving_analyse.py rit.csv --lambda 0.064 --kast-rendement 0.85
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

G = 9.81
SPEC_TREKKRACHT_N = 50 * G          # specs_hub_motor.json: 50 kgf per motor
NOMINAAL_V_PER_CEL = 3.6
KLEUR_L, KLEUR_R = "#1f77b4", "#d62728"


def laad_config():
    """Poolparen, overbrenging, bandomtrek en accu uit data/config.json (anders het voorbeeld)."""
    cfg = {}
    for naam in ("config.json", "config.example.json"):
        pad = os.path.join(PROJECT_ROOT, "data", naam)
        if os.path.exists(pad):
            with open(pad, encoding="utf-8") as f:
                cfg = json.load(f)
            break
    vesc, accu = cfg.get("vesc", {}), cfg.get("battery", {})
    return {
        "poolparen": float(vesc.get("pole_pairs", 10)),
        "overbrenging": float(vesc.get("gear_ratio", 5.0)),
        "omtrek_m": float(vesc.get("wheel_circumference_m", 1.277)),
        "max_erpm": float(vesc.get("max_erpm", 3700)),
        "cellen": int(accu.get("cells", 14)),
        "capaciteit_ah": float(accu.get("capacity_ah", 5.0)),
        "weerstand_config": float(accu.get("internal_resistance_ohm", 0.2)),
    }


def lees_rit(pad):
    """Ritlog als DataFrame met een tijdas in seconden; regels zonder tijd (de EINDE-regel) vallen weg."""
    d = pd.read_csv(pad)
    d = d[pd.to_numeric(d["WP_Doel"], errors="coerce").notna()].copy()
    for kolom in d.columns[3:]:
        d[kolom] = pd.to_numeric(d[kolom], errors="coerce")
    t = pd.to_datetime(d["Tijdstip"], format="%H:%M:%S.%f")
    sec = (t - t.iloc[0]).dt.total_seconds().to_numpy()
    sec[sec < 0] += 86400.0                      # rit over middernacht
    d["t"] = sec
    return d.reset_index(drop=True)


def schat_lambda(d, i_max=4.0):
    """Flux linkage (Wb) uit duty, accuspanning en toerental; weinig stroom = weinig weerstandsval."""
    kandidaten = []
    for z in "LR":
        erpm, duty, stroom = d[f"ERPM_{z}"], d[f"Duty_{z}"], d[f"Motorstroom_{z}_A"].abs()
        ok = (erpm > 1500) & (duty > 0.1) & (d["Accu_V"] > 20)
        for grens in (i_max, 1e9):               # eerst alleen lage stroom, anders alles
            m = ok & (stroom <= grens)
            if m.sum() >= 50:
                w = erpm[m] * 2 * math.pi / 60.0 * 1.0
                kandidaten.append(((duty[m] * d["Accu_V"][m] / math.sqrt(3.0)) / w).median())
                break
    return float(np.median(kandidaten)) if kandidaten else None


def gladder(x, n=12):
    return pd.Series(x).rolling(n, center=True, min_periods=1).median().to_numpy()


def bereken(d, cfg, lam, eta):
    """Voegt de trekkracht per wiel toe."""
    r_band = cfg["omtrek_m"] / (2 * math.pi)
    kt_motor = 1.5 * cfg["poolparen"] * lam                      # Nm per ampere
    for z in "LR":
        i = d[f"Motorstroom_{z}_A"].fillna(0.0)
        d[f"Kracht_{z}_N"] = kt_motor * i * cfg["overbrenging"] * eta / r_band
    d["Kracht_N"] = d["Kracht_L_N"] + d["Kracht_R_N"]
    d["v_ms"] = (d["Wiel_kmh_L"].fillna(0) + d["Wiel_kmh_R"].fillna(0)) / 2 / 3.6
    return kt_motor, r_band


def spanningsval(d):
    """Lineaire fit V = V0 - R x I over de accustroom: (V0, R, aantal punten)."""
    m = (d["Accu_A"] > 2.0) & (d["Accu_V"] > 20)
    if m.sum() < 100:
        return None
    r, v0 = np.polyfit(d.loc[m, "Accu_A"], d.loc[m, "Accu_V"], 1)
    return v0, -r, int(m.sum())


def figuur(d, cfg, kt, lam, vd, uit_pad, titel):
    t = d["t"].to_numpy()
    fig, ax = plt.subplots(4, 2, figsize=(16, 17), constrained_layout=True)
    fig.suptitle(titel, fontsize=14)

    a = ax[0, 0]
    a.plot(t, gladder(d["Wiel_kmh_L"]), color=KLEUR_L, label="wiel L")
    a.plot(t, gladder(d["Wiel_kmh_R"]), color=KLEUR_R, label="wiel R")
    a.plot(t, d["Echt_kmh"], color="grey", lw=0.8, label="GNSS")
    a.set_ylabel("snelheid (km/h)"); a.set_title("Snelheid en duty")
    b = a.twinx()
    b.plot(t, gladder(d["Duty_L"]), color="black", lw=0.8, ls="--", label="duty L")
    b.axhline(0.95, color="orange", lw=0.8)
    b.set_ylim(0, 1.05); b.set_ylabel("duty (1 = vol)")
    a.legend(loc="upper left", ncol=3)

    a = ax[0, 1]
    a.plot(t, gladder(d["Kracht_L_N"]), color=KLEUR_L, label="wiel L")
    a.plot(t, gladder(d["Kracht_R_N"]), color=KLEUR_R, label="wiel R")
    a.axhline(SPEC_TREKKRACHT_N, color="green", ls=":", label="spec 50 kgf per motor")
    a.set_ylabel("trekkracht (N)"); a.set_title(f"Trekkracht per wiel (geschat, lambda {lam:.3f} Wb)")
    k = a.secondary_yaxis("right", functions=(lambda n: n / G, lambda kg: kg * G))
    k.set_ylabel("kgf"); a.legend(loc="upper left", ncol=3)

    a = ax[1, 0]
    a.plot(t, d["Accu_V"], color="tab:green")
    a.set_ylabel("accuspanning (V)"); a.set_title("Accu: spanning en stroom")
    b = a.twinx()
    b.plot(t, gladder(d["Accu_A"]), color="tab:purple", lw=0.8)
    b.set_ylabel("accustroom (A)")
    for v, tekst in ((cfg["cellen"] * 3.0, "leeg 3,0 V/cel"), (cfg["cellen"] * 3.3, "bijna leeg 3,3 V/cel")):
        a.axhline(v, color="red", lw=0.7, ls=":")
        a.text(t[0], v, tekst, color="red", fontsize=8, va="bottom")

    a = ax[1, 1]
    a.plot(t, gladder(d["Accu_W"]), color="tab:purple", label="totaal uit accu")
    a.plot(t, gladder(d["Accustroom_L_A"] * d["Accu_V"]), color=KLEUR_L, lw=0.9, label="wiel L")
    a.plot(t, gladder(d["Accustroom_R_A"] * d["Accu_V"]), color=KLEUR_R, lw=0.9, label="wiel R")
    a.set_ylabel("vermogen (W)"); a.set_title("Elektrisch vermogen uit de accu")
    a.legend(loc="upper left", ncol=3)

    a = ax[2, 0]
    m = (d["Accu_A"] > 0.5) & (d["Accu_V"] > 20)
    a.scatter(d.loc[m, "Accu_A"], d.loc[m, "Accu_V"], s=3, alpha=0.3, color="tab:green")
    if vd:
        v0, r, n = vd
        x = np.array([0, d["Accu_A"].max()])
        a.plot(x, v0 - r * x, color="black",
               label=f"fit: {v0:.1f} V - {r:.3f} ohm x I  ({n} punten)")
        a.axhline(cfg["cellen"] * 3.0, color="red", lw=0.7, ls=":")
        a.legend()
    a.set_xlabel("accustroom (A)"); a.set_ylabel("accuspanning (V)")
    a.set_title(f"Spanningsval = interne weerstand (config: {cfg['weerstand_config']:.2f} ohm)")

    a = ax[2, 1]
    s = d["Wiel_kmh_L"].to_numpy()
    sc = a.scatter(np.r_[s, d["Wiel_kmh_R"].to_numpy()],
                   np.r_[d["Kracht_L_N"].to_numpy(), d["Kracht_R_N"].to_numpy()],
                   s=3, alpha=0.3, c=np.r_[t, t], cmap="viridis")
    a.axhline(SPEC_TREKKRACHT_N, color="green", ls=":")
    a.set_xlabel("wielsnelheid (km/h)"); a.set_ylabel("trekkracht per wiel (N)")
    a.set_title("Kracht tegen snelheid (kleur = tijd in de rit)")
    fig.colorbar(sc, ax=a, label="s")

    a = ax[3, 0]
    a.plot(t, d["Temp_FET_L_C"], color=KLEUR_L, label="FET L")
    a.plot(t, d["Temp_FET_R_C"], color=KLEUR_R, label="FET R")
    a.plot(t, d["Motortemp_model_L_C"], color=KLEUR_L, ls="--", label="motor L (model)")
    a.plot(t, d["Motortemp_model_R_C"], color=KLEUR_R, ls="--", label="motor R (model)")
    a.axhline(105, color="red", lw=0.7, ls=":"); a.text(t[0], 105, "motor beveiliging 105 C", color="red", fontsize=8, va="bottom")
    a.set_ylabel("temperatuur (C)"); a.set_title("Temperaturen"); a.legend(ncol=2)

    a = ax[3, 1]
    a.plot(t, d["Verbruikt_Wh"], color="tab:purple", label="verbruikt (Wh)")
    a.plot(t, d["Teruggeleverd_Wh"], color="tab:green", label="teruggeleverd (Wh)")
    a.set_ylabel("energie (Wh)"); a.set_title("Verbruik en lading"); a.legend(loc="upper left")
    b = a.twinx()
    b.plot(t, d["Accu_pct"], color="black", lw=0.8, ls="--")
    b.set_ylim(0, 100); b.set_ylabel("lading (%), schatting uit spanning")

    for a in ax.flat:
        a.grid(alpha=0.3)
    for a in (ax[0, 0], ax[0, 1], ax[1, 0], ax[1, 1], ax[3, 0], ax[3, 1]):
        a.set_xlabel("tijd in de rit (s)")
    for poging in range(4):                      # Windows geeft soms even Errno 22 op een bestand dat net vrijkomt
        try:
            fig.savefig(uit_pad, dpi=110)
            break
        except OSError:
            if poging == 3:
                raise
            time.sleep(1.0)
    plt.close(fig)


def samenvatting(d, cfg, kt, r_band, lam, eta, vd):
    rijdt = d["v_ms"] > 0.3
    afstand_m = max(d["Afstand_L_m"].iloc[-1] - d["Afstand_L_m"].iloc[0],
                    d["Afstand_R_m"].iloc[-1] - d["Afstand_R_m"].iloc[0])
    duur = d["t"].iloc[-1] - d["t"].iloc[0]
    wh = d["Verbruikt_Wh"].iloc[-1] - d["Verbruikt_Wh"].iloc[0]
    wh_terug = d["Teruggeleverd_Wh"].iloc[-1] - d["Teruggeleverd_Wh"].iloc[0]
    nominaal_wh = cfg["capaciteit_ah"] * cfg["cellen"] * NOMINAAL_V_PER_CEL
    print(f"  duur {duur:.0f} s, gereden {afstand_m:.0f} m (gemiddeld {afstand_m / duur * 3.6:.1f} km/h)")
    print(f"  motorconstante: lambda {lam:.4f} Wb -> {kt:.2f} Nm/A motor, "
          f"{kt * cfg['overbrenging'] * eta / r_band:.1f} N per ampere aan het wiel (kast {eta:.2f})")
    for z in "LR":
        kr = d[f"Kracht_{z}_N"][rijdt]
        i = d[f"Motorstroom_{z}_A"]
        print(f"  wiel {z}: kracht gem {kr.mean():.0f} N, P95 {kr.quantile(.95):.0f} N, max {d[f'Kracht_{z}_N'].max():.0f} N "
              f"({d[f'Kracht_{z}_N'].max() / G:.0f} kgf = {d[f'Kracht_{z}_N'].max() / SPEC_TREKKRACHT_N * 100:.0f}% van de spec); "
              f"stroom gem {i[rijdt].mean():.1f} A, max {i.max():.1f} A")
    verschil = (d["Kracht_L_N"] - d["Kracht_R_N"])[rijdt]
    print(f"  verschil links-rechts: gem {verschil.mean():+.0f} N (een vast verschil wijst op een wiel dat harder werkt "
          f"of weerstand in een wiel); in bochten hoort het buitenwiel meer te doen")
    print(f"  duty: gem {d['Duty_L'][rijdt].mean():.2f} / {d['Duty_R'][rijdt].mean():.2f}, max {max(d['Duty_L'].max(), d['Duty_R'].max()):.2f}; "
          f"{((d['Duty_L'] > 0.9) | (d['Duty_R'] > 0.9)).mean() * 100:.0f}% van de tijd boven 0,90 "
          f"(daar is geen ruimte meer om bij te sturen of bij te trekken)")
    print(f"  accu: {d['Accu_V'].iloc[0]:.1f} -> {d['Accu_V'].iloc[-1]:.1f} V (minimum {d['Accu_V'].min():.1f} V; "
          f"{cfg['cellen']}S leeg bij {cfg['cellen'] * 3.0:.0f} V), lading {d['Accu_pct'].iloc[0]:.0f} -> {d['Accu_pct'].iloc[-1]:.0f}%")
    print(f"  verbruik: {wh:.1f} Wh (teruggeleverd {wh_terug:.1f}) over {afstand_m:.0f} m = "
          f"{wh / max(afstand_m, 1) * 1000:.0f} Wh/km; accu {nominaal_wh:.0f} Wh nominaal "
          f"-> bereik ca. {nominaal_wh / max(wh / max(afstand_m, 1) * 1000, 1e-6):.1f} km (op een volle accu)")
    print(f"  accustroom gem {d['Accu_A'][rijdt].mean():.1f} A, max {d['Accu_A'].max():.1f} A; "
          f"vermogen gem {d['Accu_W'][rijdt].mean():.0f} W, max {d['Accu_W'].max():.0f} W")
    if vd:
        print(f"  interne weerstand uit de spanningsval: {vd[1]:.3f} ohm (config {cfg['weerstand_config']:.2f}); "
              f"rustspanning volgens de fit {vd[0]:.1f} V")
    print(f"  temperatuur: FET max {max(d['Temp_FET_L_C'].max(), d['Temp_FET_R_C'].max()):.0f} C, "
          f"motor (model) max {max(d['Motortemp_model_L_C'].max(), d['Motortemp_model_R_C'].max()):.0f} C")


def fmt(x, n=1):
    """Getal met decimaalkomma; '-' als er niets is."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    return f"{x:,.{n}f}".replace(",", " ").replace(".", ",")


def tabel(kop, rijen, klasse=""):
    """HTML-tabel: kop = lijst kolomnamen, rijen = lijst lijsten (al als tekst)."""
    th = "".join(f"<th>{k}</th>" for k in kop)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rijen)
    return f'<table class="{klasse}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def html_rapport(d, cfg, kt, r_band, lam, eta, vd, png_pad, uit_pad, naam):
    """Zelfstandige HTML met kerngetallen, tabellen, uitleg en bevindingen; het plaatje zit erin."""
    import base64
    t = d["t"].to_numpy()
    dt = np.clip(np.diff(t, prepend=t[0]), 0.0, 1.0)             # s per regel (gaten niet meetellen)
    rijdt = d["v_ms"] > 0.3
    duur = float(t[-1] - t[0])
    afstand = max(d["Afstand_L_m"].iloc[-1] - d["Afstand_L_m"].iloc[0],
                  d["Afstand_R_m"].iloc[-1] - d["Afstand_R_m"].iloc[0])
    wh = d["Verbruikt_Wh"].iloc[-1] - d["Verbruikt_Wh"].iloc[0]
    wh_terug = d["Teruggeleverd_Wh"].iloc[-1] - d["Teruggeleverd_Wh"].iloc[0]
    ah = d["Verbruikt_Ah"].iloc[-1] - d["Verbruikt_Ah"].iloc[0]
    wh_km = wh / max(afstand, 1.0) * 1000.0
    nominaal_wh = cfg["capaciteit_ah"] * cfg["cellen"] * NOMINAAL_V_PER_CEL
    soc0, soc1 = d["Accu_pct"].iloc[0], d["Accu_pct"].iloc[-1]
    cel_min = d["Accu_V"].min() / cfg["cellen"]
    w, a_acc = d["Accu_W"], d["Accu_A"]
    gem_w_rit = wh * 3600.0 / duur                                # energie / tijd, over de hele rit
    kr_max = max(d["Kracht_L_N"].max(), d["Kracht_R_N"].max())
    duty_hoog = ((d["Duty_L"] > 0.9) | (d["Duty_R"] > 0.9)).mean() * 100.0
    verschil = (d["Kracht_L_N"] - d["Kracht_R_N"])[rijdt].mean()
    kr_gem = (d["Kracht_L_N"][rijdt].mean() + d["Kracht_R_N"][rijdt].mean()) / 2.0

    kaarten = [
        ("Gemiddeld vermogen", f"{fmt(w[rijdt].mean(), 0)} W", f"tijdens rijden; hele rit {fmt(gem_w_rit, 0)} W"),
        ("Piekvermogen", f"{fmt(w.max(), 0)} W", f"P95 {fmt(w.quantile(.95), 0)} W"),
        ("Verbruik", f"{fmt(wh_km, 0)} Wh/km", f"{fmt(wh)} Wh over {fmt(afstand, 0)} m"),
        ("Gemiddelde accustroom", f"{fmt(a_acc[rijdt].mean())} A", f"max {fmt(a_acc.max())} A"),
        ("Accuspanning", f"{fmt(d['Accu_V'].iloc[0])} → {fmt(d['Accu_V'].iloc[-1])} V", f"minimum {fmt(d['Accu_V'].min())} V ({fmt(cel_min, 2)} V/cel)"),
        ("Lading (schatting)", f"{fmt(soc0, 0)} → {fmt(soc1, 0)} %", "uit de spanning, niet gemeten"),
        ("Gem. trekkracht per wiel", f"{fmt(kr_gem, 0)} N", f"≈ {fmt(kr_gem / G, 0)} kgf; max {fmt(kr_max, 0)} N"),
        ("Gem. snelheid", f"{fmt(afstand / duur * 3.6)} km/h", f"{fmt(duur, 0)} s, {fmt(afstand, 0)} m"),
    ]
    kaart_html = "".join(f'<div class="kaart"><div class="k">{k}</div><div class="g">{g}</div><div class="s">{s}</div></div>'
                         for k, g, s in kaarten)

    # --- tabel per wiel
    wielrijen = []
    for z, naam_z in (("L", "Links"), ("R", "Rechts")):
        kr = d[f"Kracht_{z}_N"]
        wielrijen.append([
            naam_z,
            f"{fmt(d[f'Wiel_kmh_{z}'][rijdt].mean())} km/h",
            f"{fmt(d[f'Motorstroom_{z}_A'][rijdt].mean())} / {fmt(d[f'Motorstroom_{z}_A'].max())} A",
            f"{fmt(kr[rijdt].mean(), 0)} / {fmt(kr[rijdt].quantile(.95), 0)} / {fmt(kr.max(), 0)} N",
            f"{fmt(kr.max() / SPEC_TREKKRACHT_N * 100, 0)} %",
            f"{fmt(d[f'Duty_{z}'][rijdt].mean(), 2)} / {fmt(d[f'Duty_{z}'].max(), 2)}",
            f"{fmt((d[f'Accustroom_{z}_A'] * d['Accu_V'])[rijdt].mean(), 0)} W",
            f"{fmt(d[f'Temp_FET_{z}_C'].max(), 0)} / {fmt(d[f'Motortemp_model_{z}_C'].max(), 0)} °C",
            f"{fmt(d[f'Afstand_{z}_m'].iloc[-1] - d[f'Afstand_{z}_m'].iloc[0], 0)} m",
        ])
    wiel_tabel = tabel(["Wiel", "Gem. snelheid", "Motorstroom gem / max", "Trekkracht gem / P95 / max",
                        "Max t.o.v. spec", "Duty gem / max", "Gem. vermogen", "Temp. FET / motor max", "Afstand"], wielrijen)

    # --- tabel per modus (rechte baan of draaien)
    modusrijen = []
    for modus, g in d.groupby("Modus"):
        sec = dt[g.index].sum()
        modusrijen.append([
            modus, f"{fmt(sec, 0)} s ({fmt(sec / max(dt.sum(), 1e-9) * 100, 0)} %)",
            f"{fmt(g['v_ms'].mean() * 3.6)} km/h",
            f"{fmt(g['Accu_W'].mean(), 0)} W", f"{fmt(g['Accu_A'].mean())} A",
            f"{fmt((g['Kracht_L_N'].mean() + g['Kracht_R_N'].mean()) / 2, 0)} N",
            f"{fmt((g['Accu_W'] * dt[g.index]).sum() / 3600.0)} Wh"])
    modus_tabel = tabel(["Modus", "Tijd", "Gem. snelheid", "Gem. vermogen", "Gem. accustroom",
                         "Gem. kracht per wiel", "Energie"], modusrijen)

    # --- tabel per snelheidsklasse
    klassen = [(0.3, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 99.0)]
    kmh = d["v_ms"] * 3.6
    snelrijen = []
    for lo, hi in klassen:
        m = (kmh >= lo) & (kmh < hi)
        if m.sum() < 10:
            continue
        snelrijen.append([
            f"{fmt(lo, 0)} - {fmt(hi, 0)} km/h" if hi < 99 else f"boven {fmt(lo, 0)} km/h",
            f"{fmt(dt[m].sum(), 0)} s", f"{fmt(d['Accu_W'][m].mean(), 0)} W", f"{fmt(d['Accu_A'][m].mean())} A",
            f"{fmt((d['Kracht_L_N'][m].mean() + d['Kracht_R_N'][m].mean()) / 2, 0)} N",
            f"{fmt(d['Duty_L'][m].mean(), 2)}",
            f"{fmt(d['Accu_W'][m].mean() / (kmh[m].mean() / 3.6) / 3.6, 0)} Wh/km"])
    snel_tabel = tabel(["Snelheid", "Tijd", "Gem. vermogen", "Gem. accustroom", "Gem. kracht per wiel",
                        "Gem. duty", "Verbruik"], snelrijen)

    # --- tabel per 30 s
    blok = (t - t[0]) // 30
    blokrijen = []
    for b, g in d.groupby(blok):
        blokrijen.append([f"{int(b * 30)} - {int(b * 30 + 30)} s", f"{fmt(g['v_ms'].mean() * 3.6)}",
                          f"{fmt(g['Accu_W'].mean(), 0)}", f"{fmt(g['Accu_V'].mean())}", f"{fmt(g['Accu_A'].mean())}",
                          f"{fmt((g['Kracht_L_N'].mean() + g['Kracht_R_N'].mean()) / 2, 0)}",
                          f"{fmt(g['Duty_L'].max(), 2)}", f"{fmt(g['Accu_pct'].iloc[-1], 0)}"])
    blok_tabel = tabel(["Periode", "km/h", "W", "V", "A", "N per wiel", "Duty max", "Lading %"], blokrijen)

    # --- accu en verbruik
    resterend_wh = nominaal_wh * soc1 / 100.0
    accurijen = [
        ["Accu", f"{cfg['cellen']}S, {fmt(cfg['capaciteit_ah'], 1)} Ah ≈ {fmt(nominaal_wh, 0)} Wh nominaal"],
        ["Spanning begin / eind / minimum", f"{fmt(d['Accu_V'].iloc[0])} / {fmt(d['Accu_V'].iloc[-1])} / {fmt(d['Accu_V'].min())} V"],
        ["Verbruikt in de rit", f"{fmt(wh)} Wh = {fmt(ah, 2)} Ah (teruggeleverd {fmt(wh_terug)} Wh)"],
        ["Verbruik per kilometer", f"{fmt(wh_km, 0)} Wh/km"],
        ["Bereik op een volle accu", f"ca. {fmt(nominaal_wh / max(wh_km, 1e-6), 1)} km (bij dit verbruik)"],
        ["Bereik op de huidige lading", f"ca. {fmt(resterend_wh / max(wh_km, 1e-6), 1)} km (bij {fmt(soc1, 0)} % ≈ {fmt(resterend_wh, 0)} Wh)"],
        ["Interne weerstand (spanningsval)", (f"{fmt(vd[1], 3)} Ω (config {fmt(cfg['weerstand_config'], 2)} Ω); rustspanning volgens fit {fmt(vd[0])} V"
                                              if vd else "te weinig data")],
        ["Spanningsval bij piekstroom", (f"{fmt(vd[1] * a_acc.max())} V bij {fmt(a_acc.max())} A" if vd else "-")],
    ]
    accu_tabel = tabel(["Onderdeel", "Waarde"], accurijen, "twee")

    # --- bevindingen
    bev = []
    if duty_hoog >= 1.0:
        bev.append(("let op", f"De duty is {fmt(duty_hoog, 0)} % van de tijd boven 0,90. Dan heeft de regeling geen ruimte meer om "
                    "bij te sturen of sneller te gaan; de topsnelheid wordt begrensd door de accuspanning, niet door het toerental."))
    if cel_min < 3.3:
        bev.append(("let op", f"Onder belasting zakte de accu tot {fmt(cel_min, 2)} V per cel (grens 'bijna leeg': 3,3 V). "
                    "Laad de accu voor een vergelijkbare rit eerst op."))
    if soc0 < 25:
        bev.append(("let op", f"De rit begon met een lage lading (ongeveer {fmt(soc0, 0)} %). Spanning, snelheid en verbruik zijn daardoor "
                    "niet vergelijkbaar met ritten op een volle accu."))
    if vd and abs(vd[1] - cfg["weerstand_config"]) / cfg["weerstand_config"] > 0.25:
        bev.append(("info", f"De gemeten interne weerstand ({fmt(vd[1], 3)} Ω) wijkt meer dan 25 % af van de config "
                    f"({fmt(cfg['weerstand_config'], 2)} Ω). Het % lading op het dashboard is dan iets minder betrouwbaar."))
    if abs(verschil) > max(10.0, 0.1 * kr_gem):
        bev.append(("info", f"Links en rechts verschillen gemiddeld {fmt(abs(verschil), 0)} N. Het {'linker' if verschil > 0 else 'rechter'} wiel "
                    "werkt harder; kan komen door bochten de ene kant op, een schuin veld of meer weerstand in dat wiel."))
    if kr_max / SPEC_TREKKRACHT_N > 0.8:
        bev.append(("let op", f"De piekkracht ({fmt(kr_max, 0)} N) zit dicht bij de spec van 490 N per motor."))
    else:
        bev.append(("goed", f"De trekkracht blijft ruim onder de spec: piek {fmt(kr_max, 0)} N van 490 N "
                    f"({fmt(kr_max / SPEC_TREKKRACHT_N * 100, 0)} %). Er is reserve voor een helling of zware grond."))
    temp_max = max(d["Temp_FET_L_C"].max(), d["Temp_FET_R_C"].max(), d["Motortemp_model_L_C"].max(), d["Motortemp_model_R_C"].max())
    bev.append(("goed" if temp_max < 80 else "let op", f"Hoogste temperatuur {fmt(temp_max, 0)} °C "
                f"(motorbeveiliging grijpt in bij 105 °C)."))
    bev_html = "".join(f'<li class="{n.replace(" ", "")}"><b>{n}</b> {tk}</li>' for n, tk in bev)

    with open(png_pad, "rb") as f:
        png64 = base64.b64encode(f.read()).decode()

    uitleg = """
<dl>
<dt>Vermogen (W)</dt><dd>Wat de accu levert: accuspanning x accustroom. Het <i>gemiddelde tijdens rijden</i> telt alleen de momenten dat de robot beweegt; het gemiddelde over de hele rit is energie gedeeld door tijd.</dd>
<dt>Motorstroom en accustroom</dt><dd>De motorstroom is de stroom die het koppel levert (per wiel). De accustroom is wat de accu levert; bij lage duty is die kleiner dan de motorstroom (de VESC zet spanning om in stroom: accustroom &asymp; duty x motorstroom).</dd>
<dt>Duty</dt><dd>Hoeveel van de accuspanning de motor krijgt: 1,0 is vol. Hoe leger de accu, hoe hoger de duty voor dezelfde snelheid. Rond 0,95 houdt het op.</dd>
<dt>Trekkracht</dt><dd>Geschat uit de motorstroom: koppel = 1,5 x poolparen x &lambda; x stroom, door de kast (x overbrenging x rendement) en gedeeld door de bandstraal. Het is een berekening, geen meting; ijk hem met een krachtmeter. &lambda; komt uit de log zelf.</dd>
<dt>Verbruik (Wh/km)</dt><dd>Energie per afgelegde kilometer. Hoger bij hogere snelheid, zware grond, veel bochten en veel optrekken.</dd>
<dt>Interne weerstand</dt><dd>De accuspanning zakt bij meer stroom. Het verband tussen stroom en spanning geeft de interne weerstand; hoger = oudere of kouder pak of slechtere verbinding.</dd>
<dt>Lading (%)</dt><dd>Een schatting uit de spanning, gecorrigeerd voor de spanningsval. Betrouwbaar als balk, niet tot op de procent.</dd>
</dl>"""
    html = f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aandrijving en accu</title>
<style>
:root{{--bg:#f6f7f4;--kaart:#fff;--tekst:#1c2321;--zacht:#5b6763;--lijn:#dde2de;--goed:#2d7a46;--let:#b4531f;--info:#2f5d8a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14181a;--kaart:#1d2326;--tekst:#e6ebe8;--zacht:#9aa6a1;--lijn:#2d3639;--goed:#5fbf82;--let:#e8905a;--info:#78a9d8}}}}
body{{margin:0;background:var(--bg);color:var(--tekst);font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:1.5rem;margin:0 0 2px}} h2{{font-size:1.15rem;margin:32px 0 10px}}
.sub{{color:var(--zacht);margin-bottom:18px;word-break:break-all}}
.kaarten{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
.kaart{{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;padding:12px 14px}}
.kaart .k{{color:var(--zacht);font-size:.8rem}} .kaart .g{{font-size:1.45rem;font-weight:650;margin:2px 0}} .kaart .s{{color:var(--zacht);font-size:.8rem}}
.tw{{overflow-x:auto;background:var(--kaart);border:1px solid var(--lijn);border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:7px 12px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--lijn)}}
th:first-child,td:first-child{{text-align:left}} th{{font-size:.78rem;color:var(--zacht);font-weight:600}}
tr:last-child td{{border-bottom:0}} table.twee td:last-child{{text-align:left;white-space:normal}}
ul{{list-style:none;padding:0;margin:0}} li{{background:var(--kaart);border:1px solid var(--lijn);border-left:4px solid var(--info);border-radius:8px;padding:9px 12px;margin-bottom:8px}}
li.goed{{border-left-color:var(--goed)}} li.letop{{border-left-color:var(--let)}} li b{{text-transform:uppercase;font-size:.72rem;letter-spacing:.05em;margin-right:6px}}
li.goed b{{color:var(--goed)}} li.letop b{{color:var(--let)}} li.info b{{color:var(--info)}}
dt{{font-weight:600;margin-top:10px}} dd{{margin:2px 0 0;color:var(--zacht)}}
img{{width:100%;height:auto;border-radius:10px;border:1px solid var(--lijn);background:#fff}}
p.noot{{color:var(--zacht);font-size:.85rem}}
</style></head><body><main>
<h1>Aandrijving en accu</h1>
<div class="sub">{naam}</div>
<div class="kaarten">{kaart_html}</div>

<h2>Bevindingen</h2><ul>{bev_html}</ul>

<h2>Per wiel</h2><div class="tw">{wiel_tabel}</div>
<p class="noot">Kracht is geschat (&lambda; {fmt(lam, 4)} Wb = {fmt(kt, 2)} Nm/A motor, kast {fmt(eta, 2)}, band {fmt(r_band * 100, 1)} cm straal); spec: 490 N (50 kgf) per motor. Gemiddelden zijn over de momenten dat de robot rijdt.</p>

<h2>Accu en verbruik</h2><div class="tw">{accu_tabel}</div>

<h2>Per rijmodus</h2><div class="tw">{modus_tabel}</div>
<p class="noot">TRACKING = op de baan rijden, TURNING = keren op de kopakker.</p>

<h2>Per snelheid</h2><div class="tw">{snel_tabel}</div>
<p class="noot">Wat elke snelheid kost. Het verbruik per kilometer is vermogen gedeeld door snelheid; blijft dat ongeveer gelijk, dan zit het verbruik vooral in rolweerstand en niet in de snelheid zelf.</p>

<h2>Verloop per 30 seconden</h2><div class="tw">{blok_tabel}</div>

<h2>Grafieken</h2><img alt="Grafieken" src="data:image/png;base64,{png64}">

<h2>Uitleg</h2>{uitleg}
</main></body></html>"""
    with open(uit_pad, "w", encoding="utf-8") as f:
        f.write(html)


def verwerk(pad, cfg, lam_arg, eta):
    naam = os.path.splitext(os.path.basename(pad))[0]
    d = lees_rit(pad)
    if len(d) < 50 or "Motorstroom_L_A" not in d or d["Motorstroom_L_A"].notna().sum() < 50:
        print(f"{naam}: geen aandrijfdata in deze log (oude rit?), overgeslagen.")
        return
    lam = lam_arg or schat_lambda(d)
    if not lam:
        print(f"{naam}: lambda niet te schatten (te weinig regels bij middelhoog toerental); geef --lambda op.")
        return
    kt, r_band = bereken(d, cfg, lam, eta)
    vd = spanningsval(d)
    print(f"\n{naam}")
    samenvatting(d, cfg, kt, r_band, lam, eta, vd)
    uit = os.path.join(os.path.dirname(pad), naam + "_aandrijving.png")
    figuur(d, cfg, kt, lam, vd, uit, f"{naam}: aandrijving en accu")
    print(f"  Plaatje: {os.path.relpath(uit)}")
    uit_html = os.path.join(os.path.dirname(pad), naam + "_aandrijving.html")
    html_rapport(d, cfg, kt, r_band, lam, eta, vd, uit, uit_html, naam)
    print(f"  Rapport: {os.path.relpath(uit_html)}")


def main():
    p = argparse.ArgumentParser(description="Trekkracht, vermogen en accugedrag uit een ritlog.")
    p.add_argument("bestanden", nargs="*", help="ritlog(s); zonder: de nieuwste rit in data/logs")
    p.add_argument("--alle", action="store_true", help="alle ritten in data/logs")
    p.add_argument("--lambda", dest="lam", type=float, help="flux linkage in Wb (uit VESC Tool); anders geschat uit de log")
    p.add_argument("--kast-rendement", type=float, default=0.9, help="rendement van de 5:1 kast (standaard 0,9)")
    args = p.parse_args()

    if args.bestanden:
        paden = [f for patroon in args.bestanden for f in sorted(glob.glob(patroon))]
    else:
        # Op de datum_tijd in de bestandsnaam; ritten zonder (old_code) komen eerst.
        def sleutel(f):
            m = re.search(r"(\d{8}_\d{6})\.csv$", f)
            return m.group(1) if m else ""
        alle = sorted(glob.glob(os.path.join(LOG_DIR, "rit_*.csv")), key=sleutel)
        paden = alle if args.alle else alle[-1:]
    if not paden:
        sys.exit("Geen ritlogs gevonden.")
    cfg = laad_config()
    for pad in paden:
        verwerk(pad, cfg, args.lam, args.kast_rendement)


if __name__ == "__main__":
    main()
