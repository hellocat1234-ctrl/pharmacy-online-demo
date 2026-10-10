-- =====================================================================
-- demo_queries.sql : เปิดโชว์หลังทำฟังก์ชันหลักเสร็จ (รันด้วย F5 ใน SQL Developer)
-- แสดงว่ามีแถวใหม่ในทุกตารางที่เกี่ยวข้อง เรียงตามลำดับของ flow
-- =====================================================================
SET LINESIZE 220
SET PAGESIZE 100

-- 1) คิว : คนไข้กด "ขอรับคำปรึกษา"
--    status: waiting (รอจับคู่) -> in_progress (จับคู่แล้ว) -> completed / cancelled
SELECT q.queue_id, q.queue_no, p.first_name AS patient, ph.name AS pharmacy,
       q.member_type, q.status, TO_CHAR(q.entered_at, 'HH24:MI:SS') AS entered_at
FROM   consult_queue q
       JOIN patient  p  ON p.patient_id   = q.patient_id
       JOIN pharmacy ph ON ph.pharmacy_id = q.pharmacy_id
ORDER  BY q.queue_id;

-- 2) ห้องแชท : ระบบสร้างและจับคู่เภสัชกรให้อัตโนมัติ (คิว 1 - 1 ห้องแชท)
--    DDL เก็บ status ได้แค่ open / closed  สถานะตามรายงาน (chat_state) คำนวณจาก
--    status ของห้อง + มีข้อความจากเภสัชกรหรือยัง + สถานะคิว
--    ตัวนับเวลาคำนวณจากข้อความล่าสุดของห้อง :
--      ข้อความล่าสุดมาจากคนไข้ (หรือยังไม่มีข้อความ) -> เภสัชกรต้องตอบภายใน 10 นาที
--      ข้อความล่าสุดมาจากเภสัชกร                  -> คนไข้ต้องตอบภายใน 5 นาที
SELECT x.chat_id, x.queue_id, x.pharmacist, x.status, x.chat_state,
       CASE WHEN x.status = 'open' THEN x.turn END AS must_reply,
       TO_CHAR(x.timer_start, 'HH24:MI:SS') AS timer_start,
       CASE WHEN x.status = 'open' THEN
            TO_CHAR(x.timer_start + NUMTODSINTERVAL(CASE x.turn WHEN 'pharmacist' THEN 10 ELSE 5 END, 'MINUTE'),
                    'HH24:MI:SS') END AS reply_deadline
FROM  (SELECT c.chat_id, c.queue_id, f.first_name AS pharmacist, c.status,
              CASE WHEN c.status = 'open' AND EXISTS (SELECT 1 FROM chat_message m
                                                      WHERE  m.chat_id = c.chat_id AND m.sender_type = 'pharmacist')
                        THEN 'ระหว่างปรึกษา'
                   WHEN c.status = 'open'      THEN 'รอตอบกลับ'
                   WHEN q.status = 'cancelled' THEN 'ให้คำปรึกษาไม่สำเร็จ'
                   ELSE 'ปิดห้องแชทแล้ว'
              END AS chat_state,
              NVL((SELECT CASE m.sender_type WHEN 'pharmacist' THEN 'patient' ELSE 'pharmacist' END
                   FROM   chat_message m
                   WHERE  m.message_id = (SELECT MAX(m2.message_id) FROM chat_message m2
                                          WHERE  m2.chat_id = c.chat_id)), 'pharmacist') AS turn,
              NVL((SELECT m.sent_at FROM chat_message m
                   WHERE  m.message_id = (SELECT MAX(m2.message_id) FROM chat_message m2
                                          WHERE  m2.chat_id = c.chat_id)), c.started_at) AS timer_start
       FROM   chat_room c
              JOIN consult_queue q ON q.queue_id = c.queue_id
              JOIN pharmacist f    ON f.pharmacist_id = c.pharmacist_id) x
ORDER  BY x.chat_id;

-- 2.1) ภาระงานของเภสัชกร : ถือห้อง open ได้คนละ 1 ห้อง (MAX_OPEN_CHATS)
--      การจับคู่เลือกคนที่ open_chats น้อยที่สุด ถ้าทุกคนเต็ม คิวใหม่จะรอจับคู่
SELECT f.pharmacist_id, f.first_name AS pharmacist,
       COUNT(CASE WHEN c.status = 'open' THEN 1 END) AS open_chats,
       COUNT(c.chat_id) AS total_chats
FROM   pharmacist f
       LEFT JOIN chat_room c ON c.pharmacist_id = f.pharmacist_id
WHERE  f.pharmacy_id = 1
GROUP  BY f.pharmacist_id, f.first_name
ORDER  BY f.pharmacist_id;

-- 2.2) คิวที่รอจับคู่ (status = waiting ยังไม่มีห้องแชท) พร้อมลำดับที่ในคิว
--      ลำดับ : VIP ก่อนสมาชิกทั่วไป แล้วตามเวลาที่เข้าคิว  (ไม่มีแถว = ไม่มีใครรอ)
SELECT ROW_NUMBER() OVER (ORDER BY CASE q.member_type WHEN 'vip' THEN 0 ELSE 1 END,
                                   q.entered_at, q.queue_id) AS position,
       q.queue_id, q.queue_no, p.first_name AS patient, q.member_type, q.status,
       TO_CHAR(q.entered_at, 'HH24:MI:SS') AS entered_at
FROM   consult_queue q
       JOIN patient p ON p.patient_id = q.patient_id
WHERE  q.status = 'waiting' AND q.pharmacy_id = 1
ORDER  BY position;

-- 3) ข้อความในห้องแชท
SELECT m.message_id, m.chat_id, m.sender_type, m.content,
       TO_CHAR(m.sent_at, 'HH24:MI:SS') AS sent_at
FROM   chat_message m
ORDER  BY m.message_id;

-- 4) ใบสั่งยา + รายละเอียด (batch_id = ล็อตที่ถูกตัดสต็อก จะมีค่าหลังคนไข้สั่งซื้อ)
SELECT r.prescription_id, r.chat_id, p.first_name AS patient, f.first_name AS pharmacist,
       TO_CHAR(r.prescribed_date, 'YYYY-MM-DD') AS prescribed_date, r.prescribed_time,
       d.line_no, g.name AS drug, d.quantity, d.dosage, d.usage_note, d.batch_id
FROM   prescription r
       JOIN prescription_detail d ON d.prescription_id = r.prescription_id
       JOIN drug       g ON g.drug_id       = d.drug_id
       JOIN patient    p ON p.patient_id    = r.patient_id
       JOIN pharmacist f ON f.pharmacist_id = r.pharmacist_id
ORDER  BY r.prescription_id, d.line_no;

-- 5) คำสั่งซื้อ (status: pending_payment -> paid)
SELECT o.order_id, o.patient_id, o.prescription_id, o.status, o.shipping_address,
       TO_CHAR(o.ordered_at, 'HH24:MI:SS') AS ordered_at
FROM   orders o
ORDER  BY o.order_id;

-- 6) รายละเอียดคำสั่งซื้อ (drug_name, unit_price เป็น snapshot ณ วันที่สั่ง)
SELECT d.order_id, d.line_no, d.drug_id, d.drug_name, d.quantity, d.unit_price,
       d.quantity * d.unit_price AS line_total
FROM   order_detail d
ORDER  BY d.order_id, d.line_no;

-- 7) การชำระเงิน + หลักฐาน (qr_code หรือ transfer_slip อย่างใดอย่างหนึ่ง)
SELECT y.payment_id, y.order_id, y.method, y.status,
       TO_CHAR(y.paid_at, 'HH24:MI:SS') AS paid_at,
       q.amount AS qr_amount, s.transaction_no, s.bank_name, s.amount AS slip_amount
FROM   payment y
       LEFT JOIN qr_code       q ON q.payment_id = y.payment_id
       LEFT JOIN transfer_slip s ON s.payment_id = y.payment_id
ORDER  BY y.payment_id;

-- 8) ใบเสร็จ + รายละเอียด
SELECT r.receipt_id, r.receipt_no, r.order_id, ph.name AS pharmacy,
       d.line_no, g.name AS drug, d.quantity, d.unit_price, d.total_amount
FROM   receipt r
       JOIN receipt_detail d ON d.receipt_id   = r.receipt_id
       JOIN drug           g ON g.drug_id      = d.drug_id
       JOIN pharmacy      ph ON ph.pharmacy_id = r.pharmacy_id
ORDER  BY r.receipt_id, d.line_no;

-- 9) สต็อกยา (ร้านที่ 1) : ยา A ก่อนทำ = 20, หลังสั่ง 2 เม็ด = 18
SELECT g.drug_id, g.name, b.lot_no, TO_CHAR(b.expiry_date, 'YYYY-MM-DD') AS expiry_date,
       b.quantity, TO_CHAR(b.updated_at, 'HH24:MI:SS') AS updated_at
FROM   drug g
       JOIN drug_batch b ON b.drug_id = g.drug_id
WHERE  g.pharmacy_id = 1
ORDER  BY g.drug_id, b.expiry_date;

-- 10) สรุปจำนวนแถวต่อตาราง (ใช้เทียบก่อน/หลังกรณีปฏิเสธ : ตัวเลขต้องไม่เปลี่ยน)
--     ปฏิเสธที่ฝั่งเภสัชกร : prescription / prescription_detail ไม่เพิ่ม
--     ปฏิเสธตอนสั่งซื้อ     : orders / order_detail ไม่เพิ่ม และสต็อก (ข้อ 9) ไม่เปลี่ยน
SELECT 'consult_queue' AS table_name, COUNT(*) AS row_count FROM consult_queue UNION ALL
SELECT 'chat_room',           COUNT(*) FROM chat_room           UNION ALL
SELECT 'chat_message',        COUNT(*) FROM chat_message        UNION ALL
SELECT 'prescription',        COUNT(*) FROM prescription        UNION ALL
SELECT 'prescription_detail', COUNT(*) FROM prescription_detail UNION ALL
SELECT 'orders',              COUNT(*) FROM orders              UNION ALL
SELECT 'order_detail',        COUNT(*) FROM order_detail        UNION ALL
SELECT 'payment',             COUNT(*) FROM payment             UNION ALL
SELECT 'qr_code',             COUNT(*) FROM qr_code             UNION ALL
SELECT 'transfer_slip',       COUNT(*) FROM transfer_slip       UNION ALL
SELECT 'receipt',             COUNT(*) FROM receipt             UNION ALL
SELECT 'receipt_detail',      COUNT(*) FROM receipt_detail;
