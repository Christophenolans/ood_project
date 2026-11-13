#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_experiments.py - ชุดการทดลองหัวข้อ 7: Consistent Hashing เทียบกับ hash mod N

วางไฟล์นี้ไว้โฟลเดอร์เดียวกับ hotel.py แล้วรัน:

    python run_experiments.py                  # รันครบ A, B, C (K สูงสุด 100,000)
    python run_experiments.py --quick          # ทดสอบเร็ว ๆ ว่าสคริปต์ทำงานครบ
    python run_experiments.py --only B,C       # รันเฉพาะบางการทดลอง
    python run_experiments.py --ks 1000,10000  # เครื่องไม่ไหว: ลดขนาด K แล้วรายงานขอบเขต

การทดลอง (ตามหัวข้อ 7.1)
  A: เปลี่ยน K = 1,000 / 10,000 / 100,000   (N=10, V=32)
     -> เวลาจัดแขก, ค้นหา, เรียงลำดับ, หน่วยความจำ
  B: เปลี่ยน N = 5 / 10 / 20                (K=10,000, V=32)
     -> เพิ่ม 1 อาคาร / ลบ 1 อาคาร: จำนวนย้าย, อัตราย้าย, เวลา เทียบกับ hash mod N
  C: เปลี่ยน V = 1 / 8 / 32                 (N=10, K=10,000)
     -> จำนวนแขกต่ออาคาร, CV, หน่วยความจำ, การย้าย

วิธีวัด (ตามหัวข้อ 7.2)
  - แขกสร้างจาก 10 ช่องทาง กระจายจำนวนให้ใกล้เคียงกัน
  - ทุกคู่เปรียบเทียบใช้รหัสแขก รหัสอาคาร (B001, B002, ...) และสูตรแฮช SHA-256 เดียวกัน
  - 3 รอบ salt = 0, 1, 2 (salt เดียวกันทั้งสองวิธีในรอบเดียวกัน)
  - เวลา: time.perf_counter() ค้นหาเป็นชุด 1,000 ครั้งแล้วหารต่อครั้ง รายงานค่ามัธยฐาน 3 รอบ
  - หน่วยความจำ: tracemalloc (ส่วนที่เพิ่มจากจุดเริ่มต้นเดียวกัน) current/peak เป็น MiB
    วัดในรอบแยกจากรอบจับเวลา -> เป็นหน่วยความจำที่ Python ติดตาม ไม่ใช่ของทั้งโปรเซส
  - ความสมดุล: CV = std / mean (ถ้าไม่มีแขก สถิติเป็น 0 และไม่คำนวณ CV)
  - hash mod N: เก็บรายการรหัสอาคารตามลำดับที่เพิ่ม เลือกดัชนี H(guest) mod N
    เพิ่มอาคารต่อท้ายรายการ ลบแล้วรักษาลำดับที่เหลือ และเทียบการย้ายด้วยรหัสอาคารจริง

ผลลัพธ์ (โฟลเดอร์ --outdir, ค่าเริ่มต้น output/experiments)
  raw_A.csv, raw_B.csv, raw_C.csv      ข้อมูลดิบทุกรอบ
  summary_A.csv, summary_B.csv, ...    median / mean / min / max ของ 3 รอบ
  counts_C.csv                         จำนวนแขกต่ออาคาร
  fig_A_time_vs_K.png, fig_B_migration_vs_N.png, fig_C_virtual_nodes.png
  meta.json                            เครื่อง, เวอร์ชัน Python, พารามิเตอร์, salt
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import platform
import random
import statistics
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

from hotel import Guest, HotelSystem, Migration, ModNRouter

MIB = 1024 * 1024
CHANNELS = 10
SEARCH_BATCH = 1000
SEARCH_SEED = 20260101
METHODS = ("consistent", "modn")
METHOD_NAME = {"consistent": "Consistent hashing", "modn": "hash mod N"}
COLOR = {"consistent": "tab:blue", "modn": "tab:orange"}
NODE_PREFIX = "B"

pc = time.perf_counter


# ---------------------------------------------------------------------------
# baseline: hash mod N ที่มีโครงสร้างข้อมูลเหมือน HotelSystem (เทียบแฟร์)
# ---------------------------------------------------------------------------
class ModNSystem:
    def __init__(self, node_count: int, salt: str = "0", node_prefix: str = NODE_PREFIX):
        self.router = ModNRouter(salt)
        self.guests: dict[tuple[int, int], Guest] = {}
        self.guest_nodes: dict[tuple[int, int], str] = {}
        self.room_index: dict[tuple[str, int], tuple[int, int]] = {}
        for i in range(1, node_count + 1):
            self.router.add_node(f"{node_prefix}{i:03d}")

    @property
    def node_ids(self) -> list[str]:
        return list(self.router.node_ids)  # ลำดับตามที่เพิ่ม

    def add_guest_group(self, channel_id: int, s_start: int, count: int) -> list[Guest]:
        out = []
        for s in range(s_start, s_start + count):
            key = (channel_id, s)
            guest = Guest(channel_id, s)
            node = self.router.locate(guest)
            self.guests[key] = guest
            self.guest_nodes[key] = node
            self.room_index[(node, guest.room_no)] = key
            out.append(guest)
        return out

    def _guest_row(self, guest: Guest) -> dict:
        key = (guest.channel_id, guest.sequence_id)
        return {
            "channel_id": guest.channel_id,
            "sequence_id": guest.sequence_id,
            "node_id": self.guest_nodes[key],
            "room_no": guest.room_no,
        }

    def find_guest(self, channel_id: int, sequence_id: int):
        guest = self.guests.get((channel_id, sequence_id))
        return None if guest is None else self._guest_row(guest)

    def list_rooms(self) -> list[dict]:
        return sorted((self._guest_row(g) for g in self.guests.values()),
                      key=lambda r: (r["node_id"], r["room_no"]))

    def _reassign(self, before: dict) -> list[Migration]:
        migrations, new_nodes = [], {}
        for key, guest in self.guests.items():
            new = self.router.locate(guest)
            new_nodes[key] = new
            if before[key] != new:
                migrations.append(Migration(guest.channel_id, guest.sequence_id,
                                            before[key], new, guest.room_no))
        self.guest_nodes = new_nodes
        self.room_index = {(new_nodes[k], g.room_no): k for k, g in self.guests.items()}
        migrations.sort(key=lambda m: (m.channel_id, m.sequence_id))
        return migrations

    def add_node(self, node_id: str) -> list[Migration]:
        before = dict(self.guest_nodes)
        self.router.add_node(node_id)
        return self._reassign(before)

    def remove_node(self, node_id: str) -> list[Migration]:
        before = dict(self.guest_nodes)
        self.router.remove_node(node_id)  # list.remove รักษาลำดับที่เหลือ
        return self._reassign(before)


# ---------------------------------------------------------------------------
# ตัวช่วย
# ---------------------------------------------------------------------------
def make_system(method: str, n: int, v: int, salt: str):
    if method == "consistent":
        return HotelSystem(n, v, salt=str(salt), node_prefix=NODE_PREFIX)
    return ModNSystem(n, salt=str(salt))


def route_fn(system):
    return system.ring.locate if hasattr(system, "ring") else system.router.locate


def channel_counts(k: int, channels: int = CHANNELS) -> list[int]:
    base, extra = divmod(k, channels)
    return [base + (1 if i < extra else 0) for i in range(channels)]


def populate(system, k: int) -> None:
    for c, cnt in enumerate(channel_counts(k), start=1):
        if cnt:
            system.add_guest_group(c, 1, cnt)


def counts_per_node(system) -> dict[str, int]:
    counts = {n: 0 for n in system.node_ids}
    for node in system.guest_nodes.values():
        counts[node] += 1
    return counts


def balance_stats(counts: dict[str, int]) -> dict:
    values = list(counts.values())
    if not values or sum(values) == 0:  # ไม่มีแขก: สถิติเป็น 0 และไม่คำนวณ CV
        return {"min": 0, "max": 0, "mean": 0.0, "std": 0.0, "cv": None}
    mean = sum(values) / len(values)
    std = math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))
    return {"min": min(values), "max": max(values), "mean": mean, "std": std,
            "cv": std / mean}


def verify_same_hash(salt: str) -> None:
    """ยืนยันว่าสองวิธีใช้ค่าแฮชและรหัสอาคารชุดเดียวกัน"""
    h = HotelSystem(3, 1, salt=str(salt), node_prefix=NODE_PREFIX)
    m = ModNSystem(3, salt=str(salt))
    for c in (1, 5, 10):
        for s in (1, 2, 999):
            g = Guest(c, s)
            assert h.ring._hash64(g.key) == m.router._hash(g), "hash ไม่ตรงกัน"
    assert h.node_ids == sorted(m.node_ids), "รหัสอาคารไม่ตรงกัน"


# ---------------------------------------------------------------------------
# รอบวัดเวลา (ไม่เปิด tracemalloc)
# ---------------------------------------------------------------------------
def timing_round(method: str, n: int, v: int, k: int, salt: str) -> dict:
    assert not tracemalloc.is_tracing()
    gc.collect()
    t0 = pc()
    system = make_system(method, n, v, salt)
    build_s = pc() - t0

    gc.collect()
    t0 = pc()
    populate(system, k)
    assign_s = pc() - t0
    assert len(system.guests) == k

    keys = list(system.guests.keys())
    sample = random.Random(SEARCH_SEED).sample(keys, min(SEARCH_BATCH, len(keys))) if keys else []
    find = system.find_guest
    gc.collect()
    t0 = pc()
    for c, s in sample:
        find(c, s)
    search_us = (pc() - t0) / len(sample) * 1e6 if sample else None

    locate = route_fn(system)
    guest_objs = [system.guests[key] for key in sample]
    gc.collect()
    t0 = pc()
    for g in guest_objs:
        locate(g)
    route_us = (pc() - t0) / len(guest_objs) * 1e6 if guest_objs else None

    gc.collect()
    t0 = pc()
    rows = system.list_rooms()
    sort_s = pc() - t0
    assert len(rows) == len(system.guests)

    st = balance_stats(counts_per_node(system))
    return {"build_s": build_s, "assign_s": assign_s, "search_us": search_us,
            "route_us": route_us, "sort_s": sort_s, "cv": st["cv"]}


def migration_round(method: str, n: int, v: int, k: int, salt: str, op: str,
                    remove_target: str) -> dict:
    assert not tracemalloc.is_tracing()
    system = make_system(method, n, v, salt)
    populate(system, k)
    before = dict(system.guest_nodes)
    guest_count = len(before)
    if op == "add":
        target = f"{NODE_PREFIX}{n + 1:03d}"
        action = system.add_node
        ideal = 1 / (n + 1)
    else:
        target = remove_target
        action = system.remove_node
        ideal = 1 / n
    gc.collect()
    t0 = pc()
    migrations = action(target)
    dt = pc() - t0
    # ตรวจซ้ำด้วยรหัสอาคารจริง (ไม่ใช่ดัชนี)
    moved_check = sum(1 for key, old in before.items() if old != system.guest_nodes[key])
    assert moved_check == len(migrations), "จำนวนย้ายไม่ตรงกับการเทียบรหัสอาคาร"
    return {"moved": len(migrations),
            "rate": (len(migrations) / guest_count) if guest_count else None,
            "ideal_rate": ideal, "time_ms": dt * 1000}


# ---------------------------------------------------------------------------
# รอบวัดหน่วยความจำ (แยกจากรอบจับเวลา)
# ---------------------------------------------------------------------------
def memory_round(method: str, n: int, v: int, k: int, salt: str) -> dict:
    gc.collect()
    tracemalloc.start()
    try:
        base, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        system = make_system(method, n, v, salt)
        populate(system, k)
        cur, peak = tracemalloc.get_traced_memory()
        assert len(system.guests) == k
    finally:
        tracemalloc.stop()
    del system
    return {"mem_current_mib": (cur - base) / MIB, "mem_peak_mib": (peak - base) / MIB}


# ---------------------------------------------------------------------------
# สรุปผล / เขียนไฟล์
# ---------------------------------------------------------------------------
def summarize(rows: list[dict], group_keys: list[str], metrics: list[str]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r.get(k) for k in group_keys), []).append(r)
    out = []
    for key, rs in groups.items():
        d = dict(zip(group_keys, key))
        d["rounds"] = len(rs)
        for m in metrics:
            vals = [r[m] for r in rs if r.get(m) is not None]
            if vals:
                d[f"{m}_median"] = statistics.median(vals)
                d[f"{m}_mean"] = statistics.fmean(vals)
                d[f"{m}_min"] = min(vals)
                d[f"{m}_max"] = max(vals)
            else:
                for suffix in ("median", "mean", "min", "max"):
                    d[f"{m}_{suffix}"] = None
        out.append(d)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for r in rows:
        for key in r:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.4g}"
    return str(x)


def print_summary(title: str, summ: list[dict], keys: list[str], metrics: list[str]) -> None:
    print(f"\n=== {title} (median ของแต่ละรอบ) ===")
    header = keys + metrics
    print(" | ".join(f"{h:>14}" for h in header))
    for r in summ:
        cells = [fmt(r.get(k)) for k in keys] + [fmt(r.get(f"{m}_median")) for m in metrics]
        print(" | ".join(f"{c:>14}" for c in cells))


# ---------------------------------------------------------------------------
# การทดลอง
# ---------------------------------------------------------------------------
def run_A(args) -> tuple[list[dict], list[dict]]:
    print("\n##### การทดลอง A: เปลี่ยนขนาดข้อมูล K #####", flush=True)
    rows: dict[tuple, dict] = {}
    for k in args.ks:                      # รอบวัดเวลา
        for salt in args.salts:
            for method in METHODS:
                print(f"  [time] K={k:,} salt={salt} {METHOD_NAME[method]}", flush=True)
                r = {"experiment": "A", "method": method, "K": k, "N": args.n_fixed,
                     "V": args.v_fixed if method == "consistent" else None, "salt": salt}
                r.update(timing_round(method, args.n_fixed, args.v_fixed, k, salt))
                rows[(method, k, salt)] = r
    for k in args.ks:                      # รอบวัดหน่วยความจำ (แยก)
        for salt in args.salts:
            for method in METHODS:
                print(f"  [mem ] K={k:,} salt={salt} {METHOD_NAME[method]}", flush=True)
                rows[(method, k, salt)].update(
                    memory_round(method, args.n_fixed, args.v_fixed, k, salt))
    raw = list(rows.values())
    metrics = ["build_s", "assign_s", "search_us", "route_us", "sort_s", "cv",
               "mem_current_mib", "mem_peak_mib"]
    return raw, summarize(raw, ["method", "K"], metrics)


def run_B(args) -> tuple[list[dict], list[dict]]:
    print("\n##### การทดลอง B: เปลี่ยนจำนวนอาคาร N #####", flush=True)
    raw = []
    for n in args.ns:
        for salt in args.salts:
            for method in METHODS:
                for op in ("add", "remove"):
                    print(f"  N={n} salt={salt} {METHOD_NAME[method]} {op}", flush=True)
                    r = {"experiment": "B", "method": method, "N": n, "K": args.k_fixed,
                         "V": args.v_fixed if method == "consistent" else None,
                         "op": op, "salt": salt}
                    r.update(migration_round(method, n, args.v_fixed, args.k_fixed, salt,
                                             op, args.remove_target))
                    raw.append(r)
    return raw, summarize(raw, ["method", "op", "N"], ["moved", "rate", "ideal_rate", "time_ms"])


def run_C(args) -> tuple[list[dict], list[dict], list[dict]]:
    print("\n##### การทดลอง C: เปลี่ยนจำนวนจุดเสมือน V #####", flush=True)
    configs = [("consistent", v) for v in args.vs] + [("modn", None)]  # mod N ไม่มี V: ใช้เป็นเส้นอ้างอิง
    rows, counts_rows = {}, []
    for method, v in configs:
        for salt in args.salts:
            print(f"  [time] V={v} salt={salt} {METHOD_NAME[method]}", flush=True)
            system = make_system(method, args.n_fixed, v or 1, salt)
            populate(system, args.k_fixed)
            counts = counts_per_node(system)
            st = balance_stats(counts)
            r = {"experiment": "C", "method": method, "V": v, "N": args.n_fixed,
                 "K": args.k_fixed, "salt": salt,
                 "min": st["min"], "max": st["max"], "mean": st["mean"],
                 "std": st["std"], "cv": st["cv"]}
            for node, cnt in counts.items():
                counts_rows.append({"method": method, "V": v, "salt": salt,
                                    "node_id": node, "guests": cnt})
            for op in ("add", "remove"):
                m = migration_round(method, args.n_fixed, v or 1, args.k_fixed, salt,
                                    op, args.remove_target)
                r[f"{op}_moved"], r[f"{op}_rate"], r[f"{op}_time_ms"] = (
                    m["moved"], m["rate"], m["time_ms"])
            rows[(method, v, salt)] = r
    for method, v in configs:
        for salt in args.salts:
            print(f"  [mem ] V={v} salt={salt} {METHOD_NAME[method]}", flush=True)
            rows[(method, v, salt)].update(
                memory_round(method, args.n_fixed, v or 1, args.k_fixed, salt))
    raw = list(rows.values())
    metrics = ["min", "max", "mean", "std", "cv", "add_moved", "add_rate", "add_time_ms",
               "remove_moved", "remove_rate", "remove_time_ms",
               "mem_current_mib", "mem_peak_mib"]
    return raw, summarize(raw, ["method", "V"], metrics), counts_rows


# ---------------------------------------------------------------------------
# กราฟ
# ---------------------------------------------------------------------------
THAI_FONTS = ["Tahoma", "Leelawadee UI", "Noto Sans Thai", "TH Sarabun New", "TH SarabunPSK",
              "Loma", "Garuda", "Norasi", "Thonburi", "Sukhumvit Set"]
USE_THAI = False


def L(th: str, en: str) -> str:
    return th if USE_THAI else en


def setup_matplotlib(force_en: bool):
    global USE_THAI
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    if not force_en:
        available = {f.name for f in font_manager.fontManager.ttflist}
        for name in THAI_FONTS:
            if name in available:
                plt.rcParams["font.family"] = name
                USE_THAI = True
                break
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def sel(rows: list[dict], **cond) -> list[dict]:
    return [r for r in rows if all(r.get(k) == v for k, v in cond.items())]


def errbar(ax, rows, x_key, metric, label, **kw):
    pts = [r for r in rows if r.get(f"{metric}_mean") is not None]
    if not pts:
        return
    xs = [r[x_key] for r in pts]
    ys = [r[f"{metric}_mean"] for r in pts]
    lo = [r[f"{metric}_mean"] - r[f"{metric}_min"] for r in pts]
    hi = [r[f"{metric}_max"] - r[f"{metric}_mean"] for r in pts]
    ax.errorbar(xs, ys, yerr=[lo, hi], label=label, capsize=3, marker="o", **kw)


def plot_A(summ, args, outdir: Path, plt) -> None:
    from matplotlib.ticker import NullLocator
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    panels = [
        (axes[0][0], [("assign_s", "-", "")], L("เวลาจัดแขก", "Guest assignment time"), "s"),
        (axes[0][1], [("search_us", "-", "")], L("เวลาค้นหาต่อครั้ง (ชุด 1,000 ครั้ง)",
                                                  "Search time per query (batch of 1,000)"), "µs / query"),
        (axes[1][0], [("sort_s", "-", "")], L("เวลาเรียงลำดับ", "Sort time"), "s"),
        (axes[1][1], [("mem_current_mib", "-", " current"), ("mem_peak_mib", "--", " peak")],
         L("หน่วยความจำที่ Python ติดตาม (tracemalloc)", "Python-tracked memory (tracemalloc)"), "MiB"),
    ]
    for ax, specs, title, ylabel in panels:
        for method in METHODS:
            ms = sel(summ, method=method)
            for metric, ls, suffix in specs:
                errbar(ax, ms, "K", metric, METHOD_NAME[method] + suffix,
                       color=COLOR[method], linestyle=ls)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks(args.ks)
        ax.set_xticklabels([f"{k:,}" for k in args.ks])
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xlabel(L("จำนวนแขก K (คน)", "Number of guests K"))
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(L(f"การทดลอง A: เวลาเทียบ K  (N={args.n_fixed}, V={args.v_fixed}, "
                   f"{len(args.salts)} รอบ: จุด=ค่าเฉลี่ย, แท่ง=ต่ำสุด–สูงสุด)",
                   f"Experiment A: time vs K  (N={args.n_fixed}, V={args.v_fixed}, "
                   f"{len(args.salts)} rounds: dot=mean, bar=min–max)"))
    fig.tight_layout()
    fig.savefig(outdir / "fig_A_time_vs_K.png", dpi=150)
    plt.close(fig)


def plot_B(summ, args, outdir: Path, plt) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    specs = [(axes[0], "add", lambda n: 1 / (n + 1), L("เพิ่ม 1 อาคาร", "Add 1 building"), "1/(N+1)"),
             (axes[1], "remove", lambda n: 1 / n, L("ลบ 1 อาคาร", "Remove 1 building"), "1/N")]
    for ax, op, ideal, title, ideal_label in specs:
        for method in METHODS:
            errbar(ax, sel(summ, method=method, op=op), "N", "rate",
                   METHOD_NAME[method], color=COLOR[method])
        ax.plot(args.ns, [ideal(n) for n in args.ns], ":", color="gray",
                label=L(f"ค่าอุดมคติ {ideal_label}", f"ideal {ideal_label}"))
        ax.set_xticks(args.ns)
        ax.set_ylim(bottom=0)
        ax.set_xlabel(L("จำนวนอาคารเริ่มต้น N (หลัง)", "Initial number of buildings N"))
        ax.set_ylabel(L("อัตราย้าย (จำนวนย้าย / K)", "Migration rate (moved / K)"))
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(L(f"การทดลอง B: อัตราการย้ายเทียบ N  (K={args.k_fixed:,}, V={args.v_fixed}, "
                   f"{len(args.salts)} รอบ: จุด=ค่าเฉลี่ย, แท่ง=ต่ำสุด–สูงสุด)",
                   f"Experiment B: migration rate vs N  (K={args.k_fixed:,}, V={args.v_fixed}, "
                   f"{len(args.salts)} rounds: dot=mean, bar=min–max)"))
    fig.tight_layout()
    fig.savefig(outdir / "fig_B_migration_vs_N.png", dpi=150)
    plt.close(fig)


def plot_C(summ, args, outdir: Path, plt) -> None:
    from matplotlib.ticker import NullLocator
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    ch = sel(summ, method="consistent")
    ref = sel(summ, method="modn")
    ref = ref[0] if ref else None

    def refline(ax, metric, label):
        if ref and ref.get(f"{metric}_mean") is not None:
            ax.axhline(ref[f"{metric}_mean"], color=COLOR["modn"], linestyle="--", label=label)
            ax.axhspan(ref[f"{metric}_min"], ref[f"{metric}_max"], color=COLOR["modn"], alpha=0.12)

    ax = axes[0]
    errbar(ax, ch, "V", "cv", "Consistent hashing", color=COLOR["consistent"])
    refline(ax, "cv", "hash mod N")
    ax.set_ylabel(L("CV = std / mean (ยิ่งต่ำยิ่งสมดุล)", "CV = std / mean (lower = more balanced)"))
    ax.set_title(L("ความสมดุลของจำนวนแขกต่ออาคาร", "Load balance (guests per building)"), fontsize=10)
    ax.set_ylim(bottom=0)

    ax = axes[1]
    errbar(ax, ch, "V", "mem_current_mib", "Consistent hashing current", color=COLOR["consistent"])
    errbar(ax, ch, "V", "mem_peak_mib", "Consistent hashing peak",
           color=COLOR["consistent"], linestyle="--")
    refline(ax, "mem_current_mib", "hash mod N current")
    ax.set_ylabel("MiB")
    ax.set_title(L("หน่วยความจำที่ Python ติดตาม (tracemalloc)", "Python-tracked memory (tracemalloc)"),
                 fontsize=10)

    ax = axes[2]
    errbar(ax, ch, "V", "add_rate", L("Consistent: เพิ่ม 1 อาคาร", "Consistent: add 1"),
           color="tab:blue")
    errbar(ax, ch, "V", "remove_rate", L("Consistent: ลบ 1 อาคาร", "Consistent: remove 1"),
           color="tab:green")
    refline(ax, "add_rate", L("hash mod N: เพิ่ม", "hash mod N: add"))
    ax.set_ylabel(L("อัตราย้าย (จำนวนย้าย / K)", "Migration rate (moved / K)"))
    ax.set_title(L("การย้ายแขก", "Migration"), fontsize=10)
    ax.set_ylim(bottom=0)

    for ax in axes:
        ax.set_xscale("log")
        ax.set_xticks(args.vs)
        ax.set_xticklabels([str(v) for v in args.vs])
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xlabel(L("จำนวนจุดเสมือนต่ออาคาร V", "Virtual nodes per building V"))
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(L(f"การทดลอง C: ผลของ V  (N={args.n_fixed}, K={args.k_fixed:,}, "
                   f"{len(args.salts)} รอบ: จุด=ค่าเฉลี่ย, แท่ง/แถบ=ต่ำสุด–สูงสุด)",
                   f"Experiment C: effect of V  (N={args.n_fixed}, K={args.k_fixed:,}, "
                   f"{len(args.salts)} rounds: dot=mean, bar/band=min–max)"))
    fig.tight_layout()
    fig.savefig(outdir / "fig_C_virtual_nodes.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def int_list(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip()]


def parse_args():
    p = argparse.ArgumentParser(description="ชุดการทดลองหัวข้อ 7 (Consistent Hashing vs hash mod N)")
    p.add_argument("--outdir", default="output/experiments")
    p.add_argument("--only", default="A,B,C", help="เลือกการทดลอง เช่น A,C")
    p.add_argument("--salts", default="0,1,2", help="salt ของแต่ละรอบ (ค่าเริ่มต้น 3 รอบ: 0,1,2)")
    p.add_argument("--ks", type=int_list, default=[1000, 10000, 100000])
    p.add_argument("--ns", type=int_list, default=[5, 10, 20])
    p.add_argument("--vs", type=int_list, default=[1, 8, 32])
    p.add_argument("--n-fixed", type=int, default=10)
    p.add_argument("--v-fixed", type=int, default=32)
    p.add_argument("--k-fixed", type=int, default=10000)
    p.add_argument("--remove-target", default=f"{NODE_PREFIX}001",
                   help="รหัสอาคารที่ลบในการทดลอง B/C (ค่าเริ่มต้น B001)")
    p.add_argument("--quick", action="store_true", help="ชุดเล็กไว้ทดสอบว่าสคริปต์ทำงานครบ")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--english-labels", action="store_true", help="บังคับป้ายกราฟเป็นภาษาอังกฤษ")
    args = p.parse_args()
    args.salts = [s.strip() for s in args.salts.split(",") if s.strip()]
    args.only = {x.strip().upper() for x in args.only.split(",")}
    if args.quick:
        args.ks, args.k_fixed = [1000, 2000, 4000], 2000
    return args


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for salt in args.salts:
        verify_same_hash(salt)
    # warm-up: ลดผลของการเรียกครั้งแรก
    w = make_system("consistent", 3, 4, "warm")
    populate(w, 300)
    w.list_rooms()
    del w

    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version, "platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor(),
        "perf_counter": str(time.get_clock_info("perf_counter")),
        "args": {k: (sorted(v) if isinstance(v, set) else v) for k, v in vars(args).items()},
        "channels": CHANNELS, "search_batch": SEARCH_BATCH, "search_seed": SEARCH_SEED,
        "notes": ["memory = Python-tracked memory via tracemalloc (not whole process), "
                  "measured in a separate pass from timing",
                  "time/memory reported as median of rounds; plots show mean with min-max"],
    }
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    plt = None if args.no_plots else setup_matplotlib(args.english_labels)

    if "A" in args.only:
        raw, summ = run_A(args)
        write_csv(outdir / "raw_A.csv", raw)
        write_csv(outdir / "summary_A.csv", summ)
        print_summary("A", summ, ["method", "K"],
                      ["assign_s", "search_us", "route_us", "sort_s", "mem_current_mib", "mem_peak_mib"])
        if plt:
            plot_A(summ, args, outdir, plt)

    if "B" in args.only:
        raw, summ = run_B(args)
        write_csv(outdir / "raw_B.csv", raw)
        write_csv(outdir / "summary_B.csv", summ)
        print_summary("B", summ, ["method", "op", "N"], ["moved", "rate", "ideal_rate", "time_ms"])
        if plt:
            plot_B(summ, args, outdir, plt)

    if "C" in args.only:
        raw, summ, counts = run_C(args)
        write_csv(outdir / "raw_C.csv", raw)
        write_csv(outdir / "summary_C.csv", summ)
        write_csv(outdir / "counts_C.csv", counts)
        print_summary("C", summ, ["method", "V"],
                      ["min", "max", "cv", "mem_current_mib", "mem_peak_mib", "add_rate", "remove_rate"])
        if plt:
            plot_C(summ, args, outdir, plt)

    print(f"\nเสร็จแล้ว ผลลัพธ์อยู่ที่ {outdir.resolve()}")


if __name__ == "__main__":
    main()