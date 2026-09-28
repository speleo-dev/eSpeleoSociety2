// Portrait crop for the eCP photo: a frame with the card ratio (220:300) that can be moved and resized.
// Works with a file input (applicant) or with an existing image in data-src (administrator).
// Sends the frame as fractions of the image (crop_x, crop_y, crop_w, crop_h); the server does the crop.
(function () {
  const RATIO = 220 / 300;
  const input = document.getElementById("photo");
  const stage = document.getElementById("crop-stage");
  const img = document.getElementById("crop-img");
  const frame = document.getElementById("crop-frame");
  const size = document.getElementById("crop-size");
  if (!stage) return;
  let box = { x: 0, y: 0, w: 0 }; // fractions of the displayed image

  function heightOf(w) { return (w * img.clientWidth / RATIO) / img.clientHeight; }
  function clamp() {
    const maxW = Math.min(1, (img.clientHeight * RATIO) / img.clientWidth);
    box.w = Math.min(box.w, maxW);
    box.x = Math.min(Math.max(0, box.x), 1 - box.w);
    box.y = Math.min(Math.max(0, box.y), 1 - heightOf(box.w));
  }
  function render() {
    clamp();
    frame.style.left = box.x * 100 + "%";
    frame.style.top = box.y * 100 + "%";
    frame.style.width = box.w * 100 + "%";
    frame.style.height = heightOf(box.w) * 100 + "%";
    for (const [k, v] of Object.entries({ x: box.x, y: box.y, w: box.w, h: heightOf(box.w) })) {
      document.getElementById("crop_" + k).value = v.toFixed(5);
    }
  }
  function resetFrame() {
    const maxW = Math.min(1, (img.clientHeight * RATIO) / img.clientWidth);
    box.w = maxW * 0.8; box.x = (1 - box.w) / 2; box.y = (1 - heightOf(box.w)) * 0.4;
    size.value = 80; render();
  }
  if (img.dataset.src) {  // administrator re-crops an existing photo
    img.onload = () => { stage.hidden = false; resetFrame(); };
    img.src = img.dataset.src;
  }
  if (input) input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    img.onload = () => { stage.hidden = false; resetFrame(); };
    img.src = URL.createObjectURL(file);
  });
  size.addEventListener("input", () => {
    const maxW = Math.min(1, (img.clientHeight * RATIO) / img.clientWidth);
    const cx = box.x + box.w / 2, cy = box.y + heightOf(box.w) / 2;
    box.w = maxW * size.value / 100;
    box.x = cx - box.w / 2; box.y = cy - heightOf(box.w) / 2; render();
  });
  let drag = null;
  frame.addEventListener("pointerdown", (e) => {
    drag = { px: e.clientX, py: e.clientY, x: box.x, y: box.y };
    frame.setPointerCapture(e.pointerId);
  });
  frame.addEventListener("pointermove", (e) => {
    if (!drag) return;
    box.x = drag.x + (e.clientX - drag.px) / img.clientWidth;
    box.y = drag.y + (e.clientY - drag.py) / img.clientHeight;
    render();
  });
  frame.addEventListener("pointerup", () => { drag = null; });
  window.addEventListener("resize", render);
})();
