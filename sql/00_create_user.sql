-- =====================================================================
-- สร้าง schema แยกสำหรับ Demo (รันครั้งเดียว ด้วยสิทธิ์ SYSDBA / SYSTEM)
--   sqlplus / as sysdba @sql\00_create_user.sql
-- ใช้ schema แยกเพื่อไม่ให้ข้อมูล Demo ปนกับ schema อื่นในเครื่อง
-- =====================================================================
ALTER SESSION SET CONTAINER = XEPDB1;

CREATE USER pharmacy_demo IDENTIFIED BY pharmacy_demo
    DEFAULT TABLESPACE users
    QUOTA UNLIMITED ON users;

GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE TO pharmacy_demo;

EXIT
