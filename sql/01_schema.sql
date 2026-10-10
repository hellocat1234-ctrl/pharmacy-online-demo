-- =====================================================================
-- ระบบร้านขายยาออนไลน์ : DDL Script (ฉบับปรับปรุงสู่ Production)
-- DBMS     : Oracle Database 11g ขึ้นไป (รันใน SQL Developer ด้วย F5)
-- ตารางใหม่ : address, drug_batch, patient_allergy (รวม 24 ตาราง)
--
-- หมายเหตุ Oracle
--  - ไม่มี AUTO_INCREMENT : ใช้ SEQUENCE ท้ายไฟล์ แล้ว INSERT ด้วย seq_xxx.NEXTVAL
--  - ไม่มี ENUM            : ใช้ VARCHAR2 + CHECK (... IN (...))
--  - ไม่มี BOOLEAN         : ใช้ NUMBER(1) + CHECK (... IN (0,1))
--  - FK ที่ไม่เขียน ON DELETE = ห้ามลบแม่ถ้ายังมีลูก (เทียบเท่า RESTRICT)
--  - Oracle ไม่มี ON UPDATE CASCADE (PK ไม่ควรถูกแก้อยู่แล้ว)
--  - updated_at ต้องให้โปรแกรมใส่ค่าเองตอน UPDATE
-- =====================================================================
SELECT table_name FROM user_tables;
-- ---------------------------------------------------------------------
-- 1. ร้านขายยา
-- ---------------------------------------------------------------------
CREATE TABLE pharmacy (
    pharmacy_id    NUMBER(10)          NOT NULL,
    name           VARCHAR2(150 CHAR)  NOT NULL,
    address        VARCHAR2(500 CHAR)  NOT NULL,
    phone          VARCHAR2(20)        NOT NULL,
    license_no     VARCHAR2(30)        NOT NULL,
    opening_hours  VARCHAR2(100 CHAR)  NOT NULL,
    open_status    VARCHAR2(20)        DEFAULT 'open' NOT NULL,
    created_at     TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP,
    CONSTRAINT pk_pharmacy PRIMARY KEY (pharmacy_id),
    CONSTRAINT uq_pharmacy_license UNIQUE (license_no),
    CONSTRAINT chk_pharmacy_status CHECK (open_status IN ('open', 'closed'))
);

-- ---------------------------------------------------------------------
-- 2. เภสัชกร
--    อีเมลเก็บค่าเดียว + UNIQUE
-- ---------------------------------------------------------------------
CREATE TABLE pharmacist (
    pharmacist_id  NUMBER(10)           NOT NULL,
    pharmacy_id    NUMBER(10)           NOT NULL,
    first_name     VARCHAR2(100 CHAR)   NOT NULL,
    last_name      VARCHAR2(100 CHAR)   NOT NULL,
    email          VARCHAR2(255)        NOT NULL,
    password       VARCHAR2(255)        NOT NULL,
    license_no     VARCHAR2(30)         NOT NULL,
    work_history   VARCHAR2(1000 CHAR),
    work_duration  VARCHAR2(50 CHAR),
    created_at     TIMESTAMP            DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP,
    deleted_at     TIMESTAMP,
    CONSTRAINT pk_pharmacist PRIMARY KEY (pharmacist_id),
    CONSTRAINT uq_pharmacist_email   UNIQUE (email),
    CONSTRAINT uq_pharmacist_license UNIQUE (license_no),
    CONSTRAINT fk_pharmacist_pharmacy FOREIGN KEY (pharmacy_id)
        REFERENCES pharmacy (pharmacy_id)
);

-- ---------------------------------------------------------------------
-- 3. คนไข้
--    อีเมล/เบอร์โทรเก็บค่าเดียว, โรคประจำตัวเป็นข้อความ
--    อายุไม่เก็บ (คำนวณจากวันเกิด), ที่อยู่ย้ายไปตาราง address
--    ประวัติแพ้ยาย้ายไปตาราง patient_allergy
-- ---------------------------------------------------------------------
CREATE TABLE patient (
    patient_id       NUMBER(10)           NOT NULL,
    first_name       VARCHAR2(100 CHAR)   NOT NULL,
    last_name        VARCHAR2(100 CHAR)   NOT NULL,
    birth_date       DATE                 NOT NULL,
    email            VARCHAR2(255)        NOT NULL,
    password         VARCHAR2(255)        NOT NULL,
    phone            VARCHAR2(20)         NOT NULL,
    weight_kg        NUMBER(5,2),
    height_cm        NUMBER(5,2),
    treatment_right  VARCHAR2(100 CHAR),
    is_vip           NUMBER(1)            DEFAULT 0 NOT NULL,
    chronic_disease  VARCHAR2(1000 CHAR),
    created_at       TIMESTAMP            DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP,
    deleted_at       TIMESTAMP,
    CONSTRAINT pk_patient PRIMARY KEY (patient_id),
    CONSTRAINT uq_patient_email   UNIQUE (email),
    CONSTRAINT chk_patient_vip    CHECK (is_vip IN (0, 1)),
    CONSTRAINT chk_patient_weight CHECK (weight_kg IS NULL OR weight_kg > 0),
    CONSTRAINT chk_patient_height CHECK (height_cm IS NULL OR height_cm > 0)
);

-- ---------------------------------------------------------------------
-- 4. ที่อยู่ (ตารางใหม่) : คนไข้ 1 - N ที่อยู่
-- ---------------------------------------------------------------------
CREATE TABLE address (
    address_id   NUMBER(10)          NOT NULL,
    patient_id   NUMBER(10)          NOT NULL,
    house_no     VARCHAR2(100 CHAR)  NOT NULL,
    moo          VARCHAR2(20 CHAR),
    soi          VARCHAR2(100 CHAR),
    road         VARCHAR2(100 CHAR),
    subdistrict  VARCHAR2(100 CHAR)  NOT NULL,
    district     VARCHAR2(100 CHAR)  NOT NULL,
    province     VARCHAR2(100 CHAR)  NOT NULL,
    postal_code  CHAR(5)             NOT NULL,
    is_default   NUMBER(1)           DEFAULT 0 NOT NULL,
    created_at   TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP,
    CONSTRAINT pk_address PRIMARY KEY (address_id),
    CONSTRAINT chk_address_default CHECK (is_default IN (0, 1)),
    CONSTRAINT chk_address_postal  CHECK (REGEXP_LIKE(postal_code, '^[0-9]{5}$')),
    CONSTRAINT fk_address_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 5. ยา
--    ตัดวันหมดอายุและจำนวนคงเหลือ (ย้ายไป drug_batch)
-- ---------------------------------------------------------------------
CREATE TABLE drug (
    drug_id          NUMBER(10)           NOT NULL,
    pharmacy_id      NUMBER(10)           NOT NULL,
    name             VARCHAR2(200 CHAR)   NOT NULL,
    description      VARCHAR2(1000 CHAR),
    usage_category   VARCHAR2(100 CHAR)   NOT NULL,
    dosage_form      VARCHAR2(50 CHAR)    NOT NULL,
    usage_method     VARCHAR2(1000 CHAR),
    precaution       VARCHAR2(1000 CHAR),
    price            NUMBER(12,2)         NOT NULL,
    created_at       TIMESTAMP            DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP,
    deleted_at       TIMESTAMP,
    CONSTRAINT pk_drug PRIMARY KEY (drug_id),
    CONSTRAINT chk_drug_price CHECK (price >= 0),
    CONSTRAINT fk_drug_pharmacy FOREIGN KEY (pharmacy_id)
        REFERENCES pharmacy (pharmacy_id)
);

-- ---------------------------------------------------------------------
-- 6. ล็อตยา (ตารางใหม่) : ยา 1 - N ล็อตยา
--    สต็อกห้ามติดลบ
--    uq_batch_drug มีไว้ให้รายละเอียดใบสั่งยาอ้างถึง (ล็อต, ยา) พร้อมกันได้
-- ---------------------------------------------------------------------
CREATE TABLE drug_batch (
    batch_id     NUMBER(10)    NOT NULL,
    drug_id      NUMBER(10)    NOT NULL,
    lot_no       VARCHAR2(50)  NOT NULL,
    expiry_date  DATE          NOT NULL,
    quantity     NUMBER(10)    DEFAULT 0 NOT NULL,
    created_at   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP,
    CONSTRAINT pk_drug_batch PRIMARY KEY (batch_id),
    CONSTRAINT uq_batch_lot  UNIQUE (drug_id, lot_no),
    CONSTRAINT uq_batch_drug UNIQUE (batch_id, drug_id),
    CONSTRAINT chk_batch_quantity CHECK (quantity >= 0),
    CONSTRAINT fk_batch_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id)
);

-- ---------------------------------------------------------------------
-- 7. ประวัติแพ้ยา (ตารางใหม่) : คนไข้ 1 - N ประวัติแพ้ยา N - 1 ยา
--    คนไข้คนหนึ่งบันทึกยาตัวเดียวกันซ้ำไม่ได้
-- ---------------------------------------------------------------------
CREATE TABLE patient_allergy (
    patient_id  NUMBER(10)          NOT NULL,
    allergy_no  NUMBER(5)           NOT NULL,
    drug_id     NUMBER(10)          NOT NULL,
    reaction    VARCHAR2(255 CHAR),
    created_at  TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_patient_allergy PRIMARY KEY (patient_id, allergy_no),
    CONSTRAINT uq_allergy_patient_drug UNIQUE (patient_id, drug_id),
    CONSTRAINT fk_allergy_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_allergy_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id)
);

-- ---------------------------------------------------------------------
-- 8. คิว
-- ---------------------------------------------------------------------
CREATE TABLE consult_queue (
    queue_id     NUMBER(10)    NOT NULL,
    patient_id   NUMBER(10)    NOT NULL,
    pharmacy_id  NUMBER(10)    NOT NULL,
    queue_no     NUMBER(10)    NOT NULL,
    member_type  VARCHAR2(20)  DEFAULT 'general' NOT NULL,
    status       VARCHAR2(20)  DEFAULT 'waiting' NOT NULL,
    entered_at   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP,
    CONSTRAINT pk_consult_queue PRIMARY KEY (queue_id),
    CONSTRAINT chk_queue_no CHECK (queue_no > 0),
    CONSTRAINT chk_queue_member CHECK (member_type IN ('general', 'vip')),
    CONSTRAINT chk_queue_status CHECK (status IN
        ('waiting', 'in_progress', 'completed', 'cancelled')),
    CONSTRAINT fk_queue_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id),
    CONSTRAINT fk_queue_pharmacy FOREIGN KEY (pharmacy_id)
        REFERENCES pharmacy (pharmacy_id)
);

-- ---------------------------------------------------------------------
-- 9. ห้องแชท : คิว 1 - 1 ห้องแชท, เภสัชกร 1 - N ห้องแชท
-- ---------------------------------------------------------------------
CREATE TABLE chat_room (
    chat_id        NUMBER(10)    NOT NULL,
    queue_id       NUMBER(10)    NOT NULL,
    pharmacist_id  NUMBER(10)    NOT NULL,
    status         VARCHAR2(20)  DEFAULT 'open' NOT NULL,
    started_at     TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP,
    CONSTRAINT pk_chat_room PRIMARY KEY (chat_id),
    CONSTRAINT uq_chat_queue UNIQUE (queue_id),
    CONSTRAINT chk_chat_status CHECK (status IN ('open', 'closed')),
    CONSTRAINT fk_chat_queue FOREIGN KEY (queue_id)
        REFERENCES consult_queue (queue_id),
    CONSTRAINT fk_chat_pharmacist FOREIGN KEY (pharmacist_id)
        REFERENCES pharmacist (pharmacist_id)
);

-- ---------------------------------------------------------------------
-- 10. ข้อความในห้องแชท
--     "ผู้ส่ง" เป็นค่าจำกัด เพราะห้องแชทรู้อยู่แล้วว่าคนไข้และเภสัชกรคือใคร
--     ลบห้องแชทแล้วข้อความลบตาม (CASCADE)
-- ---------------------------------------------------------------------
CREATE TABLE chat_message (
    message_id    NUMBER(19)           NOT NULL,
    chat_id       NUMBER(10)           NOT NULL,
    sender_type   VARCHAR2(20)         NOT NULL,
    message_type  VARCHAR2(20)         DEFAULT 'text' NOT NULL,
    content       VARCHAR2(1000 CHAR)  NOT NULL,
    sent_at       TIMESTAMP            DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_chat_message PRIMARY KEY (message_id),
    CONSTRAINT chk_message_sender CHECK (sender_type IN ('patient', 'pharmacist')),
    CONSTRAINT chk_message_type   CHECK (message_type IN ('text', 'image', 'file')),
    CONSTRAINT fk_message_chat FOREIGN KEY (chat_id)
        REFERENCES chat_room (chat_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 11. ใบสั่งยา
--     prescribed_time เก็บเวลาเป็นข้อความรูปแบบ HH:MM (Oracle ไม่มีชนิดข้อมูล TIME)
-- ---------------------------------------------------------------------
CREATE TABLE prescription (
    prescription_id  NUMBER(10)    NOT NULL,
    patient_id       NUMBER(10)    NOT NULL,
    pharmacist_id    NUMBER(10)    NOT NULL,
    chat_id          NUMBER(10)    NOT NULL,
    prescribed_date  DATE          NOT NULL,
    prescribed_time  VARCHAR2(5)   NOT NULL,
    updated_at       TIMESTAMP,
    CONSTRAINT pk_prescription PRIMARY KEY (prescription_id),
    CONSTRAINT uq_prescription_chat UNIQUE (chat_id),
    CONSTRAINT chk_prescription_time CHECK
        (REGEXP_LIKE(prescribed_time, '^([01][0-9]|2[0-3]):[0-5][0-9]$')),
    CONSTRAINT fk_prescription_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id),
    CONSTRAINT fk_prescription_pharmacist FOREIGN KEY (pharmacist_id)
        REFERENCES pharmacist (pharmacist_id),
    CONSTRAINT fk_prescription_chat FOREIGN KEY (chat_id)
        REFERENCES chat_room (chat_id)
);

-- ---------------------------------------------------------------------
-- 12. รายละเอียดใบสั่งยา
--     เพิ่ม quantity (จำนวนที่จ่าย)
--     ตัดวันหมดอายุยา (อยู่ที่ drug_batch)
--     เพิ่ม batch_id = ล็อตที่จ่ายจริง (ว่างได้จนกว่าจะจ่ายยา)
--     FK (batch_id, drug_id) บังคับว่าล็อตต้องเป็นของยาตัวเดียวกับที่สั่ง
-- ---------------------------------------------------------------------
CREATE TABLE prescription_detail (
    prescription_id  NUMBER(10)          NOT NULL,
    line_no          NUMBER(5)           NOT NULL,
    drug_id          NUMBER(10)          NOT NULL,
    strength         VARCHAR2(50 CHAR),
    dosage           VARCHAR2(100 CHAR)  NOT NULL,
    usage_note       VARCHAR2(255 CHAR)  NOT NULL,
    quantity         NUMBER(10)          NOT NULL,
    batch_id         NUMBER(10),
    CONSTRAINT pk_prescription_detail PRIMARY KEY (prescription_id, line_no),
    CONSTRAINT chk_presc_detail_qty CHECK (quantity > 0),
    CONSTRAINT fk_presc_detail_prescription FOREIGN KEY (prescription_id)
        REFERENCES prescription (prescription_id),
    CONSTRAINT fk_presc_detail_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id),
    CONSTRAINT fk_presc_detail_batch FOREIGN KEY (batch_id, drug_id)
        REFERENCES drug_batch (batch_id, drug_id)
);

-- ---------------------------------------------------------------------
-- 13. คำสั่งซื้อ
--     ใบสั่งยา 1 - 1 คำสั่งซื้อ (ไม่บังคับ เผื่อยาที่ไม่ต้องมีใบสั่ง)
--     ยอดรวมไม่เก็บ คำนวณจากรายละเอียดคำสั่งซื้อ (จำนวน x ราคาต่อหน่วย)
--     shipping_address เป็น snapshot ของที่อยู่ ณ วันที่สั่งซื้อ
-- ---------------------------------------------------------------------
CREATE TABLE orders (
    order_id          NUMBER(10)          NOT NULL,
    patient_id        NUMBER(10)          NOT NULL,
    prescription_id   NUMBER(10),
    status            VARCHAR2(20)        DEFAULT 'pending_payment' NOT NULL,
    shipping_address  VARCHAR2(500 CHAR)  NOT NULL,
    ordered_at        TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at        TIMESTAMP,
    CONSTRAINT pk_orders PRIMARY KEY (order_id),
    CONSTRAINT uq_orders_prescription UNIQUE (prescription_id),
    CONSTRAINT chk_orders_status CHECK (status IN
        ('pending_payment', 'paid', 'preparing', 'shipped', 'completed', 'cancelled')),
    CONSTRAINT fk_orders_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id),
    CONSTRAINT fk_orders_prescription FOREIGN KEY (prescription_id)
        REFERENCES prescription (prescription_id)
);

-- ---------------------------------------------------------------------
-- 14. รายละเอียดคำสั่งซื้อ
--     drug_name และ unit_price เป็น snapshot ณ วันที่สั่งซื้อ
-- ---------------------------------------------------------------------
CREATE TABLE order_detail (
    order_id    NUMBER(10)          NOT NULL,
    line_no     NUMBER(5)           NOT NULL,
    drug_id     NUMBER(10)          NOT NULL,
    drug_name   VARCHAR2(200 CHAR)  NOT NULL,
    quantity    NUMBER(10)          NOT NULL,
    unit_price  NUMBER(12,2)        NOT NULL,
    CONSTRAINT pk_order_detail PRIMARY KEY (order_id, line_no),
    CONSTRAINT chk_order_detail_qty   CHECK (quantity > 0),
    CONSTRAINT chk_order_detail_price CHECK (unit_price >= 0),
    CONSTRAINT fk_order_detail_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id),
    CONSTRAINT fk_order_detail_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id)
);

-- ---------------------------------------------------------------------
-- 15. ใบเสร็จยา : คำสั่งซื้อ 1 - 1 ใบเสร็จ
--     receipt_id = รหัสภายใน, receipt_no = เลขที่บนเอกสาร
-- ---------------------------------------------------------------------
CREATE TABLE receipt (
    receipt_id          NUMBER(10)     NOT NULL,
    receipt_no          VARCHAR2(30)   NOT NULL,
    order_id            NUMBER(10)     NOT NULL,
    patient_id          NUMBER(10)     NOT NULL,
    pharmacy_id         NUMBER(10)     NOT NULL,
    service_date        DATE           NOT NULL,
    receiver_signature  VARCHAR2(255),
    issued_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_receipt PRIMARY KEY (receipt_id),
    CONSTRAINT uq_receipt_order UNIQUE (order_id),
    CONSTRAINT fk_receipt_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id),
    CONSTRAINT fk_receipt_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id),
    CONSTRAINT fk_receipt_pharmacy FOREIGN KEY (pharmacy_id)
        REFERENCES pharmacy (pharmacy_id)
);

-- ---------------------------------------------------------------------
-- 16. รายละเอียดใบเสร็จยา
--     เพิ่ม quantity
-- ---------------------------------------------------------------------
CREATE TABLE receipt_detail (
    receipt_id  NUMBER(10)          NOT NULL,
    line_no     NUMBER(5)           NOT NULL,
    drug_id     NUMBER(10)          NOT NULL,
    dosage      VARCHAR2(100 CHAR),
    quantity    NUMBER(10)          NOT NULL,
    unit_price  NUMBER(12,2)        NOT NULL,
    total_amount  NUMBER(12,2)      NOT NULL,
    CONSTRAINT pk_receipt_detail PRIMARY KEY (receipt_id, line_no),
    CONSTRAINT chk_receipt_detail_qty   CHECK (quantity > 0),
    CONSTRAINT chk_receipt_detail_price CHECK (unit_price >= 0),
    CONSTRAINT chk_receipt_detail_total CHECK (total_amount >= 0),
    CONSTRAINT fk_receipt_detail_receipt FOREIGN KEY (receipt_id)
        REFERENCES receipt (receipt_id),
    CONSTRAINT fk_receipt_detail_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id)
);

-- ---------------------------------------------------------------------
-- 17. การชำระเงิน : คำสั่งซื้อ 1 - 1 การชำระเงิน
-- ---------------------------------------------------------------------
CREATE TABLE payment (
    payment_id  NUMBER(10)    NOT NULL,
    order_id    NUMBER(10)    NOT NULL,
    method      VARCHAR2(20)  NOT NULL,
    status      VARCHAR2(20)  DEFAULT 'pending' NOT NULL,
    paid_at     TIMESTAMP,
    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP,
    CONSTRAINT pk_payment PRIMARY KEY (payment_id),
    CONSTRAINT uq_payment_order UNIQUE (order_id),
    CONSTRAINT chk_payment_method CHECK (method IN ('qr_code', 'bank_transfer')),
    CONSTRAINT chk_payment_status CHECK (status IN
        ('pending', 'success', 'failed', 'refunded')),
    CONSTRAINT fk_payment_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id)
);

-- ---------------------------------------------------------------------
-- 18. คิวอาร์โค้ด : การชำระเงิน 1 - 1 คิวอาร์โค้ด
-- ---------------------------------------------------------------------
CREATE TABLE qr_code (
    qr_id       NUMBER(10)    NOT NULL,
    payment_id  NUMBER(10)    NOT NULL,
    amount      NUMBER(12,2)  NOT NULL,
    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_qr_code PRIMARY KEY (qr_id),
    CONSTRAINT uq_qr_payment UNIQUE (payment_id),
    CONSTRAINT chk_qr_amount CHECK (amount > 0),
    CONSTRAINT fk_qr_payment FOREIGN KEY (payment_id)
        REFERENCES payment (payment_id)
);

-- ---------------------------------------------------------------------
-- 19. สลิปการโอนเงิน : การชำระเงิน 1 - 1 สลิป
-- ---------------------------------------------------------------------
CREATE TABLE transfer_slip (
    slip_id         NUMBER(10)          NOT NULL,
    payment_id      NUMBER(10)          NOT NULL,
    transaction_no  VARCHAR2(50)        NOT NULL,
    reference_no    VARCHAR2(50),
    payer_name      VARCHAR2(200 CHAR)  NOT NULL,
    payee_name      VARCHAR2(200 CHAR)  NOT NULL,
    bank_name       VARCHAR2(100 CHAR)  NOT NULL,
    amount          NUMBER(12,2)        NOT NULL,
    fee             NUMBER(12,2)        DEFAULT 0 NOT NULL,
    transferred_at  TIMESTAMP           NOT NULL,
    created_at      TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_transfer_slip PRIMARY KEY (slip_id),
    CONSTRAINT uq_slip_payment UNIQUE (payment_id),
    CONSTRAINT chk_slip_amount CHECK (amount > 0 AND fee >= 0),
    CONSTRAINT fk_slip_payment FOREIGN KEY (payment_id)
        REFERENCES payment (payment_id)
);

-- ---------------------------------------------------------------------
-- 20. การคืนเงิน : การชำระเงิน 1 - 1 การคืนเงิน
-- ---------------------------------------------------------------------
CREATE TABLE refund (
    refund_id       NUMBER(10)          NOT NULL,
    payment_id      NUMBER(10)          NOT NULL,
    reference_no    VARCHAR2(50),
    amount          NUMBER(12,2)        NOT NULL,
    recipient_name  VARCHAR2(200 CHAR)  NOT NULL,
    status          VARCHAR2(20)        DEFAULT 'pending' NOT NULL,
    refunded_at     TIMESTAMP,
    created_at      TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_refund PRIMARY KEY (refund_id),
    CONSTRAINT uq_refund_payment UNIQUE (payment_id),
    CONSTRAINT chk_refund_status CHECK (status IN
        ('pending', 'completed', 'rejected')),
    CONSTRAINT chk_refund_amount CHECK (amount > 0),
    CONSTRAINT fk_refund_payment FOREIGN KEY (payment_id)
        REFERENCES payment (payment_id)
);

-- ---------------------------------------------------------------------
-- 21. ใบกำกับภาษี : คำสั่งซื้อ 1 - 1 ใบกำกับภาษี
--     ตัด "รายการสินค้า/จำนวนสินค้า" ที่ซ้ำกับตารางรายละเอียด
--     ชื่อ ที่อยู่ เบอร์โทรผู้ซื้อ เป็น snapshot ณ วันออกเอกสาร
--     ยอดรวมเงินไม่เก็บ คำนวณจากรายละเอียดใบกำกับภาษี
-- ---------------------------------------------------------------------
CREATE TABLE tax_invoice (
    tax_invoice_id     NUMBER(10)          NOT NULL,
    invoice_no         VARCHAR2(30)        NOT NULL,
    order_id           NUMBER(10)          NOT NULL,
    buyer_first_name   VARCHAR2(100 CHAR)  NOT NULL,
    buyer_last_name    VARCHAR2(100 CHAR)  NOT NULL,
    buyer_address      VARCHAR2(500 CHAR)  NOT NULL,
    buyer_phone        VARCHAR2(20),
    buyer_tax_id       CHAR(13)            NOT NULL,
    issued_date        DATE                NOT NULL,
    created_at         TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_tax_invoice PRIMARY KEY (tax_invoice_id),
    CONSTRAINT uq_invoice_order UNIQUE (order_id),
    CONSTRAINT chk_invoice_tax_id  CHECK (REGEXP_LIKE(buyer_tax_id, '^[0-9]{13}$')),
    CONSTRAINT fk_invoice_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id)
);

-- ---------------------------------------------------------------------
-- 22. รายละเอียดใบกำกับภาษี
-- ---------------------------------------------------------------------
CREATE TABLE tax_invoice_detail (
    tax_invoice_id  NUMBER(10)          NOT NULL,
    line_no         NUMBER(5)           NOT NULL,
    drug_id         NUMBER(10)          NOT NULL,
    product_name    VARCHAR2(200 CHAR)  NOT NULL,
    quantity        NUMBER(10)          NOT NULL,
    unit_price      NUMBER(12,2)        NOT NULL,
    line_amount     NUMBER(12,2)        NOT NULL,
    CONSTRAINT pk_tax_invoice_detail PRIMARY KEY (tax_invoice_id, line_no),
    CONSTRAINT chk_invoice_detail_qty   CHECK (quantity > 0),
    CONSTRAINT chk_invoice_detail_price CHECK (unit_price >= 0),
    CONSTRAINT chk_invoice_detail_amount CHECK (line_amount >= 0),
    CONSTRAINT fk_invoice_detail_invoice FOREIGN KEY (tax_invoice_id)
        REFERENCES tax_invoice (tax_invoice_id),
    CONSTRAINT fk_invoice_detail_drug FOREIGN KEY (drug_id)
        REFERENCES drug (drug_id)
);

-- ---------------------------------------------------------------------
-- 23. การจัดส่ง : คำสั่งซื้อ 1 - N การจัดส่ง
-- ---------------------------------------------------------------------
CREATE TABLE delivery (
    delivery_id  NUMBER(10)    NOT NULL,
    order_id     NUMBER(10)    NOT NULL,
    tracking_no  VARCHAR2(50),
    status       VARCHAR2(20)  DEFAULT 'preparing' NOT NULL,
    shipped_at   TIMESTAMP,
    created_at   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP,
    CONSTRAINT pk_delivery PRIMARY KEY (delivery_id),
    CONSTRAINT chk_delivery_status CHECK (status IN
        ('preparing', 'shipped', 'delivered', 'returned')),
    CONSTRAINT fk_delivery_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id)
);

-- ---------------------------------------------------------------------
-- 24. คะแนนและการรีวิว : คำสั่งซื้อ 1 - 1 รีวิว, คนไข้ 1 - N รีวิว
--     ใช้ชื่อ review_comment เพราะ COMMENT เป็นคำสงวนของ Oracle
-- ---------------------------------------------------------------------
CREATE TABLE review (
    review_id       NUMBER(10)           NOT NULL,
    patient_id      NUMBER(10)           NOT NULL,
    order_id        NUMBER(10)           NOT NULL,
    rating          NUMBER(1)            NOT NULL,
    review_comment  VARCHAR2(1000 CHAR),
    reviewed_at     TIMESTAMP            DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_review PRIMARY KEY (review_id),
    CONSTRAINT uq_review_order UNIQUE (order_id),
    CONSTRAINT chk_review_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT fk_review_patient FOREIGN KEY (patient_id)
        REFERENCES patient (patient_id),
    CONSTRAINT fk_review_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id)
);

-- ---------------------------------------------------------------------
-- SEQUENCE แทน AUTO_INCREMENT
-- ตัวอย่างการใช้ : INSERT INTO patient (patient_id, ...) VALUES (seq_patient.NEXTVAL, ...);
-- ---------------------------------------------------------------------
CREATE SEQUENCE seq_pharmacy      START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_pharmacist    START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_patient       START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_address       START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_drug          START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_drug_batch    START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_consult_queue START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_chat_room     START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_chat_message  START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_prescription  START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_orders        START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_receipt       START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_payment       START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_qr_code       START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_transfer_slip START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_refund        START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_tax_invoice   START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_delivery      START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_review        START WITH 1 INCREMENT BY 1 NOCACHE;

-- ---------------------------------------------------------------------
-- Index สำหรับ query หลักของระบบ
-- (Oracle สร้าง index ให้ PK และ UNIQUE อัตโนมัติ แต่ไม่สร้างให้ FK)
-- ---------------------------------------------------------------------
CREATE INDEX idx_queue_status_time    ON consult_queue (status, entered_at);
CREATE INDEX idx_orders_patient_time  ON orders (patient_id, ordered_at);
CREATE INDEX idx_drug_name            ON drug (name);
CREATE INDEX idx_batch_drug_expiry    ON drug_batch (drug_id, expiry_date);
CREATE INDEX idx_message_chat_time    ON chat_message (chat_id, sent_at);
CREATE INDEX idx_prescription_patient ON prescription (patient_id);
CREATE INDEX idx_delivery_order       ON delivery (order_id);
