// ช่องค้นหายาแบบ type-ahead ในฟอร์มใบสั่งยา (แทน dropdown)
// โครงสร้างที่ต้องมีใน template :
//   <div class="drug-search">
//     <input type="hidden" name="drug_id">            ยาที่เลือกแล้ว (ว่าง = ยังไม่เลือก)
//     <input class="drug-search-input" type="text">   ช่องพิมพ์ชื่อยาหรือรหัสยา
//     <ul class="drug-results d-none"></ul>           ผลการค้นหา ไม่เกิน 10 รายการ
//   </div>
// หยุดพิมพ์ 250 ms จึงเรียก API, คำขอเก่าที่ยังค้างถูกยกเลิก (AbortController)
// ลูกศรขึ้น/ลงเลื่อนรายการ, Enter เลือก, Esc ปิด  ยาที่คงเหลือ 0 แสดงในรายการแต่เลือกไม่ได้
const DRUG_SEARCH_DELAY_MS = 250;

function startDrugSearch(searchUrl) {
  for (const box of document.querySelectorAll(".drug-search")) setupDrugSearch(box, searchUrl);
}

function setupDrugSearch(box, searchUrl) {
  const hidden = box.querySelector('input[type="hidden"]');
  const input = box.querySelector(".drug-search-input");
  const list = box.querySelector(".drug-results");
  let timer = null;       // ตัวจับเวลารอหยุดพิมพ์
  let request = null;     // AbortController ของคำขอที่ยังค้างอยู่
  let drugs = [];         // ผลการค้นหาที่แสดงอยู่
  let active = -1;        // ตำแหน่งที่ไฮไลต์อยู่ (-1 = ไม่มี)

  const isOpen = () => !list.classList.contains("d-none");

  function close() {
    list.classList.add("d-none");
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    drugs = [];
    active = -1;
  }

  function cancelPending() {
    clearTimeout(timer);
    if (request) request.abort();
    request = null;
  }

  function setActive(index) {
    active = index;
    [...list.children].forEach((li, i) => li.classList.toggle("active", i === active));
    if (active >= 0) list.children[active].scrollIntoView({ block: "nearest" });
  }

  // เลื่อนไปยังรายการถัดไปที่เลือกได้ (ข้ามยาที่หมด) วนกลับเมื่อสุดรายการ
  function move(step) {
    if (!drugs.some((d) => d.stock > 0)) return;
    let index = active;
    do {
      index = (index + step + drugs.length) % drugs.length;
    } while (drugs[index].stock === 0);
    setActive(index);
  }

  function choose(drug) {
    hidden.value = drug.drug_id;
    input.value = drug.label;
    input.setCustomValidity("");
    close();
  }

  function render(found) {
    drugs = found;
    list.replaceChildren();
    if (!drugs.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "ไม่พบยาที่ตรงกับคำค้น";
      list.appendChild(li);
    }
    drugs.forEach((drug) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.textContent = drug.label;     // รหัส · ชื่อยา · สต็อกคงเหลือ
      if (drug.stock === 0) {
        li.className = "disabled";
        li.setAttribute("aria-disabled", "true");
      }
      // mousedown (ไม่ใช่ click) : เลือกก่อนที่ช่องพิมพ์จะเสีย focus แล้วรายการถูกปิด
      li.addEventListener("mousedown", (ev) => {
        ev.preventDefault();
        if (drug.stock > 0) choose(drug);
      });
      list.appendChild(li);
    });
    list.classList.remove("d-none");
    input.setAttribute("aria-expanded", "true");
    active = -1;
    move(1);
  }

  async function search(q) {
    request = new AbortController();
    const mine = request;
    try {
      const res = await fetch(searchUrl + "?q=" + encodeURIComponent(q), { signal: mine.signal });
      const data = await res.json();
      if (mine === request) render(data.drugs);
    } catch (e) {
      if (e.name !== "AbortError") console.error(e);
    }
  }

  input.addEventListener("input", () => {
    hidden.value = "";                 // ข้อความเปลี่ยนแล้ว ยาที่เคยเลือกไว้ไม่ใช้แล้ว
    input.setCustomValidity("");
    cancelPending();
    const q = input.value.trim();
    if (!q) {
      close();
      return;
    }
    timer = setTimeout(() => search(q), DRUG_SEARCH_DELAY_MS);
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && isOpen()) {
      ev.preventDefault();
      cancelPending();
      close();
    } else if (isOpen() && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
      ev.preventDefault();
      move(ev.key === "ArrowDown" ? 1 : -1);
    } else if (ev.key === "Enter" && (isOpen() || (input.value.trim() && !hidden.value))) {
      // Enter ระหว่างค้นหา = เลือกยา ไม่ใช่ส่งฟอร์มใบสั่งยา
      ev.preventDefault();
      if (active >= 0) choose(drugs[active]);
    }
  });

  input.addEventListener("blur", () => {
    cancelPending();
    close();
  });

  // พิมพ์ไว้แต่ไม่ได้เลือกยาจากรายการ : ไม่ให้ส่งฟอร์ม (ไม่อย่างนั้นแถวนี้จะถูกข้ามไปเงียบ ๆ)
  input.form.addEventListener("submit", (ev) => {
    if (input.value.trim() && !hidden.value) {
      ev.preventDefault();
      input.setCustomValidity("กรุณาเลือกยาจากรายการค้นหา");
      input.reportValidity();
    }
  });
}
