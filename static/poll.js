// polling สถานะหน้า : ถ้าค่าที่ได้ต่างจากครั้งแรก ให้โหลดหน้าใหม่
function reloadOnChange(url, intervalMs) {
  let first = null;
  async function tick() {
    try {
      const text = await (await fetch(url)).text();
      if (first === null) first = text;
      else if (text !== first) location.reload();
    } catch (e) {
      console.error(e);
    }
  }
  tick();
  setInterval(tick, intervalMs);
}

// แปลงวินาทีเป็น mm:ss (ติดลบ = หมดเวลา)
function formatCountdown(seconds) {
  if (seconds <= 0) return "หมดเวลา";
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

// ตัวนับเวลาถอยหลัง 10 นาที : อ่านวินาทีที่เหลือจาก data-seconds แล้วลดทีละ 1 ทุกวินาที
function startCountdowns() {
  const items = [...document.querySelectorAll(".countdown")].map((el) => ({ el, left: Number(el.dataset.seconds) }));
  function draw() {
    for (const it of items) {
      it.el.textContent = formatCountdown(it.left);
      it.el.classList.toggle("text-danger", it.left <= 60);
      it.left -= 1;
    }
  }
  draw();
  setInterval(draw, 1000);
}
