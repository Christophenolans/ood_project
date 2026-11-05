from hotel import HotelSystem, Migration
import os


def ask_int(prompt: str, minimum: int | None = None) -> int:
    while True:
        try:
            value = int(input(prompt).strip())
            if minimum is not None and value < minimum:
                print(f"กรุณาใส่จำนวนตั้งแต่ {minimum} ขึ้นไป")
                continue
            return value
        except ValueError:
            print("กรุณาใส่จำนวนเต็ม")


def show_migrations(migrations: list[Migration]) -> None:
    print(f"จำนวนแขกที่ย้าย: {len(migrations)}")
    if not migrations:
        print("ไม่มีแขกย้าย")
    else:
        for m in migrations[:50]:
            print(f"({m.channel_id}, {m.sequence_id}) | {m.old_node_id} -> "
                  f"{m.new_node_id} | room {m.room_no}")
        if len(migrations) > 50:
            print(f"... แสดง 50 รายการแรก จากทั้งหมด {len(migrations)} รายการ")
    

def main():
    print("=== Distributed Hilbert's Hotel: Consistent Hashing ===")
    n = ask_int("จำนวนอาคารเริ่มต้น N: ", 1)
    v = ask_int("จำนวน virtual node ต่ออาคาร V: ", 1)
    channels = ask_int("จำนวนช่องทางเริ่มต้น: ", 0)
    system = HotelSystem(n, v)
    for c in range(1, channels + 1):
        count = ask_int(f"จำนวนแขกช่องทาง {c}: ", 0)
        if count:
            system.add_guest_group(c, 1, count)
    print(f"เริ่มระบบแล้ว: {len(system.guests)} guests, {len(system.node_ids)} buildings.")

    while True:
        print("""
1) เพิ่มแขกรายบุคคล
2) เพิ่มแขกเป็นกลุ่ม
3) นำแขกออก
4) เพิ่มอาคาร
5) ลบอาคาร
6) ค้นหาด้วยรหัสแขก
7) ค้นหาด้วยอาคารและเลขห้อง
8) แสดงห้องที่มีผู้พัก
9) สถิติสมดุลโหลด
10) ส่งออก CSV
0) ออกจากโปรแกรม""")
        choice = input("เลือกเมนู: ").strip()
        try:
            if choice == "1":
                c = ask_int("channel_id: ", 1)
                s = ask_int("sequence_id: ", 1)
                guest = system.add_guest(c, s)
                print(f"เพิ่มสำเร็จ: ({c}, {s}) -> {system.guest_nodes[(c,s)]}, room {guest.room_no}")
            elif choice == "2":
                c = ask_int("channel_id: ", 1)
                s = ask_int("s_start: ", 1)
                count = ask_int("จำนวนแขก: ", 0)
                added = system.add_guest_group(c, s, count)
                print(f"เพิ่มสำเร็จ {len(added)} คน")
            elif choice == "3":
                c, s = ask_int("channel_id: ", 1), ask_int("sequence_id: ", 1)
                g = system.remove_guest(c, s)
                print(f"นำแขก ({g.channel_id}, {g.sequence_id}) ออกแล้ว")
            elif choice == "4":
                node = input("รหัสอาคารใหม่ (เช่น B004): ").strip()
                before = len(system.guests)
                migrations = system.add_node(node)
                show_migrations(migrations)
                rate = len(migrations) / before if before else None
                print(f"อัตราย้าย: {rate:.6f}" if rate is not None else "ไม่คำนวณอัตราย้าย: ไม่มีแขก")
            elif choice == "5":
                node = input("รหัสอาคารที่จะลบ: ").strip()
                before = len(system.guests)
                migrations = system.remove_node(node)
                show_migrations(migrations)
                rate = len(migrations) / before if before else None
                print(f"อัตราย้าย: {rate:.6f}" if rate is not None else "ไม่คำนวณอัตราย้าย: ไม่มีแขก")
            elif choice == "6":
                c, s = ask_int("channel_id: ", 1), ask_int("sequence_id: ", 1)
                print(system.find_guest(c, s) or "ไม่พบแขก")
            elif choice == "7":
                node, room = input("node_id: ").strip(), ask_int("room_no: ", 1)
                print(system.find_room(node, room) or "ไม่พบห้อง/แขก")
            elif choice == "8":
                rows = system.list_rooms()
                print(f"ห้องที่มีผู้พักทั้งหมด {len(rows)} ห้อง")
                for row in rows[:100]:
                    print(row)
                if len(rows) > 100:
                    print("แสดง 100 รายการแรก")
            elif choice == "9":
                stats = system.load_stats()
                for node, count in stats["counts"].items():
                    print(f"{node}: {count} guests")
                print(f"max={stats['max']} min={stats['min']} mean={stats['mean']:.3f} "
                      f"std={stats['std']:.3f}")
                print(f"CV={stats['cv']:.6f}" if stats["cv"] is not None else "CV: ไม่คำนวณ (ค่าเฉลี่ยเป็น 0)")
            elif choice == "10":
                os.makedirs("output", exist_ok=True)
                path = input("ชื่อไฟล์ [output/guests.csv]: ").strip() or "output/guests.csv"
                system.export_guests(path)
                print(f"ส่งออก {len(system.guests)} records ไปยัง {path}")
            elif choice == "0":
                break
            else:
                print("ไม่มีเมนูนี้")
        except (ValueError, AssertionError) as exc:
            print(f"ทำรายการไม่สำเร็จ: {exc}")


if __name__ == "__main__":
    main()
