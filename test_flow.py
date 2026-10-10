"""ทดสอบ 1 รอบเต็ม + กรณีปฏิเสธ + คิวรอ/VIP + ตัวนับเวลาตอบกลับ ผ่าน route ของ Flask กับฐานข้อมูล Oracle จริง

รัน reset.bat ก่อน แล้วสั่ง:  python test_flow.py
(สคริปต์นี้สร้างข้อมูลทดสอบจริงในฐานข้อมูล ต้องรัน reset.bat อีกครั้งก่อน Demo)
คนไข้ 1-3 เป็นสมาชิกทั่วไป คนไข้ 4 เป็น VIP, เภสัชกร 1-2 ถือห้องเปิดได้คนละ 1 ห้อง
"""
import re
import sys

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


def stock(batch_id):
    return scalar("SELECT quantity FROM drug_batch WHERE batch_id = :b", b=batch_id)


def snapshot():
    """จำนวนแถวของตารางธุรกรรม + สต็อกทุกล็อต ใช้เทียบก่อน/หลังกรณีปฏิเสธ"""
    tables = ["prescription", "prescription_detail", "orders", "order_detail", "payment", "qr_code",
              "transfer_slip", "receipt", "receipt_detail"]
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


def prescribe(phid, chat_id, lines):
    r = client.post(f"/pharmacist/{phid}/chat/{chat_id}/prescription", data=rx_form(lines))
    rx_id = scalar("SELECT MAX(prescription_id) FROM prescription WHERE chat_id = :c", c=chat_id)
    n = scalar("SELECT COUNT(*) FROM prescription_detail WHERE prescription_id = :r", r=rx_id)
    check("ออกใบสั่งยาขณะห้องยังเปิด", r.status_code == 302 and n == len(lines) and chat_state(chat_id) == "consulting",
          f"rx_id={rx_id} lines={n}")
    return rx_id


def reply(phid, chat_id):
    client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "pharmacist", "content": "สวัสดีครับ มีอาการอะไรครับ"})


def close(phid, chat_id):
    return client.post(f"/pharmacist/{phid}/chat/{chat_id}/close")


def rejected_prescription(phid, chat_id, lines, message, label):
    before = snapshot()
    r = client.post(f"/pharmacist/{phid}/chat/{chat_id}/prescription", data=rx_form(lines))
    html = r.get_data(as_text=True)
    check(label, r.status_code == 200 and "ระบบปฏิเสธรายการ:" in html and message in html and snapshot() == before,
          "(ข้อความถูกต้อง, ไม่มีแถวใหม่ใน prescription/prescription_detail)")


print("=== รอบที่ 1 : ฟังก์ชันหลักครบวงจร (คนไข้ 1) ===")
check("ก่อนทำ: ยา A = 20", stock(1) == 20, f"(จริง {stock(1)})")
check("seed: เภสัชกร 2 คนร้านเดียวกัน, คนไข้ 4 คน, VIP 1 คน",
      scalar("SELECT COUNT(*) FROM pharmacist WHERE pharmacy_id = 1") == 2
      and scalar("SELECT COUNT(*) FROM patient") == 4 and scalar("SELECT COUNT(*) FROM patient WHERE is_vip = 1") == 1)
chat_id = request(1, 1)
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
check("dropdown: ยาที่คงเหลือ 0 เลือกไม่ได้ (disabled) ยาอื่นเลือกได้",
      '<option value="6" disabled>คลอร์เฟนิรามีน 4 mg (หมด)</option>' in page
      and '<option value="1" >ยา A (พาราเซตามอล 500 mg) (เหลือ 20)</option>' in page)

print("\n--- ด่านที่ 1 : ตรวจสต็อกตอนเภสัชกรออกใบสั่งยา ---")
rejected_prescription(1, chat_id, [(6, 1)], "คลอร์เฟนิรามีน 4 mg คงเหลือ 0 ออกใบสั่งยาไม่ได้", "ยาคงเหลือ 0 -> ปฏิเสธ")
rejected_prescription(1, chat_id, [(1, 25)], "ยา A (พาราเซตามอล 500 mg) คงเหลือ 20 ออกใบสั่งยาได้ไม่เกินนี้", "สั่งเกินคงเหลือ -> ปฏิเสธ")
rejected_prescription(1, chat_id, [(2, 10), (1, 25)], "ยา A (พาราเซตามอล 500 mg) คงเหลือ 20 ออกใบสั่งยาได้ไม่เกินนี้",
                      "รายการแรกพอ รายการที่สองเกิน -> ปฏิเสธทั้งใบ")
rejected_prescription(1, chat_id, [(1, 15), (1, 15)], "ยา A (พาราเซตามอล 500 mg) คงเหลือ 20 ออกใบสั่งยาได้ไม่เกินนี้",
                      "ยาตัวเดียวกันสองแถวรวมกันเกิน -> ปฏิเสธ")
r = client.post(f"/pharmacist/1/chat/{chat_id}/prescription", data=rx_form([(1, 25)]))
check("ฟอร์มคืนค่าที่กรอกไว้หลังถูกปฏิเสธ", 'value="25"' in r.get_data(as_text=True))

rx_id = prescribe(1, chat_id, [(2, 10), (1, 2)])     # ลอราทาดีน 10, ยา A 2
r = client.post(f"/pharmacist/1/chat/{chat_id}/prescription", data=rx_form([(1, 1)]))
check("ออกใบสั่งยาซ้ำในห้องเดิมไม่ได้", "ออกใบสั่งยาไปแล้ว" in r.get_data(as_text=True))
r = close(1, chat_id)
info = latest(1)
check("เภสัชกรปิดห้องแชท -> chat closed, คิว completed", r.status_code == 302 and info["chat"] == "closed"
      and info["queue"] == "completed" and chat_state(chat_id) == "closed", str(info))
r = client.post(f"/api/chat/{chat_id}/messages", json={"sender_type": "patient", "content": "ขอบคุณค่ะ"})
check("ห้องปิดแล้วส่งข้อความไม่ได้", r.status_code == 409)

check("หน้าใบสั่งยา", client.get(f"/patient/1/prescription/{rx_id}").status_code == 200)
r = client.post(f"/patient/1/prescription/{rx_id}/order", data={"shipping_address": "12/3 หมู่ 4 ขอนแก่น 40000"})
order = db.query_one("SELECT order_id, status FROM orders WHERE prescription_id = :r", r=rx_id)
check("สั่งซื้อ: orders = pending_payment", r.status_code == 302 and order and order["status"] == "pending_payment", str(order))
oid = order["order_id"]
details = db.query("SELECT line_no, drug_name, quantity, unit_price FROM order_detail WHERE order_id = :o ORDER BY line_no", o=oid)
check("order_detail snapshot ชื่อ/ราคา", [(d["drug_name"], d["quantity"], d["unit_price"]) for d in details]
      == [("ลอราทาดีน 10 mg", 10, 5), ("ยา A (พาราเซตามอล 500 mg)", 2, 2)], str(details))
check("ตัดสต็อก: ยา A = 18", stock(1) == 18, f"(จริง {stock(1)})")
check("FEFO: ลอราทาดีนตัดล็อตหมดอายุก่อน (100->90) ล็อตหลังคงเดิม (200)", stock(2) == 90 and stock(3) == 200, f"(จริง {stock(2)}, {stock(3)})")
batches = [r_["batch_id"] for r_ in db.query("SELECT batch_id FROM prescription_detail WHERE prescription_id = :r ORDER BY line_no", r=rx_id)]
check("prescription_detail.batch_id ถูกบันทึก", batches == [2, 1], str(batches))

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
check("ประวัติคำสั่งซื้อแสดงสถานะชำระเงินแล้ว", "ชำระเงินแล้ว" in page and rc["receipt_no"] in page)
before = snapshot()
r = client.post(f"/patient/1/order/{oid}/pay", data={"method": "bank_transfer", "bank_name": "ธนาคารตัวอย่าง ก"})
check("จ่ายซ้ำถูกปฏิเสธ ข้อมูลไม่เปลี่ยน", "ชำระเงินแล้ว" in r.get_data(as_text=True) and snapshot() == before)

print("\n=== รอบที่ 2 : ด่านที่ 2 ตรวจสต็อกตอนสั่งซื้อ (สต็อกลดลงหลังออกใบสั่งยา) ===")
# ยา A เหลือ 18 : ออกใบสั่งยา 2 ใบ ใบละ 10 (ผ่านด่านที่ 1 ทั้งคู่) แล้วคนแรกสั่งซื้อก่อน
chat2 = request(2, 2)                               # เภสัชกร 2 ยังไม่เคยได้ห้อง
reply(2, chat2)
rx2 = prescribe(2, chat2, [(1, 10)])
close(2, chat2)
chat3 = request(3, 1)                               # ทั้งคู่ว่าง เภสัชกร 1 ได้ห้องล่าสุดนานกว่า
reply(1, chat3)
rx3 = prescribe(1, chat3, [(2, 5), (1, 10)])        # ลอราทาดีน 5 + ยา A 10
close(1, chat3)
r = client.post(f"/patient/2/prescription/{rx2}/order", data={"shipping_address": "88/9 อุดรธานี 41000"})
oid2 = scalar("SELECT MAX(order_id) FROM orders WHERE prescription_id = :r", r=rx2)
check("คนไข้ 2 สั่งซื้อก่อน: ยา A = 8", r.status_code == 302 and stock(1) == 8, f"(จริง {stock(1)})")
before = snapshot()
r = client.post(f"/patient/3/prescription/{rx3}/order", data={"shipping_address": "7 หมู่ 2 ขอนแก่น 40150"})
html = r.get_data(as_text=True)
check("คนไข้ 3 สั่งซื้อทีหลัง: ระบบปฏิเสธ", r.status_code == 200 and "ยา A (พาราเซตามอล 500 mg) คงเหลือ 8 สั่งได้ไม่เกินนี้" in html)
after = snapshot()
check("ROLLBACK: จำนวนแถวและสต็อกทุกล็อตไม่เปลี่ยน (รวมลอราทาดีนที่ถูกหักไปก่อนในบรรทัดที่ 1)", after == before,
      f"\n   ก่อน {before}\n   หลัง {after}")
check("ไม่มีคำสั่งซื้อของใบสั่งยานี้", scalar("SELECT COUNT(*) FROM orders WHERE prescription_id = :r", r=rx3) == 0)
r = client.post(f"/patient/2/order/{oid2}/pay", data={"method": "bank_transfer", "bank_name": "ธนาคารตัวอย่าง ก"})
slip = db.query_one("SELECT s.transaction_no, s.payer_name, s.payee_name, s.amount FROM transfer_slip s JOIN payment y ON y.payment_id = s.payment_id WHERE y.order_id = :o", o=oid2)
check("ชำระด้วยการโอน: payment + transfer_slip", r.status_code == 302 and slip is not None and slip["amount"] == 20, str(slip))

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

print("\n=== หน้าจออื่น ๆ ===")
for url in ["/", "/patient/1", "/patient/2", "/patient/3", "/patient/4", "/pharmacist/1", "/pharmacist/2",
            "/pharmacist/1/stock", "/api/patient/1/state", "/api/pharmacist/1/state",
            f"/patient/3/prescription/{rx3}", f"/pharmacist/1/chat/{chat_b}", f"/patient/2/chat/{chat_b}"]:
    check(f"GET {url}", client.get(url).status_code == 200)

print(f"\nสรุป: {'ผ่านทั้งหมด' if failed == 0 else f'ไม่ผ่าน {failed} ข้อ'}")
sys.exit(1 if failed else 0)
