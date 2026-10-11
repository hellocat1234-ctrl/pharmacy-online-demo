"""ตรรกะฐานข้อมูลที่ "เขียน" ข้อมูล (INSERT/UPDATE) ของระบบ Demo

หลักการที่ใช้ทุกฟังก์ชัน
  1. หนึ่งฟังก์ชัน = หนึ่ง Transaction : สำเร็จทั้งหมดแล้ว COMMIT, ผิดพลาดจุดใดก็ ROLLBACK ทั้งหมด
  2. ใช้ bind variable (:ชื่อ) ทุก query ไม่ต่อสตริง SQL
  3. สร้าง id ด้วย SEQUENCE ใน DDL (seq_xxx.NEXTVAL) แล้วรับค่ากลับด้วย RETURNING ... INTO
"""
import oracledb

import db


class DemoError(Exception):
    """ข้อผิดพลาดทางธุรกิจ : ข้อความเป็นภาษาไทย ใช้แสดงบนหน้าจอได้เลย"""


def _run(work):
    """ครอบ Transaction : เรียก work(cur) แล้ว COMMIT, ถ้ามี error ใด ๆ ให้ ROLLBACK ทั้งหมด"""
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            result = work(cur)
        conn.commit()          # COMMIT : ทุกคำสั่งใน work() มีผลพร้อมกัน
        return result
    except DemoError:
        conn.rollback()        # ROLLBACK : ยกเลิกทุกคำสั่งที่ทำไปแล้วใน Transaction นี้
        raise
    except oracledb.Error as exc:
        conn.rollback()        # error จากฐานข้อมูล (เช่น ผิด CHECK / UNIQUE / FK) ก็ ROLLBACK เช่นกัน
        raise DemoError(f"ฐานข้อมูลปฏิเสธรายการ ระบบยกเลิกทั้งหมดแล้ว ({exc})") from exc
    finally:
        conn.close()           # คืน connection ให้ pool


# ---------------------------------------------------------------------
# สถานะห้องแชทตามรายงาน : DDL เก็บได้แค่ open / closed (chk_chat_status)
# จึง "คำนวณ" สถานะจากข้อมูลที่มีอยู่ ไม่เพิ่มคอลัมน์และไม่แก้ CHECK
#   open   + เภสัชกรยังไม่เคยส่งข้อความ   = waiting_reply (รอตอบกลับ)
#   open   + เภสัชกรส่งข้อความแล้ว         = consulting    (ระหว่างปรึกษา)
#   closed + คิวเป็น cancelled            = failed        (ให้คำปรึกษาไม่สำเร็จ : เภสัชกรไม่ตอบทันเวลา)
#   closed + คิวเป็น completed            = closed        (ปิดห้องแชทแล้ว : เภสัชกรปิดเอง หรือคนไข้ไม่ตอบทันเวลา)
# ใช้ใน SELECT ที่ตั้ง alias chat_room เป็น c และ consult_queue เป็น q
# ---------------------------------------------------------------------
CHAT_STATE_SQL = """
    CASE WHEN c.status = 'open' AND EXISTS (SELECT 1 FROM chat_message m
                                            WHERE  m.chat_id = c.chat_id AND m.sender_type = 'pharmacist')
              THEN 'consulting'
         WHEN c.status = 'open'      THEN 'waiting_reply'
         WHEN q.status = 'cancelled' THEN 'failed'
         ELSE 'closed'
    END"""


# ---------------------------------------------------------------------
# ตัวนับเวลาตอบกลับ : เริ่มนับใหม่ทุกครั้งที่มีข้อความ คำนวณจากข้อความล่าสุดใน chat_message
# (ดู sender_type และ sent_at) ไม่เพิ่มคอลัมน์
#   ข้อความล่าสุดมาจากคนไข้ หรือยังไม่มีข้อความ -> ตาเภสัชกร ต้องตอบภายใน 10 นาที
#                                                  นับจาก sent_at ของข้อความนั้น (หรือ started_at ของห้อง)
#   ข้อความล่าสุดมาจากเภสัชกร                 -> ตาคนไข้ ต้องตอบภายใน 5 นาที นับจาก sent_at ของข้อความนั้น
# ใช้ใน SELECT ที่ตั้ง alias chat_room เป็น c
# ---------------------------------------------------------------------
PHARMACIST_REPLY_MINUTES = 10
PATIENT_REPLY_MINUTES = 5

_LAST_MESSAGE_SQL = "(SELECT MAX(m2.message_id) FROM chat_message m2 WHERE m2.chat_id = c.chat_id)"

# ใครต้องเป็นฝ่ายตอบ : 'pharmacist' หรือ 'patient'
TURN_SQL = f"""
    NVL((SELECT CASE m.sender_type WHEN 'pharmacist' THEN 'patient' ELSE 'pharmacist' END
         FROM   chat_message m WHERE m.message_id = {_LAST_MESSAGE_SQL}), 'pharmacist')"""

# จำนวนวินาทีที่เหลือของฝ่ายที่ต้องตอบ (0 หรือติดลบ = หมดเวลาแล้ว)
SECONDS_LEFT_SQL = f"""
    ROUND((CAST(NVL((SELECT m.sent_at FROM chat_message m WHERE m.message_id = {_LAST_MESSAGE_SQL}),
                    c.started_at) AS DATE)
           - CAST(CURRENT_TIMESTAMP AS DATE)) * 86400)
    + CASE {TURN_SQL} WHEN 'pharmacist' THEN {PHARMACIST_REPLY_MINUTES * 60} ELSE {PATIENT_REPLY_MINUTES * 60} END"""

TIMEOUT_MESSAGE = {
    "pharmacist": f"เภสัชกรไม่ได้ตอบภายใน {PHARMACIST_REPLY_MINUTES} นาที ห้องแชทถูกปิดเป็น “ให้คำปรึกษาไม่สำเร็จ” ส่งข้อความไม่ได้",
    "patient": f"คนไข้ไม่ได้ตอบภายใน {PATIENT_REPLY_MINUTES} นาที ห้องแชทถูกปิดแล้ว ส่งข้อความไม่ได้",
}


# ---------------------------------------------------------------------
# คิวและการจับคู่
#   MAX_OPEN_CHATS = จำนวนห้องแชท open (รอตอบกลับ/ระหว่างปรึกษา) ที่เภสัชกร 1 คนถือพร้อมกันได้
#   ถ้าเภสัชกรทุกคนเต็ม คิวจะค้างที่ waiting (รอจับคู่) จนกว่าจะมีห้องถูกปิดหรือหมดเวลา
#   ลำดับในคิว (QUEUE_ORDER_SQL) : VIP ก่อนสมาชิกทั่วไป แล้วตามเวลาที่เข้าคิว
#   ใช้ใน SELECT ที่ตั้ง alias consult_queue เป็น q
# ---------------------------------------------------------------------
MAX_OPEN_CHATS = 1

QUEUE_ORDER_SQL = "CASE q.member_type WHEN 'vip' THEN 0 ELSE 1 END, q.entered_at, q.queue_id"


def _match_waiting(cur, pharmacy_id):
    """จับคู่คิวที่รอ (waiting) กับเภสัชกรที่ว่าง วนจนกว่าคิวหมดหรือเภสัชกรเต็มทุกคน
    เรียกภายใน Transaction ของผู้เรียก (ขอคำปรึกษา / ปิดห้อง / หมดเวลา) จึง COMMIT/ROLLBACK พร้อมกัน
    คืนจำนวนคิวที่จับคู่ได้"""
    # ล็อกแถวร้านยา : ให้การจับคู่ของร้านเดียวกันทำทีละ Transaction
    # กันสองคำขอพร้อมกันเลือกเภสัชกรคนเดียวกันจนเกิน MAX_OPEN_CHATS
    cur.execute("SELECT pharmacy_id FROM pharmacy WHERE pharmacy_id = :pharmacy_id FOR UPDATE",
                pharmacy_id=pharmacy_id)
    matched = 0
    while True:
        # (ก) คิวถัดไป : VIP ก่อน แล้วตามเวลาเข้าคิว
        cur.execute(f"""
            SELECT q.queue_id
            FROM   consult_queue q
            WHERE  q.pharmacy_id = :pharmacy_id AND q.status = 'waiting'
            ORDER  BY {QUEUE_ORDER_SQL}
            FETCH FIRST 1 ROW ONLY""", pharmacy_id=pharmacy_id)
        row = cur.fetchone()
        if row is None:
            return matched                  # ไม่มีคิวรอแล้ว
        queue_id = row[0]

        # (ข) เภสัชกรที่ว่าง : ถือห้อง open น้อยกว่า MAX_OPEN_CHATS
        #     เลือกคนที่ถือน้อยที่สุด ถ้าเท่ากันเลือกคนที่ได้ห้องล่าสุดนานที่สุด
        cur.execute("""
            SELECT f.pharmacist_id
            FROM   pharmacist f
            WHERE  f.pharmacy_id = :pharmacy_id AND f.deleted_at IS NULL
            AND    (SELECT COUNT(*) FROM chat_room c
                    WHERE  c.pharmacist_id = f.pharmacist_id AND c.status = 'open') < :max_open
            ORDER  BY (SELECT COUNT(*) FROM chat_room c
                       WHERE  c.pharmacist_id = f.pharmacist_id AND c.status = 'open'),
                      (SELECT MAX(c.started_at) FROM chat_room c
                       WHERE  c.pharmacist_id = f.pharmacist_id) NULLS FIRST,
                      f.pharmacist_id
            FETCH FIRST 1 ROW ONLY""", pharmacy_id=pharmacy_id, max_open=MAX_OPEN_CHATS)
        row = cur.fetchone()
        if row is None:
            return matched                  # เภสัชกรเต็มทุกคน : คิวที่เหลือรอต่อ (รอจับคู่)
        pharmacist_id = row[0]

        # (ค) สร้างห้องแชท : คิว 1 - 1 ห้องแชท (uq_chat_queue)
        #     status = open และเภสัชกรยังไม่มีข้อความ = "รอตอบกลับ"
        #     started_at = เวลาที่จับคู่ ตัวนับ 10 นาทีของเภสัชกรจึงเริ่มตอนได้ห้อง ไม่ใช่ตอนเข้าคิว
        cur.execute("""
            INSERT INTO chat_room (chat_id, queue_id, pharmacist_id, status)
            VALUES (seq_chat_room.NEXTVAL, :queue_id, :pharmacist_id, 'open')""",
            queue_id=queue_id, pharmacist_id=pharmacist_id)

        # (ง) คิวจับคู่แล้ว : waiting -> in_progress
        cur.execute("""
            UPDATE consult_queue SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP
            WHERE  queue_id = :queue_id AND status = 'waiting'""", queue_id=queue_id)
        matched += 1


# ---------------------------------------------------------------------
# 1) คนไข้กด "ขอรับคำปรึกษา" ปุ่มเดียว  (Transaction เดียว)
#    INSERT consult_queue (waiting = รอจับคู่) -> จับคู่ทันทีถ้ามีเภสัชกรว่าง
#    ถ้าเภสัชกรเต็มทุกคน คิวค้างที่ waiting และยังไม่มีห้องแชท
# ---------------------------------------------------------------------
def request_consult(patient_id):
    def work(cur):
        # คนไข้ 1 คนมีคิวที่ยังไม่จบได้ครั้งละ 1 คิว
        cur.execute("""
            SELECT COUNT(*) FROM consult_queue
            WHERE  patient_id = :patient_id AND status IN ('waiting', 'in_progress')""",
            patient_id=patient_id)
        if cur.fetchone()[0] > 0:
            raise DemoError("คุณมีคิวที่ยังไม่เสร็จอยู่แล้ว")

        # ระบบมีร้านยาร้านเดียว : ใส่ pharmacy_id ให้เอง คนไข้ไม่ต้องเลือกร้าน
        cur.execute("SELECT MIN(pharmacy_id) FROM pharmacy WHERE open_status = 'open'")
        pharmacy_id = cur.fetchone()[0]
        if pharmacy_id is None:
            raise DemoError("ขณะนี้ร้านยาปิดให้บริการ")

        # สร้างคิว สถานะ waiting = รอจับคู่
        # queue_no = ลำดับคิวของร้านในวันนี้, member_type ใส่ตาม patient.is_vip (ใช้จัดลำดับ VIP ก่อน)
        cur.execute("""
            INSERT INTO consult_queue (queue_id, patient_id, pharmacy_id, queue_no, member_type, status)
            VALUES (seq_consult_queue.NEXTVAL, :patient_id, :pharmacy_id,
                    (SELECT NVL(MAX(q.queue_no), 0) + 1
                     FROM   consult_queue q
                     WHERE  q.pharmacy_id = :pharmacy_id AND q.entered_at >= TRUNC(SYSDATE)),
                    (SELECT CASE p.is_vip WHEN 1 THEN 'vip' ELSE 'general' END
                     FROM   patient p WHERE p.patient_id = :patient_id),
                    'waiting')""",
            patient_id=patient_id, pharmacy_id=pharmacy_id)

        # จับคู่ทันที (ถ้ามีคิวอื่นรออยู่ก่อน คิวนั้นได้ก่อนตามลำดับ)
        _match_waiting(cur, pharmacy_id)

    return _run(work)


# ---------------------------------------------------------------------
# 2) เภสัชกรกด "ปิดห้องแชท" -> chat_room = closed, consult_queue = completed
#    ปิดได้เมื่อเภสัชกรตอบคนไข้แล้วอย่างน้อย 1 ข้อความ (สถานะ ระหว่างปรึกษา)
#    เภสัชกรว่างลง -> จับคู่คิวที่รอคนถัดไปให้ทันที ใน Transaction เดียวกัน
# ---------------------------------------------------------------------
def close_chat(pharmacist_id, chat_id):
    def work(cur):
        cur.execute("""
            UPDATE chat_room c
            SET    c.status = 'closed', c.updated_at = CURRENT_TIMESTAMP
            WHERE  c.chat_id = :chat_id AND c.pharmacist_id = :pharmacist_id AND c.status = 'open'
            AND    EXISTS (SELECT 1 FROM chat_message m
                           WHERE  m.chat_id = c.chat_id AND m.sender_type = 'pharmacist')""",
            chat_id=chat_id, pharmacist_id=pharmacist_id)
        if cur.rowcount == 0:
            raise DemoError("ปิดห้องแชทไม่ได้: ห้องนี้ปิดไปแล้ว หรือคุณยังไม่ได้ตอบคนไข้")

        pharmacy_id_var = cur.var(int)
        cur.execute("""
            UPDATE consult_queue SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE  queue_id = (SELECT queue_id FROM chat_room WHERE chat_id = :chat_id)
            RETURNING pharmacy_id INTO :pharmacy_id""",
            chat_id=chat_id, pharmacy_id=pharmacy_id_var)

        # ห้องปิด + คิวถัดไปได้ห้อง สำเร็จหรือยกเลิกพร้อมกัน
        _match_waiting(cur, pharmacy_id_var.getvalue()[0])

    return _run(work)


# ---------------------------------------------------------------------
# 2.1) หมดเวลาตอบกลับ -> ปิดห้อง แล้วจับคู่คิวที่รอคนถัดไป (Transaction เดียวกัน)
#      เภสัชกรไม่ตอบภายใน 10 นาที : chat_room = closed, consult_queue = cancelled (ให้คำปรึกษาไม่สำเร็จ)
#      คนไข้ไม่ตอบภายใน 5 นาที    : chat_room = closed, consult_queue = completed (ปิดห้องแชทแล้ว)
# ---------------------------------------------------------------------
def _lock_open_rooms(cur, chat_id=None):
    """ล็อกห้องที่ยัง open ด้วย FOR UPDATE (กันอีกฝ่ายส่งข้อความแทรกระหว่างที่กำลังตัดสินว่าหมดเวลา)
    แล้วคืน [(chat_id, queue_id, turn, seconds_left), ...]"""
    cur.execute("""
        SELECT c.chat_id FROM chat_room c
        WHERE  c.status = 'open' AND (:chat_id IS NULL OR c.chat_id = :chat_id)
        FOR UPDATE""", chat_id=chat_id)
    locked = [row[0] for row in cur.fetchall()]
    rooms = []
    for locked_id in locked:
        cur.execute(f"""
            SELECT c.chat_id, c.queue_id, {TURN_SQL}, {SECONDS_LEFT_SQL}
            FROM   chat_room c WHERE c.chat_id = :chat_id""", chat_id=locked_id)
        rooms.append(cur.fetchone())
    return rooms


def _close_timed_out(cur, chat_id, queue_id, turn):
    """ปิดห้องที่หมดเวลา : สถานะคิวขึ้นกับว่าฝ่ายไหนไม่ตอบ  คืน pharmacy_id ของคิว"""
    cur.execute("""
        UPDATE chat_room SET status = 'closed', updated_at = CURRENT_TIMESTAMP
        WHERE  chat_id = :chat_id""", chat_id=chat_id)
    pharmacy_id_var = cur.var(int)
    cur.execute("""
        UPDATE consult_queue SET status = :status, updated_at = CURRENT_TIMESTAMP
        WHERE  queue_id = :queue_id
        RETURNING pharmacy_id INTO :pharmacy_id""",
        status="cancelled" if turn == "pharmacist" else "completed",
        queue_id=queue_id, pharmacy_id=pharmacy_id_var)
    return pharmacy_id_var.getvalue()[0]


def expire_overdue(chat_id=None, side=None):
    """ไม่ส่งอะไร        : ปิดทุกห้องที่เกินเวลาจริง (หน้าเว็บเรียกตอน polling)
    ส่ง chat_id + side : ปุ่มทดสอบ "หมดเวลา" ถือว่าฝ่าย side หมดเวลาทันที (ได้ผลเมื่อเป็นตาของฝ่ายนั้น)
    คืนจำนวนห้องที่ถูกปิด"""
    def work(cur):
        pharmacy_ids = set()
        closed = 0
        for room_id, queue_id, turn, seconds_left in _lock_open_rooms(cur, chat_id):
            overdue = (turn == side) if chat_id is not None else (seconds_left <= 0)
            if overdue:
                pharmacy_ids.add(_close_timed_out(cur, room_id, queue_id, turn))
                closed += 1
        # เภสัชกรว่างลง -> จับคู่คิวที่รอคนถัดไป (สำเร็จหรือยกเลิกพร้อมกับการปิดห้อง)
        for pharmacy_id in sorted(pharmacy_ids):
            _match_waiting(cur, pharmacy_id)
        return closed

    return _run(work)


# ---------------------------------------------------------------------
# 3) ส่งข้อความแชท -> chat_message
#    ตรวจเวลาฝั่งเซิร์ฟเวอร์ก่อนบันทึกทุกครั้ง : ถ้าฝ่ายที่ต้องตอบเกินเวลาแล้ว
#    ข้อความถูกปฏิเสธ และห้องถูกปิดใน Transaction นี้เลย (ไม่พึ่งการซ่อนปุ่มในหน้าเว็บ)
#    ข้อความที่บันทึกสำเร็จทำให้ตัวนับของอีกฝ่ายเริ่มใหม่ เพราะตัวนับคำนวณจากข้อความล่าสุด
# ---------------------------------------------------------------------
def send_message(chat_id, sender_type, content):
    def work(cur):
        rooms = _lock_open_rooms(cur, chat_id)
        if not rooms:
            raise DemoError("ห้องแชทนี้ปิดแล้ว")
        _, queue_id, turn, seconds_left = rooms[0]

        if seconds_left <= 0:
            # หมดเวลาแล้ว : ปิดห้อง + จับคู่คิวถัดไป แล้ว COMMIT (คืนข้อความปฏิเสธแทนการ raise
            # เพราะ raise จะทำให้ _run() ROLLBACK การปิดห้องไปด้วย)
            _match_waiting(cur, _close_timed_out(cur, chat_id, queue_id, turn))
            return TIMEOUT_MESSAGE[turn]

        cur.execute("""
            INSERT INTO chat_message (message_id, chat_id, sender_type, message_type, content)
            VALUES (seq_chat_message.NEXTVAL, :chat_id, :sender_type, 'text', :content)""",
            chat_id=chat_id, sender_type=sender_type, content=content)
        return None

    rejected = _run(work)
    if rejected:
        raise DemoError(rejected)


# ---------------------------------------------------------------------
# 4) เภสัชกรออกใบสั่งยา -> prescription + prescription_detail
#    ออกได้ขณะห้องแชทยังเปิด (ก่อนกดปิดห้องแชท) ห้องละ 1 ใบ
#    ตรงนี้กันแค่ยาที่คงเหลือรวม 0 (หมด) ไม่เทียบจำนวนที่สั่งกับคงเหลือ
#    การกันสต็อกตัวหลักอยู่ที่ place_order ตอนคนไข้สั่งซื้อ (เกินสต็อก -> ROLLBACK ทั้งคำสั่งซื้อ)
#    items = [{"drug_id", "strength", "dosage", "usage_note", "quantity"}, ...]
# ---------------------------------------------------------------------
def issue_prescription(pharmacist_id, chat_id, items):
    if not items:
        raise DemoError("กรุณาเลือกยาอย่างน้อย 1 รายการ")

    def work(cur):
        # หาคนไข้จาก ห้องแชท -> คิว และตรวจว่าเป็นห้องของเภสัชกรคนนี้ที่ยังเปิดอยู่
        cur.execute("""
            SELECT q.patient_id, q.queue_id
            FROM   chat_room c JOIN consult_queue q ON q.queue_id = c.queue_id
            WHERE  c.chat_id = :chat_id AND c.pharmacist_id = :pharmacist_id AND c.status = 'open'""",
            chat_id=chat_id, pharmacist_id=pharmacist_id)
        row = cur.fetchone()
        if row is None:
            raise DemoError("ห้องแชทนี้ปิดแล้วหรือไม่ใช่ห้องของคุณ")
        patient_id, queue_id = row

        cur.execute("SELECT COUNT(*) FROM prescription WHERE chat_id = :chat_id", chat_id=chat_id)
        if cur.fetchone()[0] > 0:
            raise DemoError("ห้องแชทนี้ออกใบสั่งยาไปแล้ว")

        # ก่อน INSERT ใด ๆ : ยาที่คงเหลือรวมของล็อตที่ยังไม่หมดอายุเป็น 0 ออกใบสั่งยาไม่ได้
        # (ไม่เทียบจำนวนที่สั่ง : สั่งเกินคงเหลือได้ แล้วไปถูกปฏิเสธตอนคนไข้สั่งซื้อ)
        for drug_id in {item["drug_id"] for item in items}:
            cur.execute("""
                SELECT g.name,
                       NVL((SELECT SUM(b.quantity) FROM drug_batch b
                            WHERE  b.drug_id = g.drug_id AND b.expiry_date > TRUNC(SYSDATE)), 0)
                FROM   drug g
                WHERE  g.drug_id = :drug_id""", drug_id=drug_id)
            drug = cur.fetchone()
            if drug is None:
                continue                    # ยาที่ไม่มีจริง จะถูกปฏิเสธตอน INSERT รายละเอียดด้านล่าง
            drug_name, available = drug
            if available == 0:
                raise DemoError(f"{drug_name} คงเหลือ 0 ออกใบสั่งยาไม่ได้")

        # หัวใบสั่งยา : ห้องแชท 1 - 1 ใบสั่งยา (uq_prescription_chat)
        # prescribed_time เก็บเป็นข้อความ HH:MM ตาม DDL
        prescription_id = cur.var(int)
        cur.execute("""
            INSERT INTO prescription (prescription_id, patient_id, pharmacist_id, chat_id,
                                      prescribed_date, prescribed_time)
            VALUES (seq_prescription.NEXTVAL, :patient_id, :pharmacist_id, :chat_id,
                    TRUNC(SYSDATE), TO_CHAR(SYSDATE, 'HH24:MI'))
            RETURNING prescription_id INTO :prescription_id""",
            patient_id=patient_id, pharmacist_id=pharmacist_id, chat_id=chat_id,
            prescription_id=prescription_id)
        rx_id = prescription_id.getvalue()[0]

        # รายละเอียดใบสั่งยา : INSERT ... SELECT จาก drug เพื่อบังคับว่าเป็นยาของร้านที่เภสัชกรสังกัด
        # batch_id ยังว่าง จะใส่ตอนตัดสต็อก (ตอนคนไข้สั่งซื้อ)
        for line_no, item in enumerate(items, start=1):
            cur.execute("""
                INSERT INTO prescription_detail (prescription_id, line_no, drug_id, strength,
                                                 dosage, usage_note, quantity)
                SELECT :rx_id, :line_no, g.drug_id, :strength, :dosage, :usage_note, :quantity
                FROM   drug g JOIN pharmacist f ON f.pharmacy_id = g.pharmacy_id
                WHERE  g.drug_id = :drug_id AND f.pharmacist_id = :pharmacist_id
                AND    g.deleted_at IS NULL""",
                rx_id=rx_id, line_no=line_no, drug_id=item["drug_id"], strength=item["strength"],
                dosage=item["dosage"], usage_note=item["usage_note"], quantity=item["quantity"],
                pharmacist_id=pharmacist_id)
            if cur.rowcount == 0:
                raise DemoError(f"รายการที่ {line_no}: ไม่พบยานี้ในร้านของคุณ")

        # แจ้งคนไข้ในห้องแชท (ห้องยังเปิดอยู่ เภสัชกรกด "ปิดห้องแชท" เองเมื่อปรึกษาเสร็จ)
        cur.execute("""
            INSERT INTO chat_message (message_id, chat_id, sender_type, message_type, content)
            VALUES (seq_chat_message.NEXTVAL, :chat_id, 'pharmacist', 'text', :content)""",
            chat_id=chat_id, content=f"ออกใบสั่งยาเลขที่ {rx_id} ให้แล้ว กดดูใบสั่งยาเพื่อสั่งซื้อได้เลย")
        return rx_id

    return _run(work)


# ---------------------------------------------------------------------
# 5) คนไข้สั่งซื้อตามใบสั่งยา  ** Transaction หลักของ Demo **
#    INSERT orders + order_detail และ UPDATE drug_batch (ตัดสต็อก) ต้องสำเร็จพร้อมกันทั้งหมด
#    ถ้ายารายการใดสต็อกไม่พอ -> ROLLBACK ทั้งคำสั่งซื้อ ข้อมูลในฐานข้อมูลไม่เปลี่ยน
# ---------------------------------------------------------------------
def place_order(patient_id, prescription_id, shipping_address):
    shipping_address = (shipping_address or "").strip()
    if not shipping_address:
        raise DemoError("กรุณาระบุที่อยู่จัดส่ง")
    if len(shipping_address) > 500:
        raise DemoError("ที่อยู่จัดส่งยาวเกิน 500 ตัวอักษร")

    def work(cur):
        # (1) อ่านรายการยาในใบสั่งยา พร้อมชื่อและราคาปัจจุบันของยา
        cur.execute("""
            SELECT d.line_no, d.drug_id, d.quantity, g.name, g.price
            FROM   prescription r
                   JOIN prescription_detail d ON d.prescription_id = r.prescription_id
                   JOIN drug g ON g.drug_id = d.drug_id
            WHERE  r.prescription_id = :rx_id AND r.patient_id = :patient_id
            ORDER  BY d.line_no""",
            rx_id=prescription_id, patient_id=patient_id)
        lines = cur.fetchall()
        if not lines:
            raise DemoError("ไม่พบใบสั่งยานี้")

        # ใบสั่งยา 1 - 1 คำสั่งซื้อ (uq_orders_prescription) : ตรวจก่อนเพื่อให้ข้อความอ่านง่าย
        cur.execute("SELECT COUNT(*) FROM orders WHERE prescription_id = :rx_id", rx_id=prescription_id)
        if cur.fetchone()[0] > 0:
            raise DemoError("ใบสั่งยานี้ถูกสั่งซื้อไปแล้ว")

        # (2) INSERT orders : สถานะเริ่มต้น pending_payment, shipping_address เป็น snapshot
        order_id_var = cur.var(int)
        cur.execute("""
            INSERT INTO orders (order_id, patient_id, prescription_id, status, shipping_address)
            VALUES (seq_orders.NEXTVAL, :patient_id, :rx_id, 'pending_payment', :shipping_address)
            RETURNING order_id INTO :order_id""",
            patient_id=patient_id, rx_id=prescription_id, shipping_address=shipping_address,
            order_id=order_id_var)
        order_id = order_id_var.getvalue()[0]

        # ใช้ในข้อความปฏิเสธ : จำนวนที่สั่งรวมต่อยา (เผื่อยาตัวเดียวกันหลายบรรทัด)
        # และจำนวนที่ Transaction นี้หักไปแล้วต่อยา (ยังไม่ COMMIT)
        wanted, taken = {}, {}
        for _, drug_id, quantity, _, _ in lines:
            wanted[drug_id] = wanted.get(drug_id, 0) + quantity

        for line_no, drug_id, quantity, drug_name, price in lines:
            # (3) เลือกล็อตที่จะจ่าย แบบ FEFO (First Expired, First Out)
            #     = ล็อตที่ยังไม่หมดอายุ มีจำนวนพอ และหมดอายุเร็วที่สุด (จ่ายจากล็อตเดียวต่อรายการ)
            cur.execute("""
                SELECT b.batch_id
                FROM   drug_batch b
                WHERE  b.drug_id = :drug_id
                AND    b.expiry_date > TRUNC(SYSDATE)
                AND    b.quantity >= :quantity
                ORDER  BY b.expiry_date
                FETCH FIRST 1 ROW ONLY""",
                drug_id=drug_id, quantity=quantity)
            batch = cur.fetchone()
            if batch is None:
                _raise_out_of_stock(cur, drug_id, drug_name, quantity, wanted[drug_id], taken.get(drug_id, 0))
            batch_id = batch[0]

            # (4) ตัดสต็อก : เงื่อนไข quantity >= :quantity อยู่ใน UPDATE เดียวกับการหัก
            #     ถ้ามีคนอื่นตัดสต็อกล็อตนี้ไปก่อนในเสี้ยววินาที จะไม่มีแถวถูกแก้ (SQL%ROWCOUNT = 0)
            #     สต็อกจึงไม่มีทางติดลบ (และ CHECK chk_batch_quantity กันไว้อีกชั้น)
            cur.execute("""
                UPDATE drug_batch
                SET    quantity = quantity - :quantity, updated_at = CURRENT_TIMESTAMP
                WHERE  batch_id = :batch_id AND quantity >= :quantity""",
                quantity=quantity, batch_id=batch_id)
            if cur.rowcount == 0:
                _raise_out_of_stock(cur, drug_id, drug_name, quantity, wanted[drug_id], taken.get(drug_id, 0))
            taken[drug_id] = taken.get(drug_id, 0) + quantity

            # (5) INSERT order_detail : drug_name และ unit_price เป็น snapshot ณ วันที่สั่งซื้อ
            cur.execute("""
                INSERT INTO order_detail (order_id, line_no, drug_id, drug_name, quantity, unit_price)
                VALUES (:order_id, :line_no, :drug_id, :drug_name, :quantity, :unit_price)""",
                order_id=order_id, line_no=line_no, drug_id=drug_id, drug_name=drug_name,
                quantity=quantity, unit_price=price)

            # (6) บันทึกล็อตที่จ่ายจริงลงใบสั่งยา (FK (batch_id, drug_id) บังคับว่าเป็นล็อตของยาตัวนี้)
            cur.execute("""
                UPDATE prescription_detail SET batch_id = :batch_id
                WHERE  prescription_id = :rx_id AND line_no = :line_no""",
                batch_id=batch_id, rx_id=prescription_id, line_no=line_no)

        return order_id

    return _run(work)


def _raise_out_of_stock(cur, drug_id, drug_name, quantity, wanted, taken):
    """สร้างข้อความปฏิเสธจากคงเหลือรวมของยา (ล็อตที่ยังไม่หมดอายุ) เทียบกับจำนวนที่สั่ง
    quantity = จำนวนของบรรทัดที่ตัดไม่ได้, wanted = จำนวนที่สั่งรวมของยานี้ทั้งใบ,
    taken = จำนวนที่ Transaction นี้หักไปแล้ว (บวกคืนเพื่อให้ได้คงเหลือก่อนสั่งซื้อ ตรงกับที่หน้าจอแสดง)
      - คงเหลือรวมไม่พอ                 -> "คงเหลือ N สั่ง Q ไม่ได้"
      - คงเหลือรวมพอ แต่ล็อตเดียวไม่พอ -> "ไม่มีล็อตเดียวที่มีจำนวนพอ" (จ่ายจากล็อตเดียวต่อรายการ)
    การ raise ตรงนี้ทำให้ _run() ROLLBACK ทั้ง Transaction"""
    cur.execute("""
        SELECT NVL(SUM(b.quantity), 0), NVL(MAX(b.quantity), 0)
        FROM   drug_batch b
        WHERE  b.drug_id = :drug_id AND b.expiry_date > TRUNC(SYSDATE)""",
        drug_id=drug_id)
    total, largest_lot = cur.fetchone()
    total += taken
    if wanted > total:
        reason = f"{drug_name} คงเหลือ {total} สั่ง {wanted} ไม่ได้"
    else:
        reason = (f"{drug_name} คงเหลือรวม {total} แต่ไม่มีล็อตเดียวที่มีจำนวนพอสำหรับ {quantity} "
                  f"(ล็อตที่มากที่สุดมี {largest_lot})")
    raise DemoError(f"{reason} ระบบไม่สร้างคำสั่งซื้อและคืนสต็อกทั้งหมดแล้ว")


# ---------------------------------------------------------------------
# 6) ชำระเงิน  ** Transaction ที่สองของ Demo **
#    INSERT payment + (qr_code หรือ transfer_slip) -> UPDATE orders เป็น paid
#    -> INSERT receipt + receipt_detail  ล้มเหลวจุดใดก็ ROLLBACK ทั้งหมด
# ---------------------------------------------------------------------
def pay_order(patient_id, order_id, method, bank_name=None):
    if method not in ("qr_code", "bank_transfer"):
        raise DemoError("วิธีชำระเงินไม่ถูกต้อง")

    def work(cur):
        # ยอดรวมไม่ได้เก็บในตาราง orders : คำนวณจาก order_detail (จำนวน x ราคาต่อหน่วย)
        # ร้านยาหาจาก orders -> prescription -> chat_room -> consult_queue
        cur.execute("""
            SELECT o.status, p.first_name || ' ' || p.last_name, ph.pharmacy_id, ph.name,
                   (SELECT SUM(d.quantity * d.unit_price) FROM order_detail d
                    WHERE  d.order_id = o.order_id)
            FROM   orders o
                   JOIN patient p       ON p.patient_id      = o.patient_id
                   JOIN prescription r  ON r.prescription_id = o.prescription_id
                   JOIN chat_room c     ON c.chat_id         = r.chat_id
                   JOIN consult_queue q ON q.queue_id        = c.queue_id
                   JOIN pharmacy ph     ON ph.pharmacy_id    = q.pharmacy_id
            WHERE  o.order_id = :order_id AND o.patient_id = :patient_id""",
            order_id=order_id, patient_id=patient_id)
        row = cur.fetchone()
        if row is None:
            raise DemoError("ไม่พบคำสั่งซื้อนี้")
        status, patient_name, pharmacy_id, pharmacy_name, amount = row
        if status != "pending_payment":
            raise DemoError("คำสั่งซื้อนี้ชำระเงินแล้ว")

        # (1) INSERT payment : คำสั่งซื้อ 1 - 1 การชำระเงิน (uq_payment_order)
        payment_id_var = cur.var(int)
        cur.execute("""
            INSERT INTO payment (payment_id, order_id, method, status, paid_at)
            VALUES (seq_payment.NEXTVAL, :order_id, :method, 'success', CURRENT_TIMESTAMP)
            RETURNING payment_id INTO :payment_id""",
            order_id=order_id, method=method, payment_id=payment_id_var)
        payment_id = payment_id_var.getvalue()[0]

        # (2) หลักฐานการชำระเงินตามวิธีที่เลือก (จำลอง ไม่ได้เชื่อมธนาคารจริง)
        if method == "qr_code":
            cur.execute("""
                INSERT INTO qr_code (qr_id, payment_id, amount)
                VALUES (seq_qr_code.NEXTVAL, :payment_id, :amount)""",
                payment_id=payment_id, amount=amount)
        else:
            cur.execute("""
                INSERT INTO transfer_slip (slip_id, payment_id, transaction_no, reference_no,
                                           payer_name, payee_name, bank_name, amount, fee, transferred_at)
                VALUES (seq_transfer_slip.NEXTVAL, :payment_id,
                        'TXN' || TO_CHAR(SYSDATE, 'YYYYMMDDHH24MISS') || LPAD(:payment_id, 4, '0'),
                        'ORDER-' || :order_id,
                        :payer_name, :payee_name, :bank_name, :amount, 0, CURRENT_TIMESTAMP)""",
                payment_id=payment_id, order_id=order_id, payer_name=patient_name,
                payee_name=pharmacy_name, bank_name=(bank_name or "ธนาคารจำลอง")[:100], amount=amount)

        # (3) เปลี่ยนสถานะคำสั่งซื้อ : เงื่อนไข status = 'pending_payment' กันการจ่ายซ้ำ
        #     ถ้าสถานะถูกเปลี่ยนไปแล้ว จะไม่มีแถวถูกแก้ (SQL%ROWCOUNT = 0) -> ROLLBACK
        cur.execute("""
            UPDATE orders
            SET    status = 'paid', updated_at = CURRENT_TIMESTAMP
            WHERE  order_id = :order_id AND status = 'pending_payment'""",
            order_id=order_id)
        if cur.rowcount == 0:
            raise DemoError("คำสั่งซื้อนี้ชำระเงินแล้ว ระบบยกเลิกรายการชำระเงินซ้ำ")

        # (4) INSERT receipt : receipt_id = รหัสภายในจาก sequence, receipt_no = เลขที่บนเอกสาร
        receipt_id_var = cur.var(int)
        cur.execute("""
            INSERT INTO receipt (receipt_id, receipt_no, order_id, patient_id, pharmacy_id, service_date)
            VALUES (seq_receipt.NEXTVAL,
                    'RC-' || TO_CHAR(SYSDATE, 'YYYY') || '-' || LPAD(seq_receipt.CURRVAL, 5, '0'),
                    :order_id, :patient_id, :pharmacy_id, TRUNC(SYSDATE))
            RETURNING receipt_id INTO :receipt_id""",
            order_id=order_id, patient_id=patient_id, pharmacy_id=pharmacy_id,
            receipt_id=receipt_id_var)
        receipt_id = receipt_id_var.getvalue()[0]

        # (5) INSERT receipt_detail : คัดลอกจาก order_detail (ราคา snapshot)
        #     dosage มาจากใบสั่งยาบรรทัดเดียวกัน
        cur.execute("""
            INSERT INTO receipt_detail (receipt_id, line_no, drug_id, dosage, quantity,
                                        unit_price, total_amount)
            SELECT :receipt_id, d.line_no, d.drug_id, pd.dosage, d.quantity,
                   d.unit_price, d.quantity * d.unit_price
            FROM   order_detail d
                   JOIN orders o ON o.order_id = d.order_id
                   LEFT JOIN prescription_detail pd
                          ON pd.prescription_id = o.prescription_id AND pd.line_no = d.line_no
            WHERE  d.order_id = :order_id""",
            receipt_id=receipt_id, order_id=order_id)
        if cur.rowcount == 0:
            raise DemoError("คำสั่งซื้อนี้ไม่มีรายการยา")

        return receipt_id

    return _run(work)
