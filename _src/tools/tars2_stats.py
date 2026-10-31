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
        "config": {"odometer_baseline_miles": None, "odometer_baseline_date": None},
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
            d["supercharging"]["sessions"][sid] = {
                "date": local_day(inv["started_at"]).isoformat(),
                "site": inv.get("site"),
                "kwh": round(inv.get("kwh_billed") or 0, 2),
                "currency": inv.get("currency"),
            }

    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(DATA, d)
    print("data.json updated:", len(d["days"]), "days,", len(d["supercharging"]["sessions"]), "Supercharger sessions")


# ---------------------------------------------------------------- summaries
def week_bounds(day):
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def summarize(days, start, end):
    out = {"miles": 0, "drives": 0, "kwh": 0, "measured_miles": 0, "longest": 0, "temp_sum": 0, "temp_n": 0, "minutes": 0, "days_driven": 0}
    cur = start
    while cur <= end:
        r = days.get(cur.isoformat())
        if r:
            out["miles"] += r["miles"]; out["drives"] += r["drives"]; out["kwh"] += r["kwh"]
            out["measured_miles"] += r["measured_miles"]; out["minutes"] += r["minutes"]
            out["longest"] = max(out["longest"], r["longest"])
            out["temp_sum"] += r["temp_c_sum"]; out["temp_n"] += r["temp_n"]
            out["days_driven"] += 1
        cur += timedelta(days=1)
    out["wh_per_mile"] = round(out["kwh"] * 1000 / out["measured_miles"]) if out["measured_miles"] else None
    out["avg_temp_f"] = round((out["temp_sum"] / out["temp_n"]) * 9 / 5 + 32) if out["temp_n"] else None
    out["start"], out["end"] = start, end
    return out


def fmt_n(n, dec=0):
    if n is None:
        return "—"
    return f"{n:,.{dec}f}"


def region(site):
    m = re.search(r",\s*([A-Z]{2})\b", site or "")
    return m.group(1) if m else None


def mdy(dt):
    return dt.strftime("%b %-d, %Y")


def md(dt):
    return dt.strftime("%b %-d")


# ---------------------------------------------------------------- render
def render(args):
    d = load_json(DATA)
    days = d["days"]
    today = datetime.now(TZ).date()
    asof = datetime.fromisoformat(d["updated"]).astimezone(TZ) if d.get("updated") else datetime.now(TZ)

    # The "week" shown is the most recently completed Mon–Sun week once the
    # Sunday run has happened; before that it is week-to-date.
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

    sc = list(d["supercharging"]["sessions"].values())
    sc_kwh = sum(s["kwh"] for s in sc)
    sites = sorted({s["site"] for s in sc if s.get("site")})
    regions = sorted({r for r in (region(s) for s in sites) if r})
    first_sc = min((s["date"] for s in sc), default=None)
    sc_week = [s for s in sc if ws.isoformat() <= s["date"] <= we.isoformat()]
    biggest = max(sc, key=lambda s: s["kwh"], default=None)
    by_month = {}
    for s in sc:
        by_month.setdefault(s["date"][:7], [0, 0])
        by_month[s["date"][:7]][0] += 1
        by_month[s["date"][:7]][1] += s["kwh"]

    home_week = 0
    for k, sess in d["home_charging"]["kwh_by_day"].items():
        if ws.isoformat() <= k <= we.isoformat():
            home_week += sum(sess.values())

    cur = d.get("current") or {}

    def stat(val, label, word=False):
        cls = ' class="word"' if word else ""
        return f'<div class="stat" role="listitem"><b{cls}>{val}</b><span>{label}</span></div>'

    def delta(a, b, unit=""):
        if not b or a is None:
            return ""
        ch = (a - b) / b * 100
        arrow = "▲" if ch > 0 else "▼"
        return f' <small class="delta">{arrow} {abs(ch):.0f}% vs last week</small>'

    h = []
    h.append(f'<p class="label">Updated {asof.strftime("%A, %b %-d, %Y at %-I:%M %p")} ET · pulled from the truck, not typed by hand</p>')

    # --- this week
    h.append(f'<section class="sec" id="week" aria-labelledby="week-h"><div class="sec-head"><div><p class="label">This week</p><h2 id="week-h">{week_label}, <em>in the truck.</em></h2></div></div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(f'{fmt_n(this_week["miles"])}', f'Miles driven{delta(this_week["miles"], last_week["miles"])}'))
    h.append(stat(f'{fmt_n(this_week["wh_per_mile"])}', f'Wh per mile, measured{delta(this_week["wh_per_mile"], last_week["wh_per_mile"])}'))
    h.append(stat(f'{fmt_n(this_week["drives"])}', f'Drives over {this_week["days_driven"]} day{"s" if this_week["days_driven"] != 1 else ""}'))
    h.append(stat(f'{fmt_n(this_week["longest"])}', 'Longest single drive, miles'))
    h.append('</div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(f'{fmt_n(this_week["kwh"])}', 'kWh used on measured drives'))
    h.append(stat(f'{fmt_n(sum(s["kwh"] for s in sc_week))}', f'kWh Supercharged across {len(sc_week)} stop{"s" if len(sc_week) != 1 else ""}'))
    h.append(stat(f'{fmt_n(home_week)}', 'kWh added at home'))
    h.append(stat(f'{fmt_n(this_week["avg_temp_f"])}°F' if this_week["avg_temp_f"] is not None else "—", 'Average outside temp while driving'))
    h.append('</div>')
    h.append(f'<p class="mnote">Last week ({md(ws - timedelta(days=7))}–{md(ws - timedelta(days=1))}): {fmt_n(last_week["miles"])} miles, {fmt_n(last_week["wh_per_mile"])} Wh/mi, {last_week["drives"]} drives.</p>' if last_week["drives"] else '<p class="mnote">Last week: not enough tracked days yet.</p>')
    h.append('</section>')

    # --- lifetime
    h.append('<section class="sec" id="lifetime" aria-labelledby="life-h"><div class="sec-head"><div><p class="label">Lifetime</p><h2 id="life-h">Free Supercharging, <em>by the kilowatt-hour.</em></h2></div></div>')
    h.append('<div class="stats" role="list">')
    h.append(stat(f'{fmt_n(sc_kwh)}', f'kWh of free Supercharging logged since {mdy(date.fromisoformat(first_sc)) if first_sc else "—"}'))
    h.append(stat(f'{len(sc)}', 'Supercharger sessions'))
    h.append(stat(f'{len(sites)}', f'Supercharger sites in {len(regions)} states and provinces'))
    h.append(stat(f'{fmt_n(biggest["kwh"]) if biggest else "—"}', f'Biggest single session, kWh ({biggest["site"]})' if biggest else 'Biggest single session'))
    h.append('</div>')
    if tracked:
        h.append('<div class="stats" role="list">')
        h.append(stat(f'{fmt_n(odo) if odo else fmt_n(tracked["miles"])}', 'Odometer, miles' if odo else f'Miles tracked here since {mdy(date.fromisoformat(d["tracking_since"]))}'))
        h.append(stat(f'{fmt_n(tracked["drives"])}', 'Drives tracked'))
        h.append(stat(f'{fmt_n(tracked["wh_per_mile"])}', 'Lifetime Wh per mile, measured drives'))
        h.append(stat(f'{fmt_n(tracked["minutes"] / 60, 1)}', 'Hours behind the wheel, tracked'))
        h.append('</div>')
    h.append('</section>')

    # --- right now
    if cur:
        h.append('<section class="sec" id="now" aria-labelledby="now-h"><div class="sec-head"><div><p class="label">Right now</p><h2 id="now-h">Where the truck <em>sits.</em></h2></div></div>')
        h.append('<div class="stats" role="list">')
        h.append(stat(f'{cur.get("battery_percent", "—")}%', 'Battery'))
        h.append(stat(f'{fmt_n(cur.get("range_miles"))}', 'Estimated range, miles'))
        h.append(stat(f'{cur.get("outside_temp_f", "—")}°F', 'Outside temperature'))
        h.append(stat(cur.get("software") or "—", 'Tesla software', word=True))
        h.append('</div></section>')

    # --- supercharging by month table
    h.append('<section class="sec" id="months" aria-labelledby="months-h"><div class="sec-head"><div><p class="label">By month</p><h2 id="months-h">Supercharger <em>stops.</em></h2></div></div>')
    h.append('<div class="tablewrap"><table><thead><tr><th>Month</th><th>Sessions</th><th>kWh</th><th>Sites</th></tr></thead><tbody>')
    for m in sorted(by_month, reverse=True):
        ms = sorted({s["site"] for s in sc if s["date"][:7] == m and s.get("site")})
        name = datetime.strptime(m, "%Y-%m").strftime("%B %Y")
        h.append(f'<tr><td>{name}</td><td>{by_month[m][0]}</td><td>{fmt_n(by_month[m][1])}</td><td>{len(ms)}</td></tr>')
    h.append('</tbody></table></div>')
    h.append(f'<p class="mnote">Sites so far: {", ".join(sites)}.</p>')
    h.append('</section>')

    html = "\n".join(h)
    page = open(PAGE, encoding="utf-8").read()
    pre, rest = page.split(START, 1)
    _, post = rest.split(END, 1)
    new = pre + START + "\n" + html + "\n" + END + post

    # keep the meta description honest
    desc = (f"TARS2, Troy's Cybertruck, by the numbers: {fmt_n(this_week['miles'])} miles this week at {fmt_n(this_week['wh_per_mile'])} Wh/mi, "
            f"{fmt_n(sc_kwh)} kWh of free Supercharging across {len(sites)} sites. Updated weekly from the truck's own data.")
    new = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + desc.replace('"', "&quot;") + m.group(2), new, count=1)
    new = re.sub(r'(<meta property="og:description" content=")[^"]*(")', lambda m: m.group(1) + desc.replace('"', "&quot;") + m.group(2), new, count=1)
    new = re.sub(r'(<meta name="twitter:description" content=")[^"]*(")', lambda m: m.group(1) + desc.replace('"', "&quot;") + m.group(2), new, count=1)
    new = re.sub(r'("description":")[^"]*(")', lambda m: m.group(1) + desc.replace('"', '\\"') + m.group(2), new, count=1)
    new = re.sub(r'("dateModified":")[^"]*(")', lambda m: m.group(1) + asof.date().isoformat() + m.group(2), new, count=1)
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(new)

    # sitemap lastmod for this page
    sm = os.path.join(ROOT, "sitemap.xml")
    s = open(sm, encoding="utf-8").read()
    s2 = re.sub(r'(<loc>https://troymeekhof.com/cybertruck/stats/</loc><lastmod>)[^<]*(</lastmod>)', lambda m: m.group(1) + asof.date().isoformat() + m.group(2), s, count=1)
    if s2 != s:
        open(sm, "w", encoding="utf-8").write(s2)
    print("rendered", PAGE)
    print(f"summary: week {week_label}: {fmt_n(this_week['miles'])} mi, {fmt_n(this_week['wh_per_mile'])} Wh/mi, {this_week['drives']} drives; lifetime SC {fmt_n(sc_kwh)} kWh / {len(sc)} sessions / {len(sites)} sites")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--status"); i.add_argument("--drives"); i.add_argument("--charges"); i.add_argument("--invoices")
    i.add_argument("--include-today", action="store_true", help="count today's drives (use on the nightly run)")
    i.set_defaults(fn=ingest)
    r = sub.add_parser("render")
    r.set_defaults(fn=render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
