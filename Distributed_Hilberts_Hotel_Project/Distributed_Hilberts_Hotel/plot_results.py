"""Create benchmark graphs as SVG using only Python standard library."""
import csv
import os
import statistics


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def median(values):
    return statistics.median(values) if values else 0.0


def xml_text(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def make_svg(path, title, x_label, y_label, series, width=1000, height=620,
             right_label=None):
    left, right, top, bottom = 95, 80 if right_label else 35, 85, 95
    plot_w, plot_h = width - left - right, height - top - bottom
    all_x = [x for item in series for x, _ in item["values"]]
    if not all_x:
        all_x = [0, 1]
    x_min, x_max = min(all_x), max(all_x)
    if x_min == x_max:
        x_max = x_min + 1
    left_series = [s for s in series if s.get("axis", "left") == "left"]
    right_series = [s for s in series if s.get("axis") == "right"]

    def scale_y(values):
        vals = [v for _, v in values] or [0, 1]
        lo, hi = min(0, min(vals)), max(vals)
        if hi == lo:
            hi = lo + 1
        pad = (hi - lo) * 0.08
        return lo - pad, hi + pad

    l_min, l_max = scale_y([p for s in left_series for p in s["values"]])
    r_min, r_max = scale_y([p for s in right_series for p in s["values"]]) if right_series else (0, 1)

    def x_pos(x):
        return left + (x - x_min) / (x_max - x_min) * plot_w

    def y_pos(y, axis):
        lo, hi = (r_min, r_max) if axis == "right" else (l_min, l_max)
        return top + plot_h - (y - lo) / (hi - lo) * plot_h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{width/2}" y="38" text-anchor="middle" font-size="23" font-family="Arial">{xml_text(title)}</text>']
    for i in range(6):
        y = top + plot_h * i / 5
        val = l_max - (l_max - l_min) * i / 5
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#dddddd"/>')
        out.append(f'<text x="{left-12}" y="{y+5:.1f}" text-anchor="end" font-size="12" font-family="Arial">{val:.3g}</text>')
        if right_series:
            rval = r_max - (r_max-r_min)*i/5
            out.append(f'<text x="{left+plot_w+12}" y="{y+5:.1f}" font-size="12" font-family="Arial">{rval:.3g}</text>')
    out.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="black"/>')
    out.append(f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="black"/>')
    for x in sorted(set(all_x)):
        xp = x_pos(x)
        out.append(f'<line x1="{xp:.1f}" y1="{top+plot_h}" x2="{xp:.1f}" y2="{top+plot_h+5}" stroke="black"/>')
        out.append(f'<text x="{xp:.1f}" y="{top+plot_h+24}" text-anchor="middle" font-size="12" font-family="Arial">{xml_text(x)}</text>')
    palette = ["#2563eb", "#dc2626", "#059669", "#7c3aed", "#d97706", "#0891b2"]
    legend_y = top + plot_h + 58
    for idx, item in enumerate(series):
        color = palette[idx % len(palette)]
        axis = item.get("axis", "left")
        pts = " ".join(f'{x_pos(x):.1f},{y_pos(y, axis):.1f}' for x, y in item["values"])
        if pts:
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>')
            for x, y in item["values"]:
                out.append(f'<circle cx="{x_pos(x):.1f}" cy="{y_pos(y, axis):.1f}" r="4" fill="{color}"/>')
        lx = left + (idx % 2) * (plot_w / 2)
        ly = legend_y + (idx // 2) * 20
        out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+25}" y2="{ly}" stroke="{color}" stroke-width="3"/>')
        out.append(f'<text x="{lx+32}" y="{ly+4}" font-size="12" font-family="Arial">{xml_text(item["label"])}</text>')
    out.append(f'<text x="{left+plot_w/2}" y="{height-12}" text-anchor="middle" font-size="15" font-family="Arial">{xml_text(x_label)}</text>')
    out.append(f'<text x="22" y="{top+plot_h/2}" text-anchor="middle" transform="rotate(-90 22 {top+plot_h/2})" font-size="15" font-family="Arial">{xml_text(y_label)}</text>')
    if right_label:
        out.append(f'<text x="{width-18}" y="{top+plot_h/2}" text-anchor="middle" transform="rotate(90 {width-18} {top+plot_h/2})" font-size="15" font-family="Arial">{xml_text(right_label)}</text>')
    out.append('</svg>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def plot_results(input_dir="output", output_dir="output"):
    os.makedirs(output_dir, exist_ok=True)
    paths = [os.path.join(input_dir, name) for name in
             ("experiment_timing.csv", "experiment_migrations.csv", "experiment_memory.csv")]
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"ไม่พบ {path}; กรุณารัน benchmark.py ก่อน")
    timing, migrations, memory = [read_csv(p) for p in paths]

    groups = {}
    for row in timing:
        if row["experiment"] == "A_size":
            groups.setdefault(int(row["K"]), []).append(float(row["assign_seconds"]))
    make_svg(os.path.join(output_dir, "graph_A_time_vs_K.svg"),
             "A. Assignment time vs K (N=10, V=32)", "Number of guests K",
             "Assignment time (seconds)", [{"label": "Median assignment time",
             "values": [(k, median(groups[k])) for k in sorted(groups)]}])

    styles = [("consistent_hashing", "add", "Consistent hashing - add"),
              ("hash_mod_N", "add", "hash mod N - add"),
              ("consistent_hashing", "remove", "Consistent hashing - remove"),
              ("hash_mod_N", "remove", "hash mod N - remove")]
    series = []
    for method, operation, label in styles:
        subset = [r for r in migrations if r["method"] == method and r["operation"] == operation]
        by_n = {}
        for row in subset:
            by_n.setdefault(int(row["N_before"]), []).append(float(row["migration_rate"]))
        series.append({"label": label, "values": [(n, median(by_n[n])) for n in sorted(by_n)]})
    make_svg(os.path.join(output_dir, "graph_B_migration_vs_N.svg"),
             "B. Migration rate vs N", "Buildings before change (N)",
             "Migration rate (moved guests / K)", series)

    cv_by_v, mem_by_v = {}, {}
    for row in timing:
        if row["experiment"] == "C_virtual_nodes":
            cv_by_v.setdefault(int(row["V"]), []).append(float(row["cv"]) if row["cv"] else 0)
    for row in memory:
        if row["experiment"] == "C_virtual_nodes":
            mem_by_v.setdefault(int(row["V"]), []).append(float(row["peak_MiB"]))
    vs = sorted(cv_by_v)
    make_svg(os.path.join(output_dir, "graph_C_V_CV_memory.svg"),
             "C. Effect of V on load balance and memory", "Virtual nodes per building V",
             "Load coefficient of variation (CV)",
             [{"label": "CV", "values": [(v, median(cv_by_v[v])) for v in vs]},
              {"label": "Peak memory (MiB)", "axis": "right",
               "values": [(v, median(mem_by_v.get(v, [0]))) for v in vs]}],
             right_label="Peak tracked memory (MiB)")
    print("Created three SVG graphs in", output_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    plot_results(args.input, args.output)
