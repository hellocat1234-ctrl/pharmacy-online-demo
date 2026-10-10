-- =====================================================================
-- reset.sql : ล้างข้อมูลที่เกิดจากการซ้อม Demo แล้วคืนสต็อกเป็นค่าตั้งต้น
-- ไม่ลบข้อมูลหลัก (ร้านยา เภสัชกร คนไข้ ที่อยู่ ยา) แต่คืนค่าร้านที่เภสัชกรสังกัด
-- รันซ้ำได้ทุกครั้งก่อนซ้อม (ปิดหน้าเว็บที่ค้างอยู่ หรือกลับไปหน้าแรกหลังรัน)
-- =====================================================================
SET DEFINE OFF;

-- 1) ลบข้อมูลธุรกรรม เรียงจากตารางลูกไปตารางแม่ (ตามทิศทาง FK)
--    (ห้ามเขียนคอมเมนต์ต่อท้าย ; ในบรรทัดเดียวกัน เพราะ SQL*Plus จะไม่รันคำสั่งนั้น)
--    receipt_detail -> receipt -> orders
--    qr_code, transfer_slip -> payment -> orders
--    order_detail -> orders -> prescription -> chat_room -> consult_queue
--    prescription_detail -> prescription,  chat_message -> chat_room
DELETE FROM receipt_detail;
DELETE FROM receipt;
DELETE FROM qr_code;
DELETE FROM transfer_slip;
DELETE FROM payment;
DELETE FROM order_detail;
DELETE FROM orders;
DELETE FROM prescription_detail;
DELETE FROM prescription;
DELETE FROM chat_message;
DELETE FROM chat_room;
DELETE FROM consult_queue;

-- 2) คืนสต็อกเป็นค่าตั้งต้น (ต้องตรงกับ seed.sql)
UPDATE drug_batch
SET    quantity = CASE batch_id
                      WHEN 1 THEN 20     -- ยา A
                      WHEN 2 THEN 100
                      WHEN 3 THEN 200
                      WHEN 4 THEN 80
                      WHEN 5 THEN 30
                      WHEN 6 THEN 50
                      WHEN 7 THEN 0
                  END,
       updated_at = NULL
WHERE  batch_id BETWEEN 1 AND 7;

-- 2.1) คืนค่าเภสัชกร : ทั้ง 2 คนสังกัดร้านที่ 1 (ร้านเดียวของระบบ) เพื่อให้การจับคู่อัตโนมัติมี 2 ตัวเลือก
UPDATE pharmacist SET pharmacy_id = 1, deleted_at = NULL WHERE pharmacist_id IN (1, 2);

-- 2.2) คืนค่าสมาชิก VIP : คนไข้คนที่ 4 เป็น VIP คนเดียว (ใช้โชว์การแซงคิว)
UPDATE patient SET is_vip = CASE patient_id WHEN 4 THEN 1 ELSE 0 END WHERE patient_id BETWEEN 1 AND 4;

COMMIT;

-- 3) ให้เลขที่เอกสารเริ่มนับ 1 ใหม่ (คิว/คำสั่งซื้อ/ใบเสร็จ จะได้เลขเดิมทุกครั้งที่ซ้อม)
ALTER SEQUENCE seq_consult_queue RESTART START WITH 1;
ALTER SEQUENCE seq_chat_room     RESTART START WITH 1;
ALTER SEQUENCE seq_chat_message  RESTART START WITH 1;
ALTER SEQUENCE seq_prescription  RESTART START WITH 1;
ALTER SEQUENCE seq_orders        RESTART START WITH 1;
ALTER SEQUENCE seq_receipt       RESTART START WITH 1;
ALTER SEQUENCE seq_payment       RESTART START WITH 1;
ALTER SEQUENCE seq_qr_code       RESTART START WITH 1;
ALTER SEQUENCE seq_transfer_slip RESTART START WITH 1;

-- ตรวจผล : ยา A ต้องกลับมาเป็น 20
SELECT g.name, b.lot_no, b.quantity
FROM   drug g JOIN drug_batch b ON b.drug_id = g.drug_id
WHERE  g.pharmacy_id = 1
ORDER  BY g.drug_id, b.expiry_date;

-- ตรวจผล : เภสัชกร 2 คนต้องอยู่ร้านที่ 1
SELECT pharmacist_id, first_name, pharmacy_id FROM pharmacist ORDER BY pharmacist_id;

-- ตรวจผล : ต้องมีคนไข้ 4 คน และคนที่ 4 เป็น VIP (ถ้าได้ไม่ครบ 4 แถว ให้รัน seed.sql ใหม่)
SELECT patient_id, first_name, is_vip FROM patient ORDER BY patient_id;
