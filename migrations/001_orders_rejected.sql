-- =====================================================================
-- 001_orders_rejected.sql : คำสั่งซื้อที่ระบบปฏิเสธเหลือร่องรอยเป็น status = 'rejected'
-- รันหลัง sql/01_schema.sql  รันซ้ำได้ (ตรวจสภาพปัจจุบันก่อนแก้ทุกขั้น) ไม่ลบข้อมูล
--
--   (1) chk_orders_status      : เพิ่มค่า 'rejected' เข้า CHECK เดิม (ชื่อ constraint เดิม)
--   (2) uq_orders_prescription : เดิมเป็น UNIQUE constraint บน prescription_id
--       เปลี่ยนเป็น unique index แบบมีเงื่อนไข (ชื่อเดิม) : แถว rejected ไม่กินสิทธิ์ใบสั่งยา
--       ใบสั่งยา 1 ใบยังมีคำสั่งซื้อที่ไม่ใช่ rejected ได้ใบเดียวเหมือนเดิม
-- =====================================================================
SET DEFINE OFF;
SET SERVEROUTPUT ON;

-- (1) CHECK ของ orders.status
DECLARE
    v_condition  user_constraints.search_condition_vc%TYPE;
BEGIN
    SELECT MAX(search_condition_vc) INTO v_condition
    FROM   user_constraints
    WHERE  table_name = 'ORDERS' AND constraint_name = 'CHK_ORDERS_STATUS';

    IF v_condition LIKE '%''rejected''%' THEN
        DBMS_OUTPUT.PUT_LINE('001 (1) chk_orders_status รองรับ rejected อยู่แล้ว : ข้าม');
    ELSE
        IF v_condition IS NOT NULL THEN
            EXECUTE IMMEDIATE 'ALTER TABLE orders DROP CONSTRAINT chk_orders_status';
        END IF;
        EXECUTE IMMEDIATE q'[ALTER TABLE orders ADD CONSTRAINT chk_orders_status CHECK (status IN
            ('pending_payment', 'paid', 'preparing', 'shipped', 'completed', 'cancelled', 'rejected'))]';
        DBMS_OUTPUT.PUT_LINE('001 (1) chk_orders_status : เพิ่มค่า rejected แล้ว');
    END IF;
END;
/

-- (2) ใบสั่งยา 1 - 1 คำสั่งซื้อ นับเฉพาะคำสั่งซื้อที่ไม่ใช่ rejected
DECLARE
    v_constraints  NUMBER;
    v_index_type   user_indexes.index_type%TYPE;
BEGIN
    SELECT COUNT(*) INTO v_constraints
    FROM   user_constraints
    WHERE  table_name = 'ORDERS' AND constraint_name = 'UQ_ORDERS_PRESCRIPTION';
    IF v_constraints > 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE orders DROP CONSTRAINT uq_orders_prescription DROP INDEX';
        DBMS_OUTPUT.PUT_LINE('001 (2) ลบ UNIQUE constraint uq_orders_prescription เดิมแล้ว');
    END IF;

    SELECT MAX(index_type) INTO v_index_type
    FROM   user_indexes
    WHERE  table_name = 'ORDERS' AND index_name = 'UQ_ORDERS_PRESCRIPTION';
    IF v_index_type LIKE 'FUNCTION-BASED%' THEN
        DBMS_OUTPUT.PUT_LINE('001 (2) uq_orders_prescription เป็น unique index แบบมีเงื่อนไขอยู่แล้ว : ข้าม');
    ELSE
        IF v_index_type IS NOT NULL THEN
            EXECUTE IMMEDIATE 'DROP INDEX uq_orders_prescription';
        END IF;
        EXECUTE IMMEDIATE q'[CREATE UNIQUE INDEX uq_orders_prescription
            ON orders (CASE WHEN status <> 'rejected' THEN prescription_id END)]';
        DBMS_OUTPUT.PUT_LINE('001 (2) สร้าง unique index uq_orders_prescription แบบมีเงื่อนไขแล้ว');
    END IF;
END;
/

-- ตรวจผล
SELECT constraint_name, search_condition_vc
FROM   user_constraints
WHERE  table_name = 'ORDERS' AND constraint_name = 'CHK_ORDERS_STATUS';

SELECT i.index_name, i.uniqueness, i.index_type, e.column_expression
FROM   user_indexes i
       LEFT JOIN user_ind_expressions e ON e.index_name = i.index_name
WHERE  i.table_name = 'ORDERS' AND i.index_name = 'UQ_ORDERS_PRESCRIPTION';
