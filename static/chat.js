// ห้องแชทแบบ polling : ถามข้อความใหม่ (message_id > ตัวล่าสุดที่มี) ทุก 1.5 วินาที
// สถานะห้อง (state) มาจากเซิร์ฟเวอร์ : waiting_reply, consulting, closed, failed
const STATE_BADGE = { waiting_reply: "bg-warning text-dark", consulting: "bg-success", failed: "bg-danger", closed: "bg-secondary" };

function startChat(cfg) {
  const byId = (id) => document.getElementById(id);
  const box = byId("chat-box");
  const form = byId("chat-form");
  const input = byId("chat-input");
  let lastId = 0;
  let busy = false;

  function addMessage(m) {
    const div = document.createElement("div");
    div.className = "msg " + (m.sender_type === cfg.role ? "mine" : "theirs");
    div.textContent = m.content;
    const time = document.createElement("small");
    time.textContent = (m.sender_type === "pharmacist" ? "เภสัชกร" : "คนไข้") + " · " + m.sent_at;
    div.appendChild(time);
    box.appendChild(div);
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
      closed.textContent = data.state === "failed"
        ? "ให้คำปรึกษาไม่สำเร็จ: เภสัชกรไม่ตอบภายใน 10 นาที ห้องแชทถูกปิด"
        : "การปรึกษาจบแล้ว ห้องแชทถูกปิด";

      if (cfg.role === "pharmacist") {
        // ตัวนับเวลา 10 นาที แสดงเฉพาะตอนรอตอบกลับ
        const waiting = data.state === "waiting_reply";
        byId("reply-timer").classList.toggle("d-none", !waiting);
        if (waiting) byId("reply-countdown").textContent = formatCountdown(data.seconds_left);
        byId("close-form").classList.toggle("d-none", !open);
      }

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
    await fetch(cfg.messagesUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender_type: cfg.role, content: content }),
    });
    poll();
  });

  poll();
  setInterval(poll, 1500);
}
