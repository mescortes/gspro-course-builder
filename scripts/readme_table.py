"""Regenerate the per-hole table in README.md from output/holes.json (between the holes-table markers)."""
import sys, json, re
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

BEGIN, END = "<!-- holes-table -->", "<!-- /holes-table -->"


def fmt_tee(t):
    d = t["yards"] - t["scorecard_yards"]
    return f"{t['yards']:.0f} ({t['scorecard_yards']})" if abs(d) > 6 else f"{t['yards']:.0f}"


def table():
    H = json.load(open(C.OUTPUT / "holes.json"))["holes"]
    rows = ["| Hole | Nine | Par | SI | Championship | Middle | Forward | Green (yd deep × wide) | Elev. change | Hazards |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for h in H:
        tees = {t["key"]: t for t in h["tees"]}
        g = h["green"]
        hz = {}
        for z in h["hazards"]:
            hz[z["type"]] = hz.get(z["type"], 0) + 1
        hz_s = ", ".join(f"{n} {k}" for k, n in sorted(hz.items())) or "–"
        rows.append(f"| {h['hole']} | {h['nine']} {h['nine_hole']} | {h['par']} | {h['handicap']} | "
                    f"{fmt_tee(tees['championship'])} | {fmt_tee(tees['middle'])} | {fmt_tee(tees['forward'])} | "
                    f"{g['depth_yd']:.0f} × {g['width_yd']:.0f} | {round(h['elevation_change_m']) or 0:+d} m | {hz_s} |")
    tot = {k: sum(next(t for t in h["tees"] if t["key"] == k)["yards"] for h in H) for k in ("championship", "middle", "forward")}
    card = {k: sum(h["scorecard_yards"][k] for h in H) for k in tot}
    rows.append(f"| **Total** | | **{sum(h['par'] for h in H)}** | | **{tot['championship']:.0f}** ({card['championship']}) | "
                f"**{tot['middle']:.0f}** ({card['middle']}) | **{tot['forward']:.0f}** ({card['forward']}) | | | |")
    return "\n".join(rows)


def main():
    p = C.ROOT / "README.md"
    s = p.read_text()
    new = f"{BEGIN}\n{table()}\n{END}"
    s2 = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: new, s, flags=re.S)
    if s2 == s and BEGIN not in s:
        raise SystemExit("README.md has no holes-table markers")
    p.write_text(s2)
    print(table())


if __name__ == "__main__":
    main()
