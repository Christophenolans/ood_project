from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from hashlib import sha256
from collections import defaultdict
from typing import Iterable
import csv


@dataclass(frozen=True, order=True)
class Guest:
    channel_id: int
    sequence_id: int

    @property
    def room_no(self) -> int:
        # Cantor pairing, using zero-based values internally.
        a, b = self.channel_id - 1, self.sequence_id - 1
        return ((a + b) * (a + b + 1)) // 2 + b + 1

    @property
    def key(self) -> str:
        return f"guest:{self.channel_id}:{self.sequence_id}"


@dataclass(frozen=True)
class VirtualNode:
    position: int
    node_id: str
    replica: int


@dataclass(frozen=True)
class Migration:
    channel_id: int
    sequence_id: int
    old_node_id: str
    new_node_id: str
    room_no: int

    def as_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "sequence_id": self.sequence_id,
            "old_node_id": self.old_node_id,
            "new_node_id": self.new_node_id,
            "room_no": self.room_no,
        }


class HashRing:
    """Consistent-hashing ring. All positions are stable 64-bit SHA-256 values."""

    def __init__(self, virtual_nodes: int, salt: str = "0"):
        if not isinstance(virtual_nodes, int) or virtual_nodes < 1:
            raise ValueError("V ต้องเป็นจำนวนเต็มตั้งแต่ 1 ขึ้นไป")
        self.virtual_nodes = virtual_nodes
        self.salt = str(salt)
        self._points: list[tuple[int, str, int]] = []
        self._positions: list[int] = []
        self._node_ids: set[str] = set()

    def _hash64(self, text: str) -> int:
        payload = f"{self.salt}|{text}".encode("utf-8")
        return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)

    def add_node(self, node_id: str) -> None:
        if not node_id or not isinstance(node_id, str):
            raise ValueError("รหัสอาคารต้องเป็นข้อความที่ไม่ว่าง")
        if node_id in self._node_ids:
            raise ValueError(f"มีอาคาร {node_id} อยู่แล้ว")
        additions = []
        for j in range(self.virtual_nodes):
            position = self._hash64(f"node:{node_id}:{j}")
            additions.append((position, node_id, j))
        self._points.extend(additions)
        self._points.sort(key=lambda x: (x[0], x[1], x[2]))
        self._positions = [p[0] for p in self._points]
        self._node_ids.add(node_id)

    def remove_node(self, node_id: str) -> None:
        if node_id not in self._node_ids:
            raise ValueError(f"ไม่พบอาคาร {node_id}")
        if len(self._node_ids) <= 1:
            raise ValueError("ไม่สามารถลบอาคารหลังสุดท้ายได้")
        self._points = [p for p in self._points if p[1] != node_id]
        self._positions = [p[0] for p in self._points]
        self._node_ids.remove(node_id)

    def locate(self, guest: Guest) -> str:
        if not self._points:
            raise ValueError("วงแหวนไม่มีอาคาร")
        position = self._hash64(guest.key)
        idx = bisect_left(self._positions, position)
        if idx == len(self._points):
            idx = 0
        return self._points[idx][1]

    @property
    def node_ids(self) -> set[str]:
        return set(self._node_ids)

    @property
    def point_count(self) -> int:
        return len(self._points)


class ModNRouter:
    """Baseline comparison: stable H(guest) mod N over insertion-ordered node IDs."""

    def __init__(self, salt: str = "0"):
        self.salt = str(salt)
        self.node_ids: list[str] = []

    def _hash(self, guest: Guest) -> int:
        payload = f"{self.salt}|{guest.key}".encode("utf-8")
        return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)

    def add_node(self, node_id: str) -> None:
        if not node_id or not isinstance(node_id, str):
            raise ValueError("รหัสอาคารต้องเป็นข้อความที่ไม่ว่าง")
        if node_id in self.node_ids:
            raise ValueError(f"มีอาคาร {node_id} อยู่แล้ว")
        self.node_ids.append(node_id)

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.node_ids:
            raise ValueError(f"ไม่พบอาคาร {node_id}")
        if len(self.node_ids) <= 1:
            raise ValueError("ไม่สามารถลบอาคารหลังสุดท้ายได้")
        self.node_ids.remove(node_id)

    def locate(self, guest: Guest) -> str:
        if not self.node_ids:
            raise ValueError("ไม่มีอาคาร")
        return self.node_ids[self._hash(guest) % len(self.node_ids)]


class HotelSystem:
    
    def __init__(self, node_count: int = 3, virtual_nodes: int = 32,
                 salt: str = "0", node_prefix: str = "B"):
        if not isinstance(node_count, int) or node_count < 1:
            raise ValueError("จำนวนอาคารต้องเป็นจำนวนเต็มตั้งแต่ 1")
        self.ring = HashRing(virtual_nodes, salt)
        self.guests: dict[tuple[int, int], Guest] = {}
        self.guest_nodes: dict[tuple[int, int], str] = {}
        self.room_index: dict[tuple[str, int], tuple[int, int]] = {}
        self.node_prefix = node_prefix
        for i in range(1, node_count + 1):
            self.ring.add_node(f"{node_prefix}{i:03d}")

    @property
    def virtual_nodes(self) -> int:
        return self.ring.virtual_nodes

    @property
    def salt(self) -> str:
        return self.ring.salt

    @property
    def node_ids(self) -> list[str]:
        return sorted(self.ring.node_ids)

    def add_node(self, node_id: str) -> list[Migration]:
        before = dict(self.guest_nodes)
        self.ring.add_node(node_id)
        return self._reassign_and_report(before, "add", node_id)

    def remove_node(self, node_id: str) -> list[Migration]:
        if node_id not in self.ring.node_ids:
            raise ValueError(f"ไม่พบอาคาร {node_id}")
        if len(self.ring.node_ids) <= 1:
            raise ValueError("ไม่สามารถลบอาคารหลังสุดท้ายได้")
        before = dict(self.guest_nodes)
        self.ring.remove_node(node_id)
        return self._reassign_and_report(before, "remove", node_id)

    def _reassign_and_report(self, before: dict, operation: str,
                             changed_node: str) -> list[Migration]:
        new_nodes = {}
        migrations = []
        for key, guest in self.guests.items():
            new_node = self.ring.locate(guest)
            new_nodes[key] = new_node
            old_node = before[key]
            if old_node != new_node:
                if operation == "add" and new_node != changed_node:
                    raise AssertionError("Invariant violated: adding a node moved a guest elsewhere")
                if operation == "remove" and old_node != changed_node:
                    raise AssertionError("Invariant violated: removing a node moved an unaffected guest")
                migrations.append(Migration(
                    guest.channel_id, guest.sequence_id, old_node, new_node, guest.room_no
                ))
        self.guest_nodes = new_nodes
        self._rebuild_room_index()
        migrations.sort(key=lambda m: (m.channel_id, m.sequence_id))
        return migrations

    def _rebuild_room_index(self) -> None:
        index = {}
        for key, guest in self.guests.items():
            address = (self.guest_nodes[key], guest.room_no)
            if address in index:
                raise AssertionError(f"Duplicate room address: {address}")
            index[address] = key
        self.room_index = index

    def add_guest(self, channel_id: int, sequence_id: int) -> Guest:
        self.add_guest_group(channel_id, sequence_id, 1)
        return self.guests[(channel_id, sequence_id)]

    def add_guest_group(self, channel_id: int, s_start: int, count: int) -> list[Guest]:
        for name, value in (("channel_id", channel_id), ("s_start", s_start), ("count", count)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} ต้องเป็นจำนวนเต็ม")
        if channel_id < 1 or s_start < 1 or count < 0:
            raise ValueError("channel_id และ s_start ต้อง >= 1 และ count ต้อง >= 0")
        if count == 0:
            return []
        keys = [(channel_id, s) for s in range(s_start, s_start + count)]
        if any(key in self.guests for key in keys):
            raise ValueError("ช่วงรหัสแขกซ้ำกับข้อมูลเดิม ปฏิเสธทั้งกลุ่ม")
        new_guests = [Guest(c, s) for c, s in keys]
        placements = [(key, guest, self.ring.locate(guest))
                      for key, guest in zip(keys, new_guests)]
        for key, guest, node_id in placements:
            self.guests[key] = guest
            self.guest_nodes[key] = node_id
            address = (node_id, guest.room_no)
            if address in self.room_index:
                raise AssertionError(f"Duplicate room address: {address}")
            self.room_index[address] = key
        return new_guests

    def remove_guest(self, channel_id: int, sequence_id: int) -> Guest:
        key = (channel_id, sequence_id)
        if key not in self.guests:
            raise ValueError(f"ไม่พบแขก {key}")
        guest = self.guests.pop(key)
        node_id = self.guest_nodes.pop(key)
        self.room_index.pop((node_id, guest.room_no), None)
        return guest

    def find_guest(self, channel_id: int, sequence_id: int) -> dict | None:
        key = (channel_id, sequence_id)
        guest = self.guests.get(key)
        if guest is None:
            return None
        return self._guest_row(guest)

    def find_room(self, node_id: str, room_no: int) -> dict | None:
        key = self.room_index.get((node_id, room_no))
        if key is None:
            return None
        return self._guest_row(self.guests[key])

    def _guest_row(self, guest: Guest) -> dict:
        key = (guest.channel_id, guest.sequence_id)
        return {
            "channel_id": guest.channel_id,
            "sequence_id": guest.sequence_id,
            "node_id": self.guest_nodes[key],
            "room_no": guest.room_no,
        }

    def list_rooms(self) -> list[dict]:
        return sorted((self._guest_row(g) for g in self.guests.values()),
                      key=lambda r: (r["node_id"], r["room_no"]))

    def load_stats(self) -> dict:
        counts = {node: 0 for node in self.node_ids}
        for node in self.guest_nodes.values():
            counts[node] += 1
        values = list(counts.values())
        k = len(self.guests)
        mean = (sum(values) / len(values)) if values else 0.0
        variance = (sum((x - mean) ** 2 for x in values) / len(values)) if values else 0.0
        std = variance ** 0.5
        return {
            "counts": counts,
            "max": max(values, default=0),
            "min": min(values, default=0),
            "mean": mean,
            "std": std,
            "cv": (std / mean) if mean > 0 else None,
            "guest_count": k,
        }

    def export_guests(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "channel_id", "sequence_id", "node_id", "room_no"
            ])
            writer.writeheader()
            writer.writerows(self.list_rooms())

    @staticmethod
    def export_migrations(migrations: Iterable[Migration], path: str) -> None:
        fields = ["channel_id", "sequence_id", "old_node_id", "new_node_id", "room_no"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(m.as_dict() for m in migrations)
