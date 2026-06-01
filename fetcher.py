"""
Scout24 SE — Live Data Fetcher
================================
Holt Markt- und Finanzdaten aus mehreren Quellen und schreibt data.json.

Quellen:
  - FMP (Financial Modeling Prep) — Financials, Multiples, Kurs
  - yfinance                      — Backup-Kurs, Shares
  - Google Trends (pytrends)      — Traffic-Proxy / KI-Disintermediation-Signal

Ausführung:
  python fetcher.py

Umgebungsvariablen (lokal in .env oder via GitHub Actions Secrets):
  FMP_API_KEY=dein-key-hier

GitHub Actions führt dieses Skript täglich aus und commitet data.json.
"""

import os
import json
import datetime
from pathlib import Path

# ── Abhängigkeiten ──────────────────────────────────────────────
try:
    import requests
except ImportError:
    raise SystemExit("requests fehlt. Bitte: pip install requests")

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False
    print("[WARN] yfinance nicht installiert — Kurs nur via FMP")

try:
    from pytrends.request import TrendReq
    TRENDS_OK = True
except ImportError:
    TRENDS_OK = False
    print("[WARN] pytrends nicht installiert — Google Trends übersprungen")

# ── Konfiguration ───────────────────────────────────────────────
FMP_KEY    = os.environ.get("FMP_API_KEY", "")
TICKER_FMP = "SDX.DE"          # FMP-Ticker für Scout24 SE
TICKER_YF  = "SDX.DE"          # yfinance-Ticker
OUTPUT     = Path(__file__).parent / "data.json"

PEER_TICKERS = {
    "Rightmove":       "RMV.L",
    "Auto Trader":     "AUTO.L",
    "REA Group":       "REA.AX",
    "Hemnet":          "HEM.ST",
    "Vend Marketplaces": "VMAR.PA",
}

FMP_BASE = "https://financialmodelingprep.com/api/v3"

def fmp(endpoint: str, **params) -> list | dict:
    """Einfacher FMP-API-Wrapper mit Fehlerbehandlung."""
    if not FMP_KEY:
        raise RuntimeError("FMP_API_KEY nicht gesetzt. Bitte in .env oder als Umgebungsvariable setzen.")
    params["apikey"] = FMP_KEY
    url = f"{FMP_BASE}/{endpoint}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "Error Message" in data:
        raise RuntimeError(f"FMP API Fehler: {data['Error Message']}")
    return data

# ─────────────────────────────────────────────────────────────────
# 1. AKTIENKURS & MARKTDATEN
# ─────────────────────────────────────────────────────────────────

def fetch_market_data() -> dict:
    print("[1/5] Marktdaten (Kurs, MarketCap)...")
    result = {}

    # Primär: FMP Quote
    try:
        quotes = fmp(f"quote/{TICKER_FMP}")
        if quotes:
            q = quotes[0]
            result = {
                "price":          round(q.get("price", 0), 2),
                "change_pct":     round(q.get("changesPercentage", 0), 2),
                "market_cap_bn":  round((q.get("marketCap", 0) or 0) / 1e9, 2),
                "pe_ratio":       round(q.get("pe", 0) or 0, 1),
                "avg_volume":     q.get("avgVolume", 0),
                "year_high":      round(q.get("yearHigh", 0) or 0, 2),
                "year_low":       round(q.get("yearLow", 0) or 0, 2),
            }
            print(f"    Kurs: €{result['price']}")
    except Exception as e:
        print(f"    [WARN] FMP Quote fehlgeschlagen: {e}")

    # Fallback: yfinance
    if not result.get("price") and YFINANCE_OK:
        try:
            ticker = yf.Ticker(TICKER_YF)
            info = ticker.info
            result["price"]         = round(info.get("currentPrice") or info.get("regularMarketPrice", 0), 2)
            result["market_cap_bn"] = round((info.get("marketCap", 0) or 0) / 1e9, 2)
            print(f"    Kurs (yfinance Fallback): €{result['price']}")
        except Exception as e:
            print(f"    [WARN] yfinance Fallback fehlgeschlagen: {e}")

    return result

# ─────────────────────────────────────────────────────────────────
# 2. UNTERNEHMENSPROFIL (Shares, Net Debt)
# ─────────────────────────────────────────────────────────────────

def fetch_profile() -> dict:
    print("[2/5] Unternehmensprofil...")
    try:
        profiles = fmp(f"profile/{TICKER_FMP}")
        if profiles:
            p = profiles[0]
            return {
                "shares_diluted_mn": round((p.get("sharesOutstanding", 0) or 0) / 1e6, 2),
                "company_name":      p.get("companyName", "Scout24 SE"),
                "description":       p.get("description", ""),
                "sector":            p.get("sector", "Technology"),
                "exchange":          p.get("exchangeShortName", "XETRA"),
            }
    except Exception as e:
        print(f"    [WARN] Profil fehlgeschlagen: {e}")
    return {"shares_diluted_mn": 72.07, "company_name": "Scout24 SE"}

# ─────────────────────────────────────────────────────────────────
# 3. FINANCIALS (GuV, Bilanz, Cashflow — letzte 5 Jahre)
# ─────────────────────────────────────────────────────────────────

def fetch_financials() -> dict:
    print("[3/5] Finanzkennzahlen (GuV / Bilanz / Cashflow)...")
    result = {"income": [], "balance": [], "cashflow": [], "metrics": []}

    try:
        # Gewinn- und Verlustrechnung
        income = fmp(f"income-statement/{TICKER_FMP}", limit=5)
        result["income"] = [
            {
                "year":          i.get("calendarYear"),
                "revenue":       round((i.get("revenue") or 0) / 1e6, 1),
                "ebitda":        round((i.get("ebitda") or 0) / 1e6, 1),
                "ebit":          round((i.get("operatingIncome") or 0) / 1e6, 1),
                "net_income":    round((i.get("netIncome") or 0) / 1e6, 1),
                "gross_profit":  round((i.get("grossProfit") or 0) / 1e6, 1),
                "rd_expense":    round((i.get("researchAndDevelopmentExpenses") or 0) / 1e6, 1),
                "eps":           round(i.get("eps") or 0, 2),
                "ebitda_margin": round((i.get("ebitdaratio") or 0) * 100, 1),
            }
            for i in income
        ]
        print(f"    GuV: {len(result['income'])} Jahre geladen")
    except Exception as e:
        print(f"    [WARN] GuV fehlgeschlagen: {e}")

    try:
        # Bilanz
        balance = fmp(f"balance-sheet-statement/{TICKER_FMP}", limit=5)
        result["balance"] = [
            {
                "year":             b.get("calendarYear"),
                "total_assets":     round((b.get("totalAssets") or 0) / 1e6, 1),
                "goodwill":         round((b.get("goodwill") or 0) / 1e6, 1),
                "intangibles":      round((b.get("intangibleAssets") or 0) / 1e6, 1),
                "total_equity":     round((b.get("totalEquity") or 0) / 1e6, 1),
                "total_debt":       round((b.get("totalDebt") or 0) / 1e6, 1),
                "cash":             round((b.get("cashAndCashEquivalents") or 0) / 1e6, 1),
                "net_debt":         round(((b.get("totalDebt") or 0) - (b.get("cashAndCashEquivalents") or 0)) / 1e6, 1),
                "goodwill_pct_assets": round(
                    ((b.get("goodwill") or 0) / (b.get("totalAssets") or 1)) * 100, 1
                ),
            }
            for b in balance
        ]
        print(f"    Bilanz: {len(result['balance'])} Jahre geladen")
    except Exception as e:
        print(f"    [WARN] Bilanz fehlgeschlagen: {e}")

    try:
        # Cashflow
        cf = fmp(f"cash-flow-statement/{TICKER_FMP}", limit=5)
        result["cashflow"] = [
            {
                "year":              c.get("calendarYear"),
                "operating_cf":      round((c.get("operatingCashFlow") or 0) / 1e6, 1),
                "capex":             round((c.get("capitalExpenditure") or 0) / 1e6, 1),
                "free_cashflow":     round((c.get("freeCashFlow") or 0) / 1e6, 1),
                "dividends":         round((c.get("dividendsPaid") or 0) / 1e6, 1),
                "buybacks":          round((c.get("commonStockRepurchased") or 0) / 1e6, 1),
            }
            for c in cf
        ]
        print(f"    Cashflow: {len(result['cashflow'])} Jahre geladen")
    except Exception as e:
        print(f"    [WARN] Cashflow fehlgeschlagen: {e}")

    try:
        # Key Metrics (EV/EBITDA, P/E, FCF Yield etc.)
        km = fmp(f"key-metrics/{TICKER_FMP}", limit=5)
        result["metrics"] = [
            {
                "year":           m.get("calendarYear"),
                "ev_ebitda":      round(m.get("evToOperatingCashFlow") or m.get("enterpriseValueOverEBITDA") or 0, 1),
                "pe_ratio":       round(m.get("peRatio") or 0, 1),
                "pb_ratio":       round(m.get("pbRatio") or 0, 1),
                "fcf_yield":      round((m.get("freeCashFlowYield") or 0) * 100, 2),
                "roce":           round((m.get("returnOnCapitalEmployed") or 0) * 100, 1),
                "ev_mn":          round((m.get("enterpriseValue") or 0) / 1e6, 1),
                "revenue_per_share": round(m.get("revenuePerShare") or 0, 2),
            }
            for m in km
        ]
        print(f"    Multiples: {len(result['metrics'])} Jahre geladen")
    except Exception as e:
        print(f"    [WARN] Multiples fehlgeschlagen: {e}")

    return result

# ─────────────────────────────────────────────────────────────────
# 4. PEER MULTIPLES
# ─────────────────────────────────────────────────────────────────

def fetch_peers() -> list:
    print("[4/5] Peer-Daten...")
    peers = []
    for name, ticker in PEER_TICKERS.items():
        try:
            quotes = fmp(f"quote/{ticker}")
            km     = fmp(f"key-metrics/{ticker}", limit=1)
            inc    = fmp(f"income-statement/{ticker}", limit=1)
            if not quotes or not km:
                raise ValueError("Keine Daten")
            q, k = quotes[0], km[0]
            i = inc[0] if inc else {}
            peers.append({
                "name":           name,
                "ticker":         ticker,
                "ev_ebitda":      round(k.get("enterpriseValueOverEBITDA") or 0, 1),
                "pe_ratio":       round(q.get("pe") or 0, 1),
                "fcf_yield":      round((k.get("freeCashFlowYield") or 0) * 100, 2),
                "ebitda_margin":  round((i.get("ebitdaratio") or 0) * 100, 1),
                "revenue_growth": round((i.get("revenueGrowth") or 0) * 100, 1),
            })
            print(f"    {name}: EV/EBITDA {peers[-1]['ev_ebitda']}x")
        except Exception as e:
            print(f"    [WARN] {name} ({ticker}): {e}")
    return peers

# ─────────────────────────────────────────────────────────────────
# 5. GOOGLE TRENDS (Traffic-Proxy)
# ─────────────────────────────────────────────────────────────────

def fetch_trends() -> dict:
    print("[5/5] Google Trends (Traffic-Proxy)...")
    if not TRENDS_OK:
        return {"status": "pytrends nicht installiert", "data": []}
    try:
        pytrends = TrendReq(hl="de-DE", tz=60)
        kw_list = ["ImmoScout24", "Wohnung mieten KI", "Wohnung ChatGPT"]
        pytrends.build_payload(kw_list, cat=0, timeframe="today 12-m", geo="DE")
        df = pytrends.interest_over_time()
        if df.empty:
            return {"status": "Keine Daten", "data": []}

        # Letzte 4 Wochen vs. Vorjahr
        recent = df.tail(4)["ImmoScout24"].mean()
        year_ago = df.head(4)["ImmoScout24"].mean()
        trend_delta = round(((recent - year_ago) / max(year_ago, 1)) * 100, 1)

        # Letzte 12 Datenpunkte als Zeitreihe
        trend_series = [
            {"date": str(idx.date()), "immoscout": int(row["ImmoScout24"])}
            for idx, row in df.tail(12).iterrows()
        ]

        print(f"    Trends Delta (12M): {trend_delta:+.1f}%")
        return {
            "status":       "ok",
            "trend_delta":  trend_delta,
            "series":       trend_series,
        }
    except Exception as e:
        print(f"    [WARN] Google Trends fehlgeschlagen: {e}")
        return {"status": f"Fehler: {str(e)}", "data": []}

# ─────────────────────────────────────────────────────────────────
# HAUPT-ROUTINE
# ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("Scout24 SE — Data Fetcher")
    print(f"Start: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    if not FMP_KEY:
        print("\n[ERROR] FMP_API_KEY nicht gesetzt!")
        print("Bitte setzen: export FMP_API_KEY='dein-key'")
        return

    market    = fetch_market_data()
    profile   = fetch_profile()
    fin       = fetch_financials()
    peers     = fetch_peers()
    trends    = fetch_trends()

    # ── Letzte verfügbare Jahresdaten herausziehen
    latest_income  = fin["income"][0]  if fin["income"]  else {}
    latest_balance = fin["balance"][0] if fin["balance"] else {}
    latest_cf      = fin["cashflow"][0] if fin["cashflow"] else {}
    latest_metrics = fin["metrics"][0] if fin["metrics"] else {}

    # ── data.json zusammenbauen
    data = {
        "_meta": {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "ticker":       TICKER_FMP,
            "source":       "FMP Free + yfinance + Google Trends",
        },

        # Kurs & Markt
        "market": {
            "price":          market.get("price", 0),
            "change_pct":     market.get("change_pct", 0),
            "market_cap_bn":  market.get("market_cap_bn", 0),
            "year_high":      market.get("year_high", 0),
            "year_low":       market.get("year_low", 0),
            "pe_ratio":       market.get("pe_ratio", 0),
        },

        # Profil
        "profile": {
            "shares_diluted_mn": profile.get("shares_diluted_mn", 72.07),
            "company_name":      profile.get("company_name", "Scout24 SE"),
        },

        # Aktuelle Schlüsselkennzahlen (für Header & Exec Summary)
        "kpis": {
            "revenue_mn":       latest_income.get("revenue", 649.6),
            "ebitda_mn":        latest_income.get("ebitda", 405.7),
            "ebitda_margin":    latest_income.get("ebitda_margin", 62.5),
            "fcf_mn":           latest_cf.get("free_cashflow", 261.4),
            "fcf_margin":       round(
                latest_cf.get("free_cashflow", 261.4) /
                max(latest_income.get("revenue", 649.6), 1) * 100, 1
            ),
            "net_debt_mn":      latest_balance.get("net_debt", 100),
            "goodwill_mn":      latest_balance.get("goodwill", 925.8),
            "goodwill_pct":     latest_balance.get("goodwill_pct_assets", 44.8),
            "total_assets_mn":  latest_balance.get("total_assets", 2065.0),
            "ev_ebitda":        latest_metrics.get("ev_ebitda", 13.1),
            "pe_ratio":         latest_metrics.get("pe_ratio", 21.7),
            "fcf_yield":        latest_metrics.get("fcf_yield", 5.0),
            "roce":             latest_metrics.get("roce", 16.8),
            "net_debt_ebitda":  round(
                latest_balance.get("net_debt", 100) /
                max(latest_income.get("ebitda", 405.7), 1), 2
            ),
            "year":             latest_income.get("year", "2025A"),
        },

        # Historische Zeitreihen (für Charts)
        "history": {
            "income":   list(reversed(fin["income"])),
            "balance":  list(reversed(fin["balance"])),
            "cashflow": list(reversed(fin["cashflow"])),
            "metrics":  list(reversed(fin["metrics"])),
        },

        # Peer-Gruppe
        "peers": peers,

        # Traffic / KI-Signal
        "trends": trends,
    }

    # ── Schreiben
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("=" * 55)
    print(f"✓ data.json geschrieben: {OUTPUT}")
    print(f"  Kurs:    €{data['market']['price']}")
    print(f"  Umsatz:  €{data['kpis']['revenue_mn']}M")
    print(f"  EBITDA:  €{data['kpis']['ebitda_mn']}M  ({data['kpis']['ebitda_margin']}%)")
    print(f"  FCF:     €{data['kpis']['fcf_mn']}M")
    print(f"  Peers:   {len(data['peers'])} geladen")
    print("=" * 55)


if __name__ == "__main__":
    main()
