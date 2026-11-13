import unittest
import tempfile
import csv
import os
from hotel import Guest, HashRing, HotelSystem


class HotelTests(unittest.TestCase):
    def setUp(self):
        self.hotel = HotelSystem(3, 8, salt="test")
        self.hotel.add_guest_group(1, 1, 100)
        self.hotel.add_guest_group(2, 1, 100)

    def test_cantor_examples(self):
        self.assertEqual(Guest(1, 1).room_no, 1)
        self.assertEqual(Guest(2, 1).room_no, 2)
        self.assertEqual(Guest(1, 2).room_no, 3)
        self.assertEqual(Guest(3, 1).room_no, 4)
        self.assertEqual(Guest(2, 2).room_no, 5)

    def test_room_numbers_unique(self):
        nums = [Guest(c, s).room_no for c in range(1, 20) for s in range(1, 20)]
        self.assertEqual(len(nums), len(set(nums)))

    def test_new_guest_does_not_move_existing(self):
        before = dict(self.hotel.guest_nodes)
        self.hotel.add_guest(3, 1)
        self.assertEqual(before, {k: self.hotel.guest_nodes[k] for k in before})

    def test_group_add_is_atomic(self):
        before = set(self.hotel.guests)
        with self.assertRaises(ValueError):
            self.hotel.add_guest_group(1, 99, 5)  # includes duplicate 99/100
        self.assertEqual(before, set(self.hotel.guests))

    def test_duplicate_guest_rejected(self):
        with self.assertRaises(ValueError):
            self.hotel.add_guest(1, 1)

    def test_remove_missing_guest(self):
        before = set(self.hotel.guests)
        with self.assertRaises(ValueError):
            self.hotel.remove_guest(9, 9)
        self.assertEqual(before, set(self.hotel.guests))

    def test_add_node_only_moves_to_new_node(self):
        moves = self.hotel.add_node("NEW")
        self.assertTrue(all(m.new_node_id == "NEW" for m in moves))
        self.assertEqual(len(moves), len({(m.channel_id, m.sequence_id) for m in moves}))
        self.assertTrue(all(m.room_no == Guest(m.channel_id, m.sequence_id).room_no for m in moves))

    def test_remove_node_only_moves_guests_from_removed_node(self):
        node = self.hotel.node_ids[0]
        moves = self.hotel.remove_node(node)
        self.assertTrue(all(m.old_node_id == node for m in moves))
        self.assertNotIn(node, self.hotel.node_ids)

    def test_cannot_remove_last_node(self):
        one = HotelSystem(1, 2)
        with self.assertRaises(ValueError):
            one.remove_node(one.node_ids[0])

    def test_duplicate_and_missing_nodes(self):
        with self.assertRaises(ValueError):
            self.hotel.add_node(self.hotel.node_ids[0])
        with self.assertRaises(ValueError):
            self.hotel.remove_node("MISSING")

    def test_search_both_directions(self):
        row = self.hotel.find_guest(1, 3)
        self.assertIsNotNone(row)
        self.assertEqual(self.hotel.find_room(row["node_id"], row["room_no"])["sequence_id"], 3)
        self.assertIsNone(self.hotel.find_guest(999, 999))
        self.assertIsNone(self.hotel.find_room("MISSING", 1))

    def test_load_stats_includes_empty_nodes(self):
        stats = self.hotel.load_stats()
        self.assertEqual(set(stats["counts"]), set(self.hotel.node_ids))
        self.assertEqual(sum(stats["counts"].values()), len(self.hotel.guests))

    def test_export_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "guests.csv")
            self.hotel.export_guests(path)
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), len(self.hotel.guests))
            self.assertEqual(set(rows[0]), {"channel_id", "sequence_id", "node_id", "room_no"})

    def test_hash_ring_stable(self):
        a, b = HashRing(8, "same"), HashRing(8, "same")
        for node in ["B001", "B002", "B003"]:
            a.add_node(node)
            b.add_node(node)
        guest = Guest(12, 45)
        self.assertEqual(a.locate(guest), b.locate(guest))


if __name__ == "__main__":
    unittest.main(verbosity=2)
