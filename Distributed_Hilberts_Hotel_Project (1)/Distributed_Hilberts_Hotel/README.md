# Distributed Hilbert's Hotel — Consistent Hashing

โปรเจกต์ Python สำหรับงาน Object Oriented Data Structure ตาม requirement ในเอกสารโจทย์

## ความสามารถหลัก
- Consistent Hashing ring ตำแหน่ง 64-bit จาก SHA-256 และ salt ที่กำหนดซ้ำได้
- Virtual nodes จำนวน V จุดต่ออาคาร โดยเก็บจุดชนกันทุกจุดและเรียง `(position, node_id, replica)`
- หมายเลขห้องจาก Cantor pairing function ของ `(channel_id, sequence_id)` ไม่ใช้เลขล่าสุด + 1
- เพิ่มแขกเดี่ยว/เป็นกลุ่มแบบ atomic, นำแขกออก, ค้นหาทั้งสองทิศทาง
- เพิ่ม/ลบอาคารพร้อมรายงานรายการย้าย โดยตรวจแขกทุกคน (วิธี A ใน requirement)
- สถิติ load รวมอาคารที่ไม่มีแขก, CSV UTF-8, baseline hash mod N
- benchmark เวลา/หน่วยความจำ, ผล migration, และกราฟ 3 ภาพ
- automated tests ด้วย `unittest`

## Requirements
- Python 3.10 หรือใหม่กว่า
- กราฟต้องติดตั้ง `matplotlib` เพิ่ม:
  `python -m pip install matplotlib`
- Core system ใช้ standard library เท่านั้น

## เริ่มใช้งาน
```bash
python main.py
```

ตัวอย่างเริ่มระบบ: N=3, V=32, ช่องทาง=2 แล้วระบุจำนวนแขกในแต่ละช่องทาง

เมนู:
1. เพิ่มแขกรายบุคคล
2. เพิ่มแขกเป็นกลุ่ม
3. นำแขกออก
4. เพิ่มอาคาร
5. ลบอาคาร
6. ค้นหาด้วยรหัสแขก
7. ค้นหาด้วยอาคารและเลขห้อง
8. แสดงรายการห้อง
9. สถิติ load balance
10. ส่งออก guest CSV

## ทดสอบอัตโนมัติ
```bash
python -m unittest -v
```

## รันการทดลอง
ทดสอบเร็วเพื่อตรวจการทำงาน:
```bash
python benchmark.py --quick
```

การทดลองตามโจทย์ (อาจใช้เวลาหลายนาทีและใช้ RAM มาก โดยเฉพาะ K=100,000):
```bash
python benchmark.py
```

สร้างกราฟ:
```bash
python -m pip install matplotlib
python plot_results.py
```

ไฟล์ผลลัพธ์จะอยู่ใน `output/`:
- `experiment_timing.csv`
- `experiment_memory.csv`
- `experiment_migrations.csv`
- `graph_A_time_vs_K.png`
- `graph_B_migration_vs_N.png`
- `graph_C_V_CV_memory.png`

## โครงสร้างคลาส
- `Guest`: รหัสช่องทาง/ลำดับและคำนวณ room number
- `HashRing`: สร้างและค้นหาวงแหวน Consistent Hashing
- `VirtualNode`: โครงสร้างข้อมูลจุดเสมือน
- `Migration`: บันทึกรายการย้าย
- `HotelSystem`: จัดการแขก, อาคาร, ดัชนีห้อง และสถิติ
- `ModNRouter`: baseline hash mod N สำหรับการทดลอง

## Big-O (ตาม implementation นี้)
ให้ `M=N×V`, `K=จำนวนแขก`, `V=virtual nodes ต่ออาคาร`:
- สร้างวงแหวนเริ่มต้นด้วยการ sort จุดทุกครั้งที่เพิ่มอาคาร: worst-case `O(N²V log(NV))` จากการสร้างทีละอาคารแบบตรงไปตรงมา; การสร้าง/เรียงครั้งเดียวแบบ batch จะลดได้ แต่ไม่ได้ใช้ในโค้ดนี้
- ค้นหาอาคารจากวงแหวน: `O(log M)` ด้วย `bisect_left` หลังสร้างตำแหน่งที่เรียงแล้ว
- เพิ่มแขก 1 คน: expected `O(1)` dictionary operations + `O(log M)` routing; การสร้าง room number คิดเป็น O(1) เมื่อถือว่าจำนวนเต็มมีขนาดคงที่
- เพิ่มกลุ่ม C คน: `O(C log M)` expected สำหรับ routing/insert dictionary; precheck ช่วงรหัสใช้ `O(C)` พื้นที่ชั่วคราว
- ลบแขก: expected `O(1)` dictionary operations
- ค้นหาด้วยรหัสแขกหรือที่อยู่ห้อง: expected `O(1)` dictionary lookup
- เรียงรายการห้อง: `O(K log K)` เวลาและ `O(K)` พื้นที่ผลลัพธ์
- เพิ่ม/ลบอาคาร: สร้าง/ลบ virtual points และ sort ring `O(M log M)` เป็นค่าประมาณต่อคำสั่ง; สแกนแขกและคำนวณตำแหน่งใหม่ `O(K log M)`; rebuild room index `O(K)`. รวม `O(M log M + K log M)` สำหรับการเปลี่ยนอาคาร (โดยไม่รวมต้นทุนการสร้าง object ที่เล็กน้อย)
- พื้นที่หลัก: `O(M+K)` สำหรับ ring, guest maps และ room index; temporary migration/placement data สูงสุด `O(K)`.
- Hash mod N: คำนวณ route `O(1)` โดยถือว่าการ hash สตริงเป็นต้นทุนตามความยาวรหัส; การเปลี่ยน N ใน baseline ยังต้องตรวจ K คนใน benchmark เพื่อวัด migration

## หมายเหตุการตีความผล
- การย้ายจริงขึ้นกับ salt, IDs, V และตำแหน่ง hash; expected migration rate เป็นค่าทฤษฎี ไม่ใช่ผลรับประกัน
- Consistent hashing ใช้ full scan ทุกครั้งที่เปลี่ยนอาคารตามวิธี A ในเอกสาร ไม่ได้ implement ช่วงกระทบแบบวิธี B
- `tracemalloc` วัดเฉพาะหน่วยความจำที่ Python ติดตาม ไม่ใช่ RAM ทั้งโปรเซส
- benchmark ใช้ salts `0,1,2` และรายงานแต่ละรอบใน CSV; ใช้ median ในการสรุปกราฟ
- ตัวเลขใน CSV/กราฟต้องสร้างบนเครื่องผู้ใช้จริง ห้ามนำค่าตัวอย่างไปอ้างเป็นผลทดลองจริงหากยังไม่ได้รัน
