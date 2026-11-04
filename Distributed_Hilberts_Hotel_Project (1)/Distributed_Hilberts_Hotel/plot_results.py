"""Create the three required graphs from benchmark CSV outputs."""
import csv
import os
import statistics
import matplotlib.pyplot as plt


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def median(values):
    return statistics.median(values) if values else 0


def plot_results(input_dir="output", output_dir="output"):
    os.makedirs(output_dir, exist_ok=True)
    timing_path = os.path.join(input_dir, "experiment_timing.csv")
    migration_path = os.path.join(input_dir, "experiment_migrations.csv")
    memory_path = os.path.join(input_dir, "experiment_memory.csv")
    for p in [timing_path, migration_path, memory_path]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"ไม่พบ {p}; กรุณารัน benchmark.py ก่อน")

    timing = read_csv(timing_path)
    migrations = read_csv(migration_path)
    memory = read_csv(memory_path)

    # Graph A: assignment time versus K, median across salts.
    groups = {}
    for row in timing:
        if row["experiment"] == "A_size":
            groups.setdefault(int(row["K"]), []).append(float(row["assign_seconds"]))
    ks = sorted(groups)
    plt.figure()
    plt.plot(ks, [median(groups[k]) for k in ks], marker="o")
    plt.xlabel("Number of guests K")
    plt.ylabel("Assignment time (seconds)")
    plt.title("A. Assignment time vs K (N=10, V=32; median of salts 0,1,2)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "graph_A_time_vs_K.png"), dpi=160)
    plt.close()

    # Graph B: migration rate versus N for both methods and operations.
    plt.figure()
    styles = [
        ("consistent_hashing", "add", "Consistent hashing - add"),
        ("hash_mod_N", "add", "hash mod N - add"),
        ("consistent_hashing", "remove", "Consistent hashing - remove"),
        ("hash_mod_N", "remove", "hash mod N - remove"),
    ]
    for method, operation, label in styles:
        subset = [r for r in migrations if r["method"] == method and r["operation"] == operation]
        by_n = {}
        for r in subset:
            by_n.setdefault(int(r["N_before"]), []).append(float(r["migration_rate"]))
        ns = sorted(by_n)
        plt.plot(ns, [median(by_n[n]) for n in ns], marker="o", label=label)
    plt.xlabel("Buildings before change (N)")
    plt.ylabel("Migration rate (moved guests / K)")
    plt.title("B. Migration rate vs N (median of salts 0,1,2)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "graph_B_migration_vs_N.png"), dpi=160)
    plt.close()

    # Graph C: V effects on CV and memory.
    c_rows = [r for r in timing if r["experiment"] == "C_virtual_nodes"]
    mem_rows = [r for r in memory if r["experiment"] == "C_virtual_nodes"]
    cv_by_v, mem_by_v = {}, {}
    for r in c_rows:
        cv_by_v.setdefault(int(r["V"]), []).append(float(r["cv"]) if r["cv"] else 0)
    for r in mem_rows:
        mem_by_v.setdefault(int(r["V"]), []).append(float(r["peak_MiB"]))
    vs = sorted(cv_by_v)
    fig, ax1 = plt.subplots()
    ax1.plot(vs, [median(cv_by_v[v]) for v in vs], marker="o", label="CV (unitless)")
    ax1.set_xlabel("Virtual nodes per building V")
    ax1.set_ylabel("Load coefficient of variation (CV)")
    ax1.grid(True)
    ax2 = ax1.twinx()
    ax2.plot(vs, [median(mem_by_v.get(v, [0])) for v in vs], marker="s", label="Peak memory")
    ax2.set_ylabel("Peak tracked memory (MiB)")
    plt.title("C. Effect of V on load balance and memory (N=10)")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "graph_C_V_CV_memory.png"), dpi=160)
    plt.close(fig)
    print("Created graph_A_time_vs_K.png, graph_B_migration_vs_N.png, graph_C_V_CV_memory.png")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    plot_results(args.input, args.output)
