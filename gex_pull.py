#!/usr/bin/env python3
"""
gex_pull.py - free gamma-exposure (GEX) levels from Cboe's public delayed quotes.

No API key, no pip installs (standard library only). Data is ~15 min delayed.

Examples
    python gex_pull.py NDX --futures-price 28034.75     # NDX options -> NQ levels
    python gex_pull.py QQQ --futures-price 28034.75     # QQQ options -> NQ levels
    python gex_pull.py NDX --max-days 10                # only expirations within 10 days
    python gex_pull.py NDX --file saved.json --spot 25800   # use a saved JSON file

Outputs (in the current folder): gex_<SYM>_<time>.csv and gex_<SYM>_<time>.html

Convention: calls = +gamma, puts = -gamma (assumes dealers long calls / short puts).
That is an assumption, not a fact. Treat the output as a map, not a signal.
Note: the Cboe endpoint is public but undocumented and may change. Personal use only.
"""
import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
OCC = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")
INDEX_SYMS = {"NDX", "SPX", "RUT", "VIX", "XSP", "DJX", "OEX"}
ET = timezone(timedelta(hours=-5))  # approximate Eastern time (ignores DST)
MULT = 100.0  # NDX/QQQ options: $100 per point / 100 shares


def fetch(symbol):
    sym = "_" + symbol if symbol in INDEX_SYMS else symbol
    req = urllib.request.Request(URL.format(sym=sym), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_spot(payload):
    d = payload.get("data", payload)
    for key in ("current_price", "close", "last_trade_price", "price"):
        v = d.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse(payload, now, max_days):
    d = payload.get("data", payload)
    rows = []
    for o in d.get("options", []):
        m = OCC.match(str(o.get("option", "")))
        if not m:
            continue
        _, ymd, cp, k = m.groups()
        exp = datetime.strptime(ymd, "%y%m%d").replace(hour=16, tzinfo=ET)
        secs = (exp - now).total_seconds()
        if secs <= 0 or secs > max_days * 86400:
            continue
        oi, iv = num(o.get("open_interest")), num(o.get("iv"))
        if oi <= 0 or iv <= 0:
            continue
        rows.append({
            "strike": int(k) / 1000.0,
            "type": cp,
            "oi": oi,
            "iv": iv,
            "T": max(secs / (365.0 * 86400.0), 1.0 / (365.0 * 24.0)),
            "exp": exp.date().isoformat(),
        })
    return rows


def bs_gamma(S, K, iv, T, r=0.04):
    sq = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / sq
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * sq)


def gex(row, S):
    sign = 1.0 if row["type"] == "C" else -1.0
    g = bs_gamma(S, row["strike"], row["iv"], row["T"])
    return sign * g * row["oi"] * MULT * S * S * 0.01  # dollars per 1% move


def by_strike(rows, S):
    agg = defaultdict(lambda: {"call": 0.0, "put": 0.0, "coi": 0.0, "poi": 0.0})
    for r in rows:
        a = agg[r["strike"]]
        v = gex(r, S)
        if r["type"] == "C":
            a["call"] += v
            a["coi"] += r["oi"]
        else:
            a["put"] += v
            a["poi"] += r["oi"]
    return dict(sorted(agg.items()))


def gamma_flip(rows, S):
    pts = []
    for i in range(-20, 21):  # -10% .. +10% in 0.5% steps
        s = S * (1 + 0.005 * i)
        pts.append((s, sum(gex(r, s) for r in rows)))
    flips = []
    for (s1, g1), (s2, g2) in zip(pts, pts[1:]):
        if g1 == 0 or g1 * g2 < 0:
            flips.append(s1 + (s2 - s1) * (0 - g1) / (g2 - g1) if g2 != g1 else s1)
    return min(flips, key=lambda x: abs(x - S)) if flips else None


def money(x):
    return "{:+,.1f}M".format(x / 1e6)


def write_html(path, title, items, spot_lvl):
    w, h, pad = 960, 380, 40
    n = len(items)
    mx = max((abs(v) for _, v in items), default=1) or 1
    bw = (w - 2 * pad) / max(n, 1)
    bars = []
    for i, (lvl, v) in enumerate(items):
        bh = abs(v) / mx * (h / 2 - pad)
        y = h / 2 - bh if v >= 0 else h / 2
        col = "#2a9d8f" if v >= 0 else "#e76f51"
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"><title>%.0f : %s</title></rect>'
                    % (pad + i * bw, y, max(bw - 1, 1), max(bh, 0.5), col, lvl, money(v)))
    lo, hi = items[0][0], items[-1][0]
    sx = pad + (spot_lvl - lo) / (hi - lo) * (w - 2 * pad) if hi > lo else pad
    html = ("<!doctype html><meta charset=utf-8><title>%s</title>"
            "<body style='font-family:sans-serif;margin:16px'><h3>%s</h3>"
            "<svg width=%d height=%d style='background:#fafafa'>%s"
            "<line x1=%d y1=%d x2=%d y2=%d stroke='#999'/>"
            "<line x1=%.1f y1=10 x2=%.1f y2=%d stroke='#264653' stroke-dasharray='4'/>"
            "<text x=%.1f y=22 font-size=12 fill='#264653'>spot %.0f</text></svg>"
            "<p style='color:#666'>Net GEX per strike ($ per 1%% move; calls +, puts -). "
            "Hover a bar for details. Estimate only.</p></body>"
            % (title, title, w, h, "".join(bars), pad, h // 2, w - pad, h // 2,
               sx, sx, h - 10, sx + 4, spot_lvl))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(description="Free GEX levels from Cboe delayed quotes")
    ap.add_argument("symbol", help="NDX, SPX, QQQ, SPY ...")
    ap.add_argument("--futures-price", type=float, help="e.g. NQ price, to map levels to futures")
    ap.add_argument("--max-days", type=float, default=45, help="max days to expiration (default 45)")
    ap.add_argument("--band", type=float, default=0.15, help="strike band around spot (default 0.15)")
    ap.add_argument("--file", help="read a saved Cboe JSON file instead of downloading")
    ap.add_argument("--spot", type=float, help="override/spot if the JSON has no price")
    a = ap.parse_args()
    sym = a.symbol.upper()

    if a.file:
        with open(a.file, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        try:
            payload = fetch(sym)
        except Exception as e:  # noqa: BLE001
            sys.exit("Download failed: %s\nOpen the URL in a browser, save it as a .json file, "
                     "then run again with --file saved.json" % e)

    spot = a.spot or find_spot(payload)
    if not spot:
        d = payload.get("data", payload)
        sys.exit("No spot price found. Re-run with --spot <price>. Keys seen: %s" % list(d.keys())[:20])

    now = datetime.now(ET)
    rows = [r for r in parse(payload, now, a.max_days) if abs(r["strike"] / spot - 1) <= a.band]
    if not rows:
        sys.exit("No usable option rows (check --max-days / --band, or the JSON layout).")

    scale = (a.futures_price / spot) if a.futures_price else 1.0
    lvl_name = "futures" if a.futures_price else sym
    agg = by_strike(rows, spot)
    net = {k: v["call"] + v["put"] for k, v in agg.items()}
    total = sum(net.values())
    call_wall = max(agg, key=lambda k: agg[k]["call"])
    put_wall = min(agg, key=lambda k: agg[k]["put"])
    flip = gamma_flip(rows, spot)

    print("\n%s spot %.2f | %d contracts | expirations within %.0f days | %s"
          % (sym, spot, len(rows), a.max_days, now.strftime("%Y-%m-%d %H:%M ET(approx)")))
    print("Levels shown in %s points (scale %.5f)\n" % (lvl_name, scale))
    print("Net GEX (calls +, puts -): %s per 1%% move" % money(total))
    print("Call wall : %10.0f   (%s)" % (call_wall * scale, money(agg[call_wall]["call"])))
    print("Put wall  : %10.0f   (%s)" % (put_wall * scale, money(agg[put_wall]["put"])))
    print("Gamma flip: %10s" % ("%.0f" % (flip * scale) if flip else "none within +/-10%"))
    print("\nTop 10 strikes by |net GEX|:")
    for k in sorted(net, key=lambda x: -abs(net[x]))[:10]:
        print("  %10.0f  net %s  (callOI %d, putOI %d)"
              % (k * scale, money(net[k]), agg[k]["coi"], agg[k]["poi"]))

    stamp = now.strftime("%Y%m%d_%H%M")
    csv_path, html_path = "gex_%s_%s.csv" % (sym, stamp), "gex_%s_%s.html" % (sym, stamp)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["strike", "level_" + lvl_name, "call_gex", "put_gex", "net_gex", "call_oi", "put_oi"])
        for k, v in agg.items():
            wr.writerow([k, round(k * scale, 2), round(v["call"]), round(v["put"]),
                         round(v["call"] + v["put"]), int(v["coi"]), int(v["poi"])])
    near = [(k * scale, net[k]) for k in sorted(net) if abs(k / spot - 1) <= 0.05]
    if len(near) > 1:
        write_html(html_path, "%s GEX (%s levels)" % (sym, lvl_name), near, spot * scale)
    print("\nWrote %s and %s" % (csv_path, html_path))


if __name__ == "__main__":
    main()
