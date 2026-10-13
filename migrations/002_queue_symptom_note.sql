-- =====================================================================
-- 002_queue_symptom_note.sql : อาการเบื้องต้นที่คนไข้พิมพ์ตอนเข้าคิว
-- รันหลัง sql/01_schema.sql  รันซ้ำได้ (มีคอลัมน์แล้วจะข้าม) ไม่ลบข้อมูล
--
--   consult_queue.symptom_note VARCHAR2(500 CHAR) NULL ได้
--   ใช้ 500 CHAR เหมือนคอลัมน์ข้อความภาษาไทยอื่นใน DDL (เช่น orders.shipping_address)
--   ถ้าเป็น VARCHAR2(500) เฉย ๆ จะนับเป็น byte และภาษาไทยจะใส่ได้ราว 166 ตัวอักษร
-- =====================================================================
SET DEFINE OFF;
SET SERVEROUTPUT ON;

DECLARE
    v_columns  NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_columns
    FROM   user_tab_columns
    WHERE  table_name = 'CONSULT_QUEUE' AND column_name = 'SYMPTOM_NOTE';
    IF v_columns > 0 THEN
        DBMS_OUTPUT.PUT_LINE('002 consult_queue.symptom_note มีอยู่แล้ว : ข้าม');
    ELSE
        EXECUTE IMMEDIATE 'ALTER TABLE consult_queue ADD (symptom_note VARCHAR2(500 CHAR))';
        DBMS_OUTPUT.PUT_LINE('002 เพิ่ม consult_queue.symptom_note แล้ว');
    END IF;
END;
/

-- ตรวจผล
SELECT column_name, data_type, char_length, char_used, nullable
FROM   user_tab_columns
WHERE  table_name = 'CONSULT_QUEUE' AND column_name = 'SYMPTOM_NOTE';
