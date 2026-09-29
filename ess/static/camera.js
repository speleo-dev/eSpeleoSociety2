// Take the eCP photo with the camera of a notebook or phone (getUserMedia). The picture is put into the
// file input #photo, so the crop (crop.js) and the upload work exactly as with a chosen file.
// Hidden when the browser cannot use a camera or cannot fill a file input; choosing a file always works.
(function () {
  const input = document.getElementById("photo");
  const open = document.getElementById("camera-open");
  const box = document.getElementById("camera-box");
  const video = document.getElementById("camera-video");
  const shoot = document.getElementById("camera-shoot");
  const cancel = document.getElementById("camera-cancel");
  const message = document.getElementById("camera-message");
  if (!input || !open || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  try { new DataTransfer(); } catch (e) { return; }
  open.hidden = false;
  let stream = null;

  function stop() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null; video.srcObject = null; box.hidden = true; open.hidden = false;
  }

  open.addEventListener("click", async () => {
    message.hidden = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
      video.srcObject = stream;
      box.hidden = false; open.hidden = true;
    } catch (e) {
      message.textContent = e.name === "NotAllowedError"
        ? "Prístup ku kamere nebol povolený. Povoľte ho v prehliadači alebo vyberte súbor s fotkou."
        : "Kameru sa nepodarilo spustiť. Vyberte súbor s fotkou.";
      message.hidden = false;
    }
  });

  shoot.addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);  // not mirrored (the preview is)
    canvas.toBlob((blob) => {
      const files = new DataTransfer();
      files.items.add(new File([blob], "kamera.jpg", { type: "image/jpeg" }));
      input.files = files.files;
      input.dispatchEvent(new Event("change"));
      stop();
    }, "image/jpeg", 0.92);
  });
  cancel.addEventListener("click", stop);
})();
