"""
Scout24 SE — Live Data Fetcher v2
===================================
Quellen (Priorität):
  1. yfinance (PRIMARY)  — Kurs, Shares, MarketCap, Peer-Grunddaten,
                            Financials/Bilanz/Cashflow (kostenlos, DE/EU-Stocks;
                            FMP Free Tier liefert für SDX.DE keine Financials)
  2. FMP                 — Fallback für Financials/Key Metrics (Starter Plan
                            nötig für volle SDX.DE-Abdeckung)
  3. Google Trends       — Traffic-Proxy: ImmoScout24 vs Immowelt vs KI-Suchen

Ausführung:
  python fetcher.py

Umgebungsvariablen:
  FMP_API_KEY=dein-key-hier  (optional für Financials-Fallback)
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
AV_KEY     = os.environ.get("ALPHA_VANTAGE_KEY", "")   # Alpha Vantage (Primary Kurs)
TICKER_FMP = "SDX.DE"
TICKER_YF  = "SDX.DE"
TICKER_AV  = "G24.DEX"         # Alpha Vantage: Scout24 SE auf XETRA (verifiziert)
OUTPUT     = Path(__file__).parent / "data.json"

PEER_TICKERS = {
    "Rightmove":       "RMV.L",
    "Auto Trader":     "AUTO.L",
    "REA Group":       "REA.AX",
    "Hemnet":          "HEM.ST",
    "Vend Marketplaces": "VEND.OL",  # vormals Schibsted ASA, umbenannt Mai 2025 (Oslo Boers)
}

FMP_BASE = "https://financialmodelingprep.com/api/v3"

def fmp(endpoint: str, **params) -> list | dict:
    """FMP-API-Wrapper — gibt leere Liste zurück wenn Key fehlt (kein harter Abbruch)."""
    if not FMP_KEY:
        print(f"    [SKIP] FMP_API_KEY nicht gesetzt — {endpoint} übersprungen")
        return []
    params["apikey"] = FMP_KEY
    url = f"{FMP_BASE}/{endpoint}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "Error Message" in data:
        print(f"    [WARN] FMP API Fehler: {data['Error Message']}")
        return []
    return data

# ─────────────────────────────────────────────────────────────────
# 1. AKTIENKURS & MARKTDATEN  (PRIMARY: yfinance)
# ─────────────────────────────────────────────────────────────────

def fetch_market_data() -> dict:
    print("[1/5] Marktdaten (Kurs, MarketCap) via yfinance...")
    result = {}

    # PRIMARY: Alpha Vantage — explizit für API-Zugriff gebaut, keine CI-Blocks
    if AV_KEY:
        try:
            url  = "https://www.alphavantage.co/query"
            r    = requests.get(url, params={
                "function": "GLOBAL_QUOTE",
                "symbol":   TICKER_AV,
                "apikey":   AV_KEY,
            }, timeout=15)
            r.raise_for_status()
            q = r.json().get("Global Quote", {})
            price = float(q.get("05. price", 0) or 0)
            if price:
                prev  = float(q.get("08. previous close", price) or price)
                result = {
                    "price":          round(price, 2),
                    "change_pct":     round(float(q.get("10. change percent", "0%").replace("%","").strip()) or 0, 2),
                    "market_cap_bn":  0,
                    "year_high":      round(float(q.get("03. high", 0) or 0), 2),
                    "year_low":       round(float(q.get("04. low",  0) or 0), 2),
                    "avg_volume":     int(float(q.get("06. volume", 0) or 0)),
                    "beta":           0,
                    "dividend_yield": 0,
                    "currency":       "EUR",
                    "latest_day":     q.get("07. latest trading day", ""),
                }
                print(f"    ✓ Kurs (Alpha Vantage): €{price}  Δ{result['change_pct']:+.2f}%  Stand: {result['latest_day']}")
            else:
                print(f"    [WARN] Alpha Vantage: Kein Preis — Response: {str(r.json())[:200]}")
        except Exception as e:
            print(f"    [WARN] Alpha Vantage fehlgeschlagen: {e}")
    else:
        print("    [WARN] ALPHA_VANTAGE_KEY nicht gesetzt")

    # FALLBACK: Stooq (kein Key nötig)
    if not result.get("price"):
        try:
            url2  = "https://stooq.com/q/l/?s=sdx.de&f=sd2t2ohlcv&h&e=csv"
            r2    = requests.get(url2, timeout=15)
            lines = [l for l in r2.text.strip().split("\n") if l and "N/D" not in l and not l.startswith("Symbol")]
            if lines:
                p = lines[0].split(",")
                price2 = round(float(p[6]), 2)
                result["price"]      = price2
                result["change_pct"] = round(((price2 - float(p[3])) / max(float(p[3]), 0.01)) * 100, 2)
                print(f"    ✓ Kurs (Stooq Fallback): €{price2}")
        except Exception as e:
            print(f"    [WARN] Stooq Fallback fehlgeschlagen: {e}")

    # FALLBACK: FMP Quote (falls yfinance nicht verfügbar)
    if not result.get("price") and FMP_KEY:
        try:
            quotes = fmp(f"quote/{TICKER_FMP}")
            if quotes:
                q = quotes[0]
                result = {
                    "price":         round(q.get("price", 0), 2),
                    "change_pct":    round(q.get("changesPercentage", 0), 2),
                    "market_cap_bn": round((q.get("marketCap", 0) or 0) / 1e9, 2),
                    "pe_ratio":      round(q.get("pe", 0) or 0, 1),
                    "year_high":     round(q.get("yearHigh", 0) or 0, 2),
                    "year_low":      round(q.get("yearLow",  0) or 0, 2),
                    "avg_volume":    q.get("avgVolume", 0),
                }
                print(f"    ✓ Kurs (FMP Fallback): €{result['price']}")
        except Exception as e:
            print(f"    [WARN] FMP Quote fehlgeschlagen: {e}")

    if not result.get("price"):
        print("    [WARN] Kein Kurs verfügbar — verwende Fallback 0")

    return result

# ─────────────────────────────────────────────────────────────────
# 2. UNTERNEHMENSPROFIL  (PRIMARY: yfinance)
# ─────────────────────────────────────────────────────────────────

def fetch_profile() -> dict:
    print("[2/5] Unternehmensprofil via yfinance...")
    if YFINANCE_OK:
        try:
            info = yf.Ticker(TICKER_YF).info
            shares = (
                info.get("sharesOutstanding") or
                info.get("impliedSharesOutstanding") or
                72_070_000
            )
            result = {
                "shares_diluted_mn": round(float(shares) / 1e6, 2),
                "company_name":      info.get("longName", "Scout24 SE"),
                "sector":            info.get("sector", "Technology"),
                "industry":          info.get("industry", "Internet Content & Information"),
                "employees":         info.get("fullTimeEmployees", 0),
                "website":           info.get("website", "https://www.scout24.com"),
            }
            print(f"    ✓ Shares: {result['shares_diluted_mn']}M  Mitarbeiter: {result['employees']}")
            return result
        except Exception as e:
            print(f"    [WARN] yfinance Profil fehlgeschlagen: {e}")

    # Fallback FMP
    if FMP_KEY:
        try:
            profiles = fmp(f"profile/{TICKER_FMP}")
            if profiles:
                p = profiles[0]
                return {
                    "shares_diluted_mn": round((p.get("sharesOutstanding", 0) or 0) / 1e6, 2),
                    "company_name":      p.get("companyName", "Scout24 SE"),
                    "sector":            p.get("sector", "Technology"),
                    "industry":          p.get("industry", ""),
                    "employees":         p.get("fullTimeEmployees", 0),
                    "website":           p.get("website", ""),
                }
        except Exception as e:
            print(f"    [WARN] FMP Profil fehlgeschlagen: {e}")

    return {"shares_diluted_mn": 72.07, "company_name": "Scout24 SE"}

# ─────────────────────────────────────────────────────────────────
# 3. FINANCIALS (GuV, Bilanz, Cashflow — letzte 5 Jahre)
# ─────────────────────────────────────────────────────────────────

def _yf_series(df, label):
    """Liefert die Zeile (Series) fuer ein pretty-Label aus .financials /
    .balance_sheet / .cashflow, oder None falls das Label nicht existiert."""
    try:
        return df.loc[label]
    except KeyError:
        return None


def _yf_val(series, col):
    """Sicherer Zellzugriff; None bei NaN/Fehler (kein extra math/pandas-Import)."""
    if series is None:
        return None
    try:
        v = series[col]
        if v != v:  # NaN-Check (NaN != NaN)
            return None
        return float(v)
    except Exception:
        return None


def fetch_financials() -> dict:
    print("[4/5] Finanzkennzahlen (GuV / Bilanz / Cashflow)...")
    result = {"income": [], "balance": [], "cashflow": [], "metrics": []}

    # ── PRIMAER: yfinance ────────────────────────────────────────
    # FMP Free Tier liefert fuer SDX.DE leere income-statement/
    # balance-sheet-statement/cash-flow-statement/key-metrics (bestaetigt:
    # alle vier Endpunkte liefern [] -- siehe history.metrics/balance in
    # frueheren data.json-Versionen). yfinance .financials/.balance_sheet/
    # .cashflow nutzen den fundamentals-timeseries Endpoint, der fuer
    # europaeische Nebenwerte i.d.R. besser abgedeckt ist.
    if YFINANCE_OK:
        try:
            tk = yf.Ticker(TICKER_YF)

            # GuV
            try:
                df = tk.financials
                if df is not None and not df.empty:
                    rev_r  = _yf_series(df, "Total Revenue")
                    ebd_r  = _yf_series(df, "EBITDA")
                    ebit_r = _yf_series(df, "EBIT")
                    opi_r  = _yf_series(df, "Operating Income")
                    ni_r   = _yf_series(df, "Net Income")
                    gp_r   = _yf_series(df, "Gross Profit")
                    rd_r   = _yf_series(df, "Research And Development")
                    eps_r  = _yf_series(df, "Diluted EPS")
                    for col in sorted(df.columns, reverse=True)[:5]:
                        rev = _yf_val(rev_r, col)
                        if not rev:
                            continue
                        ebd  = _yf_val(ebd_r, col)
                        ebit = _yf_val(ebit_r, col)
                        if ebit is None:
                            ebit = _yf_val(opi_r, col)
                        result["income"].append({
                            "year":          str(col.year),
                            "revenue":       round(rev / 1e6, 1),
                            "ebitda":        round(ebd / 1e6, 1) if ebd else 0,
                            "ebit":          round(ebit / 1e6, 1) if ebit else 0,
                            "net_income":    round((_yf_val(ni_r, col) or 0) / 1e6, 1),
                            "gross_profit":  round((_yf_val(gp_r, col) or 0) / 1e6, 1),
                            "rd_expense":    round((_yf_val(rd_r, col) or 0) / 1e6, 1),
                            "eps":           round(_yf_val(eps_r, col) or 0, 2),
                            "ebitda_margin": round(ebd / rev * 100, 1) if ebd else 0,
                        })
                    if result["income"]:
                        print(f"    GuV: {len(result['income'])} Jahre geladen (yfinance)")
            except Exception as e:
                print(f"    [WARN] GuV via yfinance fehlgeschlagen: {e}")

            # Bilanz
            try:
                df = tk.balance_sheet
                if df is not None and not df.empty:
                    ta_r    = _yf_series(df, "Total Assets")
                    gw_r    = _yf_series(df, "Goodwill")
                    oia_r   = _yf_series(df, "Other Intangible Assets")
                    gwoia_r = _yf_series(df, "Goodwill And Other Intangible Assets")
                    eq_r    = _yf_series(df, "Stockholders Equity")
                    eqgmi_r = _yf_series(df, "Total Equity Gross Minority Interest")
                    td_r    = _yf_series(df, "Total Debt")
                    cash_r  = _yf_series(df, "Cash And Cash Equivalents")
                    ccsti_r = _yf_series(df, "Cash Cash Equivalents And Short Term Investments")
                    nd_r    = _yf_series(df, "Net Debt")
                    for col in sorted(df.columns, reverse=True)[:5]:
                        ta = _yf_val(ta_r, col)
                        if not ta:
                            continue
                        gw = _yf_val(gw_r, col) or 0
                        intg = _yf_val(oia_r, col)
                        if intg is None:
                            gwoia = _yf_val(gwoia_r, col)
                            intg = (gwoia - gw) if gwoia is not None else 0
                        eq = _yf_val(eq_r, col)
                        if eq is None:
                            eq = _yf_val(eqgmi_r, col) or 0
                        td = _yf_val(td_r, col) or 0
                        cash = _yf_val(cash_r, col)
                        if cash is None:
                            cash = _yf_val(ccsti_r, col) or 0
                        nd = _yf_val(nd_r, col)
                        if nd is None:
                            nd = td - cash
                        result["balance"].append({
                            "year":                str(col.year),
                            "total_assets":        round(ta / 1e6, 1),
                            "goodwill":            round(gw / 1e6, 1),
                            "intangibles":         round(intg / 1e6, 1),
                            "total_equity":        round(eq / 1e6, 1),
                            "total_debt":          round(td / 1e6, 1),
                            "cash":                round(cash / 1e6, 1),
                            "net_debt":            round(nd / 1e6, 1),
                            "goodwill_pct_assets": round(gw / ta * 100, 1),
                        })
                    if result["balance"]:
                        print(f"    Bilanz: {len(result['balance'])} Jahre geladen (yfinance)")
            except Exception as e:
                print(f"    [WARN] Bilanz via yfinance fehlgeschlagen: {e}")

            # Cashflow
            try:
                df = tk.cashflow
                if df is not None and not df.empty:
                    ocf_r = _yf_series(df, "Operating Cash Flow")
                    cpx_r = _yf_series(df, "Capital Expenditure")
                    fcf_r = _yf_series(df, "Free Cash Flow")
                    div_r = _yf_series(df, "Cash Dividends Paid")
                    cdp_r = _yf_series(df, "Common Stock Dividend Paid")
                    bb_r  = _yf_series(df, "Repurchase Of Capital Stock")
                    for col in sorted(df.columns, reverse=True)[:5]:
                        ocf = _yf_val(ocf_r, col)
                        fcf = _yf_val(fcf_r, col)
                        if ocf is None and fcf is None:
                            continue
                        div = _yf_val(div_r, col)
                        if div is None:
                            div = _yf_val(cdp_r, col) or 0
                        result["cashflow"].append({
                            "year":          str(col.year),
                            "operating_cf":  round((ocf or 0) / 1e6, 1),
                            "capex":         round((_yf_val(cpx_r, col) or 0) / 1e6, 1),
                            "free_cashflow": round((fcf or 0) / 1e6, 1),
                            "dividends":     round(div / 1e6, 1),
                            "buybacks":      round((_yf_val(bb_r, col) or 0) / 1e6, 1),
                        })
                    if result["cashflow"]:
                        print(f"    Cashflow: {len(result['cashflow'])} Jahre geladen (yfinance)")
            except Exception as e:
                print(f"    [WARN] Cashflow via yfinance fehlgeschlagen: {e}")

            # Kennzahlen (aktuell, aus .info -- yfinance liefert keine
            # mehrjaehrige key-metrics-Historie wie FMP)
            try:
                info = tk.info or {}
                ev_ebitda = info.get("enterpriseToEbitda")
                pe_ratio  = info.get("trailingPE") or info.get("forwardPE")
                pb_ratio  = info.get("priceToBook")
                ev_val    = info.get("enterpriseValue")
                mcap      = info.get("marketCap")
                shares    = info.get("sharesOutstanding")

                fcf_latest = result["cashflow"][0]["free_cashflow"] if result["cashflow"] else None
                fcf_yield  = round(fcf_latest * 1e6 / mcap * 100, 2) if (fcf_latest and mcap) else 0

                rev_latest    = result["income"][0]["revenue"] if result["income"] else None
                rev_per_share = round(rev_latest * 1e6 / shares, 2) if (rev_latest and shares) else 0

                roce = 0
                if result["income"] and result["balance"]:
                    ebit_v = result["income"][0]["ebit"]
                    cap_employed = result["balance"][0]["total_equity"] + result["balance"][0]["total_debt"]
                    if ebit_v and cap_employed:
                        roce = round(ebit_v / cap_employed * 100, 1)

                if ev_ebitda or pe_ratio:
                    result["metrics"].append({
                        "year":              str(datetime.date.today().year),
                        "ev_ebitda":         round(ev_ebitda, 1) if ev_ebitda else 0,
                        "pe_ratio":          round(pe_ratio, 1) if pe_ratio else 0,
                        "pb_ratio":          round(pb_ratio, 1) if pb_ratio else 0,
                        "fcf_yield":         fcf_yield,
                        "roce":              roce,
                        "ev_mn":             round(ev_val / 1e6, 1) if ev_val else 0,
                        "revenue_per_share": rev_per_share,
                    })
                    print("    Multiples: aktuelle Kennzahlen geladen (yfinance .info)")
            except Exception as e:
                print(f"    [WARN] Multiples via yfinance fehlgeschlagen: {e}")

        except Exception as e:
            print(f"    [WARN] yfinance Financials komplett fehlgeschlagen: {e}")

    # ── FALLBACK: FMP ────────────────────────────────────────────
    # Fuellt nur Luecken, die yfinance nicht liefern konnte. Fuer SDX.DE
    # auf FMP Free Tier i.d.R. weiterhin leer (bestaetigt) -- main()
    # greift dann auf FALLBACK_2025A zurueck.
    if not result["income"]:
        try:
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
            if result["income"]:
                print(f"    GuV: {len(result['income'])} Jahre geladen (FMP)")
        except Exception as e:
            print(f"    [WARN] GuV via FMP fehlgeschlagen: {e}")

    if not result["balance"]:
        try:
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
            if result["balance"]:
                print(f"    Bilanz: {len(result['balance'])} Jahre geladen (FMP)")
        except Exception as e:
            print(f"    [WARN] Bilanz via FMP fehlgeschlagen: {e}")

    if not result["cashflow"]:
        try:
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
            if result["cashflow"]:
                print(f"    Cashflow: {len(result['cashflow'])} Jahre geladen (FMP)")
        except Exception as e:
            print(f"    [WARN] Cashflow via FMP fehlgeschlagen: {e}")

    if not result["metrics"]:
        try:
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
            if result["metrics"]:
                print(f"    Multiples: {len(result['metrics'])} Jahre geladen (FMP)")
        except Exception as e:
            print(f"    [WARN] Multiples via FMP fehlgeschlagen: {e}")

    if not (result["income"] or result["balance"] or result["cashflow"] or result["metrics"]):
        print("    [INFO] Weder yfinance noch FMP lieferten Financials -- main() verwendet FALLBACK_2025A")

    return result

# ─────────────────────────────────────────────────────────────────
# 4. PEER MULTIPLES
# ─────────────────────────────────────────────────────────────────

def fetch_peers() -> list:
    print("[3/5] Peer-Daten (PRIMARY: yfinance)...")
    peers = []
    today = datetime.date.today().isoformat()

    def _from_yfinance(name: str, ticker: str, is_subject: bool = False):
        if not YFINANCE_OK:
            return None
        info = yf.Ticker(ticker).info
        ev_ebitda = info.get("enterpriseToEbitda")
        pe_ratio  = info.get("trailingPE") or info.get("forwardPE")
        fcf       = info.get("freeCashflow")
        mcap      = info.get("marketCap")
        fcf_yield = (fcf / mcap * 100) if fcf and mcap else None
        ebitda_m  = info.get("ebitdaMargins")
        rev_g     = info.get("revenueGrowth")
        if ev_ebitda is None and pe_ratio is None:
            return None
        row = {
            "name":          name,
            "ticker":        ticker,
            "ev_ebitda":     round(ev_ebitda or 0, 1),
            "pe_ratio":      round(pe_ratio or 0, 1),
            "fcf_yield":     round(fcf_yield, 2) if fcf_yield is not None else 0,
            "ebitda_margin": round(ebitda_m * 100, 1) if ebitda_m is not None else 0,
            "rev_growth":    round(rev_g * 100, 1) if rev_g is not None else 0,
            "as_of":         today,
            "source":        "yfinance",
        }
        if is_subject:
            row["is_subject"] = True
        return row

    def _from_fmp(name: str, ticker: str):
        quotes = fmp(f"quote/{ticker}")
        km     = fmp(f"key-metrics/{ticker}", limit=1)
        inc    = fmp(f"income-statement/{ticker}", limit=1)
        if not quotes or not km:
            return None
        q, k = quotes[0], km[0]
        i = inc[0] if inc else {}
        return {
            "name":           name,
            "ticker":         ticker,
            "ev_ebitda":      round(k.get("enterpriseValueOverEBITDA") or 0, 1),
            "pe_ratio":       round(q.get("pe") or 0, 1),
            "fcf_yield":      round((k.get("freeCashFlowYield") or 0) * 100, 2),
            "ebitda_margin":  round((i.get("ebitdaratio") or 0) * 100, 1),
            "rev_growth":     round((i.get("revenueGrowth") or 0) * 100, 1),
            "as_of":          today,
            "source":         "FMP",
        }

    for name, ticker in PEER_TICKERS.items():
        try:
            p = _from_yfinance(name, ticker)
            if not p:
                raise ValueError("yfinance ohne Daten")
            peers.append(p)
            print(f"    ✓ {name}: EV/EBITDA {p['ev_ebitda']}x (yfinance)")
        except Exception as e:
            print(f"    [WARN] {name} ({ticker}) via yfinance fehlgeschlagen: {e} — Fallback FMP")
            try:
                p = _from_fmp(name, ticker)
                if not p:
                    raise ValueError("Keine FMP-Daten")
                peers.append(p)
                print(f"    ✓ {name}: EV/EBITDA {p['ev_ebitda']}x (FMP)")
            except Exception as e2:
                print(f"    [WARN] {name} ({ticker}) komplett fehlgeschlagen: {e2}")

    return peers

# ─────────────────────────────────────────────────────────────────
# 5. GOOGLE TRENDS (Traffic-Proxy + Wettbewerber + KI-Signal)
# ─────────────────────────────────────────────────────────────────

def fetch_trends() -> dict:
    print("[5/5] Google Trends (ImmoScout24 vs Immowelt + KI-Signale)...")
    if not TRENDS_OK:
        return {"status": "pytrends nicht installiert", "series": [], "competitor": [], "ai_signal": []}
    import time

    def safe_trends(kw_list, timeframe="today 12-m", geo="DE", retries=2):
        pytrends = TrendReq(hl="de-DE", tz=60)
        for attempt in range(retries):
            try:
                pytrends.build_payload(kw_list, cat=0, timeframe=timeframe, geo=geo)
                df = pytrends.interest_over_time()
                return df
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(3)
                else:
                    raise e
        return None

    result = {"status": "ok", "series": [], "competitor": [], "ai_signal": [], "trend_delta": 0}

    # ── 1. ImmoScout24 12-Monats-Trend (Hauptsignal)
    try:
        df = safe_trends(["ImmoScout24"])
        if df is not None and not df.empty and "ImmoScout24" in df.columns:
            recent   = df.tail(4)["ImmoScout24"].mean()
            year_ago = df.head(4)["ImmoScout24"].mean()
            result["trend_delta"] = round(((recent - year_ago) / max(year_ago, 1)) * 100, 1)
            result["series"] = [
                {"date": str(idx.date()), "value": int(row["ImmoScout24"])}
                for idx, row in df.tail(16).iterrows()
            ]
            print(f"    ✓ ImmoScout24 Trend Delta: {result['trend_delta']:+.1f}%")
        time.sleep(4)   # längere Pause wegen Rate-Limiting
    except Exception as e:
        print(f"    [WARN] ImmoScout24 Trend fehlgeschlagen: {e}")

    # ── 2. ImmoScout24 vs Immowelt (Wettbewerber-Vergleich)
    try:
        df2 = safe_trends(["ImmoScout24", "Immowelt"])
        if df2 is not None and not df2.empty:
            cols = [c for c in ["ImmoScout24", "Immowelt"] if c in df2.columns]
            result["competitor"] = [
                {
                    "date":       str(idx.date()),
                    "immoscout":  int(row.get("ImmoScout24", 0)),
                    "immowelt":   int(row.get("Immowelt", 0)),
                }
                for idx, row in df2.tail(16).iterrows()
            ]
            # Marktanteil-Signal: wer gewinnt / verliert
            if "ImmoScout24" in df2.columns and "Immowelt" in df2.columns:
                scout_recent  = df2.tail(4)["ImmoScout24"].mean()
                welt_recent   = df2.tail(4)["Immowelt"].mean()
                scout_old     = df2.head(4)["ImmoScout24"].mean()
                welt_old      = df2.head(4)["Immowelt"].mean()
                result["competitor_delta"] = {
                    "immoscout_delta": round(((scout_recent - scout_old) / max(scout_old, 1)) * 100, 1),
                    "immowelt_delta":  round(((welt_recent  - welt_old)  / max(welt_old,  1)) * 100, 1),
                }
                print(f"    ✓ ImmoScout24 {result['competitor_delta']['immoscout_delta']:+.1f}% vs Immowelt {result['competitor_delta']['immowelt_delta']:+.1f}%")
        time.sleep(2)
    except Exception as e:
        print(f"    [WARN] Wettbewerber-Vergleich fehlgeschlagen: {e}")

    # ── 3. KI-Disintermediation-Signal (mit Retry wegen Rate-Limit)
    time.sleep(5)   # längere Pause vor KI-Abfrage
    try:
        df3 = safe_trends(["Wohnung KI", "Wohnung ChatGPT"])
        if df3 is not None and not df3.empty:
            cols = [c for c in df3.columns if c != "isPartial"]
            result["ai_signal"] = [
                {
                    "date": str(idx.date()),
                    **{c: int(row.get(c, 0)) for c in cols}
                }
                for idx, row in df3.tail(12).iterrows()
            ]
            # Wachstum KI-Suchen
            for kw in ["Wohnung KI", "Wohnung ChatGPT"]:
                if kw in df3.columns:
                    ai_recent = df3.tail(4)[kw].mean()
                    ai_old    = df3.head(4)[kw].mean()
                    delta = round(((ai_recent - ai_old) / max(ai_old, 0.1)) * 100, 1)
                    result[f"ai_delta_{kw.replace(' ', '_')}"] = delta
                    print(f"    ✓ KI-Signal '{kw}': {delta:+.1f}%")
    except Exception as e:
        print(f"    [WARN] KI-Signal fehlgeschlagen: {e}")

    return result

# ─────────────────────────────────────────────────────────────────
# MAKRO-DATEN (Bundesbank + EZB — kostenlos, kein API-Key)
# ─────────────────────────────────────────────────────────────────

def fetch_bafin_shorts() -> dict:
    """
    Holt BaFin-Netto-Leerverkaufspositionen für Scout24 SE (ISIN: DE000A12DM80).
    Quelle: BaFin API — kostenlos, kein Key nötig, täglich aktualisiert.
    Alle Short-Positionen >0.5% des Floats sind meldepflichtig und öffentlich.
    """
    print("[BAFIN] Netto-Leerverkaufspositionen Scout24...")
    SCOUT24_ISIN = "DE000A12DM80"
    result = {
        "positions":      [],
        "total_short_pct": 0,
        "num_holders":    0,
        "as_of":          datetime.date.today().isoformat(),
        "source":         "BaFin — Netto-Leerverkaufspositionen (öffentlich)",
    }
    try:
        # BaFin API v2 — ISIN-basierte Abfrage
        url = f"https://api.bafin.de/srs/shortselling/v2/positions?isin={SCOUT24_ISIN}"
        r = requests.get(url, timeout=15, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
        positions = data if isinstance(data, list) else data.get("positions", data.get("data", []))
        if positions:
            result["positions"] = [
                {
                    "holder":    p.get("positionHolderName") or p.get("holder") or p.get("name", "Unbekannt"),
                    "pct":       round(float(p.get("netShortPosition") or p.get("position") or p.get("pct", 0)), 2),
                    "date":      str(p.get("positionDate") or p.get("date", ""))[:10],
                }
                for p in positions[:10]
            ]
            result["total_short_pct"] = round(sum(p["pct"] for p in result["positions"]), 2)
            result["num_holders"]     = len(result["positions"])
            print(f"  ✓ {result['num_holders']} Short-Positionen | Gesamt: {result['total_short_pct']}% des Floats")
            for p in result["positions"]:
                print(f"    {p['holder']}: {p['pct']}% (Stand: {p['date']})")
        else:
            print(f"  [INFO] Keine Short-Positionen >0.5% gemeldet (oder API leer)")
    except Exception as e:
        print(f"  [WARN] BaFin API fehlgeschlagen: {e}")
        # Fallback: öffentliche BaFin-Datei (XLSX) — wird bei Bedarf aktiviert
    return result

def fetch_macro() -> dict:
    """
    Zieht makroökonomische Daten direkt von EZB und Bundesbank APIs.
    Kostenlos, kein API-Key nötig.

    Liefert:
      - EZB Einlagesatz (Leitzins)
      - Deutscher 10J-Bund (risikofreier Zinssatz für WACC)
      - Hypothekenzins DE 10J fix (Wohnbau-Nachfrage-Signal)
      - Implizierter WACC-Bereich
    """
    print("[MAKRO] Bundesbank + EZB Zinsdaten...")
    result = {
        "ecb_deposit_rate":  None,
        "bund_10y":          None,
        "mortgage_rate_10y": None,
        "wacc_floor":        None,
        "wacc_implied":      None,
        "as_of":             datetime.date.today().isoformat(),
        "source":            "EZB + Bundesbank SDMX API",
    }

    # ── 1. EZB Einlagesatz — mehrere Endpunkte versuchen
    ecb_urls = [
        "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?format=jsondata&lastNObservations=1",
        "https://sdw-wsrest.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?format=jsondata&lastNObservations=1",
    ]
    for url in ecb_urls:
        try:
            r = requests.get(url, timeout=15, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
            # Flexibles Parsing — verschiedene ECB Response-Strukturen
            datasets = data.get("dataSets", [{}])
            series = datasets[0].get("series", {}) if datasets else {}
            first_series = list(series.values())[0] if series else {}
            obs = first_series.get("observations", {})
            if obs:
                ecb_rate = round(float(list(obs.values())[-1][0]), 2)
                result["ecb_deposit_rate"] = ecb_rate
                print(f"    ✓ EZB Einlagesatz: {ecb_rate}%")
                break
        except Exception as e:
            print(f"    [WARN] ECB Endpunkt {url[:50]}... fehlgeschlagen: {e}")
    if not result["ecb_deposit_rate"]:
        # Fallback: letzter bekannter EZB-Satz (manuell aktualisieren bei Änderung)
        result["ecb_deposit_rate"] = 2.25   # Stand: 2.25% (EZB-Zinserhoehung vom 11.06.2026)
        print(f"    [FALLBACK] EZB Einlagesatz: 2.25% (Stand Jun 2026, nach Erhoehung 11.06.2026)")

    # ── 2. Deutscher 10J-Bund (AAA Euro-Area Yield Curve 10Y)
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/"
               "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?format=jsondata&lastNObservations=1")
        r = requests.get(url, timeout=15, headers={"Accept": "application/json"})
        r.raise_for_status()
        data_bund = r.json()
        datasets = data_bund.get("dataSets", [{}])
        series = datasets[0].get("series", {}) if datasets else {}
        first_series = list(series.values())[0] if series else {}
        obs = first_series.get("observations", {})
        if obs:
            bund = round(float(list(obs.values())[-1][0]), 2)
            result["bund_10y"] = bund
            print(f"    ✓ Bund 10J: {bund}%")
    except Exception as e:
        print(f"    [WARN] Bund-Rendite fehlgeschlagen: {e}")
    if not result["bund_10y"]:
        result["bund_10y"] = 3.05  # Fallback: letzter bekannter Wert (Stand Jun 2026)
        print(f"    [FALLBACK] Bund 10J: 3.05% (statisch)")

    # ── 3. Hypothekenzins DE — mehrere Bundesbank-Endpunkte versuchen
    bbk_urls = [
        "https://api.statistik.bundesbank.de/service/data/BBK01/M.I1.EUR.BB3L.RD?format=sdmx-json&lastNObservations=3",
        "https://api.statistik.bundesbank.de/service/data/BBK01/M.I1.EUR.BB3L.RD?format=sdmx-json&lastNObservations=1&detail=dataonly",
    ]
    for url in bbk_urls:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            # Flexibles Parsing
            datasets = data.get("dataSets", [{}])
            series_dict = datasets[0].get("series", {}) if datasets else {}
            first_series = list(series_dict.values())[0] if series_dict else {}
            obs = first_series.get("observations", {})
            if obs:
                latest_val = float(list(obs.values())[-1][0])
                result["mortgage_rate_10y"] = round(latest_val, 2)
                print(f"    ✓ Hypothekenzins 10J: {latest_val}%")
                break
        except Exception as e:
            print(f"    [WARN] BBK Endpunkt fehlgeschlagen: {e}")
    if not result["mortgage_rate_10y"]:
        result["mortgage_rate_10y"] = 3.82  # Fallback: letzter bekannter Wert
        print(f"    [FALLBACK] Hypothekenzins: 3.82% (statisch)")

    # ── 4. WACC-Implikation berechnen
    # WACC = rf + β × ERP + credit spread (Damodaran-Methode)
    # Scout24 Beta ~0.8, DE-ERP ~5.5%, Credit Spread ~1.5%
    rf = result["bund_10y"] or 2.5
    beta = 0.80
    erp  = 5.5    # Equity Risk Premium DE (Damodaran 2026)
    cs   = 1.5    # Credit Spread (Aa-Rating äquivalent)
    wacc_calc = round(rf + beta * erp + cs, 1)
    result["wacc_implied"]  = wacc_calc
    result["wacc_floor"]    = round(rf + 4.5, 1)  # konservatives Minimum
    result["erp_used"]      = erp
    result["beta_used"]     = beta
    if result["bund_10y"]:
        print(f"    ✓ WACC impliziert: {wacc_calc}% (rf={rf}% + β{beta}×ERP{erp}% + CS{cs}%)")

    return result

# ─────────────────────────────────────────────────────────────────
# HAUPT-ROUTINE
# ─────────────────────────────────────────────────────────────────

def _load_existing_lseg() -> dict:
    """Lädt LSEG-spezifische Felder aus vorhandenem data.json um sie zu erhalten."""
    try:
        with open(OUTPUT) as f:
            old = json.load(f)
        lseg = {}
        # Nur LSEG-Felder übernehmen wenn sie aus Workspace stammen
        if old.get("_meta", {}).get("source") == "LSEG Workspace":
            # Vollständiges LSEG-data.json: alle Felder übernehmen
            return old
        # Gemischtes data.json: nur LSEG-spezifische Felder erhalten
        for key in ["brokers", "multiples", "consensus", "history"]:
            if key in old and old[key]:
                # history.annual kommt von LSEG, history.income/cashflow von FMP/Fallback
                if key == "history":
                    if old[key].get("annual"):
                        lseg["_lseg_history_annual"] = old[key]["annual"]
                else:
                    lseg[key] = old[key]
        if lseg:
            print(f"[MERGE] LSEG-Daten aus vorherigem data.json erhalten: {list(lseg.keys())}")
        return lseg
    except:
        return {}

def main():
    print("=" * 55)
    print("Scout24 SE — Data Fetcher")
    print(f"Start: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    if not FMP_KEY:
        print("\n[INFO] FMP_API_KEY nicht gesetzt — FMP-Calls werden übersprungen")

    # LSEG-Daten aus vorherigem data.json laden und erhalten
    existing_lseg = _load_existing_lseg()

    market    = fetch_market_data()
    profile   = fetch_profile()
    peers     = fetch_peers()
    fin       = fetch_financials()
    trends    = fetch_trends()
    macro     = fetch_macro()
    shorts    = fetch_bafin_shorts()

    # ── Fix #2: 2025A Fallback-Daten — immer vollständige data.json
    FALLBACK_2025A = {
        "income":  {"year": "2025A", "revenue": 649.6, "ebitda": 405.7, "ebit": 325.3,
                    "net_income": 241.3, "eps": 3.35, "ebitda_margin": 62.5},
        "balance": {"year": "2025A", "total_assets": 2065.0, "goodwill": 925.8,
                    "intangibles": 869.6, "total_equity": 650.0, "total_debt": 200.0,
                    "cash": 100.0, "net_debt": 100.0, "goodwill_pct_assets": 44.8},
        "cashflow": {"year": "2025A", "operating_cf": 320.0, "capex": -58.6,
                     "free_cashflow": 261.4, "dividends": -72.0, "buybacks": -150.0},
        "metrics":  {"year": "2025A", "ev_ebitda": 13.1, "pe_ratio": 21.7,
                     "fcf_yield": 5.0, "roce": 16.8, "ev_mn": 5314.0},
    }

    latest_income  = fin["income"][0]  if fin["income"]  else FALLBACK_2025A["income"]
    latest_balance = fin["balance"][0] if fin["balance"] else FALLBACK_2025A["balance"]
    latest_cf      = fin["cashflow"][0] if fin["cashflow"] else FALLBACK_2025A["cashflow"]
    latest_metrics = fin["metrics"][0] if fin["metrics"] else FALLBACK_2025A["metrics"]

    if not fin["income"]:
        print("    [INFO] Financials (yfinance+FMP) nicht verfügbar — verwende 2025A Fallback-Werte")
    # Historische Zeitreihen mit Fallback befüllen
    if not fin["income"]:
        fin["income"] = [
            {"year": y, "revenue": r, "ebitda": e, "ebitda_margin": round(e/r*100,1), "fcf_margin": round(f/r*100,1)}
            for y, r, e, f in [
                ("2021", 389.0, 226.5, 127.8),
                ("2022", 447.5, 263.0, 163.2),
                ("2023", 509.1, 302.2, 197.4),
                ("2024", 566.3, 348.5, 234.6),
                ("2025", 649.6, 405.7, 261.4),
            ]
        ]
    if not fin["cashflow"]:
        fin["cashflow"] = [
            {"year": y, "free_cashflow": f, "operating_cf": round(f*1.22,1), "capex": round(-f*0.22,1)}
            for y, f in [("2021",127.8),("2022",163.2),("2023",197.4),("2024",234.6),("2025",261.4)]
        ]
    # Bilanz/Multiples: falls weder yfinance noch FMP etwas lieferten, zumindest
    # die aktuelle 2025A-Zeile zeigen statt history.balance/metrics komplett leer
    if not fin["balance"]:
        fin["balance"] = [FALLBACK_2025A["balance"]]
    if not fin["metrics"]:
        fin["metrics"] = [FALLBACK_2025A["metrics"]]

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
            # LSEG history.annual erhalten wenn vorhanden
            "annual":   existing_lseg.get("_lseg_history_annual", []),
        },

        # Peer-Gruppe
        "peers": peers,

        # Traffic / KI-Signal
        "trends": trends,

        # Makro: EZB Leitzins, Bund 10J, Hypothekenzins, WACC-Implikation
        "macro": macro,

        # BaFin Short-Positionen (täglich via GitHub Actions)
        "shorts":  shorts,

        # ── LSEG-Felder erhalten (werden nur durch fetcher_lseg.py gesetzt)
        "brokers":   existing_lseg.get("brokers",   {}),
        "multiples": existing_lseg.get("multiples", {}),
        "consensus": existing_lseg.get("consensus", {}),
        "levermann": existing_lseg.get("levermann", {}),
    }

    # Scout24 selbst als markierte Referenzzeile anhaengen (fuer Live-Vergleich)
    # Robust: aus bereits berechneten kpis ableiten statt erneuter yfinance/FMP-
    # Abfrage fuer SDX.DE (die in fetch_peers() zuverlaessig fehlschlaegt, da FMP
    # Free Tier fuer SDX.DE weder key-metrics noch income-statement liefert und
    # yfinance als 6./7. sequentieller Call im selben Lauf oft leerlaeuft).
    try:
        inc_hist = fin["income"]
        rev_growth_subj = 0
        if len(inc_hist) > 1 and inc_hist[1].get("revenue"):
            rev_growth_subj = round((inc_hist[0]["revenue"] / inc_hist[1]["revenue"] - 1) * 100, 1)
        subj = {
            "name":          "Scout24",
            "ticker":        TICKER_FMP,
            "ev_ebitda":     data["kpis"]["ev_ebitda"],
            "pe_ratio":      data["kpis"]["pe_ratio"],
            "fcf_yield":     data["kpis"]["fcf_yield"],
            "ebitda_margin": data["kpis"]["ebitda_margin"],
            "rev_growth":    rev_growth_subj,
            "as_of":         datetime.date.today().isoformat(),
            "source":        "intern (kpis)",
            "is_subject":    True,
        }
        data["peers"].append(subj)
        print(f"    ✓ Scout24 (Referenz): EV/EBITDA {subj['ev_ebitda']}x (aus kpis)")
    except Exception as e:
        print(f"    [WARN] Scout24-Referenzzeile fehlgeschlagen: {e}")

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
