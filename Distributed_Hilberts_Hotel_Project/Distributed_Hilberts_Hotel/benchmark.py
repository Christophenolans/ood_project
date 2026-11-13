"""Reproducible benchmark suite for assignment experiments A, B, and C."""
from __future__ import annotations
import argparse
import csv
import os
import statistics
import time
import tracemalloc
from hotel import Guest, HashRing, ModNRouter, HotelSystem


def median(values):
    return statistics.median(values) if values else 0.0


def make_guests(k: int, channels: int = 10) -> list[Guest]:
    # Near-even distribution over channels, deterministic IDs starting at sequence 1.
    base, extra = divmod(k, channels)
    guests = []
    for c in range(1, channels + 1):
        amount = base + (1 if c <= extra else 0)
        guests.extend(Guest(c, s) for s in range(1, amount + 1))
    return guests


def seed_system(n: int, v: int, k: int, salt: str) -> HotelSystem:
    system = HotelSystem(n, v, salt=salt)
    for guest in make_guests(k):
        # Add one by one for measuring assignment only in separate timing functions;
        # direct internal seeding avoids measuring setup overhead for other operations.
        key = (guest.channel_id, guest.sequence_id)
        node = system.ring.locate(guest)
        system.guests[key] = guest
        system.guest_nodes[key] = node
        system.room_index[(node, guest.room_no)] = key
    return system


def timed_memory(func):
    tracemalloc.start()
    before_current, _ = tracemalloc.get_traced_memory()
    func()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return max(0, current - before_current) / (1024 * 1024), max(0, peak - before_current) / (1024 * 1024)


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_benchmarks(output_dir="output", quick=False):
    os.makedirs(output_dir, exist_ok=True)
    salts = ["0", "1", "2"]
    rows = []
    memory_rows = []
    migration_rows = []
    search_rows = []

    # A: size K; use median across three salts/runs.
    k_values = [1000, 10000] if quick else [1000, 10000, 100000]
    for k in k_values:
        for salt in salts:
            t0 = time.perf_counter()
            ring = HashRing(32, salt)
            for i in range(1, 11):
                ring.add_node(f"B{i:03d}")
            ring_build = time.perf_counter() - t0

            guests = make_guests(k)
            t0 = time.perf_counter()
            placements = { (g.channel_id, g.sequence_id): ring.locate(g) for g in guests }
            assign_time = time.perf_counter() - t0

            system = seed_system(10, 32, k, salt)
            lookups = guests[:1000]
            t0 = time.perf_counter()
            for g in lookups:
                system.find_guest(g.channel_id, g.sequence_id)
            lookup_per = (time.perf_counter() - t0) / max(1, len(lookups))

            t0 = time.perf_counter()
            sorted_rooms = system.list_rooms()
            sort_time = time.perf_counter() - t0

            rows.append({
                "experiment": "A_size", "K": k, "N": 10, "V": 32, "salt": salt,
                "ring_build_seconds": ring_build, "assign_seconds": assign_time,
                "lookup_seconds_per_call": lookup_per, "sort_seconds": sort_time,
                "assigned_count": len(placements)
            })

            # Separate memory run from timing run as required by specification.
            def build_for_memory():
                mem_sys = seed_system(10, 32, k, salt)
                return mem_sys
            current, peak = timed_memory(build_for_memory)
            memory_rows.append({
                "experiment": "A_size", "K": k, "N": 10, "V": 32, "salt": salt,
                "current_MiB": current, "peak_MiB": peak
            })

    # B: compare migration rate on same guest set and same salt per round.
    for n in [5, 10, 20]:
        k = 10000 if not quick else 1000
        for salt in salts:
            guests = make_guests(k)
            # Consistent hashing: add one node, then remove one node from fresh baseline.
            ch = HotelSystem(n, 32, salt=salt)
            for g in guests:
                key = (g.channel_id, g.sequence_id)
                node = ch.ring.locate(g)
                ch.guests[key] = g
                ch.guest_nodes[key] = node
                ch.room_index[(node, g.room_no)] = key
            old_nodes = dict(ch.guest_nodes)
            new_id = f"ADD{n:03d}"
            t0 = time.perf_counter()
            ch_m_add = ch.add_node(new_id)
            ch_add_time = time.perf_counter() - t0
            migration_rows.append({
                "experiment": "B_migration", "method": "consistent_hashing",
                "operation": "add", "N_before": n, "K": k, "V": 32, "salt": salt,
                "moved": len(ch_m_add), "migration_rate": len(ch_m_add)/k if k else 0,
                "expected_rate": 1/(n+1), "seconds": ch_add_time
            })

            # Mod N add uses the same insertion-ordered IDs and stable hash family.
            mod = ModNRouter(salt)
            for i in range(1, n + 1):
                mod.add_node(f"B{i:03d}")
            before_mod = { (g.channel_id, g.sequence_id): mod.locate(g) for g in guests }
            t0 = time.perf_counter()
            mod.add_node(new_id)
            after_mod = { (g.channel_id, g.sequence_id): mod.locate(g) for g in guests }
            mod_add_time = time.perf_counter() - t0
            moved = sum(before_mod[key] != after_mod[key] for key in before_mod)
            migration_rows.append({
                "experiment": "B_migration", "method": "hash_mod_N",
                "operation": "add", "N_before": n, "K": k, "V": 32, "salt": salt,
                "moved": moved, "migration_rate": moved/k if k else 0,
                "expected_rate": n/(n+1), "seconds": mod_add_time
            })

            # Remove the last baseline node from fresh systems to make comparison fair.
            ch2 = HotelSystem(n, 32, salt=salt)
            for g in guests:
                key = (g.channel_id, g.sequence_id)
                node = ch2.ring.locate(g)
                ch2.guests[key] = g
                ch2.guest_nodes[key] = node
                ch2.room_index[(node, g.room_no)] = key
            removed_node = ch2.node_ids[-1]
            t0 = time.perf_counter()
            ch_m_remove = ch2.remove_node(removed_node)
            ch_remove_time = time.perf_counter() - t0
            migration_rows.append({
                "experiment": "B_migration", "method": "consistent_hashing",
                "operation": "remove", "N_before": n, "K": k, "V": 32, "salt": salt,
                "moved": len(ch_m_remove), "migration_rate": len(ch_m_remove)/k if k else 0,
                "expected_rate": 1/n, "seconds": ch_remove_time
            })
            mod2 = ModNRouter(salt)
            for i in range(1, n + 1):
                mod2.add_node(f"B{i:03d}")
            before_mod = {(g.channel_id, g.sequence_id): mod2.locate(g) for g in guests}
            t0 = time.perf_counter()
            mod2.remove_node(removed_node)
            after_mod = {(g.channel_id, g.sequence_id): mod2.locate(g) for g in guests}
            mod_remove_time = time.perf_counter() - t0
            moved = sum(before_mod[key] != after_mod[key] for key in before_mod)
            migration_rows.append({
                "experiment": "B_migration", "method": "hash_mod_N",
                "operation": "remove", "N_before": n, "K": k, "V": 32, "salt": salt,
                "moved": moved, "migration_rate": moved/k if k else 0,
                "expected_rate": 1/n, "seconds": mod_remove_time
            })

    # C: V effect on load balance and tracked memory.
    for v in [1, 8, 32]:
        k = 10000 if not quick else 1000
        for salt in salts:
            system = seed_system(10, v, k, salt)
            stats = system.load_stats()
            current, peak = timed_memory(lambda: seed_system(10, v, k, salt))
            rows.append({
                "experiment": "C_virtual_nodes", "K": k, "N": 10, "V": v, "salt": salt,
                "ring_build_seconds": "", "assign_seconds": "", "lookup_seconds_per_call": "",
                "sort_seconds": "", "assigned_count": k, "cv": stats["cv"],
                "max_load": stats["max"], "min_load": stats["min"]
            })
            memory_rows.append({
                "experiment": "C_virtual_nodes", "K": k, "N": 10, "V": v, "salt": salt,
                "current_MiB": current, "peak_MiB": peak
            })

    write_csv(os.path.join(output_dir, "experiment_timing.csv"), rows)
    write_csv(os.path.join(output_dir, "experiment_memory.csv"), memory_rows)
    write_csv(os.path.join(output_dir, "experiment_migrations.csv"), migration_rows)
    print("Benchmark complete.")
    print(f"Timing: {os.path.join(output_dir, 'experiment_timing.csv')}")
    print(f"Memory: {os.path.join(output_dir, 'experiment_memory.csv')}")
    print(f"Migrations: {os.path.join(output_dir, 'experiment_migrations.csv')}")
    print("หมายเหตุ: ใช้ผลจริงจากเครื่องที่รัน; quick mode ลด K เพื่อทดสอบโค้ดเร็วขึ้น.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output")
    parser.add_argument("--quick", action="store_true", help="ใช้ K ขนาดเล็กเพื่อตรวจการทำงาน")
    args = parser.parse_args()
    run_benchmarks(args.output, args.quick)
