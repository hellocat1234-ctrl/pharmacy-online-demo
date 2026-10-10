// ห้องแชทแบบ polling : ถามข้อความใหม่ (message_id > ตัวล่าสุดที่มี) ทุก 1.5 วินาที
// สถานะห้อง (state) มาจากเซิร์ฟเวอร์ : waiting_reply, consulting, closed, failed
// ตัวนับเวลา : เซิร์ฟเวอร์ส่ง turn (ฝ่ายที่ต้องตอบ) และ seconds_left ซึ่งคำนวณจากข้อความล่าสุด
//             จึงรีเซ็ตเองเมื่อมีข้อความใหม่ ระหว่างรอบ polling หน้าเว็บลดเลขเองทุกวินาที
const STATE_BADGE = { waiting_reply: "bg-warning text-dark", consulting: "bg-success", failed: "bg-danger", closed: "bg-secondary" };
const SIDE_LABEL = { pharmacist: "เภสัชกร", patient: "คนไข้" };

function startChat(cfg) {
  const byId = (id) => document.getElementById(id);
  const box = byId("chat-box");
  const form = byId("chat-form");
  const input = byId("chat-input");
  let lastId = 0;
  let busy = false;
  let turn = null;        // ฝ่ายที่ต้องตอบ
  let secondsLeft = null; // เวลาที่เหลือของฝ่ายนั้น
  let rejectReason = null; // ข้อความจากเซิร์ฟเวอร์เมื่อส่งข้อความไม่ผ่าน

  function addMessage(m) {
    const div = document.createElement("div");
    div.className = "msg " + (m.sender_type === cfg.role ? "mine" : "theirs");
    div.textContent = m.content;
    const time = document.createElement("small");
    time.textContent = (m.sender_type === "pharmacist" ? "เภสัชกร" : "คนไข้") + " · " + m.sent_at;
    div.appendChild(time);
    box.appendChild(div);
  }

  // ฝ่ายที่ต้องตอบเห็น "ต้องตอบภายใน mm:ss" อีกฝ่ายเห็น "รอ[เภสัชกร/คนไข้]ตอบกลับ mm:ss"
  function drawTimer() {
    if (turn === null) return;
    const mine = turn === cfg.role;
    byId("reply-timer").classList.toggle("timer-mine", mine);
    byId("reply-label").textContent = mine ? "ต้องตอบภายใน" : "รอ" + SIDE_LABEL[turn] + "ตอบกลับ";
    byId("reply-countdown").textContent = formatCountdown(secondsLeft);
    byId("expire-side").value = turn;
    byId("expire-button").textContent = "ทดสอบ: " + SIDE_LABEL[turn] + "หมดเวลา";
  }

  async function poll() {
    if (busy) return;
    busy = true;
    try {
      const res = await fetch(cfg.messagesUrl + "?after=" + lastId);
      const data = await res.json();
      for (const m of data.messages) {
        addMessage(m);
        lastId = m.message_id;
      }
      if (data.messages.length) box.scrollTop = box.scrollHeight;

      const open = data.status === "open";
      const badge = byId("chat-status");
      badge.textContent = data.state_label;
      badge.className = "badge " + STATE_BADGE[data.state];
      form.classList.toggle("d-none", !open);
      const closed = byId("chat-closed");
      closed.classList.toggle("d-none", open);
      closed.textContent = rejectReason || (data.state === "failed"
        ? "ให้คำปรึกษาไม่สำเร็จ: เภสัชกรไม่ตอบภายใน 10 นาที ห้องแชทถูกปิด"
        : "การปรึกษาจบแล้ว ห้องแชทถูกปิด");

      // ตัวนับเวลาและปุ่มทดสอบ แสดงเฉพาะตอนห้องยังเปิด ค่าจากเซิร์ฟเวอร์ทับค่าที่นับเองทุกรอบ
      byId("reply-timer").classList.toggle("d-none", !open);
      byId("expire-form").classList.toggle("d-none", !open);
      turn = open ? data.turn : null;
      secondsLeft = open ? data.seconds_left : null;
      drawTimer();
      if (cfg.role === "pharmacist") byId("close-form").classList.toggle("d-none", !open);

      if (data.prescription_id) {
        if (cfg.role === "patient") {
          byId("rx-link").href = cfg.prescriptionUrl + data.prescription_id;
          byId("rx-banner").classList.remove("d-none");
        } else if (!cfg.hasPrescription) {
          location.reload();
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      busy = false;
    }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    const res = await fetch(cfg.messagesUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender_type: cfg.role, content: content }),
    });
    if (!res.ok) {
      // เซิร์ฟเวอร์ปฏิเสธ (เช่น หมดเวลาแล้ว) : แสดงเหตุผลแทนช่องพิมพ์ รอบ polling ถัดไปจะปิดห้องให้
      rejectReason = (await res.json()).error;
    }
    poll();
  });

  poll();
  setInterval(poll, 1500);
  setInterval(() => {
    if (secondsLeft !== null) {
      secondsLeft -= 1;
      drawTimer();
    }
  }, 1000);
}
