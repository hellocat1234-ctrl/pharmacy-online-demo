-- =====================================================================
-- 003_drop_symptom_note.sql : ยกเลิกคอลัมน์อาการเบื้องต้นของคิว (consult_queue.symptom_note)
-- ระบบกลับไปใช้การจับคู่อัตโนมัติ ตาราง consult_queue จึงกลับไปตรงกับ sql/01_schema.sql
-- รันซ้ำได้ : ตรวจก่อนว่ามีคอลัมน์ ถ้าไม่มี (เช่น schema ที่สร้างใหม่) จะข้าม
-- ลบเฉพาะคอลัมน์นี้ ไม่แตะแถวหรือคอลัมน์อื่นของ consult_queue
-- (เดิมคอลัมน์นี้เพิ่มโดย 002_queue_symptom_note.sql ซึ่งถูกถอดออกแล้ว จึงไม่มีไฟล์ 002)
-- =====================================================================
SET DEFINE OFF;
SET SERVEROUTPUT ON;

DECLARE
    v_columns  NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_columns
    FROM   user_tab_columns
    WHERE  table_name = 'CONSULT_QUEUE' AND column_name = 'SYMPTOM_NOTE';
    IF v_columns = 0 THEN
        DBMS_OUTPUT.PUT_LINE('003 consult_queue ไม่มีคอลัมน์ symptom_note อยู่แล้ว : ข้าม');
    ELSE
        EXECUTE IMMEDIATE 'ALTER TABLE consult_queue DROP COLUMN symptom_note';
        DBMS_OUTPUT.PUT_LINE('003 ลบ consult_queue.symptom_note แล้ว');
    END IF;
END;
/

-- ตรวจผล : คอลัมน์ของ consult_queue ต้องเหลือ 8 คอลัมน์ตาม DDL เดิม
SELECT column_name, data_type
FROM   user_tab_columns
WHERE  table_name = 'CONSULT_QUEUE'
ORDER  BY column_id;
