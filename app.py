"""ระบบ Demo ร้านขายยาออนไลน์ (Flask + python-oracledb)

ไม่มีระบบ login : บทบาทอยู่ใน URL (/patient/<id>/..., /pharmacist/<id>/...)
จึงเปิดหน้าต่างคนไข้และเภสัชกรพร้อมกันในเบราว์เซอร์เดียวได้
ไฟล์นี้มีเฉพาะหน้าจอและ SELECT ส่วนที่เขียนข้อมูลอยู่ใน transactions.py
"""
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import db
import transactions as tx
from transactions import (CHAT_STATE_SQL, QUEUE_ORDER_SQL, SECONDS_LEFT_SQL, SYMPTOM_NOTE_MAX, TURN_SQL,
                          DemoError, RejectedError)

app = Flask(__name__)

STATUS_TH = {
    # สถานะคิว (consult_queue.status)
    "waiting": "รอเภสัชกรรับเคส", "in_progress": "เภสัชกรรับเคสแล้ว", "completed": "เสร็จสิ้น", "cancelled": "ยกเลิก",
    # สถานะห้องแชทตามรายงาน (คำนวณจาก chat_room.status + ข้อความ + สถานะคิว ดู CHAT_STATE_SQL)
    "waiting_reply": "รอตอบกลับ", "consulting": "ระหว่างปรึกษา",
    "failed": "ให้คำปรึกษาไม่สำเร็จ", "closed": "ปิดห้องแชทแล้ว", "open": "เปิด",
    "pending_payment": "รอชำระเงิน", "paid": "ชำระเงินแล้ว", "preparing": "กำลังจัดยา", "rejected": "ถูกปฏิเสธ",
    "shipped": "จัดส่งแล้ว", "success": "สำเร็จ", "qr_code": "QR Code", "bank_transfer": "โอนเงิน",
}


@app.template_filter("th")
def th(value):
    return STATUS_TH.get(value, value)


@app.template_filter("baht")
def baht(value):
    return f"{float(value or 0):,.2f}"


# ---------------------------------------------------------------------
# ตัวช่วยอ่านข้อมูล
# ---------------------------------------------------------------------
def get_patient(patient_id):
    patient = db.query_one("""
        SELECT patient_id, first_name, last_name, first_name || ' ' || last_name AS full_name
        FROM   patient WHERE patient_id = :id AND deleted_at IS NULL""", id=patient_id)
    return patient or abort(404)


def get_pharmacist(pharmacist_id):
    pharmacist = db.query_one("""
        SELECT f.pharmacist_id, f.first_name || ' ' || f.last_name AS full_name,
               f.pharmacy_id, ph.name AS pharmacy_name
        FROM   pharmacist f JOIN pharmacy ph ON ph.pharmacy_id = f.pharmacy_id
        WHERE  f.pharmacist_id = :id AND f.deleted_at IS NULL""", id=pharmacist_id)
    return pharmacist or abort(404)


def get_chat(chat_id):
    """ห้องแชท + คิว + ชื่อทั้งสองฝ่าย + ใบสั่งยาของห้องนี้ (ถ้าออกแล้ว)"""
    chat = db.query_one(f"""
        SELECT c.chat_id, c.status, c.pharmacist_id, q.patient_id, q.queue_no,
               {CHAT_STATE_SQL} AS state, {TURN_SQL} AS turn, {SECONDS_LEFT_SQL} AS seconds_left,
               p.first_name || ' ' || p.last_name AS patient_name,
               f.first_name || ' ' || f.last_name AS pharmacist_name,
               ph.name AS pharmacy_name, r.prescription_id
        FROM   chat_room c
               JOIN consult_queue q ON q.queue_id = c.queue_id
               JOIN patient p       ON p.patient_id = q.patient_id
               JOIN pharmacist f    ON f.pharmacist_id = c.pharmacist_id
               JOIN pharmacy ph     ON ph.pharmacy_id = q.pharmacy_id
               LEFT JOIN prescription r ON r.chat_id = c.chat_id
        WHERE  c.chat_id = :id""", id=chat_id)
    return chat or abort(404)


def get_prescription(prescription_id, patient_id):
    # คำสั่งซื้อของใบสั่งยา = คำสั่งซื้อที่ไม่ใช่ rejected (มีได้ใบเดียว ตาม uq_orders_prescription)
    # rejected_count = จำนวนครั้งที่ใบสั่งยานี้เคยถูกระบบปฏิเสธตอนสั่งซื้อ
    rx = db.query_one("""
        SELECT r.prescription_id, r.chat_id, TO_CHAR(r.prescribed_date, 'DD/MM/YYYY') AS prescribed_date,
               r.prescribed_time, f.first_name || ' ' || f.last_name AS pharmacist_name,
               ph.name AS pharmacy_name, o.order_id, o.status AS order_status,
               (SELECT COUNT(*) FROM orders x
                WHERE  x.prescription_id = r.prescription_id AND x.status = 'rejected') AS rejected_count
        FROM   prescription r
               JOIN pharmacist f    ON f.pharmacist_id = r.pharmacist_id
               JOIN chat_room c     ON c.chat_id = r.chat_id
               JOIN consult_queue q ON q.queue_id = c.queue_id
               JOIN pharmacy ph     ON ph.pharmacy_id = q.pharmacy_id
               LEFT JOIN orders o   ON o.prescription_id = r.prescription_id AND o.status <> 'rejected'
        WHERE  r.prescription_id = :rx_id AND r.patient_id = :patient_id""",
        rx_id=prescription_id, patient_id=patient_id)
    if rx is None:
        abort(404)
    rx["lines"] = db.query("""
        SELECT d.line_no, g.name AS drug_name, d.strength, d.dosage, d.usage_note, d.quantity,
               g.price, d.quantity * g.price AS line_total
        FROM   prescription_detail d JOIN drug g ON g.drug_id = d.drug_id
        WHERE  d.prescription_id = :rx_id
        ORDER  BY d.line_no""", rx_id=prescription_id)
    rx["total"] = sum(line["line_total"] for line in rx["lines"])
    return rx


def get_order(order_id, patient_id):
    order = db.query_one("""
        SELECT o.order_id, o.status, o.shipping_address, o.prescription_id,
               TO_CHAR(o.ordered_at, 'DD/MM/YYYY HH24:MI') AS ordered_at
        FROM   orders o
        WHERE  o.order_id = :order_id AND o.patient_id = :patient_id""",
        order_id=order_id, patient_id=patient_id)
    if order is None:
        abort(404)
    order["lines"] = db.query("""
        SELECT line_no, drug_name, quantity, unit_price, quantity * unit_price AS line_total
        FROM   order_detail WHERE order_id = :order_id ORDER BY line_no""", order_id=order_id)
    order["total"] = sum(line["line_total"] for line in order["lines"])
    return order


def default_address(patient_id):
    """ประกอบที่อยู่เริ่มต้นจากตาราง address เป็นข้อความ (คนไข้แก้ไขก่อนสั่งซื้อได้)"""
    a = db.query_one("""
        SELECT house_no, moo, soi, road, subdistrict, district, province, postal_code
        FROM   address WHERE patient_id = :id
        ORDER  BY is_default DESC, address_id FETCH FIRST 1 ROW ONLY""", id=patient_id)
    if a is None:
        return ""
    parts = [a["house_no"],
             f"หมู่ {a['moo']}" if a["moo"] else None,
             f"ซอย{a['soi']}" if a["soi"] else None,
             f"ถนน{a['road']}" if a["road"] else None,
             f"ตำบล{a['subdistrict']}", f"อำเภอ{a['district']}",
             f"จังหวัด{a['province']}", a["postal_code"]]
    return " ".join(p for p in parts if p)


def patient_home_data(patient_id):
    """การขอคำปรึกษาครั้งล่าสุด (คิว + ห้องแชท + สถานะห้องแชท) และใบสั่งยาทั้งหมดของคนไข้"""
    queue = db.query_one(f"""
        SELECT q.queue_id, q.queue_no, q.status, q.member_type, q.pharmacy_id, q.symptom_note, c.chat_id,
               f.first_name || ' ' || f.last_name AS pharmacist_name,
               CASE WHEN c.chat_id IS NOT NULL THEN {CHAT_STATE_SQL} END AS chat_state
        FROM   consult_queue q
               LEFT JOIN chat_room c  ON c.queue_id = q.queue_id
               LEFT JOIN pharmacist f ON f.pharmacist_id = c.pharmacist_id
        WHERE  q.patient_id = :id
        ORDER  BY q.queue_id DESC FETCH FIRST 1 ROW ONLY""", id=patient_id)
    if queue and queue["status"] == "waiting":
        # ลำดับที่ในคิวจริง : นับเฉพาะคิวที่ยัง waiting ของร้านเดียวกัน เรียง VIP ก่อน แล้วตามเวลาเข้าคิว
        queue.update(db.query_one(f"""
            SELECT w.position, w.waiting_total
            FROM  (SELECT q.queue_id,
                          ROW_NUMBER() OVER (ORDER BY {QUEUE_ORDER_SQL}) AS position,
                          COUNT(*) OVER () AS waiting_total
                   FROM   consult_queue q
                   WHERE  q.status = 'waiting' AND q.pharmacy_id = :pharmacy_id) w
            WHERE  w.queue_id = :queue_id""",
            pharmacy_id=queue["pharmacy_id"], queue_id=queue["queue_id"]) or {})
    prescriptions = db.query("""
        SELECT r.prescription_id, r.chat_id, TO_CHAR(r.prescribed_date, 'DD/MM/YYYY') AS prescribed_date,
               r.prescribed_time, f.first_name || ' ' || f.last_name AS pharmacist_name,
               o.order_id, o.status AS order_status,
               (SELECT COUNT(*) FROM orders x
                WHERE  x.prescription_id = r.prescription_id AND x.status = 'rejected') AS rejected_count
        FROM   prescription r
               JOIN pharmacist f  ON f.pharmacist_id = r.pharmacist_id
               LEFT JOIN orders o ON o.prescription_id = r.prescription_id AND o.status <> 'rejected'
        WHERE  r.patient_id = :id
        ORDER  BY r.prescription_id DESC""", id=patient_id)
    return queue, prescriptions


def waiting_queue(pharmacy_id):
    """คิวที่รอเภสัชกรรับเคส "ทั้งหมด" ของร้าน : VIP ก่อน แล้วตามเวลาที่เข้าคิว
    waited_seconds = เวลาที่รอมาแล้ว นับจาก entered_at"""
    return db.query(f"""
        SELECT q.queue_id, q.queue_no, q.member_type, q.symptom_note,
               p.first_name || ' ' || p.last_name AS patient_name, p.chronic_disease,
               TO_CHAR(q.entered_at, 'HH24:MI:SS') AS entered_at,
               ROUND((CAST(CURRENT_TIMESTAMP AS DATE) - CAST(q.entered_at AS DATE)) * 86400) AS waited_seconds
        FROM   consult_queue q
               JOIN patient p ON p.patient_id = q.patient_id
        WHERE  q.pharmacy_id = :pharmacy_id AND q.status = 'waiting'
        ORDER  BY {QUEUE_ORDER_SQL}""", pharmacy_id=pharmacy_id)


def open_rooms(pharmacist_id):
    """ห้องแชทที่ยังเปิดอยู่ของเภสัชกร (รับได้หลายห้องพร้อมกัน) ใช้ทำรายการสลับห้องในหน้าแชท
    last_patient_message_id ใช้บอกว่าห้องไหนมีข้อความใหม่จากคนไข้ (0 = คนไข้ยังไม่ส่งข้อความ)"""
    return db.query(f"""
        SELECT c.chat_id, q.queue_no, q.member_type, p.first_name || ' ' || p.last_name AS patient_name,
               {TURN_SQL} AS turn,
               NVL((SELECT MAX(m.message_id) FROM chat_message m
                    WHERE  m.chat_id = c.chat_id AND m.sender_type = 'patient'), 0) AS last_patient_message_id
        FROM   chat_room c
               JOIN consult_queue q ON q.queue_id = c.queue_id
               JOIN patient p       ON p.patient_id = q.patient_id
        WHERE  c.pharmacist_id = :id AND c.status = 'open'
        ORDER  BY c.chat_id""", id=pharmacist_id)


def pharmacist_home_data(pharmacist):
    """ห้องแชททั้งหมดที่เภสัชกรคนนี้รับเคสไว้ : ห้องที่รอตอบกลับขึ้นก่อน"""
    return db.query(f"""
        SELECT c.chat_id, q.queue_no, p.first_name || ' ' || p.last_name AS patient_name,
               p.chronic_disease, TO_CHAR(c.started_at, 'HH24:MI:SS') AS started_at,
               c.status, {CHAT_STATE_SQL} AS state, {TURN_SQL} AS turn, {SECONDS_LEFT_SQL} AS seconds_left,
               r.prescription_id
        FROM   chat_room c
               JOIN consult_queue q ON q.queue_id = c.queue_id
               JOIN patient p       ON p.patient_id = q.patient_id
               LEFT JOIN prescription r ON r.chat_id = c.chat_id
        WHERE  c.pharmacist_id = :id
        ORDER  BY c.status DESC, c.chat_id""", id=pharmacist["pharmacist_id"])


# ---------------------------------------------------------------------
# หน้าแรก : เลือกบทบาท
# ---------------------------------------------------------------------
@app.get("/")
def index():
    patients = db.query("""
        SELECT patient_id, first_name || ' ' || last_name AS full_name, is_vip
        FROM   patient WHERE deleted_at IS NULL ORDER BY patient_id""")
    pharmacists = db.query("""
        SELECT f.pharmacist_id, f.first_name || ' ' || f.last_name AS full_name, ph.name AS pharmacy_name
        FROM   pharmacist f JOIN pharmacy ph ON ph.pharmacy_id = f.pharmacy_id
        WHERE  f.deleted_at IS NULL ORDER BY f.pharmacist_id""")
    return render_template("index.html", patients=patients, pharmacists=pharmacists)


@app.get("/enter")
def enter():
    role = request.args.get("role")
    user_id = request.args.get("id", type=int)
    if role == "patient" and user_id:
        return redirect(url_for("patient_home", pid=user_id))
    if role == "pharmacist" and user_id:
        return redirect(url_for("pharmacist_home", phid=user_id))
    return redirect(url_for("index"))


# ---------------------------------------------------------------------
# ฝั่งคนไข้
# ---------------------------------------------------------------------
def render_patient_home(pid, error=None, symptom_note=""):
    patient = get_patient(pid)
    queue, prescriptions = patient_home_data(pid)
    return render_template("patient_home.html", patient=patient, queue=queue,
                           prescriptions=prescriptions, error=error, symptom_note=symptom_note,
                           symptom_note_max=SYMPTOM_NOTE_MAX)


@app.get("/patient/<int:pid>")
def patient_home(pid):
    return render_patient_home(pid)


@app.post("/patient/<int:pid>/queue")
def patient_request_consult(pid):
    # textarea ส่งขึ้นบรรทัดใหม่เป็น \r\n : แปลงเป็น \n ก่อน เพื่อให้นับความยาวตรงกับ maxlength ของหน้าเว็บ
    symptom_note = request.form.get("symptom_note", "").replace("\r\n", "\n")
    try:
        tx.request_consult(pid, symptom_note)
    except DemoError as exc:
        return render_patient_home(pid, error=str(exc), symptom_note=symptom_note)
    return redirect(url_for("patient_home", pid=pid))


@app.get("/patient/<int:pid>/chat/<int:chat_id>")
def patient_chat(pid, chat_id):
    patient = get_patient(pid)
    chat = get_chat(chat_id)
    if chat["patient_id"] != pid:
        abort(404)
    return render_template("chat.html", role="patient", patient=patient, chat=chat)


def render_prescription(pid, rx_id, error=None, shipping_address=None):
    patient = get_patient(pid)
    rx = get_prescription(rx_id, pid)
    if shipping_address is None:
        shipping_address = default_address(pid)
    return render_template("prescription.html", patient=patient, rx=rx, error=error,
                           shipping_address=shipping_address)


@app.get("/patient/<int:pid>/prescription/<int:rx_id>")
def patient_prescription(pid, rx_id):
    return render_prescription(pid, rx_id)


@app.post("/patient/<int:pid>/prescription/<int:rx_id>/order")
def patient_place_order(pid, rx_id):
    shipping_address = request.form.get("shipping_address", "")
    try:
        order_id = tx.place_order(pid, rx_id, shipping_address)
    except RejectedError as exc:
        # ระบบปฏิเสธ (เช่น สต็อกไม่พอ) : Transaction ถูก ROLLBACK แล้ว และมีแถว orders สถานะ rejected เป็นร่องรอย
        error = str(exc)
        if exc.rejected_order_id:
            error += f" (บันทึกเป็นคำสั่งซื้อเลขที่ {exc.rejected_order_id} สถานะ “ถูกปฏิเสธ”)"
        return render_prescription(pid, rx_id, error=error, shipping_address=shipping_address)
    except DemoError as exc:
        # กรอกข้อมูลไม่ถูกต้อง (เช่น ที่อยู่ว่าง, สั่งซ้ำ) : ไม่บันทึกร่องรอย แสดงข้อความบนหน้าเดิม
        return render_prescription(pid, rx_id, error=str(exc), shipping_address=shipping_address)
    return redirect(url_for("patient_pay", pid=pid, order_id=order_id))


def render_pay(pid, order_id, error=None):
    patient = get_patient(pid)
    order = get_order(order_id, pid)
    return render_template("pay.html", patient=patient, order=order, error=error)


@app.get("/patient/<int:pid>/order/<int:order_id>/pay")
def patient_pay(pid, order_id):
    order = get_order(order_id, pid)
    if order["status"] == "rejected":
        # คำสั่งซื้อที่ถูกปฏิเสธไม่มีรายการยาและชำระเงินไม่ได้ : กลับไปหน้าประวัติคำสั่งซื้อ
        return redirect(url_for("patient_orders", pid=pid))
    if order["status"] != "pending_payment":
        return redirect(url_for("patient_receipt", pid=pid, order_id=order_id))
    return render_pay(pid, order_id)


@app.post("/patient/<int:pid>/order/<int:order_id>/pay")
def patient_pay_submit(pid, order_id):
    try:
        tx.pay_order(pid, order_id, request.form.get("method"), request.form.get("bank_name"))
    except DemoError as exc:
        return render_pay(pid, order_id, error=str(exc))
    return redirect(url_for("patient_receipt", pid=pid, order_id=order_id))


@app.get("/patient/<int:pid>/order/<int:order_id>/receipt")
def patient_receipt(pid, order_id):
    patient = get_patient(pid)
    receipt = db.query_one("""
        SELECT r.receipt_id, r.receipt_no, TO_CHAR(r.service_date, 'DD/MM/YYYY') AS service_date,
               TO_CHAR(r.issued_at, 'DD/MM/YYYY HH24:MI') AS issued_at,
               ph.name AS pharmacy_name, ph.address AS pharmacy_address, ph.license_no,
               o.order_id, o.status AS order_status, o.shipping_address,
               y.payment_id, y.method, y.status AS payment_status,
               TO_CHAR(y.paid_at, 'DD/MM/YYYY HH24:MI:SS') AS paid_at,
               s.transaction_no, s.bank_name, q.qr_id
        FROM   receipt r
               JOIN orders o    ON o.order_id = r.order_id
               JOIN pharmacy ph ON ph.pharmacy_id = r.pharmacy_id
               JOIN payment y   ON y.order_id = o.order_id
               LEFT JOIN transfer_slip s ON s.payment_id = y.payment_id
               LEFT JOIN qr_code q       ON q.payment_id = y.payment_id
        WHERE  r.order_id = :order_id AND r.patient_id = :patient_id""",
        order_id=order_id, patient_id=pid)
    if receipt is None:
        # ยังไม่มีใบเสร็จ : patient_pay ส่งต่อไปหน้าชำระเงิน หรือหน้าประวัติถ้าเป็นคำสั่งซื้อที่ถูกปฏิเสธ
        return redirect(url_for("patient_pay", pid=pid, order_id=order_id))
    lines = db.query("""
        SELECT d.line_no, g.name AS drug_name, d.dosage, d.quantity, d.unit_price, d.total_amount
        FROM   receipt_detail d JOIN drug g ON g.drug_id = d.drug_id
        WHERE  d.receipt_id = :receipt_id ORDER BY d.line_no""", receipt_id=receipt["receipt_id"])
    total = sum(line["total_amount"] for line in lines)
    return render_template("receipt.html", patient=patient, receipt=receipt, lines=lines, total=total)


@app.get("/patient/<int:pid>/orders")
def patient_orders(pid):
    patient = get_patient(pid)
    orders = db.query("""
        SELECT o.order_id, o.status, o.prescription_id, o.shipping_address,
               TO_CHAR(o.ordered_at, 'DD/MM/YYYY HH24:MI') AS ordered_at,
               (SELECT SUM(d.quantity * d.unit_price) FROM order_detail d
                WHERE  d.order_id = o.order_id) AS total,
               (SELECT LISTAGG(d.drug_name || ' x' || d.quantity, ', ')
                       WITHIN GROUP (ORDER BY d.line_no)
                FROM   order_detail d WHERE d.order_id = o.order_id) AS items,
               y.method, r.receipt_no
        FROM   orders o
               LEFT JOIN payment y ON y.order_id = o.order_id
               LEFT JOIN receipt r ON r.order_id = o.order_id
        WHERE  o.patient_id = :id
        ORDER  BY o.order_id DESC""", id=pid)
    return render_template("orders.html", patient=patient, orders=orders)


# ---------------------------------------------------------------------
# ฝั่งเภสัชกร
# ---------------------------------------------------------------------
def render_pharmacist_home(phid, error=None):
    pharmacist = get_pharmacist(phid)
    chats = pharmacist_home_data(pharmacist)
    return render_template("pharmacist_home.html", pharmacist=pharmacist, chats=chats, error=error,
                           queue=waiting_queue(pharmacist["pharmacy_id"]))


@app.get("/pharmacist/<int:phid>")
def pharmacist_home(phid):
    return render_pharmacist_home(phid)


@app.post("/pharmacist/<int:phid>/queue/<int:queue_id>/claim")
def pharmacist_claim(phid, queue_id):
    """ปุ่ม "รับเคส" : สำเร็จ -> เข้าห้องแชทที่สร้าง, มีคนรับไปก่อน -> กลับหน้ารายการคิว (รายการล่าสุด) พร้อมข้อความ"""
    get_pharmacist(phid)
    try:
        chat_id = tx.claim_queue(phid, queue_id)
    except DemoError as exc:
        return render_pharmacist_home(phid, error=str(exc))
    return redirect(url_for("pharmacist_chat", phid=phid, chat_id=chat_id))


@app.post("/pharmacist/<int:phid>/chat/<int:chat_id>/close")
def pharmacist_close_chat(phid, chat_id):
    try:
        tx.close_chat(phid, chat_id)
    except DemoError as exc:
        return render_pharmacist_chat(phid, chat_id, error=str(exc))
    return redirect(url_for("pharmacist_home", phid=phid))


def expire_side(default):
    """ฝ่ายที่ปุ่มทดสอบสั่งให้หมดเวลา : หน้าแชทส่ง side = ฝ่ายที่ต้องตอบอยู่ตอนนั้น"""
    side = request.form.get("side", default)
    return side if side in ("pharmacist", "patient") else default


SIDE_TH = {"pharmacist": "เภสัชกร", "patient": "คนไข้"}


@app.post("/pharmacist/<int:phid>/chat/<int:chat_id>/expire")
def pharmacist_expire_chat(phid, chat_id):
    """ปุ่มทดสอบ : จำลองว่าฝ่ายที่ต้องตอบหมดเวลาแล้ว (ไม่ต้องรอจริงตอน Demo)"""
    if get_chat(chat_id)["pharmacist_id"] != phid:
        abort(404)
    side = expire_side("pharmacist")
    if tx.expire_overdue(chat_id, side) == 0:
        return render_pharmacist_home(
            phid, error=f"ห้องนี้ปิดไปแล้ว หรือตอนนี้ไม่ใช่ฝ่าย{SIDE_TH[side]}ที่ต้องตอบ จึงไม่นับว่าหมดเวลา")
    return redirect(url_for("pharmacist_home", phid=phid))


@app.post("/patient/<int:pid>/chat/<int:chat_id>/expire")
def patient_expire_chat(pid, chat_id):
    """ปุ่มทดสอบฝั่งคนไข้ : ใช้กติกาเดียวกับฝั่งเภสัชกร"""
    if get_chat(chat_id)["patient_id"] != pid:
        abort(404)
    tx.expire_overdue(chat_id, expire_side("patient"))
    return redirect(url_for("patient_chat", pid=pid, chat_id=chat_id))


# ยา + คงเหลือรวมของล็อตที่ยังไม่หมดอายุ (ตัวเลขเดียวกับหน้าสต็อกยาและข้อความปฏิเสธตอนสั่งซื้อ)
DRUG_SELECT_SQL = """
    SELECT g.drug_id, g.name,
           NVL((SELECT SUM(b.quantity) FROM drug_batch b
                WHERE  b.drug_id = g.drug_id AND b.expiry_date > TRUNC(SYSDATE)), 0) AS stock
    FROM   drug g"""

DRUG_SEARCH_LIMIT = 10


def drug_label(drug):
    """ข้อความที่แสดงในช่องค้นหายา : รหัส · ชื่อยา · สต็อกคงเหลือ"""
    stock = "หมด" if drug["stock"] == 0 else f"เหลือ {drug['stock']}"
    return f"{drug['drug_id']} · {drug['name']} · {stock}"


def search_drugs(pharmacy_id, q):
    """ค้นยาของร้านจากข้อความที่พิมพ์ : ชื่อยา (ค้นกลางคำได้) หรือรหัสยา (ขึ้นต้นด้วย) ไม่เกิน 10 รายการ
    ข้อความของผู้ใช้ส่งเป็น bind variable (:q) เท่านั้น  ตัวอักษร % _ \\ ถูก escape ให้ LIKE มองเป็นตัวอักษรธรรมดา"""
    q = (q or "").strip()[:100]
    if not q:
        return []
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return db.query(DRUG_SELECT_SQL + """
        WHERE  g.pharmacy_id = :pharmacy_id AND g.deleted_at IS NULL
        AND   (LOWER(g.name) LIKE '%' || LOWER(:q) || '%' ESCAPE '\\'
           OR  TO_CHAR(g.drug_id) LIKE :q || '%' ESCAPE '\\')
        ORDER  BY g.name
        FETCH FIRST :limit ROWS ONLY""", pharmacy_id=pharmacy_id, q=q, limit=DRUG_SEARCH_LIMIT)


def render_pharmacist_chat(phid, chat_id, error=None, form_rows=None):
    pharmacist = get_pharmacist(phid)
    chat = get_chat(chat_id)
    if chat["pharmacist_id"] != phid:
        abort(404)
    # ฟอร์มใบสั่งยาที่ถูกปฏิเสธ : คืนค่าที่กรอกไว้ พร้อมข้อความในช่องค้นหายาของยาที่เลือกไว้แล้ว
    form_rows = [dict(row) for row in (form_rows or [])]
    for row in form_rows:
        if str(row.get("drug_id") or "").isdigit():
            drug = db.query_one(DRUG_SELECT_SQL + " WHERE g.pharmacy_id = :pharmacy_id AND g.drug_id = :drug_id",
                                pharmacy_id=pharmacist["pharmacy_id"], drug_id=int(row["drug_id"]))
            row["drug_label"] = drug_label(drug) if drug else ""
    rx_lines = []
    if chat["prescription_id"]:
        rx_lines = db.query("""
            SELECT d.line_no, g.name AS drug_name, d.strength, d.dosage, d.usage_note, d.quantity
            FROM   prescription_detail d JOIN drug g ON g.drug_id = d.drug_id
            WHERE  d.prescription_id = :rx_id ORDER BY d.line_no""", rx_id=chat["prescription_id"])
    return render_template("chat.html", role="pharmacist", pharmacist=pharmacist, chat=chat,
                           rooms=open_rooms(phid), rx_lines=rx_lines, error=error,
                           form_rows=form_rows + [{}] * 3)


@app.get("/pharmacist/<int:phid>/chat/<int:chat_id>")
def pharmacist_chat(phid, chat_id):
    return render_pharmacist_chat(phid, chat_id)


@app.post("/pharmacist/<int:phid>/chat/<int:chat_id>/prescription")
def pharmacist_prescribe(phid, chat_id):
    form = request.form
    items = []
    try:
        # ฟอร์มมีหลายแถว : แถวที่ไม่ได้เลือกยาถือว่าไม่ใช้
        rows = list(zip(form.getlist("drug_id"), form.getlist("strength"), form.getlist("dosage"),
                        form.getlist("usage_note"), form.getlist("quantity")))
        for drug_id, strength, dosage, usage_note, quantity in rows:
            if not drug_id:
                continue
            if not dosage.strip() or not usage_note.strip():
                raise DemoError("กรุณากรอกขนาดยาและวิธีใช้ให้ครบทุกรายการที่เลือก")
            if not quantity.isdigit() or int(quantity) <= 0:
                raise DemoError("จำนวนยาต้องเป็นจำนวนเต็มมากกว่า 0")
            items.append({"drug_id": int(drug_id), "strength": strength.strip() or None,
                          "dosage": dosage.strip(), "usage_note": usage_note.strip(),
                          "quantity": int(quantity)})
        tx.issue_prescription(phid, chat_id, items)
    except DemoError as exc:
        # ถูกปฏิเสธ (เช่น ยาหมด หรือกรอกไม่ครบ) : ไม่มีใบสั่งยาถูกสร้าง คืนค่าที่กรอกไว้ให้แก้ต่อได้
        form_rows = [{"drug_id": r[0], "dosage": r[2], "usage_note": r[3], "quantity": r[4]} for r in rows]
        return render_pharmacist_chat(phid, chat_id, error=str(exc), form_rows=form_rows)
    return redirect(url_for("pharmacist_chat", phid=phid, chat_id=chat_id))


@app.get("/pharmacist/<int:phid>/stock")
def pharmacist_stock(phid):
    pharmacist = get_pharmacist(phid)
    # สต็อกอยู่ที่ drug_batch (ยา 1 - N ล็อต) : แสดงทีละล็อต พร้อมยอดรวมต่อยา
    rows = db.query("""
        SELECT g.drug_id, g.name, g.dosage_form, g.price, b.lot_no,
               TO_CHAR(b.expiry_date, 'DD/MM/YYYY') AS expiry_date,
               CASE WHEN b.expiry_date <= TRUNC(SYSDATE) THEN 1 ELSE 0 END AS expired,
               b.quantity, TO_CHAR(b.updated_at, 'DD/MM/YYYY HH24:MI:SS') AS updated_at,
               SUM(b.quantity) OVER (PARTITION BY g.drug_id) AS drug_total,
               COUNT(*) OVER (PARTITION BY g.drug_id) AS lot_count,
               ROW_NUMBER() OVER (PARTITION BY g.drug_id ORDER BY b.expiry_date) AS lot_seq
        FROM   drug g LEFT JOIN drug_batch b ON b.drug_id = g.drug_id
        WHERE  g.pharmacy_id = :pharmacy_id AND g.deleted_at IS NULL
        ORDER  BY g.drug_id, b.expiry_date""", pharmacy_id=pharmacist["pharmacy_id"])
    return render_template("stock.html", pharmacist=pharmacist, rows=rows)


# ---------------------------------------------------------------------
# API สำหรับ polling (หน้าเว็บเรียกทุก 1.5-2 วินาที ไม่ใช้ WebSocket)
# ---------------------------------------------------------------------
@app.get("/api/chat/<int:chat_id>/messages")
def api_messages(chat_id):
    """ข้อความใหม่ที่ message_id มากกว่า after + สถานะห้อง + ใบสั่งยา (ถ้าออกแล้ว)"""
    after = request.args.get("after", default=0, type=int)
    tx.expire_overdue()         # ปิดห้องที่ฝ่ายที่ต้องตอบเกินเวลาแล้ว (เภสัชกร 10 นาที / คนไข้ 5 นาที)
    messages = db.query("""
        SELECT message_id, sender_type, content, TO_CHAR(sent_at, 'HH24:MI') AS sent_at
        FROM   chat_message
        WHERE  chat_id = :chat_id AND message_id > :after
        ORDER  BY message_id""", chat_id=chat_id, after=after)
    room = db.query_one(f"""
        SELECT c.status, {CHAT_STATE_SQL} AS state, {TURN_SQL} AS turn, {SECONDS_LEFT_SQL} AS seconds_left,
               r.prescription_id
        FROM   chat_room c
               JOIN consult_queue q ON q.queue_id = c.queue_id
               LEFT JOIN prescription r ON r.chat_id = c.chat_id
        WHERE  c.chat_id = :chat_id""", chat_id=chat_id)
    if room is None:
        abort(404)
    return jsonify(messages=messages, status=room["status"], state=room["state"],
                   state_label=STATUS_TH[room["state"]], turn=room["turn"], seconds_left=room["seconds_left"],
                   prescription_id=room["prescription_id"])


@app.post("/api/chat/<int:chat_id>/messages")
def api_send_message(chat_id):
    data = request.get_json(silent=True) or {}
    sender_type = data.get("sender_type")
    content = (data.get("content") or "").strip()
    if sender_type not in ("patient", "pharmacist") or not content:
        return jsonify(error="ข้อความไม่ถูกต้อง"), 400
    try:
        tx.send_message(chat_id, sender_type, content[:1000])
    except DemoError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(ok=True)


@app.get("/api/patient/<int:pid>/state")
def api_patient_state(pid):
    """ลายเซ็นของสถานะหน้าแรกคนไข้ : หน้าเว็บ reload เมื่อค่านี้เปลี่ยน"""
    tx.expire_overdue()
    queue, prescriptions = patient_home_data(pid)
    return jsonify(state=[queue, [(p["prescription_id"], p["order_status"]) for p in prescriptions]])


@app.get("/api/pharmacist/<int:phid>/state")
def api_pharmacist_state(phid):
    """ลายเซ็นของหน้ารายการคิว/ห้องของเภสัชกร : หน้าเว็บ reload เมื่อคิวที่รอหรือห้องของตัวเองเปลี่ยน"""
    tx.expire_overdue()
    pharmacist = get_pharmacist(phid)
    chats = pharmacist_home_data(pharmacist)
    return jsonify(state=[[q["queue_id"] for q in waiting_queue(pharmacist["pharmacy_id"])],
                          [(c["chat_id"], c["state"], c["turn"], c["prescription_id"]) for c in chats]])


@app.get("/api/pharmacist/<int:phid>/rooms")
def api_pharmacist_rooms(phid):
    """ห้องที่เปิดอยู่ของเภสัชกร + จำนวนคิวที่รอรับเคส : หน้าแชทใช้ทำรายการสลับห้องและแจ้งข้อความใหม่ในห้องอื่น"""
    tx.expire_overdue()
    pharmacist = get_pharmacist(phid)
    return jsonify(rooms=open_rooms(phid), waiting=len(waiting_queue(pharmacist["pharmacy_id"])))


@app.get("/api/pharmacist/<int:phid>/drugs")
def api_drug_search(phid):
    """ช่องค้นหายาในฟอร์มใบสั่งยา : q ว่าง -> รายการว่าง"""
    pharmacist = get_pharmacist(phid)
    drugs = search_drugs(pharmacist["pharmacy_id"], request.args.get("q", ""))
    return jsonify(drugs=[dict(d, label=drug_label(d)) for d in drugs])


@app.errorhandler(DemoError)
def handle_demo_error(exc):
    return render_template("error.html", message=str(exc)), 400


if __name__ == "__main__":
    # threaded=True : หน้าต่างคนไข้และเภสัชกร polling พร้อมกันได้
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
