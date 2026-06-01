"""
Scout24 SE — LSEG Workspace Data Fetcher
==========================================
Zieht institutionelle Daten aus LSEG Workspace (ehemals Refinitiv Eikon)
und schreibt ein reiches data.json für das Equity Research Dashboard.

VORAUSSETZUNG:
  - LSEG Workspace Desktop-App muss laufen
  - pip install lseg-data eikon

AUSFÜHRUNG:
  python fetcher_lseg.py

Das erzeugte data.json committen und pushen:
  git add data.json && git commit -m "data: LSEG update $(date +%Y-%m-%d)" && git push
"""

import json
import datetime
import time
from pathlib import Path

# ── Konfiguration ───────────────────────────────────────────────────────────
APP_KEY   = "4776ea80927f44ec8b12897bc6b0cab4b2ad4f88"
RIC_MAIN  = "SDXG.DE"          # Scout24 SE auf XETRA (Refinitiv RIC)
RIC_ALT   = "SDX.DE"           # Fallback-RIC
OUTPUT    = Path(__file__).parent / "data.json"

PEER_RICS = {
    "Rightmove":   "RMV.L",
    "Auto Trader": "AUTO.L",
    "REA Group":   "REA.AX",
    "Hemnet":      "HEM.ST",
    "Immowelt":    "HMWG.DE",   # Immowelt / HausHeld (Monitoring)
}

# ── LSEG / Eikon Library laden ──────────────────────────────────────────────
ld = None
ek = None

try:
    import lseg.data as _ld
    _ld.open_session(app_key=APP_KEY)
    ld = _ld
    print("[OK] lseg-data Bibliothek verbunden")
except Exception as e:
    print(f"[INFO] lseg-data nicht verfügbar ({e}) — versuche eikon...")
    try:
        import eikon as _ek
        _ek.set_app_key(APP_KEY)
        ek = _ek
        print("[OK] eikon Bibliothek verbunden")
    except Exception as e2:
        raise SystemExit(
            f"[ERROR] Weder lseg-data noch eikon verbunden: {e2}\n"
            "Bitte sicherstellen dass LSEG Workspace läuft und 'pip install lseg-data eikon' ausgeführt wurde."
        )

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def get_data(rics, fields, params=None):
    """Universeller Wrapper für lseg-data und eikon."""
    try:
        if ld:
            df = ld.get_data(rics, fields, parameters=params or {})
            return df, None
        elif ek:
            df, err = ek.get_data(rics, fields, parameters=params or {})
            return df, err
    except Exception as e:
        return None, str(e)

def safe_float(val, default=0.0):
    """Konvertiert beliebige Werte zu float, gibt default bei Fehler."""
    try:
        if val is None or str(val).strip() in ('', 'nan', 'NaN', 'N/A', '<NA>'):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    try:
        return int(safe_float(val, default))
    except:
        return default

def first_row(df):
    """Gibt erste Zeile als dict zurück."""
    if df is None or df.empty:
        return {}
    return df.iloc[0].to_dict()

# ─────────────────────────────────────────────────────────────────────────────
# 1. MARKTDATEN & KURS (Real-Time / EOD)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market():
    print("\n[1/7] Marktdaten & Kurs...")
    fields = [
        'TR.PriceClose',          # letzter Schlusskurs
        'TR.PricePctChg1D',       # Tagesveränderung %
        'TR.Volume',              # Volumen
        'TR.MarketCap',           # Marktkapitalisierung
        'TR.PriceHigh52Week',     # 52-Wochen-Hoch
        'TR.PriceLow52Week',      # 52-Wochen-Tief
        'TR.SharesOutstanding',   # Aktien ausstehend
        'TR.Beta',                # Beta
        'TR.DivYield',            # Dividendenrendite
        'TR.VWAP',                # VWAP
    ]
    df, err = get_data(RIC_MAIN, fields)
    if err or df is None or df.empty:
        print(f"  [WARN] {RIC_MAIN} fehlgeschlagen ({err}), versuche {RIC_ALT}...")
        df, err = get_data(RIC_ALT, fields)

    row = first_row(df)
    result = {
        "price":          safe_float(row.get('Price Close')),
        "change_pct":     safe_float(row.get('Price Pct Chg 1D')),
        "volume":         safe_int(row.get('Volume')),
        "market_cap_bn":  round(safe_float(row.get('Market Capitalization')) / 1e9, 2),
        "year_high":      safe_float(row.get('Price High - 52 Week')),
        "year_low":       safe_float(row.get('Price Low - 52 Week')),
        "shares_mn":      round(safe_float(row.get('Shares Outstanding')) / 1e6, 2),
        "beta":           safe_float(row.get('Beta')),
        "div_yield":      safe_float(row.get('Dividend Yield')),
        "vwap":           safe_float(row.get('Volume Weighted Avg Price')),
        "source":         "LSEG Workspace",
        "as_of":          datetime.date.today().isoformat(),
    }
    print(f"  ✓ Kurs: €{result['price']}  Δ{result['change_pct']:+.2f}%  MCap: €{result['market_cap_bn']}Mrd")
    return result

# ─────────────────────────────────────────────────────────────────────────────
# 2. HISTORISCHE FINANCIALS (2018–2025)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_financials():
    print("\n[2/7] Historische Financials (2018–2025)...")
    fields = [
        'TR.Revenue',
        'TR.GrossProfit',
        'TR.EBITDA',
        'TR.EBIT',
        'TR.NetIncome',
        'TR.EPS',
        'TR.FreeCashFlow',
        'TR.CapitalExpenditures',
        'TR.TotalAssets',
        'TR.TotalDebt',
        'TR.CashAndSTInvestments',
        'TR.Goodwill',
        'TR.IntangibleAssets',
        'TR.TotalEquity',
        'TR.DividendsPaid',
        'TR.Revenue.periodenddate',
    ]
    params = {'SDate': '2017-01-01', 'EDate': '2025-12-31', 'Period': 'FY0', 'Frq': 'FY'}
    df, err = get_data(RIC_MAIN, fields, params)
    if err or df is None or df.empty:
        print(f"  [WARN] Financials fehlgeschlagen: {err}")
        return {"annual": [], "error": str(err)}

    rows = []
    for _, row in df.iterrows():
        rev = safe_float(row.get('Revenue'))
        ebitda = safe_float(row.get('EBITDA'))
        fcf = safe_float(row.get('Free Cash Flow'))
        total_debt = safe_float(row.get('Total Debt'))
        cash = safe_float(row.get('Cash and ST Investments'))
        rows.append({
            "year":           str(row.get('Period End Date', ''))[:4],
            "revenue_mn":     round(rev / 1e6, 1),
            "gross_profit_mn":round(safe_float(row.get('Gross Profit')) / 1e6, 1),
            "ebitda_mn":      round(ebitda / 1e6, 1),
            "ebit_mn":        round(safe_float(row.get('EBIT')) / 1e6, 1),
            "net_income_mn":  round(safe_float(row.get('Net Income')) / 1e6, 1),
            "eps":            round(safe_float(row.get('Earnings Per Share')), 2),
            "fcf_mn":         round(fcf / 1e6, 1),
            "capex_mn":       round(safe_float(row.get('Capital Expenditures')) / 1e6, 1),
            "total_assets_mn":round(safe_float(row.get('Total Assets')) / 1e6, 1),
            "total_debt_mn":  round(total_debt / 1e6, 1),
            "cash_mn":        round(cash / 1e6, 1),
            "net_debt_mn":    round((total_debt - cash) / 1e6, 1),
            "goodwill_mn":    round(safe_float(row.get('Goodwill')) / 1e6, 1),
            "equity_mn":      round(safe_float(row.get('Total Equity')) / 1e6, 1),
            "dividends_mn":   round(safe_float(row.get('Dividends Paid')) / 1e6, 1),
            # Berechnete Margen
            "ebitda_margin":  round(ebitda / max(rev, 1) * 100, 1) if rev else 0,
            "fcf_margin":     round(fcf / max(rev, 1) * 100, 1) if rev else 0,
        })

    rows = [r for r in rows if r["year"] and r["revenue_mn"] > 0]
    rows.sort(key=lambda x: x["year"])
    print(f"  ✓ {len(rows)} Jahresabschlüsse geladen ({rows[0]['year'] if rows else '—'} – {rows[-1]['year'] if rows else '—'})")
    return {"annual": rows}

# ─────────────────────────────────────────────────────────────────────────────
# 3. ANALYST-CONSENSUS (Forward Estimates)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_consensus():
    print("\n[3/7] Analyst-Consensus (Forward Estimates)...")
    fields = [
        'TR.RevenueEstMean',      'TR.RevenueEstHigh',  'TR.RevenueEstLow',
        'TR.EBITDAEstMean',       'TR.EBITDAEstHigh',   'TR.EBITDAEstLow',
        'TR.EPSMeanEstimate',     'TR.EPSHighEstimate',  'TR.EPSLowEstimate',
        'TR.NetIncomeEstMean',
        'TR.FCFEstMean',
        'TR.NumOfEst',
        'TR.RevenueEstMean.periodenddate',
    ]
    consensus = {}
    for period, label in [('FY1', '2026E'), ('FY2', '2027E'), ('FY3', '2028E')]:
        df, err = get_data(RIC_MAIN, fields, {'Period': period})
        if err or df is None or df.empty:
            print(f"  [WARN] {label}: {err}")
            continue
        row = first_row(df)
        rev_est = safe_float(row.get('Revenue Estimate - Mean'))
        ebitda_est = safe_float(row.get('EBITDA Estimate - Mean'))
        consensus[label] = {
            "revenue_mn":     round(rev_est / 1e6, 1),
            "revenue_high_mn":round(safe_float(row.get('Revenue Estimate - High')) / 1e6, 1),
            "revenue_low_mn": round(safe_float(row.get('Revenue Estimate - Low')) / 1e6, 1),
            "ebitda_mn":      round(ebitda_est / 1e6, 1),
            "ebitda_high_mn": round(safe_float(row.get('EBITDA Estimate - High')) / 1e6, 1),
            "ebitda_low_mn":  round(safe_float(row.get('EBITDA Estimate - Low')) / 1e6, 1),
            "eps_mean":       round(safe_float(row.get('EPS Mean Estimate')), 2),
            "eps_high":       round(safe_float(row.get('EPS High Estimate')), 2),
            "eps_low":        round(safe_float(row.get('EPS Low Estimate')), 2),
            "fcf_mn":         round(safe_float(row.get('FCF Estimate - Mean')) / 1e6, 1),
            "num_analysts":   safe_int(row.get('Number Of Estimates')),
            "ebitda_margin_e":round(ebitda_est / max(rev_est, 1) * 100, 1) if rev_est else 0,
        }
        print(f"  ✓ {label}: Umsatz €{consensus[label]['revenue_mn']}M  EBITDA €{consensus[label]['ebitda_mn']}M  EPS €{consensus[label]['eps_mean']}  (n={consensus[label]['num_analysts']})")
        time.sleep(0.5)

    return consensus

# ─────────────────────────────────────────────────────────────────────────────
# 4. BROKER-KURSZIELE & EMPFEHLUNGEN
# ─────────────────────────────────────────────────────────────────────────────

def fetch_broker_targets():
    print("\n[4/7] Broker-Kursziele & Empfehlungen...")
    fields = [
        'TR.TPMean',              # Median-Kursziel
        'TR.TPHigh',              # Höchstes Kursziel
        'TR.TPLow',               # Niedrigstes Kursziel
        'TR.TPNumOfRec',          # Anzahl Empfehlungen
        'TR.RecommendationMean',  # 1=Strong Buy, 3=Hold, 5=Sell
        'TR.TotalBuyRecom',       # Anzahl Buy/Strong Buy
        'TR.TotalHoldRecom',      # Anzahl Hold
        'TR.TotalSellRecom',      # Anzahl Sell/Strong Sell
        'TR.RecommendationDate',  # Datum letzte Änderung
    ]
    df, err = get_data(RIC_MAIN, fields)
    if err or df is None or df.empty:
        print(f"  [WARN] Broker-Daten fehlgeschlagen: {err}")
        return {}

    row = first_row(df)
    tp_mean = safe_float(row.get('Target Price - Mean'))
    buy = safe_int(row.get('Total Buy Recommendations'))
    hold = safe_int(row.get('Total Hold Recommendations'))
    sell = safe_int(row.get('Total Sell Recommendations'))
    total = max(buy + hold + sell, 1)

    result = {
        "tp_mean":       round(tp_mean, 2),
        "tp_high":       round(safe_float(row.get('Target Price - High')), 2),
        "tp_low":        round(safe_float(row.get('Target Price - Low')), 2),
        "num_analysts":  safe_int(row.get('Number Of Recommendations')),
        "rec_mean":      round(safe_float(row.get('Recommendation Mean')), 2),
        "buy_count":     buy,
        "hold_count":    hold,
        "sell_count":    sell,
        "buy_pct":       round(buy / total * 100, 1),
        "hold_pct":      round(hold / total * 100, 1),
        "sell_pct":      round(sell / total * 100, 1),
        "last_updated":  str(row.get('Recommendation Date', ''))[:10],
        # Upside vs. letzter bekannter Kurs
        "implied_upside_pct": 0,  # wird weiter unten berechnet
    }
    print(f"  ✓ Kursziel: €{tp_mean:.2f} (€{result['tp_low']}–€{result['tp_high']})  Buy: {buy}  Hold: {hold}  Sell: {sell}")
    return result

# ─────────────────────────────────────────────────────────────────────────────
# 5. PEER-GRUPPE (Trading Multiples)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_peers():
    print("\n[5/7] Peer-Gruppe (Trading Multiples)...")
    fields = [
        'TR.PriceClose',
        'TR.MarketCap',
        'TR.EVToEBITDA',         # EV/EBITDA
        'TR.PETotalReturn',      # P/E
        'TR.PriceToBVPerShare',  # P/B
        'TR.DivYield',           # FCF Yield Proxy
        'TR.Revenue',
        'TR.EBITDA',
        'TR.RevenueGrowth',      # Umsatzwachstum YoY
    ]
    peers = []
    for name, ric in PEER_RICS.items():
        df, err = get_data(ric, fields)
        if err or df is None or df.empty:
            print(f"  [WARN] {name} ({ric}): {err}")
            continue
        row = first_row(df)
        rev = safe_float(row.get('Revenue'))
        ebitda = safe_float(row.get('EBITDA'))
        peers.append({
            "name":           name,
            "ric":            ric,
            "price":          safe_float(row.get('Price Close')),
            "market_cap_bn":  round(safe_float(row.get('Market Capitalization')) / 1e9, 2),
            "ev_ebitda":      round(safe_float(row.get('Enterprise Value / EBITDA')), 1),
            "pe_ratio":       round(safe_float(row.get('P/E Total Return')), 1),
            "pb_ratio":       round(safe_float(row.get('Price to Book Value Per Share')), 1),
            "div_yield":      round(safe_float(row.get('Dividend Yield')), 2),
            "revenue_mn":     round(rev / 1e6, 1),
            "ebitda_mn":      round(ebitda / 1e6, 1),
            "ebitda_margin":  round(ebitda / max(rev, 1) * 100, 1) if rev else 0,
            "revenue_growth": round(safe_float(row.get('Revenue Growth')) * 100, 1),
        })
        print(f"  ✓ {name}: EV/EBITDA {peers[-1]['ev_ebitda']}×  P/E {peers[-1]['pe_ratio']}×")
        time.sleep(0.3)
    return peers

# ─────────────────────────────────────────────────────────────────────────────
# 6. SCOUT24 LIVE-MULTIPLES (aktuell berechnet)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_live_multiples():
    print("\n[6/7] Scout24 Live-Multiples...")
    fields = [
        'TR.EVToEBITDA',
        'TR.PETotalReturn',
        'TR.PriceToBVPerShare',
        'TR.ROIC',               # Return on Invested Capital
        'TR.ROCE',               # ROCE
        'TR.FCFYield',
        'TR.NetDebtToEBITDA',
        'TR.AltmanZScore',
        'TR.ShortInterestPct',   # Short Interest % of Float
        'TR.ShortInterestRatio', # Days to Cover
        'TR.InsiderOwnershipPct',
        'TR.InstitutionalOwnershipPct',
    ]
    df, err = get_data(RIC_MAIN, fields)
    if err or df is None or df.empty:
        print(f"  [WARN] Live-Multiples fehlgeschlagen: {err}")
        return {}

    row = first_row(df)
    result = {
        "ev_ebitda":            round(safe_float(row.get('Enterprise Value / EBITDA')), 1),
        "pe_ratio":             round(safe_float(row.get('P/E Total Return')), 1),
        "pb_ratio":             round(safe_float(row.get('Price to Book Value Per Share')), 1),
        "roic":                 round(safe_float(row.get('ROIC')) * 100, 1),
        "roce":                 round(safe_float(row.get('ROCE')) * 100, 1),
        "fcf_yield":            round(safe_float(row.get('FCF Yield')) * 100, 2),
        "net_debt_ebitda":      round(safe_float(row.get('Net Debt/EBITDA')), 2),
        "altman_z":             round(safe_float(row.get('Altman Z-Score')), 2),
        "short_interest_pct":   round(safe_float(row.get('Short Interest % Float')), 2),
        "short_days_to_cover":  round(safe_float(row.get('Short Interest Ratio')), 1),
        "insider_ownership":    round(safe_float(row.get('Insider Ownership %')), 1),
        "institutional_own":    round(safe_float(row.get('Institutional Ownership %')), 1),
    }
    print(f"  ✓ EV/EBITDA {result['ev_ebitda']}×  P/E {result['pe_ratio']}×  Short Interest {result['short_interest_pct']}%")
    return result

# ─────────────────────────────────────────────────────────────────────────────
# 7. NEWS-HEADLINES (Catalyst-Monitoring)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_news():
    print("\n[7/7] News-Headlines (letzte 10)...")
    try:
        if ld:
            headlines = ld.news.get_headlines(
                query=f'R:{RIC_MAIN} OR "Scout24" OR "ImmoScout24"',
                count=10
            )
            if headlines is not None and not headlines.empty:
                news = [
                    {
                        "date":  str(row.get('versionCreated', ''))[:10],
                        "title": str(row.get('text', '')),
                        "source": str(row.get('sourceCode', '')),
                    }
                    for _, row in headlines.iterrows()
                ]
                print(f"  ✓ {len(news)} Headlines geladen")
                return news
        elif ek:
            headlines = ek.get_news_headlines(
                query=f'R:{RIC_MAIN} OR "Scout24"',
                count=10
            )
            if headlines is not None and not headlines.empty:
                news = [
                    {"date": str(row.name)[:10], "title": str(row.get('text', ''))}
                    for _, row in headlines.iterrows()
                ]
                print(f"  ✓ {len(news)} Headlines geladen")
                return news
    except Exception as e:
        print(f"  [WARN] News fehlgeschlagen: {e}")
    return []

# ─────────────────────────────────────────────────────────────────────────────
# HAUPTROUTINE
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Scout24 SE — LSEG Workspace Data Fetcher")
    print(f"Start: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    market    = fetch_market()
    fin       = fetch_financials()
    consensus = fetch_consensus()
    brokers   = fetch_broker_targets()
    peers     = fetch_peers()
    multiples = fetch_live_multiples()
    news      = fetch_news()

    # Upside Broker-Kursziel berechnen
    if brokers and market.get("price", 0) > 0:
        brokers["implied_upside_pct"] = round(
            (brokers["tp_mean"] - market["price"]) / market["price"] * 100, 1
        )

    # Letztes Finanzjahr für KPIs
    last_annual = fin["annual"][-1] if fin.get("annual") else {}

    # data.json aufbauen
    data = {
        "_meta": {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source":       "LSEG Workspace",
            "ric":          RIC_MAIN,
            "version":      "lseg-v1",
        },
        "market":    market,
        "profile": {
            "shares_diluted_mn": market.get("shares_mn", 72.07),
            "company_name":      "Scout24 SE",
        },
        "kpis": {
            "revenue_mn":       last_annual.get("revenue_mn", 649.6),
            "ebitda_mn":        last_annual.get("ebitda_mn", 405.7),
            "ebitda_margin":    last_annual.get("ebitda_margin", 62.5),
            "fcf_mn":           last_annual.get("fcf_mn", 261.4),
            "fcf_margin":       last_annual.get("fcf_margin", 40.2),
            "net_debt_mn":      last_annual.get("net_debt_mn", 100),
            "goodwill_mn":      last_annual.get("goodwill_mn", 925.8),
            "goodwill_pct":     round(
                last_annual.get("goodwill_mn", 925.8) /
                max(last_annual.get("total_assets_mn", 2065), 1) * 100, 1
            ),
            "total_assets_mn":  last_annual.get("total_assets_mn", 2065),
            "ev_ebitda":        multiples.get("ev_ebitda", 13.1),
            "pe_ratio":         multiples.get("pe_ratio", 21.7),
            "fcf_yield":        multiples.get("fcf_yield", 5.0),
            "roce":             multiples.get("roce", 16.8),
            "net_debt_ebitda":  multiples.get("net_debt_ebitda", 0.25),
            "altman_z":         multiples.get("altman_z", 10.87),
            "short_interest":   multiples.get("short_interest_pct", 0),
            "year":             last_annual.get("year", "2025A"),
        },
        "history": {
            "annual": fin.get("annual", []),
        },
        "consensus":  consensus,
        "brokers":    brokers,
        "multiples":  multiples,
        "peers":      peers,
        "news":       news,
        # Google Trends werden vom normalen fetcher.py befüllt
        # → beim Mergen die trends-Sektion aus vorherigem data.json übernehmen
        "trends":     _load_existing_trends(),
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"✓ data.json geschrieben: {OUTPUT}")
    print(f"  Kurs:       €{data['market'].get('price', 0)}")
    print(f"  Umsatz:     €{data['kpis']['revenue_mn']}M")
    print(f"  EBITDA:     €{data['kpis']['ebitda_mn']}M  ({data['kpis']['ebitda_margin']}%)")
    print(f"  Kursziel:   €{data['brokers'].get('tp_mean', '—')}  ({data['brokers'].get('buy_count', 0)} Buy / {data['brokers'].get('hold_count', 0)} Hold / {data['brokers'].get('sell_count', 0)} Sell)")
    print(f"  Consensus:  {len(data['consensus'])} Perioden")
    print(f"  Peers:      {len(data['peers'])} geladen")
    print(f"  News:       {len(data['news'])} Headlines")
    print("=" * 60)
    print("\nNächster Schritt:")
    print("  git add data.json")
    print(f"  git commit -m 'data: LSEG update {datetime.date.today()}'")
    print("  git push")


def _load_existing_trends():
    """Übernimmt Google Trends aus vorherigem data.json um sie nicht zu überschreiben."""
    try:
        with open(OUTPUT) as f:
            old = json.load(f)
        return old.get("trends", {})
    except:
        return {}


if __name__ == "__main__":
    main()
