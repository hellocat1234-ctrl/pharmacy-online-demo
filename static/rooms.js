// รายการห้องแชทที่เปิดอยู่ของเภสัชกร (แถบด้านบนของหน้าแชท) : polling ทุก 3 วินาที
// เภสัชกรรับได้หลายเคสพร้อมกัน จึงสลับห้องจากแถบนี้ และเห็นป้าย "ข้อความใหม่" เมื่อคนไข้ห้องอื่นส่งข้อความ
// ข้อความใหม่ = message_id ล่าสุดของคนไข้ในห้องนั้น มากกว่าตัวที่เภสัชกรเห็นแล้ว
// ตัวที่เห็นแล้วจำไว้ใน localStorage ของเบราว์เซอร์ (ไม่เพิ่มคอลัมน์ในฐานข้อมูล)
const ROOMS_POLL_MS = 3000;

function startRooms(cfg) {
  const list = document.getElementById("room-list");
  const waitingCount = document.getElementById("waiting-count");
  const baseTitle = document.title;
  const seenKey = (chatId) => "pharmacy-seen:" + cfg.pharmacistId + ":" + chatId;

  function seen(chatId) {
    return Number(localStorage.getItem(seenKey(chatId)) || 0);
  }

  function render(rooms) {
    let unread = 0;
    list.replaceChildren();
    for (const room of rooms) {
      const current = room.chat_id === cfg.currentChatId;
      // ห้องที่เปิดดูอยู่ถือว่าเห็นข้อความล่าสุดแล้ว
      if (current) localStorage.setItem(seenKey(room.chat_id), room.last_patient_message_id);
      const hasNew = !current && room.last_patient_message_id > seen(room.chat_id);
      if (hasNew) unread += 1;

      const a = document.createElement("a");
      a.className = "room-tab" + (current ? " active" : "") + (hasNew ? " has-new" : "");
      a.href = cfg.chatUrl + room.chat_id;
      a.textContent = "ห้อง #" + room.chat_id + " · " + room.patient_name;
      if (hasNew) {
        const badge = document.createElement("span");
        badge.className = "room-new";
        badge.textContent = "ข้อความใหม่";
        a.appendChild(badge);
      }
      list.appendChild(a);
    }
    document.title = (unread ? "(" + unread + " ห้องมีข้อความใหม่) " : "") + baseTitle;
  }

  async function poll() {
    try {
      const data = await (await fetch(cfg.roomsUrl)).json();
      render(data.rooms);
      waitingCount.textContent = data.waiting;
      waitingCount.classList.toggle("has-waiting", data.waiting > 0);
    } catch (e) {
      console.error(e);
    }
  }

  poll();
  setInterval(poll, ROOMS_POLL_MS);
}
