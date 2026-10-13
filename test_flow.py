"""ทดสอบ 1 รอบเต็ม + ค้นหายา + กรณีปฏิเสธตอนสั่งซื้อ (ROLLBACK + แถว rejected) + คิวรอ/VIP + ตัวนับเวลาตอบกลับ
ผ่าน route ของ Flask กับฐานข้อมูล Oracle จริง

รัน migrate.bat (ครั้งเดียว) และ reset.bat ก่อน แล้วสั่ง:  python test_flow.py
(สคริปต์นี้สร้างข้อมูลทดสอบจริงในฐานข้อมูล ต้องรัน reset.bat อีกครั้งก่อน Demo)
คนไข้ 1-3 เป็นสมาชิกทั่วไป คนไข้ 4 เป็น VIP, เภสัชกร 1-2 ถือห้องเปิดได้คนละ 1 ห้อง
"""
import re
import sys

import oracledb

import app as app_module
import db
import transactions as tx
from app import app

sys.stdout.reconfigure(encoding="utf-8")
client = app.test_client()
failed = 0


def check(label, ok, detail=""):
    global failed
    failed += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")


def scalar(sql, **binds):
    return list(db.query_one(sql, **binds).values())[0]


def execute(sql, **binds):
    """แก้ข้อมูลตรง ๆ เพื่อจัดฉากทดสอบ (เช่น ตั้งสต็อก, ย้อนเวลา)"""
    with db.connect() as conn:
        conn.cursor().execute(sql, binds)
        conn.commit()


def stock(batch_id):
    return scalar("SELECT quantity FROM drug_batch WHERE batch_id = :b", b=batch_id)


def snapshot():
    """จำนวนแถวของทุกตารางใน schema + สต็อกทุกล็อต ใช้เทียบก่อน/หลังกรณีปฏิเสธ"""
    tables = [r["table_name"] for r in db.query("SELECT table_name FROM user_tables ORDER BY table_name")]
    counts = {t: scalar(f"SELECT COUNT(*) FROM {t}") for t in tables}
    counts["stock"] = [(r["batch_id"], r["quantity"]) for r in
                       db.query("SELECT batch_id, quantity FROM drug_batch ORDER BY batch_id")]
    counts["rx_batch"] = scalar("SELECT COUNT(batch_id) FROM prescription_detail")
    return counts


def latest(pid):
    """การขอคำปรึกษาครั้งล่าสุดของคนไข้ : สถานะคิว, ห้องแชท, เภสัชกรที่ถูกจับคู่"""
    return db.query_one("""
        SELECT q.status AS queue, c.chat_id, c.pharmacist_id, c.status AS chat
        FROM   consult_queue q LEFT JOIN chat_room c ON c.queue_id = q.queue_id
        WHERE  q.patient_id = :p ORDER BY q.queue_id DESC FETCH FIRST 1 ROW ONLY""", p=pid)


def chat_state(chat_id):
    """สถานะห้องแชทตามรายงาน ที่ API ส่งให้หน้าเว็บ (คำนวณจาก open/closed + ข้อความ + คิว)"""
    return client.get(f"/api/chat/{chat_id}/messages?after=999999").get_json()["state"]


def position(pid):
    """ลำดับในคิวที่ API polling ส่งให้หน้าหลักคนไข้ (None ถ้าไม่ได้รอจับคู่)"""
    return client.get(f"/api/patient/{pid}/state").get_json()["state"][0].get("position")


def open_chats():
    return {r["pharmacist_id"]: r["n"] for r in db.query(
        "SELECT pharmacist_id, COUNT(*) AS n FROM chat_room WHERE status = 'open' GROUP BY pharmacist_id")}


def request(pid, expect_pharmacist):
    """คนไข้กดปุ่มเดียว -> คิว + จับคู่เภสัชกร + ห้องแชท "รอตอบกลับ"  คืน chat_id"""
    r = client.post(f"/patient/{pid}/queue")
    info = latest(pid)
    check(f"คนไข้ {pid} ขอรับคำปรึกษา: ระบบจับคู่เภสัชกร {expect_pharmacist} เอง, ห้อง 'รอตอบกลับ'",
          r.status_code == 302 and info["queue"] == "in_progress" and info["pharmacist_id"] == expect_pharmacist
          and info["chat"] == "open" and chat_state(info["chat_id"]) == "waiting_reply", str(info))
    return info["chat_id"]


def rx_form(lines):
    form = {"drug_id": [], "strength": [], "dosage": [], "usage_note": [], "quantity": []}
    for drug_id, qty in lines + [("", "")]:
        form["drug_id"].append(str(drug_id)); form["strength"].append("")
        form["dosage"].append("ครั้งละ 1 เม็ด" if drug_id else ""); form["usage_note"].append("หลังอาหาร" if drug_id else "")
        form["quantity"].append(str(qty))
    return form


def prescribe(phid, chat_id, lines, label="ออกใบสั่งยาขณะห้องยังเปิด"):
    r = client.post(f"/pharmacist/{phid}/chat/{chat_id}/prescription", data=rx_form(lines))
    rx_id = scalar("SELECT MAX(prescription_id) FROM prescription WHERE chat_id = :c", c=chat_id)
    n = scalar("SELECT COUNT(*) FROM prescription_detail WHERE prescription_id = :r", r=rx_id)
    check(label, r.status_code == 302 and n == len(lines) and chat_state(chat_id) == "consulting",
          f"rx_id={rx_id} lines={n}")
    return rx_id


def reply(phid, chat_id):
    client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "pharmacist", "content": "สวัสดีครับ มีอาการอะไรครับ"})


def close(phid, chat_id):
    return client.post(f"/pharmacist/{phid}/chat/{chat_id}/close")


def consult(pid, phid, lines):
    """รอบปรึกษาสั้น ๆ : ขอรับคำปรึกษา (ระบบจับคู่เภสัชกร phid) -> ตอบ -> ออกใบสั่งยา -> ปิดห้อง  คืน prescription_id"""
    chat_id = request(pid, phid)
    reply(phid, chat_id)
    rx_id = prescribe(phid, chat_id, lines)
    close(phid, chat_id)
    return rx_id


def rejected_prescription(phid, chat_id, lines, message, label, form=None):
    before = snapshot()
    r = client.post(f"/pharmacist/{phid}/chat/{chat_id}/prescription", data=form or rx_form(lines))
    html = r.get_data(as_text=True)
    check(label, r.status_code == 200 and "ระบบปฏิเสธรายการ:" in html and message in html and snapshot() == before,
          "(ข้อความถูกต้อง, ไม่มีแถวใหม่ในตารางใดเลย)")


ADDRESS = "7 หมู่ 2 ขอนแก่น 40150"


def rejected_order(pid, rx_id, message, label):
    """คนไข้กดสั่งซื้อแล้วระบบปฏิเสธ : ข้อความถูกต้อง, ROLLBACK งานหลักทั้งใบ (สต็อกทุกล็อตเท่าเดิม)
    และเหลือร่องรอยเป็น orders สถานะ rejected เพิ่ม 1 แถวเท่านั้น  คืน order_id ของแถว rejected"""
    before = snapshot()
    r = client.post(f"/patient/{pid}/prescription/{rx_id}/order", data={"shipping_address": ADDRESS})
    html = r.get_data(as_text=True)
    after = snapshot()
    check(f"{label}: หน้าเว็บแสดงเหตุผลที่ถูกปฏิเสธ", r.status_code == 200 and "ระบบปฏิเสธรายการ:" in html
          and f"สต็อกไม่พอ: {message} ระบบยกเลิกคำสั่งซื้อและคืนสต็อกทั้งหมดแล้ว" in html
          and "สถานะ “ถูกปฏิเสธ”" in html, message)
    expected = dict(before, ORDERS=before["ORDERS"] + 1)
    check(f"{label}: เพิ่มเฉพาะ orders 1 แถว ตารางอื่นและสต็อกทุกล็อตเท่าเดิม", after == expected,
          f"\n   ก่อน {before}\n   หลัง {after}")
    row = db.query_one("""
        SELECT o.order_id, o.status, o.patient_id, o.shipping_address,
               (SELECT COUNT(*) FROM order_detail d WHERE d.order_id = o.order_id) AS details
        FROM   orders o WHERE o.prescription_id = :r ORDER BY o.order_id DESC FETCH FIRST 1 ROW ONLY""", r=rx_id)
    check(f"{label}: แถวใหม่เป็น status = rejected ของคนไข้/ที่อยู่ที่กรอก ไม่มี order_detail และยังไม่บันทึกล็อตที่จ่าย",
          row is not None and row["status"] == "rejected" and row["patient_id"] == pid
          and row["shipping_address"] == ADDRESS and row["details"] == 0
          and f"คำสั่งซื้อเลขที่ {row['order_id']} " in html
          and scalar("SELECT COUNT(batch_id) FROM prescription_detail WHERE prescription_id = :r", r=rx_id) == 0, str(row))
    return row["order_id"]


def search(q=None, phid=1):
    """เรียก API ช่องค้นหายา คืน (status, รายการยา)"""
    r = client.get(f"/api/pharmacist/{phid}/drugs", query_string=None if q is None else {"q": q})
    return r.status_code, (r.get_json() or {}).get("drugs")


def found(q):
    status, drugs = search(q)
    return status, [d["drug_id"] for d in drugs]


print("=== ตรวจ schema หลัง migration ===")
check("chk_orders_status รองรับ 'rejected'", "'rejected'" in scalar(
    "SELECT search_condition_vc FROM user_constraints WHERE constraint_name = 'CHK_ORDERS_STATUS'"))
check("uq_orders_prescription เป็น unique index แบบมีเงื่อนไข (function-based)", db.query_one(
    "SELECT uniqueness, index_type FROM user_indexes WHERE index_name = 'UQ_ORDERS_PRESCRIPTION'")
    == {"uniqueness": "UNIQUE", "index_type": "FUNCTION-BASED NORMAL"})
check("consult_queue ไม่มีคอลัมน์ symptom_note (8 คอลัมน์ตาม DDL เดิม)", [r["column_name"] for r in db.query(
    "SELECT column_name FROM user_tab_columns WHERE table_name = 'CONSULT_QUEUE' ORDER BY column_id")]
    == ["QUEUE_ID", "PATIENT_ID", "PHARMACY_ID", "QUEUE_NO", "MEMBER_TYPE", "STATUS", "ENTERED_AT", "UPDATED_AT"])

print("\n=== รอบที่ 1 : ปฏิเสธตอนสั่งซื้อ (ROLLBACK + rejected) แล้วทำฟังก์ชันหลักครบวงจร (คนไข้ 1) ===")
check("ก่อนทำ: ยา A = 20", stock(1) == 20, f"(จริง {stock(1)})")
check("seed: เภสัชกร 2 คนร้านเดียวกัน, คนไข้ 4 คน, VIP 1 คน",
      scalar("SELECT COUNT(*) FROM pharmacist WHERE pharmacy_id = 1") == 2
      and scalar("SELECT COUNT(*) FROM patient") == 4 and scalar("SELECT COUNT(*) FROM patient WHERE is_vip = 1") == 1)
home = client.get("/patient/1").get_data(as_text=True)
check("หน้าคนไข้: ขอรับคำปรึกษาปุ่มเดียว ไม่มีช่องอาการเบื้องต้น", "ขอรับคำปรึกษา" in home and "symptom_note" not in home
      and "<textarea" not in home)
chat_id = request(1, 1)
home = client.get("/pharmacist/1").get_data(as_text=True)
check("หน้าเภสัชกร: ไม่มีตารางคิวรอรับเคส/ปุ่มรับเคส มีห้องที่ระบบจับคู่ให้", "รับเคส" not in home
      and "ห้องแชทที่รอตอบกลับ (1)" in home and client.post("/pharmacist/1/queue/1/claim").status_code == 404
      and client.get("/api/pharmacist/1/rooms").status_code == 404)
r = close(1, chat_id)
check("ปิดห้องแชทก่อนตอบคนไข้ไม่ได้", "ยังไม่ได้ตอบคนไข้" in r.get_data(as_text=True) and latest(1)["chat"] == "open")
client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "patient", "content": "ปวดหัว มีไข้ค่ะ"})
check("คนไข้ส่งข้อความ ยังเป็น 'รอตอบกลับ'", chat_state(chat_id) == "waiting_reply")
client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "pharmacist", "content": "เป็นมากี่วันแล้วครับ"})
msgs = client.get(f"/api/chat/{chat_id}/messages?after=0").get_json()
check("เภสัชกรตอบข้อความแรก -> 'ระหว่างปรึกษา'", msgs["state"] == "consulting" and msgs["state_label"] == "ระหว่างปรึกษา"
      and [m["sender_type"] for m in msgs["messages"]] == ["patient", "pharmacist"])
page = client.get(f"/pharmacist/1/chat/{chat_id}").get_data(as_text=True)
check("หน้าแชททั้งสองฝั่ง", "ออกใบสั่งยา" in page and client.get(f"/patient/1/chat/{chat_id}").status_code == 200)
check("ฟอร์มใบสั่งยาใช้ช่องค้นหายา 3 แถว ไม่มี dropdown แล้ว",
      page.count('class="drug-search relative"') == 3 and page.count('name="drug_id"') == 3
      and "<select" not in page and "drugsearch.js" in page and "/api/pharmacist/1/drugs" in page
      and "rooms.js" not in page and "room-tab" not in page)

print("\n--- ช่องค้นหายา (API ที่ type-ahead เรียก) ---")
status, drugs = search("พารา")
check("พิมพ์ชื่อบางส่วน 'พารา' (กลางคำ) -> ยา A, แสดง รหัส · ชื่อยา · สต็อกคงเหลือ",
      status == 200 and drugs == [{"drug_id": 1, "name": "ยา A (พาราเซตามอล 500 mg)", "stock": 20,
                                   "label": "1 · ยา A (พาราเซตามอล 500 mg) · เหลือ 20"}], str(drugs))
check("ไม่สนตัวพิมพ์ใหญ่เล็ก: 'MG' และ 'ors'", set(found("MG")[1]) == {1, 2, 3, 6} and found("ors")[1] == [5],
      f"({found('MG')[1]}, {found('ors')[1]})")
names = [d["name"] for d in search("MG")[1]]
check("เรียงตามชื่อยา", names == [r["name"] for r in db.query(
    "SELECT name FROM drug WHERE LOWER(name) LIKE '%mg%' ORDER BY name")], str(names))
check("พิมพ์รหัส '3' (ขึ้นต้นด้วย) -> ยารหัส 3", found("3")[1] == [3], str(found("3")[1]))
check("พิมพ์ '2' -> ยารหัส 2 และยาที่ชื่อมีเลข 2 (ยาธาตุน้ำขาว 200 มล.)", set(found("2")[1]) == {2, 4}, str(found("2")[1]))
status, drugs = search("6")
check("ยาที่คงเหลือ 0 แสดงเป็น 'หมด'", status == 200 and [d["label"] for d in drugs] == ["6 · คลอร์เฟนิรามีน 4 mg · หมด"], str(drugs))
check("สต็อกในผลค้นหา = ผลรวมล็อตที่ยังไม่หมดอายุ (ลอราทาดีน 100 + 200)", search("ลอรา")[1][0]["stock"] == 300)
for q in ["%", "_", "%%", "\\", "ยา%A", "ยา_A", "'", "' OR 1=1 --", "\"", ";"]:
    check(f"พิมพ์ {q!r} -> ถือเป็นตัวอักษรธรรมดา ไม่มี error ไม่มีผลลัพธ์", found(q) == (200, []), str(found(q)))
for q, label in [("", "ว่าง"), ("   ", "ช่องว่างล้วน"), (None, "ไม่ส่ง q")]:
    check(f"พิมพ์{label} -> รายการว่าง", search(q) == (200, []), str(search(q)))
check("คำค้นยาวมาก (300 ตัวอักษร) ไม่ error", found("ก" * 300) == (200, []))
check("มีช่องว่างหน้าหลังคำค้น ก็ค้นได้", found("  พารา  ")[1] == [1])
app_module.DRUG_SEARCH_LIMIT = 2
check("จำกัดจำนวนผลลัพธ์ (ตั้งเป็น 2 เพื่อทดสอบ เพราะยามี 6 รายการ ค่าจริงคือ 10)", len(search("mg")[1]) == 2)
app_module.DRUG_SEARCH_LIMIT = 10
check("ค่าจริง: แสดงสูงสุด 10 รายการ", app_module.DRUG_SEARCH_LIMIT == 10 and len(search("mg")[1]) == 4)

print("\n--- ฝั่งเภสัชกร : กันเฉพาะยาที่หมด และตรวจการกรอกฟอร์ม (ไม่เทียบจำนวนกับคงเหลือ) ---")
rejected_prescription(1, chat_id, [(6, 1)], "คลอร์เฟนิรามีน 4 mg คงเหลือ 0 ออกใบสั่งยาไม่ได้", "ยาคงเหลือ 0 -> ปฏิเสธ")
rejected_prescription(1, chat_id, [(1, 0)], "จำนวนยาต้องเป็นจำนวนเต็มมากกว่า 0", "จำนวน 0 -> ปฏิเสธ")
rejected_prescription(1, chat_id, [(1, "2.5")], "จำนวนยาต้องเป็นจำนวนเต็มมากกว่า 0", "จำนวนไม่ใช่จำนวนเต็ม -> ปฏิเสธ")
rejected_prescription(1, chat_id, None, "กรุณากรอกขนาดยาและวิธีใช้ให้ครบทุกรายการที่เลือก", "ไม่กรอกขนาดยา/วิธีใช้ -> ปฏิเสธ",
                      form={"drug_id": "1", "strength": "", "dosage": "", "usage_note": "", "quantity": "2"})
r = client.post(f"/pharmacist/1/chat/{chat_id}/prescription", data=rx_form([(1, 0)]))
html = r.get_data(as_text=True)
check("ฟอร์มคืนค่าที่กรอกไว้หลังถูกปฏิเสธ รวมยาที่เลือกในช่องค้นหา", 'value="0"' in html
      and 'name="drug_id" value="1"' in html and 'value="1 · ยา A (พาราเซตามอล 500 mg) · เหลือ 20"' in html)

before = snapshot()
rx_over = prescribe(1, chat_id, [(2, 5), (1, 25)],   # ลอราทาดีน 5, ยา A 25 (คงเหลือ 20)
                    "จำนวนเกินคงเหลือ (ยา A 25 จาก 20): เภสัชกรออกใบสั่งยาได้ ไม่ถูกปฏิเสธ")
check("ออกใบสั่งยายังไม่ตัดสต็อก", snapshot()["stock"] == before["stock"])
r = client.post(f"/pharmacist/1/chat/{chat_id}/prescription", data=rx_form([(1, 1)]))
check("ออกใบสั่งยาซ้ำในห้องเดิมไม่ได้", "ออกใบสั่งยาไปแล้ว" in r.get_data(as_text=True))
r = close(1, chat_id)
info = latest(1)
check("เภสัชกรปิดห้องแชท -> chat closed, คิว completed", r.status_code == 302 and info["chat"] == "closed"
      and info["queue"] == "completed" and chat_state(chat_id) == "closed", str(info))
r = client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "patient", "content": "ขอบคุณค่ะ"})
check("ห้องปิดแล้วส่งข้อความไม่ได้", r.status_code == 409)

print("\n--- ฝั่งคนไข้ : กรอกข้อมูลผิด -> ไม่บันทึก rejected ---")
before = snapshot()
r = client.post(f"/patient/1/prescription/{rx_over}/order", data={"shipping_address": "   "})
check("ที่อยู่ว่าง: แจ้งให้กรอก ไม่มีแถวใหม่", "กรุณาระบุที่อยู่จัดส่ง" in r.get_data(as_text=True) and snapshot() == before)
r = client.post(f"/patient/1/prescription/{rx_over}/order", data={"shipping_address": "ก" * 501})
check("ที่อยู่ยาวเกิน 500: แจ้งเตือน ไม่มีแถวใหม่", "ที่อยู่จัดส่งยาวเกิน 500 ตัวอักษร" in r.get_data(as_text=True) and snapshot() == before)
for label, args in [("ไม่พบใบสั่งยา", (1, 9999, ADDRESS)), ("ใบสั่งยาของคนไข้คนอื่น", (2, rx_over, ADDRESS))]:
    try:
        tx.place_order(*args)
        raised = None
    except tx.DemoError as exc:
        raised = exc
    check(f"{label}: DemoError ธรรมดา (ไม่ใช่ RejectedError) ไม่มีแถวใหม่", raised is not None
          and not isinstance(raised, tx.RejectedError) and "ไม่พบใบสั่งยานี้" in str(raised) and snapshot() == before, str(raised))

print("\n--- ฝั่งคนไข้ : สั่งซื้อเกินสต็อก -> ROLLBACK ทั้งใบ + เหลือแถว rejected ---")
# บรรทัดที่ 1 (ลอราทาดีน 5) ถูกหักสต็อกไปก่อน แล้วบรรทัดที่ 2 (ยา A 25) ไม่พอ -> ต้องคืนลอราทาดีนด้วย
rej_1 = rejected_order(1, rx_over, "ยา A (พาราเซตามอล 500 mg) คงเหลือ 20 สั่ง 25 ไม่ได้", "ลอราทาดีน 5 + ยา A 25")
check("ลอราทาดีนเท่าเดิม (100, 200) และยา A เท่าเดิม (20)", (stock(2), stock(3), stock(1)) == (100, 200, 20),
      f"(จริง {stock(2)}, {stock(3)}, {stock(1)})")
page = client.get("/patient/1/orders").get_data(as_text=True)
check("ประวัติคำสั่งซื้อ: แถว rejected ขึ้นป้าย 'ถูกปฏิเสธ' ไม่มีปุ่มชำระเงิน/ใบเสร็จ มีลิงก์กลับไปใบสั่งยา",
      "ถูกปฏิเสธ" in page and "แสดงทั้งหมด <strong>1</strong> คำสั่งซื้อ" in page and f"/order/{rej_1}/pay" not in page
      and f"/order/{rej_1}/receipt" not in page and f"/patient/1/prescription/{rx_over}" in page)
page = client.get(f"/patient/1/prescription/{rx_over}").get_data(as_text=True)
check("หน้าใบสั่งยา: ยังสั่งซื้อได้ (rejected ไม่กินสิทธิ์ใบสั่งยา) และบอกว่าเคยถูกปฏิเสธ 1 ครั้ง",
      'id="order-form"' in page and "เคยถูกปฏิเสธตอนสั่งซื้อ 1 ครั้ง" in page and "สั่งซื้อแล้ว" not in page)
home = client.get("/patient/1").get_data(as_text=True)
check("หน้าหลักคนไข้: ใบสั่งยาที่ถูกปฏิเสธไม่ขึ้น 'รอชำระเงิน'", "ถูกปฏิเสธ · สั่งซื้อใหม่ได้" in home and "รอชำระเงิน" not in home)
r = client.get(f"/patient/1/order/{rej_1}/pay")
check("หน้าชำระเงินของคำสั่งซื้อ rejected: ส่งกลับหน้าประวัติ (ไม่วนลูป)", r.status_code == 302 and r.location.endswith("/patient/1/orders"))
r = client.get(f"/patient/1/order/{rej_1}/receipt", follow_redirects=True)
check("หน้าใบเสร็จของคำสั่งซื้อ rejected: จบที่หน้าประวัติ", r.status_code == 200 and "ประวัติคำสั่งซื้อ" in r.get_data(as_text=True))
before = snapshot()
r = client.post(f"/patient/1/order/{rej_1}/pay", data={"method": "qr_code"}, follow_redirects=True)
check("ชำระเงินคำสั่งซื้อ rejected ไม่ได้: ไม่มี payment/receipt ใหม่ สถานะยังเป็น rejected", snapshot() == before
      and scalar("SELECT status FROM orders WHERE order_id = :o", o=rej_1) == "rejected")
try:
    tx.pay_order(1, rej_1, "qr_code")
    raised = ""
except tx.DemoError as exc:
    raised = str(exc)
check("pay_order ปฏิเสธคำสั่งซื้อ rejected ด้วยข้อความที่ถูกต้อง", raised == "คำสั่งซื้อนี้ถูกปฏิเสธ ชำระเงินไม่ได้", raised)

print("\n--- เดโมสั่งซื้อปกติ (สต็อกพอ) : คนไข้ 1 ขอรับคำปรึกษาใหม่ ---")
rx_id = consult(1, 2, [(2, 10), (1, 2)])             # เภสัชกร 2 ยังไม่เคยได้ห้อง : ลอราทาดีน 10, ยา A 2
check("หน้าใบสั่งยา", client.get(f"/patient/1/prescription/{rx_id}").status_code == 200)
r = client.post(f"/patient/1/prescription/{rx_id}/order", data={"shipping_address": "12/3 หมู่ 4 ขอนแก่น 40000"})
order = db.query_one("SELECT order_id, status FROM orders WHERE prescription_id = :r", r=rx_id)
check("สั่งซื้อ: orders = pending_payment", r.status_code == 302 and order and order["status"] == "pending_payment", str(order))
oid = order["order_id"]
check("สั่งซื้อสำเร็จแล้วไปหน้าชำระเงิน", r.location.endswith(f"/patient/1/order/{oid}/pay"))
details = db.query("SELECT line_no, drug_name, quantity, unit_price FROM order_detail WHERE order_id = :o ORDER BY line_no", o=oid)
check("order_detail snapshot ชื่อ/ราคา", [(d["drug_name"], d["quantity"], d["unit_price"]) for d in details]
      == [("ลอราทาดีน 10 mg", 10, 5), ("ยา A (พาราเซตามอล 500 mg)", 2, 2)], str(details))
check("ตัดสต็อก: ยา A = 18", stock(1) == 18, f"(จริง {stock(1)})")
check("FEFO: ลอราทาดีนตัดล็อตหมดอายุก่อน (100->90) ล็อตหลังคงเดิม (200)", stock(2) == 90 and stock(3) == 200, f"(จริง {stock(2)}, {stock(3)})")
batches = [r_["batch_id"] for r_ in db.query("SELECT batch_id FROM prescription_detail WHERE prescription_id = :r ORDER BY line_no", r=rx_id)]
check("prescription_detail.batch_id ถูกบันทึก (ผูกล็อต)", batches == [2, 1], str(batches))

check("หน้าชำระเงิน", client.get(f"/patient/1/order/{oid}/pay").status_code == 200)
r = client.post(f"/patient/1/order/{oid}/pay", data={"method": "qr_code"})
pay = db.query_one("SELECT y.method, y.status, q.amount FROM payment y JOIN qr_code q ON q.payment_id = y.payment_id WHERE y.order_id = :o", o=oid)
check("ชำระเงิน QR: payment + qr_code", r.status_code == 302 and pay == {"method": "qr_code", "status": "success", "amount": 54}, str(pay))
check("orders.status = paid", scalar("SELECT status FROM orders WHERE order_id = :o", o=oid) == "paid")
rc = db.query_one("SELECT r.receipt_no, r.pharmacy_id, COUNT(*) AS n, SUM(d.total_amount) AS total FROM receipt r JOIN receipt_detail d ON d.receipt_id = r.receipt_id WHERE r.order_id = :o GROUP BY r.receipt_no, r.pharmacy_id", o=oid)
check("receipt + receipt_detail", rc is not None and rc["n"] == 2 and rc["total"] == 54 and rc["pharmacy_id"] == 1, str(rc))
page = client.get(f"/patient/1/order/{oid}/receipt")
check("หน้าใบเสร็จแสดงเลขที่ใบเสร็จ", page.status_code == 200 and rc["receipt_no"] in page.get_data(as_text=True))
page = client.get("/patient/1/orders").get_data(as_text=True)
check("ประวัติคำสั่งซื้อ: มีทั้งแถว 'ชำระเงินแล้ว' (พร้อมใบเสร็จ) และแถว 'ถูกปฏิเสธ'",
      "ชำระเงินแล้ว" in page and rc["receipt_no"] in page and "ถูกปฏิเสธ" in page and "แสดงทั้งหมด <strong>2</strong> คำสั่งซื้อ" in page)
before = snapshot()
r = client.post(f"/patient/1/order/{oid}/pay", data={"method": "bank_transfer", "bank_name": "ธนาคารตัวอย่าง ก"})
check("จ่ายซ้ำถูกปฏิเสธ ข้อมูลไม่เปลี่ยน", "ชำระเงินแล้ว" in r.get_data(as_text=True) and snapshot() == before)

print("\n=== รอบที่ 2 : เดโมกรณีปฏิเสธ (สต็อก 3 สั่ง 5) แล้วเติมสต็อกและสั่งซ้ำจากใบสั่งยาเดิม ===")
rx2 = consult(2, 1, [(1, 5)])                        # ทั้งคู่ว่าง เภสัชกร 1 ได้ห้องล่าสุดนานกว่า : ยา A 5
execute("UPDATE drug_batch SET quantity = 3 WHERE batch_id = 1")
rej_2 = rejected_order(2, rx2, "ยา A (พาราเซตามอล 500 mg) คงเหลือ 3 สั่ง 5 ไม่ได้", "สต็อก 3 สั่ง 5")
rows = db.query("SELECT order_id, status FROM orders WHERE prescription_id = :r", r=rx2)
check("orders ของใบสั่งยานี้มีแถว status = 'rejected' 1 แถว", rows == [{"order_id": rej_2, "status": "rejected"}], str(rows))
check("order_detail ไม่มีแถวของคำสั่งนี้", scalar("SELECT COUNT(*) FROM order_detail WHERE order_id = :o", o=rej_2) == 0)
check("drug_batch.quantity ยังเท่าเดิม (3)", stock(1) == 3, f"(จริง {stock(1)})")

execute("UPDATE drug_batch SET quantity = 18 WHERE batch_id = 1")        # เติมสต็อกให้พอ
r = client.post(f"/patient/2/prescription/{rx2}/order", data={"shipping_address": "88/9 อุดรธานี 41000"})
rows = db.query("SELECT order_id, status FROM orders WHERE prescription_id = :r ORDER BY order_id", r=rx2)
oid2 = rows[-1]["order_id"]
check("เติมสต็อกแล้วสั่งซ้ำจากใบสั่งยาเดิมสำเร็จ (unique แบบมีเงื่อนไขทำงาน): rejected 1 + pending_payment 1",
      r.status_code == 302 and [x["status"] for x in rows] == ["rejected", "pending_payment"], str(rows))
check("คำสั่งซื้อใหม่ตัดสต็อกตามปกติ: ยา A 18 -> 13, มี order_detail และผูกล็อต", stock(1) == 13
      and scalar("SELECT COUNT(*) FROM order_detail WHERE order_id = :o", o=oid2) == 1
      and scalar("SELECT batch_id FROM prescription_detail WHERE prescription_id = :r", r=rx2) == 1, f"(ยา A จริง {stock(1)})")
before = snapshot()
r = client.post(f"/patient/2/prescription/{rx2}/order", data={"shipping_address": "88/9 อุดรธานี 41000"})
html = r.get_data(as_text=True)
check("สั่งซ้ำอีกครั้งหลังสำเร็จ: 'ถูกสั่งซื้อไปแล้ว' ไม่บันทึก rejected เพิ่ม", r.status_code == 200 and snapshot() == before
      and (f"คำสั่งซื้อเลขที่ {oid2}" in html) and 'id="order-form"' not in html)
try:
    tx.place_order(2, rx2, ADDRESS)
    raised = None
except tx.DemoError as exc:
    raised = exc
check("place_order ขั้น (1): ใบสั่งยาที่มีคำสั่งซื้อจริงแล้ว -> DemoError ธรรมดา ไม่มีแถวใหม่", raised is not None
      and not isinstance(raised, tx.RejectedError) and str(raised) == "ใบสั่งยานี้ถูกสั่งซื้อไปแล้ว" and snapshot() == before, str(raised))
with db.connect() as conn:                           # พิสูจน์ unique index โดยตรง แล้ว ROLLBACK
    cur = conn.cursor()
    insert = ("INSERT INTO orders (order_id, patient_id, prescription_id, status, shipping_address) "
              "VALUES (seq_orders.NEXTVAL, 2, :r, :s, 'x')")
    try:
        cur.execute(insert, r=rx2, s="pending_payment")
        code = None
    except oracledb.IntegrityError as exc:
        code = exc.args[0].full_code
    cur.execute(insert, r=rx2, s="rejected")
    conn.rollback()
check("unique index: คำสั่งซื้อจริงใบที่ 2 ของใบสั่งยาเดียวกันถูกกัน (ORA-00001) แต่แถว rejected เพิ่มได้", code == "ORA-00001", str(code))
r = client.post(f"/patient/2/order/{oid2}/pay", data={"method": "bank_transfer", "bank_name": "ธนาคารตัวอย่าง ก"})
slip = db.query_one("SELECT s.transaction_no, s.payer_name, s.payee_name, s.amount FROM transfer_slip s JOIN payment y ON y.payment_id = s.payment_id WHERE y.order_id = :o", o=oid2)
check("ชำระด้วยการโอน: payment + transfer_slip", r.status_code == 302 and slip is not None and slip["amount"] == 10, str(slip))
check("มี payment เฉพาะคำสั่งซื้อจริง ไม่มีของแถว rejected", scalar(
    "SELECT COUNT(*) FROM payment y JOIN orders o ON o.order_id = y.order_id WHERE o.status = 'rejected'") == 0)

print("\n--- สต็อกลดลงหลังออกใบสั่งยา และยาหลายล็อต (ปฏิเสธตอนสั่งซื้อ) ---")
# ยา A เหลือ 13 : บรรทัดที่ 1 (ลอราทาดีน 5) หักได้ แล้วบรรทัดที่ 2 (ยา A 15) ไม่พอ
rx3 = consult(3, 2, [(2, 5), (1, 15)])              # ทั้งคู่ว่าง เภสัชกร 2 ได้ห้องล่าสุดนานกว่า
rejected_order(3, rx3, "ยา A (พาราเซตามอล 500 mg) คงเหลือ 13 สั่ง 15 ไม่ได้", "คนไข้ 3 สั่งซื้อเกินคงเหลือ")
# ลอราทาดีนเหลือ 90 + 200 = 290 : สั่ง 250 ยอดรวมพอ แต่จ่ายจากล็อตเดียวต่อรายการ และไม่มีล็อตใดมีถึง 250
rx4 = consult(2, 1, [(2, 250)])
rejected_order(2, rx4, "ลอราทาดีน 10 mg คงเหลือรวม 290 แต่ไม่มีล็อตเดียวที่มีจำนวนพอสำหรับ 250 (ล็อตที่มากที่สุดมี 200)",
               "ยาหลายล็อต ยอดรวมพอแต่ล็อตเดียวไม่พอ")
rejected_order(2, rx4, "ลอราทาดีน 10 mg คงเหลือรวม 290 แต่ไม่มีล็อตเดียวที่มีจำนวนพอสำหรับ 250 (ล็อตที่มากที่สุดมี 200)",
               "กดสั่งซ้ำทั้งที่สต็อกยังไม่พอ (rejected แถวที่ 2 ของใบสั่งยาเดิม)")
check("ใบสั่งยาเดียวมีแถว rejected ได้หลายแถว", scalar(
    "SELECT COUNT(*) FROM orders WHERE prescription_id = :r AND status = 'rejected'", r=rx4) == 2)

print("\n=== รอบที่ 3 : คิวรอจริง, VIP แซงคิว, จับคู่ต่อเมื่อห้องว่าง ===")
check(f"เภสัชกรถือห้องเปิดได้คนละ {tx.MAX_OPEN_CHATS} ห้อง และตอนนี้ไม่มีห้องเปิด", tx.MAX_OPEN_CHATS == 1 and open_chats() == {})
chat_a = request(1, 2)                              # ทั้งคู่ว่าง เภสัชกร 2 ได้ห้องล่าสุดนานกว่า
chat_b = request(2, 1)                              # เหลือเภสัชกร 1 คนเดียวที่ว่าง
check("เภสัชกรเต็มทั้ง 2 คน", open_chats() == {1: 1, 2: 1}, str(open_chats()))

r = client.post("/patient/3/queue")                 # คนไข้ 3 (ทั่วไป) ต้องรอ
info = latest(3)
check("คนไข้ 3: ทุกคนเต็ม -> คิว waiting (รอจับคู่) ไม่สร้างห้อง", r.status_code == 302 and info["queue"] == "waiting" and info["chat_id"] is None, str(info))
home = client.get("/patient/3").get_data(as_text=True)
check("หน้าคนไข้ 3 แสดง 'รอจับคู่' ลำดับที่ 1 (รอทั้งหมด 1 คิว)", "รอจับคู่" in home and "ลำดับที่ 1 ในคิว" in home
      and "รอจับคู่ทั้งหมด 1 คิว" in home and position(3) == 1)

r = client.post("/patient/4/queue")                 # คนไข้ 4 (VIP) มาทีหลัง
info = latest(4)
check("คนไข้ 4 (VIP): รอจับคู่เช่นกัน", info["queue"] == "waiting" and info["chat_id"] is None
      and scalar("SELECT member_type FROM consult_queue WHERE patient_id = 4") == "vip", str(info))
check("VIP แซงคิว: คนไข้ 4 ลำดับที่ 1, คนไข้ 3 ถูกเลื่อนเป็นลำดับที่ 2 (ค่าจาก polling)", position(4) == 1 and position(3) == 2,
      f"(VIP={position(4)}, ทั่วไป={position(3)})")
home = client.get("/patient/3").get_data(as_text=True)
check("หน้าคนไข้ 3 อัปเดตเป็นลำดับที่ 2 (รอทั้งหมด 2 คิว)", "ลำดับที่ 2 ในคิว" in home and "รอจับคู่ทั้งหมด 2 คิว" in home)
check("คนไข้ที่มีคิวค้างขอซ้ำไม่ได้", "มีคิวที่ยังไม่เสร็จ" in client.post("/patient/3/queue").get_data(as_text=True))
home = client.get("/pharmacist/1").get_data(as_text=True)
check("หน้าเภสัชกร: รายการห้องรอตอบกลับ + ตัวนับเวลา ไม่มีปุ่มรับคิว",
      'class="countdown' in home and "รับคิว" not in home and "ห้องแชทที่รอตอบกลับ (1)" in home)

reply(2, chat_a)
r = close(2, chat_a)                                # เภสัชกร 2 ปิดห้อง -> คิวถัดไป (VIP) ได้ห้องอัตโนมัติ
info4, info3 = latest(4), latest(3)
check("ปิดห้อง -> VIP (คนไข้ 4) ได้ห้องกับเภสัชกร 2 อัตโนมัติ ใน Transaction เดียวกัน", r.status_code == 302
      and info4["queue"] == "in_progress" and info4["pharmacist_id"] == 2 and info4["chat"] == "open"
      and chat_state(info4["chat_id"]) == "waiting_reply", str(info4))
check("คนไข้ 3 ยังรอ และเลื่อนขึ้นเป็นลำดับที่ 1", info3["queue"] == "waiting" and position(3) == 1)
left = client.get(f"/api/chat/{info4['chat_id']}/messages").get_json()["seconds_left"]
check("ตัวนับ 10 นาทีของห้องใหม่เริ่มตอนจับคู่", 590 <= left <= 600, f"(เหลือ {left} วินาที)")
check("ไม่มีเภสัชกรถือเกิน 1 ห้อง", open_chats() == {1: 1, 2: 1}, str(open_chats()))

check("ยังไม่ครบ 10 นาที: ระบบไม่ปิดห้องเอง", chat_state(chat_b) == "waiting_reply")
r = client.post(f"/pharmacist/1/chat/{chat_b}/expire")      # ปุ่มทดสอบ: เภสัชกร 1 ไม่ตอบคนไข้ 2
info2, info3 = latest(2), latest(3)
check("หมดเวลา -> 'ให้คำปรึกษาไม่สำเร็จ' (chat closed, คิว cancelled)", r.status_code == 302 and info2["chat"] == "closed"
      and info2["queue"] == "cancelled" and chat_state(chat_b) == "failed", str(info2))
check("หมดเวลา -> คนไข้ 3 ที่รออยู่ได้ห้องกับเภสัชกร 1 อัตโนมัติ", info3["queue"] == "in_progress" and info3["pharmacist_id"] == 1
      and info3["chat"] == "open", str(info3))
check("ไม่มีคิวรอจับคู่เหลือ", scalar("SELECT COUNT(*) FROM consult_queue WHERE status = 'waiting'") == 0)
check("หน้าคนไข้ 2 แจ้งว่าไม่สำเร็จและขอใหม่ได้", "ให้คำปรึกษาไม่สำเร็จ" in client.get("/patient/2").get_data(as_text=True))

# หมดเวลาจริง + จับคู่ต่อ : คนไข้ 2 ขอใหม่ (ต้องรอ) แล้วย้อนเวลาเริ่มห้องของคนไข้ 3 ไป 11 นาที ให้ polling ทำงาน
client.post("/patient/2/queue")
check("คนไข้ 2 ขอใหม่: เต็มทุกคน -> รอจับคู่ ลำดับที่ 1", latest(2)["queue"] == "waiting" and position(2) == 1)
with db.connect() as conn:
    conn.cursor().execute("UPDATE chat_room SET started_at = started_at - INTERVAL '11' MINUTE WHERE chat_id = :c", c=info3["chat_id"])
    conn.commit()
client.get("/api/pharmacist/1/state")
info2 = latest(2)
check("เกิน 10 นาทีจริง: polling ปิดห้องให้ และจับคู่คนไข้ 2 กับเภสัชกร 1 ต่อทันที", chat_state(info3["chat_id"]) == "failed"
      and latest(3)["queue"] == "cancelled" and info2["queue"] == "in_progress" and info2["pharmacist_id"] == 1, str(info2))
reply(1, info2["chat_id"])
r = client.post(f"/pharmacist/1/chat/{info2['chat_id']}/expire")
check("ห้องที่เภสัชกรตอบแล้วไม่ถูกนับว่าหมดเวลา", chat_state(info2["chat_id"]) == "consulting" and "ไม่นับว่าหมดเวลา" in r.get_data(as_text=True))

print("\n=== รอบที่ 4 : ตัวนับเวลาเริ่มใหม่ทุกข้อความ (เภสัชกร 10 นาที / คนไข้ 5 นาที) ===")


def timer(chat_id):
    """(ฝ่ายที่ต้องตอบ, วินาทีที่เหลือ) ที่ API polling ส่งให้หน้าแชท"""
    data = client.get(f"/api/chat/{chat_id}/messages?after=999999").get_json()
    return data["turn"], data["seconds_left"]


def rewind(chat_id, minutes):
    """ย้อนเวลาเริ่มห้องและเวลาส่งของทุกข้อความในห้อง เพื่อจำลองว่าเวลาผ่านไปแล้ว"""
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE chat_room SET started_at = started_at - NUMTODSINTERVAL(:m, 'MINUTE') WHERE chat_id = :c", m=minutes, c=chat_id)
        cur.execute("UPDATE chat_message SET sent_at = sent_at - NUMTODSINTERVAL(:m, 'MINUTE') WHERE chat_id = :c", m=minutes, c=chat_id)
        conn.commit()


def say(chat_id, sender, text):
    return client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": sender, "content": text})


def message_count(chat_id):
    return scalar("SELECT COUNT(*) FROM chat_message WHERE chat_id = :c", c=chat_id)


# เคลียร์ห้องที่ค้างจากรอบที่ 3 ให้เภสัชกรว่างทั้งสองคน
reply(2, info4["chat_id"]); close(2, info4["chat_id"]); close(1, info2["chat_id"])
check("เริ่มรอบ: ไม่มีห้องเปิดและไม่มีคิวรอ", open_chats() == {} and scalar("SELECT COUNT(*) FROM consult_queue WHERE status = 'waiting'") == 0)

client.post("/patient/3/queue")
room_a = latest(3); chat_t1, ph_a = room_a["chat_id"], room_a["pharmacist_id"]
turn, left = timer(chat_t1)
check("ห้องใหม่ยังไม่มีข้อความ: ตาเภสัชกร นับ 10 นาทีจากเวลาสร้างห้อง", turn == "pharmacist" and 590 <= left <= 600, f"({turn}, {left} วินาที)")
rewind(chat_t1, 4)
check("เวลาผ่านไป 4 นาที: เหลือประมาณ 6 นาที", 350 <= timer(chat_t1)[1] <= 360, f"({timer(chat_t1)[1]} วินาที)")
r = say(chat_t1, "patient", "ปวดท้องค่ะ")
turn, left = timer(chat_t1)
check("คนไข้ส่งข้อความ: ตัวนับเภสัชกรเริ่มใหม่ 10 นาทีจากข้อความล่าสุดของคนไข้", r.status_code == 200 and turn == "pharmacist" and 590 <= left <= 600, f"({turn}, {left} วินาที)")

page_f = client.get(f"/pharmacist/{ph_a}/chat/{chat_t1}").get_data(as_text=True)
page_p = client.get(f"/patient/3/chat/{chat_t1}").get_data(as_text=True)
check("หน้าแชทเภสัชกร (ฝ่ายที่ต้องตอบ): 'ต้องตอบภายใน' + ปุ่มทดสอบ", 'id="reply-timer"' in page_f and "timer-mine flex" in page_f
      and ">ต้องตอบภายใน</span>" in page_f and "ทดสอบ: เภสัชกรหมดเวลา" in page_f)
check("หน้าแชทคนไข้ (อีกฝ่าย): 'รอเภสัชกรตอบกลับ' + ปุ่มทดสอบ", 'id="reply-timer"' in page_p and ">รอเภสัชกรตอบกลับ</span>" in page_p
      and "timer-mine flex" not in page_p and "ทดสอบ: เภสัชกรหมดเวลา" in page_p)

r = say(chat_t1, "pharmacist", "ปวดมากี่วันแล้วครับ")
turn, left = timer(chat_t1)
check("เภสัชกรตอบ: ตัวนับคนไข้ 5 นาทีเริ่ม", r.status_code == 200 and turn == "patient" and 290 <= left <= 300, f"({turn}, {left} วินาที)")
page_p = client.get(f"/patient/3/chat/{chat_t1}").get_data(as_text=True)
page_f = client.get(f"/pharmacist/{ph_a}/chat/{chat_t1}").get_data(as_text=True)
check("สลับฝั่ง: คนไข้เห็น 'ต้องตอบภายใน' เภสัชกรเห็น 'รอคนไข้ตอบกลับ'", ">ต้องตอบภายใน</span>" in page_p and "timer-mine flex" in page_p
      and ">รอคนไข้ตอบกลับ</span>" in page_f and "ทดสอบ: คนไข้หมดเวลา" in page_f)
home = client.get(f"/pharmacist/{ph_a}").get_data(as_text=True)
check("หน้ารายการห้อง: ห้องที่รอคนไข้ตอบไม่อยู่ในตารางรอตอบกลับ และมีตัวนับ 'รอคนไข้ตอบ'", "ห้องแชทที่รอตอบกลับ (0)" in home and "รอคนไข้ตอบ" in home)

rewind(chat_t1, 2)
check("เวลาผ่านไป 2 นาที: คนไข้เหลือประมาณ 3 นาที", 170 <= timer(chat_t1)[1] <= 180, f"({timer(chat_t1)[1]} วินาที)")
r = say(chat_t1, "patient", "2 วันแล้วค่ะ")
turn, left = timer(chat_t1)
check("คนไข้ตอบ: ตัวนับเภสัชกรรีเซ็ตเป็น 10 นาที", r.status_code == 200 and turn == "pharmacist" and 590 <= left <= 600, f"({turn}, {left} วินาที)")
home = client.get(f"/pharmacist/{ph_a}").get_data(as_text=True)
check("หน้ารายการห้อง: ห้องระหว่างปรึกษาที่รอเภสัชกรตอบ กลับมาอยู่ในตารางรอตอบกลับพร้อมตัวนับ",
      "ห้องแชทที่รอตอบกลับ (1)" in home and chat_state(chat_t1) == "consulting" and re.search(r'class="countdown" data-seconds="(59\d|600)"', home) is not None)

print("\n--- หมดเวลา: ข้อความถูกปฏิเสธฝั่งเซิร์ฟเวอร์ และคิวถัดไปได้ห้อง ---")
client.post("/patient/1/queue")
room_b = latest(1); chat_t2, ph_b = room_b["chat_id"], room_b["pharmacist_id"]
client.post("/patient/2/queue"); client.post("/patient/4/queue")
check("เภสัชกรเต็มทั้งสองคน มีคิวรอ 2 คิว (คนไข้ 2 ทั่วไป, คนไข้ 4 VIP)", {ph_a, ph_b} == {1, 2}
      and latest(2)["queue"] == "waiting" and latest(4)["queue"] == "waiting" and position(4) == 1 and position(2) == 2)

rewind(chat_t1, 11)                                  # เภสัชกร ph_a ไม่ตอบคนไข้ 3 เกิน 10 นาที
before_msgs = message_count(chat_t1)
r = say(chat_t1, "pharmacist", "ขออภัยที่ตอบช้าครับ")
info = latest(3)
check("เภสัชกรส่งหลังเกิน 10 นาที: เซิร์ฟเวอร์ปฏิเสธ (409) ข้อความไม่ถูกบันทึก", r.status_code == 409
      and "เภสัชกรไม่ได้ตอบภายใน 10 นาที" in r.get_json()["error"] and message_count(chat_t1) == before_msgs, r.get_json()["error"])
check("เภสัชกรหมดเวลา -> 'ให้คำปรึกษาไม่สำเร็จ' (chat closed, คิว cancelled)", info["chat"] == "closed" and info["queue"] == "cancelled"
      and chat_state(chat_t1) == "failed", str(info))
info4 = latest(4)
check("หมดเวลาแล้วคิวถัดไป (VIP คนไข้ 4) ได้ห้องกับเภสัชกรคนเดิมใน Transaction เดียวกัน", info4["queue"] == "in_progress"
      and info4["pharmacist_id"] == ph_a and info4["chat"] == "open" and latest(2)["queue"] == "waiting" and position(2) == 1, str(info4))
r = say(chat_t1, "patient", "ยังอยู่ไหมคะ")
check("ห้องที่หมดเวลาแล้ว ส่งข้อความต่อไม่ได้ทั้งสองฝ่าย", r.status_code == 409 and message_count(chat_t1) == before_msgs, r.get_json()["error"])

say(chat_t2, "pharmacist", "สวัสดีครับ มีอาการอะไรครับ")   # ตาคนไข้ 1
rewind(chat_t2, 6)                                   # คนไข้ 1 ไม่ตอบเกิน 5 นาที
before_msgs = message_count(chat_t2)
r = say(chat_t2, "patient", "ขอโทษค่ะ เพิ่งเห็น")
info = latest(1)
check("คนไข้ส่งหลังเกิน 5 นาที: เซิร์ฟเวอร์ปฏิเสธ (409) ข้อความไม่ถูกบันทึก", r.status_code == 409
      and "คนไข้ไม่ได้ตอบภายใน 5 นาที" in r.get_json()["error"] and message_count(chat_t2) == before_msgs, r.get_json()["error"])
check("คนไข้หมดเวลา -> 'ปิดห้องแชทแล้ว' (chat closed, คิว completed)", info["chat"] == "closed" and info["queue"] == "completed"
      and chat_state(chat_t2) == "closed", str(info))
info2 = latest(2)
check("คนไข้หมดเวลาแล้วคิวถัดไป (คนไข้ 2) ได้ห้องกับเภสัชกรที่ว่างลง", info2["queue"] == "in_progress" and info2["pharmacist_id"] == ph_b
      and info2["chat"] == "open", str(info2))
r = say(chat_t2, "pharmacist", "ยังอยู่ไหมครับ")
check("ห้องที่คนไข้หมดเวลาแล้ว เภสัชกรก็ส่งต่อไม่ได้", r.status_code == 409 and message_count(chat_t2) == before_msgs)

print("\n--- ปุ่มทดสอบหมดเวลา ทั้งสองฝั่ง และการหมดเวลาจริงผ่าน polling ---")
chat_v, chat_g = info4["chat_id"], info2["chat_id"]  # ห้องของคนไข้ 4 (กับ ph_a) และคนไข้ 2 (กับ ph_b) ยังไม่มีข้อความ
r = client.post(f"/patient/4/chat/{chat_v}/expire", data={"side": "patient"})
check("ปุ่มทดสอบ 'คนไข้หมดเวลา' ตอนเป็นตาเภสัชกร: ไม่มีผล", r.status_code == 302 and latest(4)["chat"] == "open")
say(chat_v, "pharmacist", "สวัสดีครับ")
r = client.post(f"/patient/4/chat/{chat_v}/expire", data={"side": "patient"})
info = latest(4)
check("ปุ่มทดสอบ 'คนไข้หมดเวลา' (กดจากฝั่งคนไข้): ห้องปิดเป็น 'ปิดห้องแชทแล้ว'", r.status_code == 302 and r.location.endswith(f"/patient/4/chat/{chat_v}")
      and info["chat"] == "closed" and info["queue"] == "completed" and chat_state(chat_v) == "closed", str(info))
r = client.post(f"/pharmacist/{ph_b}/chat/{chat_g}/expire", data={"side": "pharmacist"})
info = latest(2)
check("ปุ่มทดสอบ 'เภสัชกรหมดเวลา' (กดจากหน้าแชทเภสัชกร): 'ให้คำปรึกษาไม่สำเร็จ'", r.status_code == 302 and info["chat"] == "closed"
      and info["queue"] == "cancelled" and chat_state(chat_g) == "failed", str(info))

client.post("/patient/3/queue")
chat_w = latest(3)["chat_id"]; ph_w = latest(3)["pharmacist_id"]
say(chat_w, "pharmacist", "สวัสดีครับ")
rewind(chat_w, 6)
client.get(f"/api/pharmacist/{ph_w}/state")          # polling ของหน้ารายการห้อง
check("คนไข้เกิน 5 นาทีจริง: polling ปิดห้องให้อัตโนมัติเป็น 'ปิดห้องแชทแล้ว'", chat_state(chat_w) == "closed" and latest(3)["queue"] == "completed")
check("จบรอบ: ไม่มีห้องเปิดค้าง", open_chats() == {})

print("\n=== ตรวจรวม : แถว rejected ไม่ปนกับคำสั่งซื้อจริง ===")
check("แถว rejected ทุกแถวไม่มี order_detail / payment / receipt", scalar("""
    SELECT COUNT(*) FROM orders o
    WHERE  o.status = 'rejected'
    AND   (EXISTS (SELECT 1 FROM order_detail d WHERE d.order_id = o.order_id)
        OR EXISTS (SELECT 1 FROM payment y      WHERE y.order_id = o.order_id)
        OR EXISTS (SELECT 1 FROM receipt r      WHERE r.order_id = o.order_id))""") == 0)
check("ใบสั่งยาแต่ละใบมีคำสั่งซื้อจริง (ไม่ใช่ rejected) ไม่เกิน 1 ใบ", scalar("""
    SELECT NVL(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM orders WHERE status <> 'rejected' GROUP BY prescription_id)""") == 1)
statuses = {r_["status"]: r_["n"] for r_ in db.query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status")}
check("สรุป orders: paid 2 (คนไข้ 1, 2) + rejected 5", statuses == {"paid": 2, "rejected": 5}, str(statuses))
for pid in (1, 2, 3, 4):
    page = client.get(f"/patient/{pid}/orders").get_data(as_text=True)
    home = client.get(f"/patient/{pid}").get_data(as_text=True)
    check(f"คนไข้ {pid}: หน้าประวัติและหน้าหลักไม่มีรายการ rejected ไปโผล่เป็น 'รอชำระเงิน' หรือมีปุ่มชำระเงิน",
          "รอชำระเงิน" not in page and ">ชำระเงิน</a>" not in page and "รอชำระเงิน" not in home)

print("\n=== หน้าจออื่น ๆ ===")
for url in ["/", "/patient/1", "/patient/2", "/patient/3", "/patient/4", "/pharmacist/1", "/pharmacist/2",
            "/pharmacist/1/stock", "/api/patient/1/state", "/api/pharmacist/1/state", "/patient/1/orders", "/patient/3/orders",
            f"/patient/3/prescription/{rx3}", f"/pharmacist/1/chat/{chat_b}", f"/patient/2/chat/{chat_b}"]:
    check(f"GET {url}", client.get(url).status_code == 200)

print(f"\nสรุป: {'ผ่านทั้งหมด' if failed == 0 else f'ไม่ผ่าน {failed} ข้อ'}")
sys.exit(1 if failed else 0)
