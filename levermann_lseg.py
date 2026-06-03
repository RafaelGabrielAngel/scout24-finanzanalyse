"""
Scout24 SE — Levermann-Score Analyse via LSEG Workspace
=========================================================
Berechnet alle 13 Levermann-Kriterien für Large Caps (DAX-Standard)
nach der Methodik von Susan Levermann ("Der entspannte Weg zum Reichtum").

VORAUSSETZUNG: LSEG Workspace läuft, pip install lseg-data

AUSFÜHRUNG:
    python levermann_lseg.py

Ergebnis wird in data.json als "levermann"-Sektion gespeichert.

Levermann-Skala für Large Caps:
    Gesamt ≥ 4  → KAUFEN
    -3 bis +3   → HALTEN
    ≤ -4        → VERKAUFEN
"""

import json
import datetime
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────
APP_KEY  = "4776ea80927f44ec8b12897bc6b0cab4b2ad4f88"
RIC      = "DE000A12DM80"        # Scout24 SE ISIN (verifiziert)
OUTPUT   = Path(__file__).parent / "data.json"

try:
    import lseg.data as ld
    ld.open_session(app_key=APP_KEY)
    print("[OK] LSEG Workspace verbunden")
except Exception as e:
    raise SystemExit(f"[ERROR] LSEG nicht verbunden: {e}")

def get(fields, params=None):
    """LSEG get_data mit Fehlerbehandlung."""
    try:
        df = ld.get_data(RIC, fields, parameters=params or {})
        if df is None or df.empty:
            return {}
        return df.iloc[0].to_dict()
    except Exception as e:
        print(f"  [WARN] Felder {fields}: {e}")
        return {}

def sf(row, *keys):
    """Sicherer Float — durchsucht mehrere mögliche Spaltennamen."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                f = float(v)
                if f == f:  # NaN check
                    return f
            except:
                pass
    return None

def score(value, thresholds, points):
    """Gibt Punkte zurück basierend auf Schwellenwerten."""
    if value is None:
        return 0, "n/a"
    for i, t in enumerate(thresholds):
        if value >= t:
            return points[i], f"{value:.2f}"
    return points[-1], f"{value:.2f}"

# ══════════════════════════════════════════════════════════════
# DIE 13 LEVERMANN-KRITERIEN (Large Cap Version)
# ══════════════════════════════════════════════════════════════

results = {}

print("\n" + "="*60)
print("Scout24 SE — Levermann-Score (13 Kriterien, Large Cap)")
print("="*60)

# ── Kriterium 1: Return on Equity (RoE) ──────────────────────
print("\n[K1] Return on Equity...")
row1 = get(['TR.ReturnOnEquityActValue', 'TR.ROE', 'TR.ReturnOnEquity'])
roe = sf(row1, 'Return On Equity (Actual Value)', 'Return On Equity', 'ROE')
if roe and abs(roe) < 5:
    roe = roe * 100  # Dezimal → Prozent
k1_val = roe
if k1_val:
    k1 = 1 if k1_val > 20 else (0 if k1_val >= 10 else -1)
    k1_reason = f"RoE = {k1_val:.1f}% (≥20%=+1, 10-20%=0, <10%=-1)"
else:
    k1, k1_reason = 0, "Keine Daten"
print(f"  RoE: {k1_val}% → {k1:+d} Punkte")
results['k1_roe'] = {'value': k1_val, 'score': k1, 'label': 'Return on Equity', 'reason': k1_reason}

# ── Kriterium 2: EBIT-Marge ───────────────────────────────────
print("\n[K2] EBIT-Marge...")
row2 = get(['TR.EBITMarginActValue', 'TR.EBITMargin'])
ebit_margin = sf(row2, 'EBIT Margin (Actual Value)', 'EBIT Margin')
# Fallback: aus Financials berechnen (EBIT / Revenue)
if ebit_margin is None:
    row2b = get(['TR.EBIT', 'TR.Revenue'])
    ebit = sf(row2b, 'EBIT')
    rev  = sf(row2b, 'Revenue')
    if ebit and rev and rev > 0:
        ebit_margin = (ebit / rev) * 100
if ebit_margin and abs(ebit_margin) < 2:
    ebit_margin = ebit_margin * 100
k2_val = ebit_margin
if k2_val:
    k2 = 1 if k2_val > 12 else (0 if k2_val >= 6 else -1)
    k2_reason = f"EBIT-Marge = {k2_val:.1f}% (≥12%=+1, 6-12%=0, <6%=-1)"
else:
    k2, k2_reason = 0, "Keine Daten"
print(f"  EBIT-Marge: {k2_val}% → {k2:+d} Punkte")
results['k2_ebit_margin'] = {'value': k2_val, 'score': k2, 'label': 'EBIT-Marge', 'reason': k2_reason}

# ── Kriterium 3: Eigenkapitalquote ────────────────────────────
print("\n[K3] Eigenkapitalquote...")
row3 = get(['TR.TotalEquity', 'TR.TotalAssets'])
eq  = sf(row3, 'Total Equity')
ta  = sf(row3, 'Total Assets')
eq_ratio = (eq / ta * 100) if (eq and ta and ta > 0) else None
k3_val = eq_ratio
if k3_val:
    k3 = 1 if k3_val > 25 else (0 if k3_val >= 15 else -1)
    k3_reason = f"EK-Quote = {k3_val:.1f}% (≥25%=+1, 15-25%=0, <15%=-1)"
else:
    k3, k3_reason = 0, "Keine Daten"
print(f"  EK-Quote: {k3_val}% → {k3:+d} Punkte")
results['k3_equity_ratio'] = {'value': k3_val, 'score': k3, 'label': 'Eigenkapitalquote', 'reason': k3_reason}

# ── Kriterium 4: KGV aktuell (P/E) ───────────────────────────
print("\n[K4] KGV aktuell...")
row4 = get(['TR.PETotalReturn', 'TR.PE'])
pe = sf(row4, 'P/E Total Return', 'P/E')
k4_val = pe
if k4_val and k4_val > 0:
    k4 = 1 if k4_val < 12 else (0 if k4_val <= 16 else -1)
    k4_reason = f"KGV = {k4_val:.1f}× (<12=+1, 12-16=0, >16=-1)"
else:
    k4, k4_reason = 0, "Keine Daten oder negativ"
print(f"  KGV: {k4_val}× → {k4:+d} Punkte")
results['k4_pe'] = {'value': k4_val, 'score': k4, 'label': 'KGV aktuell', 'reason': k4_reason}

# ── Kriterium 5: KGV 5-Jahres-Durchschnitt ───────────────────
print("\n[K5] KGV 5-Jahres-Durchschnitt...")
pe_hist = []
for yr in range(1, 6):
    r = get(['TR.PETotalReturn'], {'Period': f'FY-{yr}'})
    v = sf(r, 'P/E Total Return', 'P/E')
    if v and 0 < v < 200:
        pe_hist.append(v)
pe5y = sum(pe_hist) / len(pe_hist) if pe_hist else None
k5_val = pe5y
if k5_val:
    k5 = 1 if k5_val < 12 else (0 if k5_val <= 16 else -1)
    k5_reason = f"KGV 5J-Ø = {k5_val:.1f}× (aus {len(pe_hist)} Jahren, <12=+1, 12-16=0, >16=-1)"
else:
    k5, k5_reason = -1, "Nicht verfügbar — Annahme: historisch >16× → -1"
    k5_val = None
print(f"  KGV 5J-Ø: {k5_val}× → {k5:+d} Punkte")
results['k5_pe5y'] = {'value': k5_val, 'score': k5, 'label': 'KGV 5-Jahres-Ø', 'reason': k5_reason}

# ── Kriterium 6: Analystenrating (KONTRÄR) ────────────────────
print("\n[K6] Analystenrating (konträr)...")
row6 = get(['TR.RecommendationMean', 'TR.TotalBuyRecom', 'TR.TotalHoldRecom', 'TR.TotalSellRecom'])
rec_mean = sf(row6, 'Recommendation Mean')
buy  = sf(row6, 'Total Buy Recommendations') or 0
hold = sf(row6, 'Total Hold Recommendations') or 0
sell = sf(row6, 'Total Sell Recommendations') or 0
# Levermann-Skala: 1=Strong Buy, 5=Strong Sell. KONTRÄR:
# ≤ 2.0 (bullischer Konsens) → -1 | 2.0-3.5 → 0 | > 3.5 → +1
k6_val = rec_mean
if k6_val:
    k6 = -1 if k6_val <= 2.0 else (0 if k6_val <= 3.5 else 1)
    k6_reason = f"Rec-Mean = {k6_val:.2f} (KONTRÄR: ≤2.0=-1, 2.0-3.5=0, ≥3.5=+1) | Buy:{buy} Hold:{hold} Sell:{sell}"
else:
    k6, k6_reason = -1, "100% Buy-Konsens angenommen → konträr -1"
print(f"  Rec-Mean: {k6_val} → {k6:+d} Punkte (konträr!)")
results['k6_analyst'] = {'value': k6_val, 'score': k6, 'label': 'Analystenrating (konträr)', 'reason': k6_reason,
                          'buy': int(buy), 'hold': int(hold), 'sell': int(sell)}

# ── Kriterium 7: Kursreaktion auf letzten Quartalsbericht ─────
print("\n[K7] Kursreaktion auf letzten Quartalsbericht...")
# Earnings Date + 1-Tages-Rendite am Reporting-Tag
row7 = get(['TR.EPSReportDate'])
earn_date = str(row7.get('EPS Report Date', ''))[:10] if row7 else ''
k7_val = None
if earn_date:
    # Kurs am Earnings-Tag vs. Tag davor
    import time; time.sleep(0.5)
    try:
        ts = ld.get_history(RIC, fields=['TRDPRC_1'], start=earn_date, end=earn_date)
        if ts is not None and not ts.empty:
            k7_val = float(ts['TRDPRC_1'].pct_change().iloc[-1] * 100)
    except Exception as e:
        print(f"  [WARN] Kursreaktion: {e}")
if k7_val is not None:
    k7 = 1 if k7_val >= 1 else (0 if k7_val >= -1 else -1)
    k7_reason = f"Kursreaktion am {earn_date}: {k7_val:+.2f}% (≥+1%=+1, -1%/+1%=0, ≤-1%=-1)"
else:
    k7, k7_reason = 0, f"Earnings-Datum: {earn_date or 'unbekannt'} — Keine Daten verfügbar"
print(f"  Kursreaktion Quartalsbericht: {k7_val}% → {k7:+d} Punkte")
results['k7_earnings_reaction'] = {'value': k7_val, 'score': k7, 'label': 'Kursreaktion Quartalsbericht',
                                    'reason': k7_reason, 'earnings_date': earn_date}

# ── Kriterium 8: Gewinnrevision aktuell ──────────────────────
print("\n[K8] Gewinnrevision (EPS-Schätzung aktuell vs. vor 6M)...")
row8_now  = get(['TR.EPSMeanEstimate'], {'Period': 'FY1'})
row8_6m   = get(['TR.EPSMeanEstimate'], {'Period': 'FY1', 'SDate': (datetime.date.today() - datetime.timedelta(days=180)).isoformat()})
eps_now   = sf(row8_now,  'Earnings Per Share - Mean Estimate', 'EPS Mean Estimate')
eps_6mago = sf(row8_6m,   'Earnings Per Share - Mean Estimate', 'EPS Mean Estimate')
if eps_now and eps_6mago and eps_6mago != 0:
    rev_pct = (eps_now - eps_6mago) / abs(eps_6mago) * 100
    k8_val  = rev_pct
    k8 = 1 if rev_pct > 5 else (0 if rev_pct >= -5 else -1)
    k8_reason = f"EPS jetzt: {eps_now:.2f} vs. vor 6M: {eps_6mago:.2f} → {rev_pct:+.1f}% (>+5%=+1, ±5%=0, <-5%=-1)"
else:
    k8, k8_reason = 0, f"EPS jetzt: {eps_now} | vor 6M: {eps_6mago} — Revision nicht berechenbar"
    k8_val = None
print(f"  EPS-Revision: {k8_val}% → {k8:+d} Punkte")
results['k8_eps_revision'] = {'value': k8_val, 'score': k8, 'label': 'Gewinnrevision (6M)', 'reason': k8_reason,
                               'eps_now': eps_now, 'eps_6m_ago': eps_6mago}

# ── Kriterium 9: Kursentwicklung 6 Monate ────────────────────
print("\n[K9] Kursentwicklung 6 Monate...")
try:
    date_6m = (datetime.date.today() - datetime.timedelta(days=182)).isoformat()
    hist_6m = ld.get_history(RIC, fields=['TRDPRC_1'], start=date_6m, end=datetime.date.today().isoformat())
    if hist_6m is not None and not hist_6m.empty and len(hist_6m) >= 2:
        p_now  = float(hist_6m['TRDPRC_1'].iloc[-1])
        p_6m   = float(hist_6m['TRDPRC_1'].iloc[0])
        k9_val = (p_now - p_6m) / p_6m * 100
        k9 = 1 if k9_val > 5 else (0 if k9_val >= -5 else -1)
        k9_reason = f"Kurs heute: {p_now:.2f} vs. vor 6M: {p_6m:.2f} → {k9_val:+.1f}% (>+5%=+1, ±5%=0, <-5%=-1)"
    else:
        k9, k9_reason, k9_val = 0, "Keine Kursdaten", None
except Exception as e:
    k9, k9_reason, k9_val = 0, f"Fehler: {e}", None
print(f"  6M-Performance: {k9_val}% → {k9:+d} Punkte")
results['k9_perf_6m'] = {'value': k9_val, 'score': k9, 'label': 'Kursentwicklung 6 Monate', 'reason': k9_reason}

# ── Kriterium 10: Kursentwicklung 12 Monate ──────────────────
print("\n[K10] Kursentwicklung 12 Monate...")
try:
    date_12m = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    hist_12m = ld.get_history(RIC, fields=['TRDPRC_1'], start=date_12m, end=datetime.date.today().isoformat())
    if hist_12m is not None and not hist_12m.empty and len(hist_12m) >= 2:
        p_now   = float(hist_12m['TRDPRC_1'].iloc[-1])
        p_12m   = float(hist_12m['TRDPRC_1'].iloc[0])
        k10_val = (p_now - p_12m) / p_12m * 100
        k10 = 1 if k10_val > 5 else (0 if k10_val >= -5 else -1)
        k10_reason = f"Kurs heute: {p_now:.2f} vs. vor 12M: {p_12m:.2f} → {k10_val:+.1f}% (>+5%=+1, ±5%=0, <-5%=-1)"
    else:
        k10, k10_reason, k10_val = 0, "Keine Kursdaten", None
        p_12m = None
except Exception as e:
    k10, k10_reason, k10_val = 0, f"Fehler: {e}", None
    p_12m = None
print(f"  12M-Performance: {k10_val}% → {k10:+d} Punkte")
results['k10_perf_12m'] = {'value': k10_val, 'score': k10, 'label': 'Kursentwicklung 12 Monate', 'reason': k10_reason}

# ── Kriterium 11: Kursmomentum (6M vs 12M) ───────────────────
print("\n[K11] Kursmomentum (Beschleunigung 6M vs 12M)...")
k9_val_safe  = results['k9_perf_6m']['value']
k10_val_safe = results['k10_perf_12m']['value']
if k9_val_safe is not None and k10_val_safe is not None:
    # Levermann: 6M > 12M Performance → positives Momentum → +1
    if k9_val_safe > k10_val_safe and k9_val_safe > 0:
        k11, k11_reason = 1, f"6M ({k9_val_safe:+.1f}%) > 12M ({k10_val_safe:+.1f}%) & positiv → Momentum beschleunigt"
    elif k9_val_safe > 0 and k10_val_safe < 0:
        k11, k11_reason = 1, f"6M positiv, 12M negativ → Trendwende"
    elif k9_val_safe < 0 and k10_val_safe < 0:
        k11, k11_reason = -1, f"6M ({k9_val_safe:+.1f}%) und 12M ({k10_val_safe:+.1f}%) negativ → negativer Trend"
    else:
        k11, k11_reason = 0, f"6M ({k9_val_safe:+.1f}%) vs 12M ({k10_val_safe:+.1f}%) — neutrales Momentum"
    k11_val = round(k9_val_safe - k10_val_safe, 1)
else:
    k11, k11_reason, k11_val = 0, "Keine Kursdaten für Momentum-Berechnung", None
print(f"  Momentum: {k11_val}% Differenz → {k11:+d} Punkte")
results['k11_momentum'] = {'value': k11_val, 'score': k11, 'label': 'Kursmomentum (6M vs 12M)', 'reason': k11_reason}

# ── Kriterium 12: Gewinnrevision 3 Monate ────────────────────
print("\n[K12] Gewinnrevision 3 Monate...")
row12_3m = get(['TR.EPSMeanEstimate'], {'Period': 'FY1',
    'SDate': (datetime.date.today() - datetime.timedelta(days=90)).isoformat()})
eps_3mago = sf(row12_3m, 'Earnings Per Share - Mean Estimate', 'EPS Mean Estimate')
if eps_now and eps_3mago and eps_3mago != 0:
    rev3_pct = (eps_now - eps_3mago) / abs(eps_3mago) * 100
    k12_val  = rev3_pct
    k12 = 1 if rev3_pct > 2 else (0 if rev3_pct >= -2 else -1)
    k12_reason = f"EPS jetzt: {eps_now:.2f} vs. vor 3M: {eps_3mago:.2f} → {rev3_pct:+.1f}% (>+2%=+1, ±2%=0, <-2%=-1)"
else:
    k12, k12_reason = 0, f"EPS jetzt: {eps_now} | vor 3M: {eps_3mago} — Revision nicht berechenbar"
    k12_val = None
print(f"  EPS-Revision 3M: {k12_val}% → {k12:+d} Punkte")
results['k12_eps_rev_3m'] = {'value': k12_val, 'score': k12, 'label': 'Gewinnrevision (3M)', 'reason': k12_reason}

# ── Kriterium 13: Gewinnüberraschung letztes Quartal ──────────
print("\n[K13] Gewinnüberraschung (Actual vs. Konsens)...")
row13 = get(['TR.EPSActValue', 'TR.EPSMeanEstimate'], {'Period': 'FQ-1'})
eps_act  = sf(row13, 'EPS (Actual Value)', 'Earnings Per Share')
eps_est  = sf(row13, 'Earnings Per Share - Mean Estimate', 'EPS Mean Estimate')
if eps_act is not None and eps_est is not None and eps_est != 0:
    surprise_pct = (eps_act - eps_est) / abs(eps_est) * 100
    k13_val = surprise_pct
    k13 = 1 if surprise_pct > 2 else (0 if surprise_pct >= -2 else -1)
    k13_reason = f"EPS actual: {eps_act:.2f} vs. Konsens: {eps_est:.2f} → {surprise_pct:+.1f}% (>+2%=+1, ±2%=0, <-2%=-1)"
else:
    k13, k13_reason = 0, f"EPS actual: {eps_act} | Konsens: {eps_est} — Keine Daten"
    k13_val = None
print(f"  Gewinnüberraschung: {k13_val}% → {k13:+d} Punkte")
results['k13_eps_surprise'] = {'value': k13_val, 'score': k13, 'label': 'Gewinnüberraschung', 'reason': k13_reason}

# ══════════════════════════════════════════════════════════════
# GESAMTAUSWERTUNG
# ══════════════════════════════════════════════════════════════

keys_ordered = ['k1_roe','k2_ebit_margin','k3_equity_ratio','k4_pe','k5_pe5y',
                'k6_analyst','k7_earnings_reaction','k8_eps_revision','k9_perf_6m',
                'k10_perf_12m','k11_momentum','k12_eps_rev_3m','k13_eps_surprise']

total_score = sum(results[k]['score'] for k in keys_ordered)

if total_score >= 4:
    rating = "KAUFEN"
    rating_color = "green"
elif total_score <= -4:
    rating = "VERKAUFEN"
    rating_color = "red"
else:
    rating = "HALTEN"
    rating_color = "amber"

levermann = {
    "_meta": {
        "calculated": datetime.datetime.now().isoformat(),
        "source": "LSEG Workspace",
        "ric": RIC,
        "method": "Levermann Large Cap (13 Kriterien)",
        "scale": "≥+4=KAUFEN, -3 bis +3=HALTEN, ≤-4=VERKAUFEN"
    },
    "total_score": total_score,
    "rating": rating,
    "rating_color": rating_color,
    "criteria": results,
    "ordered_keys": keys_ordered,
}

# ── Print Summary ─────────────────────────────────────────────
print("\n" + "="*60)
print(f"LEVERMANN-SCORE: {total_score:+d} → {rating}")
print("="*60)
print(f"{'Kriterium':<35} {'Wert':<12} {'Punkte'}")
print("-"*60)
for k in keys_ordered:
    r = results[k]
    lbl = r['label']
    val = f"{r['value']:.2f}" if r['value'] is not None else "n/a"
    sc  = r['score']
    arrow = "✅" if sc == 1 else ("❌" if sc == -1 else "➖")
    print(f"  {lbl:<33} {val:<12} {arrow} {sc:+d}")
print("-"*60)
print(f"  {'GESAMT':<33} {'':12} {total_score:+d} → {rating}")
print("="*60)

# ── In data.json speichern ────────────────────────────────────
try:
    with open(OUTPUT) as f:
        data = json.load(f)
except:
    data = {}

data['levermann'] = levermann

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"\n✓ Levermann-Score in data.json gespeichert: {OUTPUT}")
print(f"\nNächster Schritt:")
print(f"  git add data.json && git commit -m 'data: Levermann {total_score:+d} {rating}' && git push")
