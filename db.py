"""การเชื่อมต่อ Oracle และตัวช่วยอ่านข้อมูล (SELECT)

ตั้งค่าผ่าน environment variable ได้ ถ้าไม่ตั้งจะใช้ค่าของ schema demo
    ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN
"""
import os

import oracledb

DB_USER = os.environ.get("ORACLE_USER", "pharmacy_demo")
DB_PASSWORD = os.environ.get("ORACLE_PASSWORD", "pharmacy_demo")
DB_DSN = os.environ.get("ORACLE_DSN", "localhost:1521/XEPDB1")

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN,
                                     min=1, max=5, increment=1)
    return _pool


def connect():
    """ยืม connection จาก pool : python-oracledb ไม่ autocommit
    ทุกคำสั่งจึงอยู่ใน transaction เดียวกันจนกว่าจะ commit() หรือ rollback()"""
    return get_pool().acquire()


def dict_rows(cur):
    """ให้ cursor คืนแต่ละแถวเป็น dict ที่ key เป็นชื่อคอลัมน์ตัวพิมพ์เล็ก"""
    cols = [d[0].lower() for d in cur.description]
    cur.rowfactory = lambda *vals: dict(zip(cols, vals))


def query(sql, **binds):
    """SELECT หลายแถว (ส่งค่าด้วย bind variable เท่านั้น)"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, binds)
            dict_rows(cur)
            return cur.fetchall()


def query_one(sql, **binds):
    rows = query(sql, **binds)
    return rows[0] if rows else None
