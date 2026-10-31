#!/usr/bin/env python3
"""TARS2 stats: ingest Autonimator data and render /cybertruck/stats/.

Standard library only. Two subcommands:

  ingest  --status S.json --drives D.json --charges C.json [--invoices I.json]
          Reads raw tool output (the JSON returned by the Autonimator tools:
          get_vehicle_status, list_recent_drives, list_recent_charges,
          list_charging_invoices) and updates cybertruck/stats/data.json.
          Raw drives are reduced to per-day totals before anything is stored:
          no addresses, no routes, no times ever reach the repo.

  render  Rewrites the block between <!-- tars2:start --> and <!-- tars2:end -->
          in cybertruck/stats/index.html from data.json. Nothing outside the
          markers is touched.

Weeks run Monday to Sunday in America/Detroit.
"""
import argparse, json, os, re, sys
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "cybertruck", "stats", "data.json")
PAGE = os.path.join(ROOT, "cybertruck", "stats", "index.html")
TZ = ZoneInfo("America/Detroit")
START = "<!-- tars2:start -->"
MSTART, MEND = "<!-- tars2-mini:start -->", "<!-- tars2-mini:end -->"
MINI_PAGES = ["cybertruck/index.html", "adventure/index.html"]
END = "<!-- tars2:end -->"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")


def local_day(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).date()


def empty():
    return {
        "vehicle": "TARS2",
        "tracking_since": None,
        "updated": None,
        "config": {"odometer_baseline_miles": None, "odometer_baseline_date": None, "supercharging_before_ledger_kwh": None},
        "current": {},
        "days": {},
        "drive_ids": [],
        "supercharging": {"sessions": {}},
        "home_charging": {"kwh_by_day": {}},
    }


# ---------------------------------------------------------------- ingest
def ingest(args):
    d = load_json(DATA) if os.path.exists(DATA) else empty()
    today = datetime.now(TZ).date()

    # current status
    if args.status:
        s = load_json(args.status)
        s = s.get("status", s)
        d["current"] = {
            "battery_percent": s.get("battery_percent"),
            "range_miles": round(s.get("range_miles") or 0),
            "software": s.get("software_version"),
            "outside_temp_f": None if s.get("outside_temp_c") is None else round(s["outside_temp_c"] * 9 / 5 + 32),
            "plugged_in": s.get("plugged_in"),
            "charging_state": s.get("charging_state"),
            "as_of": s.get("last_updated"),
        }

    # drives -> per-day totals (dedup by id). Skip the day still in progress
    # unless --include-today is set (the nightly run sets it).
    if args.drives:
        raw = load_json(args.drives)
        drives = raw["drives"] if isinstance(raw, dict) else raw
        seen = set(d["drive_ids"])
        for dr in drives:
            did = dr.get("id")
            if not did or did in seen:
                continue
            miles = dr.get("distance_miles") or 0
            if miles < 0.3:
                continue  # repositioning in the driveway, not a drive
            day = local_day(dr["started_at"])
            if day > today or (day == today and not args.include_today):
                continue
            if d.get("csv_cutoff") and day.isoformat() <= d["csv_cutoff"]:
                continue
            seen.add(did)
            d["drive_ids"].append(did)
            k = day.isoformat()
            row = d["days"].setdefault(k, {"miles": 0, "drives": 0, "kwh": 0, "measured_miles": 0, "longest": 0, "temp_c_sum": 0, "temp_n": 0, "minutes": 0})
            row["miles"] = round(row["miles"] + miles, 2)
            row["drives"] += 1
            row["minutes"] += dr.get("duration_minutes") or 0
            row["longest"] = round(max(row["longest"], miles), 2)
            if dr.get("efficiency_method") == "measured" and dr.get("energy_kwh"):
                row["kwh"] = round(row["kwh"] + dr["energy_kwh"], 2)
                row["measured_miles"] = round(row["measured_miles"] + miles, 2)
            if dr.get("outside_temp_c") is not None:
                row["temp_c_sum"] = round(row["temp_c_sum"] + dr["outside_temp_c"], 1)
                row["temp_n"] += 1
                row["temp_min_c"] = min(row.get("temp_min_c", 99), dr["outside_temp_c"])
                row["temp_max_c"] = max(row.get("temp_max_c", -99), dr["outside_temp_c"])
        d["drive_ids"] = d["drive_ids"][-400:]
        if d["days"] and not d["tracking_since"]:
            d["tracking_since"] = min(d["days"])

    # home / third-party charging -> kWh by day
    if args.charges:
        raw = load_json(args.charges)
        for c in (raw["sessions"] if isinstance(raw, dict) else raw):
            if c.get("supercharger"):
                continue
            kwh = c.get("energy_added_kwh") or 0
            if kwh < 0.5:
                continue
            k = local_day(c["started_at"]).isoformat()
            if d.get("csv_cutoff") and k <= d["csv_cutoff"]:
                continue
            key = c["started_at"][:16]
            byday = d["home_charging"]["kwh_by_day"].setdefault(k, {})
            byday[key] = round(kwh, 2)

    # Supercharger invoices -> session ledger keyed by Tesla session id
    if args.invoices:
        raw = load_json(args.invoices)
        for inv in (raw["invoices"] if isinstance(raw, dict) else raw):
            sid = str(inv.get("session_id"))
            if not sid:
                continue
            if d.get("csv_cutoff") and local_day(inv["started_at"]).isoformat() <= d["csv_cutoff"]:
                continue
            d["supercharging"]["sessions"][sid] = {
                "date": local_day(inv["started_at"]).isoformat(),
                "site": inv.get("site"),
                "kwh": round(inv.get("kwh_billed") or 0, 2),
                "currency": inv.get("currency"),
            }

    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(DATA, d)
    print("data.json updated:", len(d["days"]), "days,", len(d["supercharging"]["sessions"]), "Supercharger sessions")



# ---------------------------------------------------------------- history import
US_STATES = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY","District of Columbia":"DC",
"Alberta":"AB","British Columbia":"BC","Manitoba":"MB","New Brunswick":"NB","Newfoundland and Labrador":"NL","Nova Scotia":"NS","Ontario":"ON","Prince Edward Island":"PE","Quebec":"QC","Saskatchewan":"SK"}


def site_from_address(addr):
    """'17 Some St, City, State 49503, United States' -> 'City, ST' (never the street)."""
    parts = [x.strip() for x in (addr or "").split(",")]
    if len(parts) < 3:
        return None
    city = parts[-3]
    st = re.sub(r"\s+\d{5}(-\d{4})?$", "", parts[-2])
    st = re.sub(r"\s+[A-Z]\d[A-Z] ?\d[A-Z]\d$", "", st)
    return f"{city}, {US_STATES.get(st, st)}"


def import_history(args):
    """Fold an earlier drive/charge export (CSV) into data.json as per-day totals
    and a Supercharger ledger. Only totals and 'City, ST' site names are kept."""
    import csv
    d = load_json(DATA) if os.path.exists(DATA) else empty()
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else None
    if args.target == "current":
        # The export is the complete record for the current truck up to its last
        # row. It replaces anything the nightly feed stored on or before that day,
        # so nothing is counted twice; the feed takes over from the next day.
        hist = {"days": d["days"], "supercharging": d["supercharging"]["sessions"], "odometer_miles": None, "through": None, "since": None}
    else:
        hist = d.setdefault("history", {"days": {}, "supercharging": {}, "odometer_miles": None, "through": None, "since": None})
    if args.drives:
        rows = list(csv.DictReader(open(args.drives, encoding="utf-8")))
        if args.target == "current":
            last = max(r["Started At (EDT)"][:10] for r in rows)
            for k in [k for k in hist["days"] if k <= last]:
                del hist["days"][k]
            for k in [k for k, v in hist["supercharging"].items() if v["date"] <= last]:
                del hist["supercharging"][k]
            d["home_charging"]["kwh_by_day"] = {k: v for k, v in d["home_charging"]["kwh_by_day"].items() if k > last}
            d["csv_cutoff"] = last
            d["drive_ids"] = []
        for r in rows:
            miles = f(r, "Distance (mi)") or 0
            if miles < 0.3:
                continue
            k = r["Started At (EDT)"][:10]
            row = hist["days"].setdefault(k, {"miles": 0, "drives": 0, "kwh": 0, "measured_miles": 0, "longest": 0, "temp_c_sum": 0, "temp_n": 0, "minutes": 0})
            row["miles"] = round(row["miles"] + miles, 2); row["drives"] += 1
            row["minutes"] += int(f(r, "Duration (Minutes)") or 0)
            row["longest"] = round(max(row["longest"], miles), 2)
            kwh = f(r, "Total Energy Used (kWh)")
            if kwh:
                row["kwh"] = round(row["kwh"] + kwh, 2); row["measured_miles"] = round(row["measured_miles"] + miles, 2)
            t = f(r, "Average Outside Temperature (°F)")
            if t is not None:
                c = (t - 32) * 5 / 9
                row["temp_c_sum"] = round(row["temp_c_sum"] + c, 1); row["temp_n"] += 1
                row["temp_min_c"] = round(min(row.get("temp_min_c", 99), c), 1)
                row["temp_max_c"] = round(max(row.get("temp_max_c", -99), c), 1)
            ap = f(r, "Autopilot Distance (mi)")
            if ap is not None:
                row["fsd_miles"] = round(row.get("fsd_miles", 0) + ap, 2)
                row["fsd_base_miles"] = round(row.get("fsd_base_miles", 0) + miles, 2)
            odo = f(r, "Ending Odometer (mi)")
            if odo and odo > (hist["odometer_miles"] or 0):
                hist["odometer_miles"] = round(odo, 1)
        ks = sorted(hist["days"])
        hist["since"], hist["through"] = ks[0], ks[-1]
        if args.target == "current":
            d["tracking_since"] = ks[0]
            d["config"]["odometer_baseline_miles"] = hist["odometer_miles"]
            d["config"]["odometer_baseline_date"] = (date.fromisoformat(ks[-1]) + timedelta(days=1)).isoformat()
            d["config"]["odometer_note"] = f"odometer {hist['odometer_miles']} from the complete export through {ks[-1]}; tracked drives after that are added"
    if args.charges:
        for i, r in enumerate(csv.DictReader(open(args.charges, encoding="utf-8"))):
            kwh = f(r, "Energy Added (kWh)") or 0
            if kwh < 0.5:
                continue
            if r.get("Supercharger") != "true":
                if args.target == "current":
                    k = r["Started At (EDT)"][:10]
                    d["home_charging"]["kwh_by_day"].setdefault(k, {})[r["Started At (EDT)"].replace(" ", "T")] = round(kwh, 2)
                continue
            site = site_from_address(r.get("Location"))
            key = "h-" + r["Started At (EDT)"].replace(" ", "T")
            hist["supercharging"][key] = {"date": r["Started At (EDT)"][:10], "site": site, "kwh": round(kwh, 2), "currency": "CAD" if site and site.endswith(tuple(f", {v}" for v in ("AB","BC","MB","NB","NL","NS","ON","PE","QC","SK"))) else "USD"}
    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(DATA, d)
    print("history:", len(hist["days"]), "days,", len(hist["supercharging"]), "Supercharger sessions, odometer", hist["odometer_miles"], hist["since"], "→", hist["through"])


# ---------------------------------------------------------------- summaries
def week_bounds(day):
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def summarize(days, start, end):
    out = {"miles": 0, "drives": 0, "kwh": 0, "measured_miles": 0, "longest": 0, "temp_sum": 0, "temp_n": 0, "minutes": 0, "days_driven": 0, "temp_min_c": None, "temp_max_c": None, "best_day": (None, 0)}
    cur = start
    while cur <= end:
        r = days.get(cur.isoformat())
        if r:
            if r.get("temp_min_c") is not None:
                out["temp_min_c"] = r["temp_min_c"] if out["temp_min_c"] is None else min(out["temp_min_c"], r["temp_min_c"])
            if r.get("temp_max_c") is not None:
                out["temp_max_c"] = r["temp_max_c"] if out["temp_max_c"] is None else max(out["temp_max_c"], r["temp_max_c"])
            if r["miles"] > out["best_day"][1]:
                out["best_day"] = (cur.isoformat(), r["miles"])
            out["fsd_miles"] = out.get("fsd_miles", 0) + r.get("fsd_miles", 0)
            out["fsd_base_miles"] = out.get("fsd_base_miles", 0) + r.get("fsd_base_miles", 0)
            out["miles"] += r["miles"]; out["drives"] += r["drives"]; out["kwh"] += r["kwh"]
            out["measured_miles"] += r["measured_miles"]; out["minutes"] += r["minutes"]
            out["longest"] = max(out["longest"], r["longest"])
            out["temp_sum"] += r["temp_c_sum"]; out["temp_n"] += r["temp_n"]
            out["days_driven"] += 1
        cur += timedelta(days=1)
    out["wh_per_mile"] = round(out["kwh"] * 1000 / out["measured_miles"]) if out["measured_miles"] else None
    out["avg_temp_f"] = round((out["temp_sum"] / out["temp_n"]) * 9 / 5 + 32) if out["temp_n"] else None
    out.setdefault("fsd_miles", 0); out.setdefault("fsd_base_miles", 0)
    out["fsd_share"] = round(100 * out["fsd_miles"] / out["fsd_base_miles"]) if out["fsd_base_miles"] else None
    out["min_temp_f"] = round(out["temp_min_c"] * 9 / 5 + 32) if out["temp_min_c"] is not None else None
    out["max_temp_f"] = round(out["temp_max_c"] * 9 / 5 + 32) if out["temp_max_c"] is not None else None
    out["start"], out["end"] = start, end
    return out


def fmt_n(n, dec=0):
    if n is None:
        return "—"
    return f"{n:,.{dec}f}"


def base_site(site):
    """'Grand Rapids, MI - Lake Michigan Drive Northwest' -> 'Grand Rapids, MI'."""
    return re.split(r"\s+-\s+", site or "", maxsplit=1)[0].strip()


def region(site):
    m = re.search(r",\s*([A-Z]{2})\b", site or "")
    return m.group(1) if m else None


def mdy(dt):
    return dt.strftime("%b %-d, %Y")


def md(dt):
    return dt.strftime("%b %-d")


# ---------------------------------------------------------------- charts
def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def svg_bars(series, title, unit="", height=220, highlight=None, narrow=False):
    """Vertical bars. series = [(label, value, tooltip)]. Single hue, thin marks,
    rounded data-ends, direct labels on the max only, native <title> tooltips."""
    n = len(series)
    if not n:
        return ""
    W, H, pad_l, pad_b, pad_t = (360, 240, 12, 30, 24) if narrow else (720, height, 24, 34, 26)
    vmax = max((v for _, v, _ in series if v is not None), default=0) or 1
    gap = 2 if narrow else 3
    bw = (W - pad_l - (12 if narrow else 24)) / n - gap
    out = [f'<svg class="chart {"narrow" if narrow else "wide"}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>']
    for i, (lab, v, tip) in enumerate(series):
        x = pad_l + i * (bw + gap)
        if v:
            h = max(4, (H - pad_b - pad_t) * v / vmax)
            y = H - pad_b - h
            fill = "var(--amber)" if highlight is not None and i == highlight else "var(--primary)"
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" fill="{fill}"><title>{esc(tip)}</title></rect>')
            if v == vmax:
                out.append(f'<text x="{x + bw/2:.1f}" y="{y - 8:.1f}" text-anchor="middle" class="val">{fmt_n(v)}{unit}</text>')
        else:
            out.append(f'<rect x="{x:.1f}" y="{H - pad_b - 2}" width="{bw:.1f}" height="2" fill="var(--line)"><title>{esc(tip)}</title></rect>')
        step = max(1, -(-n // (4 if narrow else 7)))
        if i % step == 0 or n <= (4 if narrow else 7):
            out.append(f'<text x="{x + bw/2:.1f}" y="{H - 10}" text-anchor="middle" class="ax">{esc(lab)}</text>')
    out.append(f'<line x1="{pad_l}" y1="{H - pad_b}" x2="{W}" y2="{H - pad_b}" class="base"/>')
    out.append("</svg>")
    return "".join(out)


def svg_line(series, title, unit="", height=220, narrow=False):
    """Single 2px line with 8px markers; series = [(label, value, tooltip)]; None = gap."""
    n = len(series)
    if n < 2:
        return ""
    W, H, pad_l, pad_b, pad_t = (360, 240, 20, 30, 24) if narrow else (720, height, 28, 34, 26)
    vals = [v for _, v, _ in series if v is not None]
    if not vals:
        return ""
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1
    lo, hi = vmin - span * 0.25, vmax + span * 0.25
    def X(i): return pad_l + i * (W - pad_l - (20 if narrow else 28)) / (n - 1)
    def Y(v): return H - pad_b - (H - pad_b - pad_t) * (v - lo) / (hi - lo)
    out = [f'<svg class="chart {"narrow" if narrow else "wide"}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>']
    path, pen = [], False
    for i, (_, v, _) in enumerate(series):
        if v is None:
            pen = False; continue
        path.append(f'{"L" if pen else "M"}{X(i):.1f},{Y(v):.1f}'); pen = True
    out.append(f'<path d="{" ".join(path)}" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linejoin="round"/>')
    for i, (lab, v, tip) in enumerate(series):
        if v is not None:
            out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5" fill="var(--primary)" stroke="var(--surface)" stroke-width="2"><title>{esc(tip)}</title></circle>')
            if v == vmax or v == vmin:
                out.append(f'<text x="{X(i):.1f}" y="{Y(v) - 12 if v == vmax else Y(v) + 20:.1f}" text-anchor="middle" class="val">{fmt_n(v)}{unit}</text>')
        step = max(1, -(-n // (4 if narrow else 7)))
        if i % step == 0 or n <= (4 if narrow else 7):
            out.append(f'<text x="{X(i):.1f}" y="{H - 10}" text-anchor="middle" class="ax">{esc(lab)}</text>')
    out.append(f'<line x1="{pad_l}" y1="{H - pad_b}" x2="{W}" y2="{H - pad_b}" class="base"/></svg>')
    return "".join(out)


def svg_hbars(series, title, unit="", narrow=False):
    """Horizontal bars for ranked categories: [(label, value, tooltip)]."""
    n = len(series)
    if not n:
        return ""
    W, row, pad_t, lab_w = (360, 30, 4, 118) if narrow else (720, 34, 4, 200)
    H = pad_t + n * row
    vmax = max(v for _, v, _ in series) or 1
    out = [f'<svg class="chart hbars {"narrow" if narrow else "wide"}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>']
    for i, (lab, v, tip) in enumerate(series):
        y = pad_t + i * row
        w = max(4, (W - lab_w - (62 if narrow else 70)) * v / vmax)
        out.append(f'<text x="{lab_w - 12}" y="{y + 21}" text-anchor="end" class="lab">{esc(lab)}</text>')
        out.append(f'<rect x="{lab_w}" y="{y + 8}" width="{w:.1f}" height="18" rx="4" fill="var(--primary)"><title>{esc(tip)}</title></rect>')
        out.append(f'<text x="{lab_w + w + 10:.1f}" y="{y + 21}" class="val">{fmt_n(v)}{unit}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_gauge(pct, label):
    import math
    r, cx, cy = 70, 90, 92
    def pt(p):
        a = math.pi * (1 - p)
        return cx + r * math.cos(a), cy - r * math.sin(a)
    x0, y0 = pt(0); x1, y1 = pt(pct / 100)
    big = 1 if pct > 50 else 0
    return (f'<svg class="gauge" viewBox="0 0 180 110" role="img" aria-label="{esc(label)}"><title>{esc(label)}</title>'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 1 1 {cx + r},{cy}" fill="none" stroke="var(--line)" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {big} 1 {x1:.1f},{y1:.1f}" fill="none" stroke="var(--primary)" stroke-width="12" stroke-linecap="round"/>'
            f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" class="big">{pct}%</text></svg>')


def both(fn, *a, **k):
    return fn(*a, **k) + fn(*a, narrow=True, **k)


# ---------------------------------------------------------------- render
MAP = ('<div class="map" id="tars2-map" role="img" aria-label="Map of every logged drive, drawn start to end on a 5 km grid"><span>Loading the drive map…</span></div>'
       '<p class="mnote">Every logged drive since June 2024, drawn as a straight line from where it started to where it ended, on a 5 km grid; the busiest routes are amber and the dots are Supercharger stops (tap one). Zoom stays at state level on purpose.</p>')
POWERED = '<a class="powered" href="https://www.autonimator.com" rel="noopener"><span class="pw-dot" aria-hidden="true"></span>Powered by <b>Autonimator</b></a>'


def render(args):
    d = load_json(DATA)
    days = d["days"]
    today = datetime.now(TZ).date()
    asof = datetime.fromisoformat(d["updated"]).astimezone(TZ) if d.get("updated") else datetime.now(TZ)

    ws, we = week_bounds(today)
    this_week = summarize(days, ws, min(we, today))
    last_week = summarize(days, ws - timedelta(days=7), ws - timedelta(days=1))
    week_label = f"{md(ws)}–{md(min(we, today))}" if today < we else f"{md(ws)}–{md(we)}"

    tracked = summarize(days, date.fromisoformat(d["tracking_since"]), today) if d.get("tracking_since") else None
    cfg = d.get("config") or {}
    odo = None
    if cfg.get("odometer_baseline_miles") and cfg.get("odometer_baseline_date") and tracked:
        since = summarize(days, date.fromisoformat(cfg["odometer_baseline_date"]), today)
        odo = cfg["odometer_baseline_miles"] + since["miles"]
    sc_before = 0

    hist = d.get("history") or {"days": {}, "supercharging": {}}
    sc = list(d["supercharging"]["sessions"].values()) + list(hist.get("supercharging", {}).values())
    life_days = dict(hist.get("days", {})); life_days.update(days)
    life_since = min(life_days) if life_days else None
    lifetime = summarize(life_days, date.fromisoformat(life_since), today) if life_since else None
    hist_odo = hist.get("odometer_miles") or 0
    sc_kwh = sum(s["kwh"] for s in sc)
    for x in sc:
        x["site"] = base_site(x.get("site"))
    sites = sorted({s["site"] for s in sc if s.get("site")})
    regions = sorted({r for r in (region(s) for s in sites) if r})
    countries = sorted({"Canada" if s.get("currency") == "CAD" else "United States" for s in sc})
    first_sc = min((s["date"] for s in sc), default=None)
    sc_week = [s for s in sc if ws.isoformat() <= s["date"] <= we.isoformat()]
    biggest = max(sc, key=lambda s: s["kwh"], default=None)
    by_month, by_site = {}, {}
    for s in sc:
        m = s["date"][:7]
        by_month.setdefault(m, [0, 0.0, set()])
        by_month[m][0] += 1; by_month[m][1] += s["kwh"]; by_month[m][2].add(s.get("site"))
        by_site.setdefault(s.get("site"), [0, 0.0])
        by_site[s["site"]][0] += 1; by_site[s["site"]][1] += s["kwh"]

    home_week = 0
    for k, sess in d["home_charging"]["kwh_by_day"].items():
        if ws.isoformat() <= k <= we.isoformat():
            home_week += sum(sess.values())
    cur = d.get("current") or {}

    def stat(val, label, word=False):
        cls = ' class="word"' if word else ""
        return f'<div class="stat" role="listitem"><b{cls}>{val}</b><span>{label}</span></div>'

    def delta(a, b):
        if not b or a is None:
            return ""
        ch = (a - b) / b * 100
        return f' <small class="delta">{"▲" if ch > 0 else "▼"} {abs(ch):.0f}% vs last week</small>'

    # --- chart data
    last14 = [today - timedelta(days=13 - i) for i in range(14)]
    daily_miles = [(dd.strftime("%a %-d"), days.get(dd.isoformat(), {}).get("miles"), f'{mdy(dd)}: {fmt_n(days.get(dd.isoformat(), {}).get("miles"), 1)} miles, {days.get(dd.isoformat(), {}).get("drives", 0)} drives') for dd in last14]
    daily_eff = []
    for dd in last14:
        r = days.get(dd.isoformat())
        v = round(r["kwh"] * 1000 / r["measured_miles"]) if r and r["measured_miles"] else None
        daily_eff.append((dd.strftime("%a %-d"), v, f'{mdy(dd)}: {fmt_n(v)} Wh/mi over {fmt_n(r["measured_miles"] if r else 0, 1)} measured miles'))
    months = sorted(by_month)
    if months:
        m0, m1 = months[0], months[-1]
        y, mo = int(m0[:4]), int(m0[5:])
        months = []
        while f"{y:04d}-{mo:02d}" <= m1:
            months.append(f"{y:04d}-{mo:02d}"); mo += 1
            if mo == 13: y, mo = y + 1, 1
        for m in months: by_month.setdefault(m, [0, 0.0, set()])
    month_bars = [(datetime.strptime(m, "%Y-%m").strftime("%b '%y"), round(by_month[m][1]), f'{datetime.strptime(m, "%Y-%m").strftime("%B %Y")}: {fmt_n(by_month[m][1])} kWh across {by_month[m][0]} sessions at {len(by_month[m][2])} sites') for m in months]
    top_sites = sorted(by_site.items(), key=lambda kv: -kv[1][1])[:8]
    site_bars = [(k, round(v[1]), f'{k}: {fmt_n(v[1])} kWh over {v[0]} session{"s" if v[0] != 1 else ""}') for k, v in top_sites]

    h = []
    h.append(f'<div class="stamp"><p class="label">Updated {asof.strftime("%A, %b %-d, %Y at %-I:%M %p")} ET · refreshed every Sunday night from the truck</p></div>')

    # --- lifetime (tracked drives + imported history + odometer seed)
    life_miles = (hist_odo + (odo if odo else tracked["miles"])) if tracked else hist_odo
    h.append('<section class="sec" id="lifetime" aria-labelledby="life-h"><div class="sec-head"><div><p class="label">Lifetime</p><h2 id="life-h">Since 2024, <em>every mile logged.</em></h2></div></div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(fmt_n(life_miles), 'Cybertruck miles, lifetime'))
    h.append(stat(fmt_n(lifetime["drives"]) if lifetime else "—", f'Drives logged since {mdy(date.fromisoformat(life_since))}' if life_since else 'Drives logged'))
    h.append(stat(fmt_n(lifetime["wh_per_mile"]) if lifetime else "—", 'Wh per mile, lifetime average'))
    h.append(stat(fmt_n(lifetime["minutes"] / 60) if lifetime else "—", 'Hours behind the wheel'))
    h.append('</div><div class="stats" role="list">')
    h.append(stat(fmt_n(sc_kwh + sc_before), 'kWh Supercharged, lifetime'))
    h.append(stat(f'{len(sc)}', 'Supercharger sessions'))
    h.append(stat(f'{len(sites)}', f'Supercharger sites in {len(regions)} states and provinces, {len(countries)} countries'))
    h.append(stat(fmt_n(biggest["kwh"]) if biggest else "—", f'Biggest single session, kWh ({esc(biggest["site"])})' if biggest else 'Biggest single session'))
    h.append('</div><div class="stats" role="list">')
    co = cfg.get("coldest_override")
    if co:
        h.append(stat(f'{co["temp_f"]}°F', f'Coldest drive on record ({mdy(date.fromisoformat(co["date"]))}, <a href="{esc(co["source"])}" rel="noopener">on the dash</a>)'))
    else:
        h.append(stat(f'{lifetime["min_temp_f"]}°F' if lifetime and lifetime["min_temp_f"] is not None else "—", 'Coldest drive on record, average outside temp'))
    h.append(stat(f'{lifetime["max_temp_f"]}°F' if lifetime and lifetime["max_temp_f"] is not None else "—", 'Hottest drive on record, average outside temp'))
    h.append(stat(fmt_n(lifetime["longest"]) if lifetime else "—", 'Longest single drive, miles'))
    h.append(stat(fmt_n(lifetime["best_day"][1]) if lifetime else "—", f'Biggest day, miles ({mdy(date.fromisoformat(lifetime["best_day"][0]))})' if lifetime and lifetime["best_day"][0] else 'Biggest day, miles'))
    h.append('</div>')
    h.append('<div class="grid2 charts">')
    h.append(f'<figure class="card"><figcaption><p class="tag">By month</p><h3>Supercharged kWh</h3></figcaption>{both(svg_bars, month_bars, "Supercharged kWh by month", " kWh")}</figure>')
    h.append(f'<figure class="card"><figcaption><p class="tag">Top sites</p><h3>Where the kWh came from</h3></figcaption>{both(svg_hbars, site_bars, "Top Supercharger sites by kWh", " kWh")}</figure>')
    h.append('</div>')
    h.append('<figure class="map-fig"><figcaption class="sec-head" style="margin:28px 0 16px"><div><p class="tag">Every drive</p><h3>On the map</h3></div></figcaption>' + MAP + '</figure>')
    h.append('<p class="chips" aria-label="States and provinces with a Supercharger stop">' + "".join(f'<span>{esc(r)}</span>' for r in regions) + '</p>')
    def mrow(m):
        return f'<tr><td>{datetime.strptime(m, "%Y-%m").strftime("%B %Y")}</td><td>{by_month[m][0]}</td><td>{fmt_n(by_month[m][1])}</td><td>{len(by_month[m][2])}</td></tr>'
    used = [m for m in reversed(months) if by_month[m][0]]
    h.append('<div class="tablewrap"><table id="months-t"><thead><tr><th>Month</th><th>Sessions</th><th>kWh</th><th>Sites</th></tr></thead><tbody>')
    h.extend(mrow(m) for m in used[:12])
    h.append('</tbody></table></div>')
    if len(used) > 12:
        h.append('<details class="mnote"><summary>Earlier months</summary><div class="tablewrap"><table id="months-t2" class="months"><tbody>' + "".join(mrow(m) for m in used[12:]) + '</tbody></table></div></details>')
    h.append(f'<details class="mnote"><summary>All {len(sites)} Supercharger sites</summary><p>{esc(", ".join(sites))}.</p></details>')
    h.append('</section>')

    # --- this week
    h.append(f'<section class="sec" id="week" aria-labelledby="week-h"><div class="sec-head"><div><p class="label">This week</p><h2 id="week-h">{week_label}, <em>in the truck.</em></h2></div></div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(fmt_n(this_week["miles"]), f'Miles driven{delta(this_week["miles"], last_week["miles"])}'))
    h.append(stat(fmt_n(this_week["wh_per_mile"]), f'Wh per mile, measured{delta(this_week["wh_per_mile"], last_week["wh_per_mile"])}'))
    h.append(stat(fmt_n(this_week["drives"]), f'Drives over {this_week["days_driven"]} day{"s" if this_week["days_driven"] != 1 else ""}'))
    h.append(stat(fmt_n(this_week["longest"]), 'Longest single drive, miles'))
    h.append('</div><div class="stats" role="list">')
    h.append(stat(f'{len(sc_week)}', f'Supercharger stop{"s" if len(sc_week) != 1 else ""}, {fmt_n(sum(s["kwh"] for s in sc_week))} kWh added'))
    h.append(stat(fmt_n(home_week), 'kWh added charging at home'))
    h.append(stat(fmt_n(this_week["kwh"]), 'kWh used driving'))
    h.append(stat(f'{this_week["min_temp_f"]}°F' if this_week["min_temp_f"] is not None else "—", 'Coldest drive this week, outside temp'))
    h.append('</div>')
    h.append('<div class="grid2 charts">')
    h.append(f'<figure class="card"><figcaption><p class="tag">Daily miles</p><h3>Last two weeks</h3></figcaption>{both(svg_bars, daily_miles, "Miles driven per day, last two weeks", " mi")}</figure>')
    h.append(f'<figure class="card"><figcaption><p class="tag">Efficiency</p><h3>Wh per mile, by day</h3></figcaption>{both(svg_line, daily_eff, "Watt-hours per mile by day, last two weeks")}</figure>')
    h.append('</div>')
    if last_week["drives"]:
        h.append(f'<p class="mnote">Last week ({md(ws - timedelta(days=7))}–{md(ws - timedelta(days=1))}): {fmt_n(last_week["miles"])} miles, {fmt_n(last_week["wh_per_mile"])} Wh/mi, {last_week["drives"]} drives.</p>')
    h.append('</section>')

    # --- FSD
    fsd_months = {}
    for k, r in life_days.items():
        if r.get("fsd_base_miles"):
            fsd_months.setdefault(k[:7], [0, 0])
            fsd_months[k[:7]][0] += r.get("fsd_miles", 0); fsd_months[k[:7]][1] += r["fsd_base_miles"]
    fsd_all = sorted(m for m in fsd_months if fsd_months[m][1] >= 50)
    # chart only the unbroken recent run of months (the log has an early gap)
    fsd_m = []
    for m in reversed(fsd_all):
        if fsd_m:
            y, mo = int(fsd_m[0][:4]), int(fsd_m[0][5:])
            prev = f"{y - 1 if mo == 1 else y:04d}-{12 if mo == 1 else mo - 1:02d}"
            if m != prev:
                break
        fsd_m.insert(0, m)
    fsd_bars = [(datetime.strptime(m, "%Y-%m").strftime("%b '%y"), round(100 * fsd_months[m][0] / fsd_months[m][1]), f'{datetime.strptime(m, "%Y-%m").strftime("%B %Y")}: {fmt_n(fsd_months[m][0])} of {fmt_n(fsd_months[m][1])} miles on FSD ({round(100 * fsd_months[m][0] / fsd_months[m][1])}%)') for m in fsd_m]
    fsd_days = {k: r for k, r in life_days.items() if r.get("fsd_base_miles")}
    fsd_since = min(fsd_days) if fsd_days else None
    fsd_last = max(fsd_days) if fsd_days else None
    recent = summarize(life_days, date.fromisoformat(fsd_last) - timedelta(days=89), date.fromisoformat(fsd_last)) if fsd_last else None
    best_fsd_month = max(fsd_all, key=lambda m: fsd_months[m][0], default=None)
    h.append('<section class="sec" id="fsd" aria-labelledby="fsd-h"><div class="sec-head"><div><p class="label">Full Self-Driving (Supervised)</p><h2 id="fsd-h">How much the truck <em>drives itself.</em></h2></div></div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(fmt_n(lifetime["fsd_miles"]) if lifetime else "—", f'Miles driven on FSD (logged since {mdy(date.fromisoformat(fsd_since))})' if fsd_since else 'Miles driven on FSD'))
    h.append(stat(f'{lifetime["fsd_share"]}%' if lifetime and lifetime["fsd_share"] is not None else "—", 'Share of logged miles driven on FSD'))
    h.append(stat(f'{recent["fsd_share"]}%' if recent and recent["fsd_share"] is not None else "—", 'FSD share, last 90 days'))
    h.append(stat(fmt_n(fsd_months[best_fsd_month][0]) if best_fsd_month else "—", f'Biggest FSD month, miles ({datetime.strptime(best_fsd_month, "%Y-%m").strftime("%B %Y")})' if best_fsd_month else 'Biggest FSD month'))
    h.append('</div><div class="stats" role="list">')
    h.append(stat(esc(cfg.get("fsd_version") or "—"), 'FSD (Supervised) version', word=True))
    h.append(stat(esc(cur.get("software") or "—"), 'Tesla software', word=True))
    h.append(stat(fmt_n(lifetime["fsd_base_miles"]) if lifetime else "—", 'Miles where the truck logged FSD use'))
    h.append(stat(f'{round(100 * fsd_months[fsd_m[-1]][0] / fsd_months[fsd_m[-1]][1])}%' if fsd_m else "—", f'FSD share in {datetime.strptime(fsd_m[-1], "%Y-%m").strftime("%B")}' if fsd_m else 'Latest month'))
    h.append('</div>')
    h.append('<div class="grid2 charts">')
    h.append(f'<figure class="card"><figcaption><p class="tag">FSD share</p><h3>Percent of miles on FSD, by month</h3></figcaption>{both(svg_bars, fsd_bars, "Percent of miles driven on FSD by month", "%")}</figure>')
    h.append(f'<figure class="card"><figcaption><p class="tag">FSD miles</p><h3>Miles on FSD, by month</h3></figcaption>{both(svg_bars, [(l, round(fsd_months[m][0]), tip) for (l, _, tip), m in zip(fsd_bars, fsd_m)], "Miles driven on FSD by month", " mi")}</figure>')
    h.append('</div>')
    h.append(f'<p class="mnote">FSD distance comes from the truck\'s own trip log; the charts cover the months with a continuous record. Through {mdy(date.fromisoformat(fsd_last)) if fsd_last else "—"}.</p>')
    h.append('</section>')

    # --- compact strip for other pages (between tars2-mini markers)
    mini = []
    mini.append('<section class="sec tars2-mini" id="live-stats" aria-labelledby="live-h"><div class="sec-head"><div><p class="label">Live from the truck</p><h2 id="live-h">Every mile, <em>on the record.</em></h2></div><a class="more" href="/cybertruck/stats/">The full dashboard →</a></div>')
    mini.append('<div class="stats" role="list">')
    mini.append(stat(fmt_n(life_miles), 'Cybertruck miles, lifetime'))
    mini.append(stat(fmt_n(sc_kwh + sc_before), f'kWh Supercharged over {len(sc)} sessions'))
    mini.append(stat(f'{len(sites)}', f'Supercharger sites in {len(regions)} states and provinces'))
    mini.append(stat(fmt_n(this_week["miles"]), f'Miles this week at {fmt_n(this_week["wh_per_mile"])} Wh/mi'))
    mini.append('</div>')
    mini.append(MAP)
    mini.append(f'<p class="mnote">Updated {asof.strftime("%b %-d, %Y")} straight from the truck through <a href="https://www.autonimator.com" rel="noopener">Autonimator</a>. <a href="/cybertruck/stats/">Weekly numbers, charts, and the Supercharger log →</a></p>')
    mini.append('</section>')
    mini_html = "\n".join(mini)
    for rel in MINI_PAGES:
        mp = os.path.join(ROOT, rel)
        if not os.path.exists(mp):
            continue
        mpage = open(mp, encoding="utf-8").read()
        if MSTART not in mpage or MEND not in mpage:
            continue
        a, b = mpage.split(MSTART, 1)
        _, c = b.split(MEND, 1)
        mnew = a + MSTART + "\n" + mini_html + "\n" + MEND + c
        if mnew != mpage:
            open(mp, "w", encoding="utf-8").write(mnew)
            print("updated strip in", rel)

    html = "\n".join(h)
    page = open(PAGE, encoding="utf-8").read()
    pre, rest = page.split(START, 1)
    _, post = rest.split(END, 1)
    new = pre + START + "\n" + html + "\n" + END + post

    desc = (f"Cybertruck life, by the numbers: {fmt_n(this_week['miles'])} miles this week at {fmt_n(this_week['wh_per_mile'])} Wh/mi, "
            f"{fmt_n(sc_kwh + sc_before)} kWh of free Supercharging across {len(sites)} sites. Updated weekly from the truck's own data via Autonimator.")
    for pat in (r'(<meta name="description" content=")[^"]*(")', r'(<meta property="og:description" content=")[^"]*(")', r'(<meta name="twitter:description" content=")[^"]*(")'):
        new = re.sub(pat, lambda m: m.group(1) + desc.replace('"', "&quot;") + m.group(2), new, count=1)
    new = re.sub(r'("description":")[^"]*(")', lambda m: m.group(1) + desc.replace('"', '\\"') + m.group(2), new, count=1)
    new = re.sub(r'("dateModified":")[^"]*(")', lambda m: m.group(1) + asof.date().isoformat() + m.group(2), new, count=1)
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(new)

    sm = os.path.join(ROOT, "sitemap.xml")
    s = open(sm, encoding="utf-8").read()
    s2 = re.sub(r'(<loc>https://troymeekhof.com/cybertruck/stats/</loc><lastmod>)[^<]*(</lastmod>)', lambda m: m.group(1) + asof.date().isoformat() + m.group(2), s, count=1)
    if s2 != s:
        open(sm, "w", encoding="utf-8").write(s2)
    print("rendered", PAGE)
    print(f"summary: week {week_label}: {fmt_n(this_week['miles'])} mi, {fmt_n(this_week['wh_per_mile'])} Wh/mi, {this_week['drives']} drives; lifetime SC {fmt_n(sc_kwh + sc_before)} kWh / {len(sc)} sessions / {len(sites)} sites")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--status"); i.add_argument("--drives"); i.add_argument("--charges"); i.add_argument("--invoices")
    i.add_argument("--include-today", action="store_true", help="count today's drives (use on the nightly run)")
    i.set_defaults(fn=ingest)
    hh = sub.add_parser("import-history", help="fold an earlier drive/charge CSV export into lifetime totals")
    hh.add_argument("--drives"); hh.add_argument("--charges")
    hh.add_argument("--target", choices=["history", "current"], default="history", help="'current' = the complete export of the truck the nightly feed tracks")
    hh.set_defaults(fn=import_history)
    r = sub.add_parser("render")
    r.set_defaults(fn=render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
