#!/usr/bin/env python3
"""
GEX Dashboard data engine.
Pulls options chains from yfinance, computes Greeks via Black-Scholes from
the quoted IVs (yfinance no longer returns greeks columns), then aggregates:
  - GEX / DEX / VEX / Theta exposure per strike & expiry, Zero Gamma level
  - Call/Put walls, IV per strike, Volume & Open Interest
Writes JSON into docs/data/ for the static site.
"""
import json
import math
import os
import datetime as dt

import pandas as pd
import yfinance as yf

TICKERS = ["GLD", "SLV", "^GSPC", "QQQ", "SPY", "IBIT", "ETHA", "NVDA", "TSLA"]
# Yahoo exposes no SPX options chain -> use SPY chain as a proxy, label SPX.
SYMBOL_MAP = {"^GSPC": "SPX"}
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "data"))

RISK_FREE = 0.045  # approx risk-free rate
DIV_YIELD = 0.0


def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def norm_pdf(x):
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def bs_greeks(S, K, T, sigma, kind):
    """Black-Scholes greeks: returns (gamma, delta, vega, theta)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0, (1.0 if kind == "call" else -1.0), 0.0, 0.0
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (RISK_FREE - DIV_YIELD + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    nd1 = norm_pdf(d1)
    gamma = math.exp(-DIV_YIELD * T) * nd1 / (S * sq)
    if kind == "call":
        delta = math.exp(-DIV_YIELD * T) * norm_cdf(d1)
        theta = (-(S * nd1 * sigma * math.exp(-DIV_YIELD * T)) / (2 * math.sqrt(T))
                 - RISK_FREE * K * math.exp(-RISK_FREE * T) * norm_cdf(d2)) / 365.0
    else:
        delta = -math.exp(-DIV_YIELD * T) * norm_cdf(-d1)
        theta = (-(S * nd1 * sigma * math.exp(-DIV_YIELD * T)) / (2 * math.sqrt(T))
                 + RISK_FREE * K * math.exp(-RISK_FREE * T) * norm_cdf(-d2)) / 365.0
    vega = S * math.exp(-DIV_YIELD * T) * nd1 * math.sqrt(T) / 100.0  # per 1 vol pt
    return gamma, delta, vega, theta


def kstr(k):
    f = float(k)
    return str(int(f)) if f == int(f) else str(f)


def compute_chain(tk, spot, max_expiries=8):
    """Compute exposures per expiry; returns aggregate + by_expiry breakdown."""
    expirations = (tk.options or [])[:max_expiries]
    expirations = tk.options or []
    total_gex = 0.0
    gex_by_strike, dex_by_strike, vex_by_strike = {}, {}, {}
    theta_by_strike, iv_sum, iv_cnt = {}, {}, {}
    vol_by_strike, oi_by_strike = {}, {}
    net_gex_by_expiry = {}
    daily_theta = 0.0
    gex_matrix = {}  # {expiry: {strike_str: gex}} for the heatmap
    dex_matrix, vex_matrix, theta_matrix = {}, {}, {}
    iv_matrix, vol_matrix, oi_matrix = {}, {}, {}
    cp_oi = {}    # {strike: {'c':oi,'p':oi}} call/put split
    cp_vol = {}   # {strike: {'c':vol,'p':vol}}
    totals_by_expiry = {}  # {exp: {'total_gex':..,'daily_theta':..,'zero_gamma':..,'call_wall':..,'put_wall':..}}

    now = dt.datetime.now(dt.timezone.utc)
    for exp in expirations[:8]:
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue
        exp_dt = dt.datetime.strptime(exp, "%Y-%m-%d").replace(hour=21, tzinfo=dt.timezone.utc)
        T = max((exp_dt - now).total_seconds() / (365.0 * 24 * 3600), 1e-4)

        for kind, df in (("call", chain.calls), ("put", chain.puts)):
            for _, r in df.iterrows():
                K = float(r["strike"])
                sigma = float(r.get("impliedVolatility") or 0.0)
                if sigma > 5.0 or not math.isfinite(sigma) or sigma <= 0:  # junk/missing IVs
                    continue
                oi = float(r.get("openInterest") or 0.0)
                vol = float(r.get("volume") or 0.0)
                if not math.isfinite(oi):
                    continue
                if not math.isfinite(vol):
                    vol = 0.0
                gamma, delta, vega, theta = bs_greeks(spot, K, T, sigma, kind)

                # Dealer positioning assumption: customers long calls / short puts
                sign = 1 if kind == "call" else -1
                m = 100  # contract multiplier

                gex = sign * gamma * oi * m * spot * spot * 0.01
                dex = delta * oi * m * spot
                # vanna ~ dvanna/dS; per-contract vanna approximated as vega*d1/S
                vanna_per_pt = (vega * d1_of(spot, K, T, sigma) / max(spot, 1e-9)) if sigma > 0 else 0.0
                vex = sign * vanna_per_pt * oi * m * spot * 0.01
                th_ex = theta * oi * m

                total_gex += gex
                daily_theta += th_ex
                ks = kstr(K)
                gex_by_strike[ks] = gex_by_strike.get(ks, 0) + gex
                dex_by_strike[ks] = dex_by_strike.get(ks, 0) + dex
                vex_by_strike[ks] = vex_by_strike.get(ks, 0) + vex
                theta_by_strike[ks] = theta_by_strike.get(ks, 0) + th_ex
                iv_sum[ks] = iv_sum.get(ks, 0.0) + sigma
                iv_cnt[ks] = iv_cnt.get(ks, 0) + 1
                vol_by_strike[ks] = vol_by_strike.get(ks, 0) + vol
                oi_by_strike[ks] = oi_by_strike.get(ks, 0) + oi
                net_gex_by_expiry[exp] = net_gex_by_expiry.get(exp, 0) + gex
                gex_matrix.setdefault(exp, {})[ks] = gex_matrix.get(exp, {}).get(ks, 0) + gex
                dex_matrix.setdefault(exp, {})[ks] = dex_matrix.get(exp, {}).get(ks, 0) + dex
                vex_matrix.setdefault(exp, {})[ks] = vex_matrix.get(exp, {}).get(ks, 0) + vex
                theta_matrix.setdefault(exp, {})[ks] = theta_matrix.get(exp, {}).get(ks, 0) + th_ex
                vol_matrix.setdefault(exp, {})[ks] = vol_matrix.get(exp, {}).get(ks, 0) + vol
                oi_matrix.setdefault(exp, {})[ks] = oi_matrix.get(exp, {}).get(ks, 0) + oi
                slotc = cp_oi.setdefault(ks, {"c": 0.0, "p": 0.0})
                slotc["c" if kind == "call" else "p"] += oi
                slotv = cp_vol.setdefault(ks, {"c": 0.0, "p": 0.0})
                slotv["c" if kind == "call" else "p"] += vol

    # per-expiry totals from the matrices
    for exp, smap in gex_matrix.items():
        tmap = theta_matrix.get(exp, {})
        totals_by_expiry[exp] = {
            "total_gex": sum(smap.values()),
            "daily_theta": sum(tmap.values()),
        }

    def round_dict(d):
        return {str(k): round(v, 2) for k, v in sorted(d.items())}

    def strike_dict(d):
        return {k: round(v, 2) for k, v in sorted(d.items(), key=lambda x: float(x[0]))}

    iv_avg = {k: round(iv_sum[k] / iv_cnt[k], 4) for k in iv_sum}

    return {
        "spot": round(spot, 2),
        "total_gex": round(total_gex, 2),
        "daily_theta": round(daily_theta, 2),
        "net_gex_by_expiry": round_dict(net_gex_by_expiry),
        "gex_by_strike": strike_dict(gex_by_strike),
        "dex_by_strike": strike_dict(dex_by_strike),
        "vex_by_strike": strike_dict(vex_by_strike),
        "theta_by_strike": strike_dict(theta_by_strike),
        "iv_by_strike": {k: v for k, v in sorted(iv_avg.items(), key=lambda x: float(x[0]))},
        "volume_by_strike": strike_dict(vol_by_strike),
        "oi_by_strike": strike_dict(oi_by_strike),
        "gex_matrix": {exp: strike_dict(strikes_d) for exp, strikes_d in sorted(gex_matrix.items())},
        "call_put_oi": {k: {"c": round(v["c"], 1), "p": round(v["p"], 1)} for k, v in sorted(cp_oi.items(), key=lambda x: float(x[0]))},
        "call_put_volume": {k: {"c": round(v["c"], 1), "p": round(v["p"], 1)} for k, v in sorted(cp_vol.items(), key=lambda x: float(x[0]))},
        # total call/put split across all loaded expiries
        "expirations_used": expirations[:max_expiries],
        "by_expiry": {
            exp: {
                "total_gex": round(totals_by_expiry[exp]["total_gex"], 2),
                "daily_theta": round(totals_by_expiry[exp]["daily_theta"], 2),
                "zero_gamma": zero_gamma(spot, gex_matrix[exp]),
                "call_wall": call_put_walls(gex_matrix[exp])[0],
                "put_wall": call_put_walls(gex_matrix[exp])[1],
                "gex_by_strike": strike_dict(gex_matrix[exp]),
                "dex_by_strike": strike_dict(dex_matrix.get(exp, {})),
                "vex_by_strike": strike_dict(vex_matrix.get(exp, {})),
                "theta_by_strike": strike_dict(theta_matrix.get(exp, {})),
                "iv_by_strike": {k: round(iv_sum[k] / iv_cnt[k], 4) for k in
                                 sorted({k for k in iv_sum if k in gex_matrix[exp]}, key=float)},
                "volume_by_strike": strike_dict(vol_matrix.get(exp, {})),
                "oi_by_strike": strike_dict(oi_matrix.get(exp, {})),
            }
            for exp in sorted(gex_matrix.keys())
        },
    }


def d1_of(S, K, T, sigma):
    sq = sigma * math.sqrt(T)
    return (math.log(S / K) + (RISK_FREE + 0.5 * sigma * sigma) * T) / sq


def zero_gamma(spot, gex_by_strike):
    """Zero-gamma level: cumulative net GEX from ATM outward, searching
    strikes within +/-25% of spot for the sign flip."""
    if not gex_by_strike:
        return None
    lo, hi = spot * 0.75, spot * 1.25
    strikes = sorted(float(k) for k in gex_by_strike.keys() if lo <= float(k) <= hi)
    if len(strikes) < 2:
        return None

    # order: nearest to spot first (below descending toward ATM, above ascending),
    # then accumulate outward in both directions and find sign flip.
    below = [s for s in strikes if s <= spot][::-1]
    above = [s for s in strikes if s > spot]
    merged = []
    cum_b = cum_a = 0.0
    bi = ai = 0
    while bi < len(below) or ai < len(above):
        take_below = False
        if bi < len(below) and ai < len(above):
            take_below = abs(below[bi] - spot) <= abs(above[ai] - spot)
        else:
            take_below = bi < len(below)
        if take_below:
            cum_b += gex_by_strike[kstr(below[bi])]
            merged.append((below[bi], cum_b))
            bi += 1
        else:
            cum_a += gex_by_strike[kstr(above[ai])]
            merged.append((above[ai], cum_a))
            ai += 1

    for i in range(1, len(merged)):
        s0, c0 = merged[i - 1]
        s1, c1 = merged[i]
        if abs(c0) < 1e-9:
            return round(s0, 2)
        if c0 * c1 < 0:
            t = abs(c0) / (abs(c0) + abs(c1))
            return round(s0 + t * (s1 - s0), 2)
    return None


def call_put_walls(gex_by_strike):
    if not gex_by_strike:
        return None, None
    pos = {k: v for k, v in gex_by_strike.items() if v > 0}
    neg = {k: v for k, v in gex_by_strike.items() if v < 0}
    cw = max(pos, key=pos.get) if pos else None
    pw = min(neg, key=neg.get) if neg else None
    return cw, pw


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {"updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "tickers": {}}
    for sym in TICKERS:
        label = SYMBOL_MAP.get(sym, sym)
        try:
            chain_sym = "SPY" if sym == "^GSPC" else sym
            tk = yf.Ticker(chain_sym)
            hist = tk.history(period="1d")
            if hist.empty:
                raise ValueError(f"no price history for {chain_sym}")
            spot = float(hist["Close"].iloc[-1])
            data = compute_chain(tk, spot)
            data["zero_gamma"] = zero_gamma(spot, data["gex_by_strike"])
            data["call_wall"], data["put_wall"] = call_put_walls(data["gex_by_strike"])
            data["symbol"] = label
            result["tickers"][label] = data
            print(f"OK {label}: spot={data['spot']} gex={data['total_gex']:.3e} "
                  f"zg={data['zero_gamma']} walls=({data['call_wall']},{data['put_wall']})")
        except Exception as e:
            print(f"FAIL {label}: {e}")
            result["tickers"][label] = {"error": str(e)}
    out_path = os.path.join(OUT_DIR, "gex_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(f"WROTE {out_path}")

    # ── history archive for backtesting ──
    hist_dir = os.path.join(OUT_DIR, "history")
    os.makedirs(hist_dir, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    snap = {
        "t": now.isoformat(),
        "tickers": {
            label: {
                "spot": d.get("spot"),
                "total_gex": d.get("total_gex"),
                "daily_theta": d.get("daily_theta"),
                "zero_gamma": d.get("zero_gamma"),
                "call_wall": d.get("call_wall"),
                "put_wall": d.get("put_wall"),
                "call_oi": round(sum(v["c"] for v in (d.get("call_put_oi") or {}).values()), 0),
                "put_oi": round(sum(v["p"] for v in (d.get("call_put_oi") or {}).values()), 0),
                "call_vol": round(sum(v["c"] for v in (d.get("call_put_volume") or {}).values()), 0),
                "put_vol": round(sum(v["p"] for v in (d.get("call_put_volume") or {}).values()), 0),
            }
            for label, d in result["tickers"].items()
            if "error" not in d
        },
    }
    day_path = os.path.join(hist_dir, f"{now:%Y-%m-%d}.json")
    try:
        with open(day_path, encoding="utf-8") as f:
            day = json.load(f)
    except Exception:
        day = []
    day.append(snap)
    tmp = day_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(day, f)
    os.replace(tmp, day_path)
    print(f"HISTORY +{len(day)} snaps -> {day_path}")


if __name__ == "__main__":
    main()
