-- =====================================================================
-- seed.sql : ข้อมูลตั้งต้นสำหรับ Demo (รันหลัง 01_schema.sql)
-- รันซ้ำได้ : ลบข้อมูลทุกตารางใน schema นี้ก่อนแล้วใส่ใหม่
-- ใช้กับ schema pharmacy_demo เท่านั้น (ข้อมูลทั้งหมดเป็นข้อมูลสมมติ)
--
-- ข้อมูลที่ได้
--   ร้านยา 1 ร้าน (ระบบมีร้านเดียว), เภสัชกร 2 คนสังกัดร้านนี้, คนไข้ 4 คน (คนที่ 4 เป็น VIP)
--   ยา 6 รายการ : "ยา A" คงเหลือ 20 เม็ด (ล็อตเดียว)
--   ตารางธุรกรรม (คิว แชท ใบสั่งยา คำสั่งซื้อ ชำระเงิน ใบเสร็จ) ว่างทั้งหมด
-- =====================================================================
SET DEFINE OFF;

-- ลบจากตารางลูกไปตารางแม่ (ตามทิศทาง FK)
DELETE FROM review;
DELETE FROM delivery;
DELETE FROM tax_invoice_detail;
DELETE FROM tax_invoice;
DELETE FROM refund;
DELETE FROM transfer_slip;
DELETE FROM qr_code;
DELETE FROM payment;
DELETE FROM receipt_detail;
DELETE FROM receipt;
DELETE FROM order_detail;
DELETE FROM orders;
DELETE FROM prescription_detail;
DELETE FROM prescription;
DELETE FROM chat_message;
DELETE FROM chat_room;
DELETE FROM consult_queue;
DELETE FROM patient_allergy;
DELETE FROM drug_batch;
DELETE FROM drug;
DELETE FROM address;
DELETE FROM patient;
DELETE FROM pharmacist;
DELETE FROM pharmacy;

-- 1. ร้านขายยา --------------------------------------------------------
INSERT INTO pharmacy (pharmacy_id, name, address, phone, license_no, opening_hours, open_status)
VALUES (1, 'ร้านขายยาแมนนี่จัง', '99/1 ถนนมิตรภาพ ตำบลในเมือง อำเภอเมือง จังหวัดขอนแก่น 40000',
        '043-000-111', 'ขย.1-0001/2565', 'ทุกวัน 08:00-20:00', 'open');

-- 2. เภสัชกร (ทั้ง 2 คนสังกัดร้านที่ 1 : ใช้โชว์การจับคู่คนที่ถือห้องแชทน้อยที่สุด) ----
INSERT INTO pharmacist (pharmacist_id, pharmacy_id, first_name, last_name, email, password,
                        license_no, work_history, work_duration)
VALUES (1, 1, 'สมชาย', 'ใจดี', 'somchai@jaidee-pharmacy.example', 'sample-password-1',
        'ภ.10001', 'เภสัชกรโรงพยาบาล 5 ปี', '5 ปี 7 เดือน');

INSERT INTO pharmacist (pharmacist_id, pharmacy_id, first_name, last_name, email, password,
                        license_no, work_history, work_duration)
VALUES (2, 1, 'วิภา', 'รักษ์สุข', 'wipa@jaidee-pharmacy.example', 'sample-password-2',
        'ภ.10002', 'เภสัชกรร้านยา 3 ปี', '3 ปี 3 เดือน');

-- 3. คนไข้ ------------------------------------------------------------
INSERT INTO patient (patient_id, first_name, last_name, birth_date, email, password, phone,
                     weight_kg, height_cm, treatment_right, is_vip, chronic_disease)
VALUES (1, 'สมหญิง', 'รักดี', DATE '1998-05-12', 'somying@mail.example', 'sample-password-3',
        '080-000-0001', 52.5, 160, 'บัตรทอง', 0, 'ภูมิแพ้อากาศ');

INSERT INTO patient (patient_id, first_name, last_name, birth_date, email, password, phone,
                     weight_kg, height_cm, treatment_right, is_vip, chronic_disease)
VALUES (2, 'ธนากร', 'มั่นคง', DATE '1985-11-03', 'thanakorn@mail.example', 'sample-password-4',
        '080-000-0002', 78, 172, 'ประกันสังคม', 0, 'ความดันโลหิตสูง');

INSERT INTO patient (patient_id, first_name, last_name, birth_date, email, password, phone,
                     weight_kg, height_cm, treatment_right, is_vip, chronic_disease)
VALUES (3, 'มาลี', 'ศรีสุข', DATE '2001-02-20', 'malee@mail.example', 'sample-password-5',
        '080-000-0003', 48, 155, NULL, 0, NULL);

-- คนไข้ VIP : ใช้โชว์การแซงคิว (member_type = 'vip' ได้ลำดับก่อนสมาชิกทั่วไป)
INSERT INTO patient (patient_id, first_name, last_name, birth_date, email, password, phone,
                     weight_kg, height_cm, treatment_right, is_vip, chronic_disease)
VALUES (4, 'วีระ', 'ทองดี', DATE '1975-08-09', 'weera@mail.example', 'sample-password-6',
        '080-000-0004', 70, 168, 'ข้าราชการ', 1, 'เบาหวาน');

-- 4. ที่อยู่ (ใช้เป็นค่าเริ่มต้นของที่อยู่จัดส่ง) -------------------------
INSERT INTO address (address_id, patient_id, house_no, moo, soi, road, subdistrict, district, province, postal_code, is_default)
VALUES (1, 1, '12/3', '4', NULL, 'มิตรภาพ', 'ศิลา', 'เมืองขอนแก่น', 'ขอนแก่น', '40000', 1);

INSERT INTO address (address_id, patient_id, house_no, moo, soi, road, subdistrict, district, province, postal_code, is_default)
VALUES (2, 2, '88/9', NULL, 'สุขใจ', 'โพศรี', 'หมากแข้ง', 'เมืองอุดรธานี', 'อุดรธานี', '41000', 1);

INSERT INTO address (address_id, patient_id, house_no, moo, soi, road, subdistrict, district, province, postal_code, is_default)
VALUES (3, 3, '7', '2', NULL, NULL, 'ภูเวียง', 'ภูเวียง', 'ขอนแก่น', '40150', 1);

INSERT INTO address (address_id, patient_id, house_no, moo, soi, road, subdistrict, district, province, postal_code, is_default)
VALUES (4, 4, '201/5', NULL, NULL, 'ศรีจันทร์', 'ในเมือง', 'เมืองขอนแก่น', 'ขอนแก่น', '40000', 1);

-- 5. ยา (ราคาต่อ 1 หน่วย) ---------------------------------------------
INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (1, 1, 'ยา A (พาราเซตามอล 500 mg)', 'ยาบรรเทาปวด ลดไข้', 'ยาแก้ปวดลดไข้', 'เม็ด',
        'ครั้งละ 1-2 เม็ด ทุก 4-6 ชั่วโมงเมื่อมีอาการ', 'ไม่ควรใช้เกิน 8 เม็ดต่อวัน', 2.00);

INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (2, 1, 'ลอราทาดีน 10 mg', 'ยาแก้แพ้ชนิดไม่ง่วง', 'ยาแก้แพ้', 'เม็ด',
        'วันละ 1 เม็ด', 'ผู้ป่วยโรคตับควรปรึกษาเภสัชกรก่อนใช้', 5.00);

INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (3, 1, 'อะม็อกซีซิลลิน 500 mg', 'ยาปฏิชีวนะกลุ่มเพนนิซิลลิน', 'ยาปฏิชีวนะ', 'แคปซูล',
        'ครั้งละ 1 แคปซูล วันละ 3 ครั้ง หลังอาหาร', 'ห้ามใช้ในผู้ที่แพ้ยากลุ่มเพนนิซิลลิน', 6.00);

INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (4, 1, 'ยาธาตุน้ำขาว 200 มล.', 'บรรเทาอาการท้องอืด ท้องเฟ้อ', 'ยาระบบทางเดินอาหาร', 'ยาน้ำ',
        'ครั้งละ 1-2 ช้อนโต๊ะ วันละ 3 ครั้ง ก่อนอาหาร', 'เขย่าขวดก่อนใช้', 35.00);

INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (5, 1, 'ผงเกลือแร่ ORS', 'ทดแทนการเสียน้ำจากท้องเสีย', 'ยาระบบทางเดินอาหาร', 'ผง',
        'ละลายน้ำ 1 ซองต่อน้ำ 1 แก้ว จิบแทนน้ำ', 'ผู้ป่วยโรคไตควรปรึกษาเภสัชกรก่อนใช้', 5.00);

INSERT INTO drug (drug_id, pharmacy_id, name, description, usage_category, dosage_form, usage_method, precaution, price)
VALUES (6, 1, 'คลอร์เฟนิรามีน 4 mg', 'ยาแก้แพ้ ลดน้ำมูก', 'ยาแก้แพ้', 'เม็ด',
        'ครั้งละ 1 เม็ด วันละ 3 ครั้ง', 'ทำให้ง่วงซึม ไม่ควรขับรถ', 1.00);

-- 6. ล็อตยา = สต็อก ---------------------------------------------------
--    ค่า quantity ตรงนี้คือ "ค่าตั้งต้น" ที่ reset.sql ใช้คืนสต็อก (ถ้าแก้ที่นี่ต้องแก้ที่ reset.sql ด้วย)
-- ยา A = 20 เม็ด (ล็อตเดียว)
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (1, 1, 'A2601', DATE '2027-12-31', 20);
-- ลอราทาดีนมี 2 ล็อต หมดอายุไม่พร้อมกัน (ใช้โชว์การเลือกล็อตที่หมดอายุก่อน)
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (2, 2, 'L2601', DATE '2027-06-30', 100);
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (3, 2, 'L2602', DATE '2028-03-31', 200);
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (4, 3, 'X2601', DATE '2027-09-30', 80);
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (5, 4, 'M2601', DATE '2027-08-31', 30);
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (6, 5, 'R2601', DATE '2028-01-31', 50);
-- คลอร์เฟนิรามีน หมดสต็อก
INSERT INTO drug_batch (batch_id, drug_id, lot_no, expiry_date, quantity) VALUES (7, 6, 'C2601', DATE '2027-10-31', 0);

COMMIT;

-- SEQUENCE : ข้อมูลหลักใส่ id ตายตัว จึงเลื่อน sequence ให้พ้น id ที่ใช้ไปแล้ว
--            ส่วนตารางธุรกรรมเริ่มนับ 1 ใหม่ (ALTER SEQUENCE ... RESTART ใช้ได้ตั้งแต่ Oracle 18c)
ALTER SEQUENCE seq_pharmacy      RESTART START WITH 2;
ALTER SEQUENCE seq_pharmacist    RESTART START WITH 3;
ALTER SEQUENCE seq_patient       RESTART START WITH 5;
ALTER SEQUENCE seq_address       RESTART START WITH 5;
ALTER SEQUENCE seq_drug          RESTART START WITH 7;
ALTER SEQUENCE seq_drug_batch    RESTART START WITH 8;
ALTER SEQUENCE seq_consult_queue RESTART START WITH 1;
ALTER SEQUENCE seq_chat_room     RESTART START WITH 1;
ALTER SEQUENCE seq_chat_message  RESTART START WITH 1;
ALTER SEQUENCE seq_prescription  RESTART START WITH 1;
ALTER SEQUENCE seq_orders        RESTART START WITH 1;
ALTER SEQUENCE seq_receipt       RESTART START WITH 1;
ALTER SEQUENCE seq_payment       RESTART START WITH 1;
ALTER SEQUENCE seq_qr_code       RESTART START WITH 1;
ALTER SEQUENCE seq_transfer_slip RESTART START WITH 1;
