/* ACEVIDS front-end: upload chunked, cek media, susun klip, render. Tanpa framework. */
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const api = async (url, opts = {}) => {
    const res = await fetch(url, {headers: {"Content-Type": "application/json"}, ...opts});
    const ct = res.headers.get("content-type") || "";
    const body = ct.includes("json") ? await res.json() : await res.text();
    if (!res.ok) {
      const d = body && body.detail;
      throw new Error(typeof d === "string" ? d : JSON.stringify(d || body));
    }
    return body;
  };
  const fmtTime = (s) => {
    s = Math.max(0, Number(s) || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = (s % 60).toFixed(1).padStart(4, "0");
    return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + sec;
  };
  const fmtBytes = (b) => {
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; b = Number(b) || 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(i ? 1 : 0) + " " + u[i];
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  const state = {media: [], current: null, projects: [], project: null, inPoint: 0, outPoint: null, chunkSize: 16 * 1024 * 1024, whisper: false, whisperModels: ["base", "small"], whisperDefault: "small"};

  // ------------------------------------------------------------------ health
  api("/api/health").then((h) => {
    state.chunkSize = h.chunk_size || state.chunkSize;
    state.whisper = !!h.whisper; state.whisperModels = h.whisper_models || state.whisperModels; state.whisperDefault = h.whisper_default || state.whisperDefault;
    $("#health").textContent = `${h.ffmpeg.split(" ").slice(0, 3).join(" ")} · scenedetect ${h.scenedetect || "–"} · disk bebas ${h.disk_free_gb} GB`;
    state.lanUrls = h.lan_urls || [];
  }).catch((e) => $("#health").textContent = "server tidak terjangkau: " + e.message);

  // ------------------------------------------------------------------ buka di HP
  $("#btn-phone").addEventListener("click", () => {
    const box = $("#phone-box");
    if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
    const urls = state.lanUrls && state.lanUrls.length ? state.lanUrls : [location.origin];
    $("#phone-urls").innerHTML = urls.map((u) => `<a href="${esc(u)}" target="_blank">${esc(u)}</a>`).join("");
    const qr = $("#phone-qr");
    qr.src = `/api/qr.png?url=${encodeURIComponent(urls[0])}&t=${Date.now()}`;
    qr.onerror = () => { qr.style.display = "none"; };
    box.classList.remove("hidden");
  });

  // ------------------------------------------------------------------ upload
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => [...e.dataTransfer.files].forEach(uploadFile));
  $("#file-input").addEventListener("change", (e) => { [...e.target.files].forEach(uploadFile); e.target.value = ""; });

  async function uploadFile(file) {
    const box = document.createElement("div");
    box.className = "upload";
    box.innerHTML = `<div class="name">${esc(file.name)}</div><div class="bar"><div></div></div><div class="msg">Menyiapkan… (${fmtBytes(file.size)})</div>`;
    $("#upload-list").prepend(box);
    const bar = $(".bar > div", box), msg = $(".msg", box);
    try {
      const up = await api("/api/uploads/init", {method: "POST", body: JSON.stringify({filename: file.name, size: file.size, chunk_size: state.chunkSize})});
      const received = new Set(up.received || []);
      const total = up.total_chunks, chunk = up.chunk_size;
      let done = received.size;
      const t0 = Date.now();
      const pending = [];
      for (let i = 0; i < total; i++) if (!received.has(i)) pending.push(i);
      const PAR = 3; // 3 chunk sekaligus
      let idx = 0;
      const worker = async () => {
        while (idx < pending.length) {
          const i = pending[idx++];
          const blob = file.slice(i * chunk, Math.min(file.size, (i + 1) * chunk));
          let attempt = 0;
          for (;;) {
            try {
              const res = await fetch(`/api/uploads/${up.id}/chunks/${i}`, {method: "PUT", body: blob});
              if (!res.ok) throw new Error(await res.text());
              break;
            } catch (e) {
              if (++attempt > 5) throw e;
              await new Promise((r) => setTimeout(r, 1000 * attempt));
            }
          }
          done++;
          const frac = done / total, elapsed = (Date.now() - t0) / 1000;
          const speed = (done - received.size) * chunk / Math.max(elapsed, 0.1);
          bar.style.width = (frac * 100).toFixed(1) + "%";
          msg.textContent = `${(frac * 100).toFixed(1)} % · ${fmtBytes(speed)}/s · sisa ${fmtTime((total - done) * chunk / Math.max(speed, 1))}`;
        }
      };
      await Promise.all(Array.from({length: Math.min(PAR, pending.length || 1)}, worker));
      msg.textContent = "Menggabungkan & memulai pengecekan…";
      const media = await api(`/api/uploads/${up.id}/complete`, {method: "POST"});
      bar.style.width = "100%";
      msg.textContent = "Upload selesai. Pengecekan berjalan di server.";
      setTimeout(() => box.remove(), 4000);
      await refreshMedia();
      selectMedia(media.id);
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--bad)">Gagal: ${esc(e.message)}</span> — pilih ulang file yang sama untuk melanjutkan.`;
    }
  }

  // ------------------------------------------------------------------ media list
  async function refreshMedia() {
    state.media = await api("/api/media");
    const list = $("#media-list");
    if (!state.media.length) { list.innerHTML = '<p class="muted">Belum ada media.</p>'; return; }
    list.innerHTML = state.media.map((m) => {
      const v = m.probe && m.probe.video;
      const meta = m.status === "ready"
        ? `${fmtTime(m.duration)} · ${v ? v.width + "×" + v.height + " " + (v.fps || "?") + "fps" : "audio"} · ${fmtBytes(m.size)}`
        : (m.job ? `${Math.round((m.job.progress || 0) * 100)} % · ${esc(m.job.message)}` : fmtBytes(m.size));
      const img = m.status === "ready" && m.probe && m.probe.has_video
        ? `<img src="/api/media/${m.id}/thumbs/poster.jpg" alt="">` : `<div class="noimg">${m.status === "ready" ? "audio" : "…"}</div>`;
      return `<div class="media ${state.current === m.id ? "active" : ""}" data-id="${m.id}">${img}
        <div class="info"><div class="name" title="${esc(m.filename)}">${esc(m.filename)}</div>
        <div class="meta">${meta}</div><span class="status ${m.status}">${statusLabel(m.status)}</span></div></div>`;
    }).join("");
    list.querySelectorAll(".media").forEach((el) => el.addEventListener("click", () => selectMedia(el.dataset.id)));
  }
  const statusLabel = (s) => ({queued: "antre", analyzing: "mengecek", ready: "siap", failed: "gagal"}[s] || s);

  // ------------------------------------------------------------------ detail
  function selectMedia(id) {
    state.current = id; state.inPoint = 0; state.outPoint = null;
    refreshMedia();
    renderDetail();
  }

  function renderDetail() {
    const m = state.media.find((x) => x.id === state.current);
    const box = $("#detail");
    if (!m) { box.innerHTML = '<p class="muted">Pilih media di kiri.</p>'; return; }
    const p = m.probe || {}, v = p.video, a = p.audio, an = m.analysis || {};
    let html = `<div class="row"><strong style="flex:1;word-break:break-all">${esc(m.filename)}</strong>
      <span class="status ${m.status}">${statusLabel(m.status)}</span>
      <button class="btn small" id="btn-recheck" title="Cek ulang seluruh file (decode penuh)">Cek penuh</button>
      <a class="btn small" href="/api/media/${m.id}/source">Unduh asli</a>
      <button class="btn small danger" id="btn-del-media">Hapus</button></div>`;
    if (m.status !== "ready") {
      html += m.job ? `<div class="bar"><div style="width:${(m.job.progress * 100).toFixed(1)}%"></div></div><div class="muted">${esc(m.job.message)}</div>`
        : (m.error ? `<div class="err">${esc(m.error)}</div>` : '<p class="muted">Menunggu…</p>');
      box.innerHTML = html; bindDetail(m); return;
    }
    if (p.has_video) html += `<video id="player" src="/api/media/${m.id}/proxy" controls preload="metadata"></video>`;
    else html += `<audio id="player" src="/api/media/${m.id}/proxy" controls></audio>`;
    html += `<div class="inout">
      <button class="btn small" id="btn-in">IN = posisi</button><input id="in-val" type="number" step="0.1" min="0" value="${state.inPoint}">
      <button class="btn small" id="btn-out">OUT = posisi</button><input id="out-val" type="number" step="0.1" min="0" value="${state.outPoint ?? m.duration.toFixed(1)}">
      <button class="btn small primary" id="btn-add">+ Tambah ke timeline</button>
      <button class="btn small" id="btn-add-all">+ Seluruh file</button>
      <button class="btn small" id="btn-autocut" title="Pecah jadi klip tanpa keheningan (gaya auto-editor)">⚡ Potong otomatis</button>
    </div>`;
    (an.warnings || []).forEach((w) => html += `<div class="warn">⚠ ${esc(w)}</div>`);
    const integ = an.integrity || {};
    html += integ.ok ? `<div class="okbox">✔ Decode OK (${integ.full_file ? "seluruh file" : "cek cepat " + Math.round(integ.checked_seconds || 0) + " detik pertama"})</div>`
      : `<div class="err">✘ Decode bermasalah: ${integ.error_count || 0} error\n${esc((integ.errors || []).slice(0, 5).join("\n"))}</div>`;
    html += `<div class="kv">
      <div><span>Durasi</span> ${fmtTime(p.duration)}</div><div><span>Ukuran</span> ${fmtBytes(p.size)}</div>
      <div><span>Kontainer</span> ${esc(p.format_name)}</div><div><span>Bitrate</span> ${p.bit_rate ? (p.bit_rate / 1e6).toFixed(1) + " Mb/s" : "–"}</div>
      ${v ? `<div><span>Video</span> ${esc(v.codec)} ${esc(v.profile || "")}</div><div><span>Resolusi</span> ${v.width}×${v.height}${v.rotation ? " (rot " + v.rotation + "°)" : ""}</div>
      <div><span>FPS</span> ${v.fps}${v.vfr_suspected ? " (VFR?)" : ""}</div><div><span>Pixel</span> ${esc(v.pix_fmt)}${v.hdr_suspected ? " HDR" : ""}</div>` : "<div><span>Video</span> tidak ada</div>"}
      ${a ? `<div><span>Audio</span> ${esc(a.codec)} ${a.sample_rate} Hz ${a.channels}ch</div>` : "<div><span>Audio</span> tidak ada</div>"}
      ${an.loudness && an.loudness.integrated_lufs != null ? `<div><span>Loudness</span> ${an.loudness.integrated_lufs} LUFS · peak ${an.loudness.true_peak_dbfs} dBFS</div>` : ""}
      <div><span>Keheningan</span> ${(an.silences || []).length} bagian, ${fmtTime(an.silence_total || 0)}</div>
      <div><span>Adegan</span> ${((an.scenes || {}).scenes || []).length} (${esc((an.scenes || {}).engine || "–")})</div>
    </div>`;
    html += `<div id="transcript-block">${renderTranscriptBlock(m)}</div>`;
    if (p.has_video) html += `<img class="sheet" src="/api/media/${m.id}/thumbs/sheet.jpg" alt="contact sheet">`;
    const scenes = ((an.scenes || {}).scenes || []);
    if (scenes.length) {
      html += `<h3>Adegan (klik: isi IN/OUT · tombol +: langsung ke timeline)</h3><div class="scenes">` + scenes.map((s) =>
        `<div class="scene" data-s="${s.start}" data-e="${s.end}">${s.thumb ? `<img src="/api/media/${m.id}/thumbs/${s.thumb}" loading="lazy">` : '<div class="noimg"></div>'}
         <div class="t">#${s.index + 1} ${fmtTime(s.start)} – ${fmtTime(s.end)} <button class="btn small add-scene" data-s="${s.start}" data-e="${s.end}">+</button></div></div>`).join("") + "</div>";
    }
    const sil = an.silences || [];
    if (sil.length) {
      html += `<h3>Keheningan (klik untuk lompat)</h3><div class="silences">` + sil.slice(0, 200).map((s) =>
        `<div data-t="${s.start}"><span>${fmtTime(s.start)} – ${fmtTime(s.end)}</span><span>${s.duration.toFixed(2)} s</span></div>`).join("") + (sil.length > 200 ? `<div class="muted">… ${sil.length - 200} lagi</div>` : "") + "</div>";
    }
    box.innerHTML = html;
    bindDetail(m);
  }

  function renderTranscriptBlock(m) {
    if (!(m.probe && m.probe.has_audio)) return "";
    const t = m.transcript || {}, tj = m.transcribe_job;
    const opts = state.whisperModels.map((x) => `<option value="${x}" ${x === (t.model || state.whisperDefault) ? "selected" : ""}>${x}</option>`).join("");
    let html = `<h3>Transkrip (Whisper lokal)</h3><div class="row">
      <select id="tr-model" title="model Whisper" ${!state.whisper ? "disabled" : ""}>${opts}</select>
      <select id="tr-lang" title="bahasa"><option value="id">Indonesia</option><option value="en">English</option><option value="auto">Deteksi otomatis</option></select>
      <button class="btn small" id="btn-transcribe" ${!state.whisper || tj ? "disabled" : ""}>🎙 ${t.status === "done" ? "Transkrip ulang" : "Transkrip"}</button>`;
    if (!state.whisper) html += `<span class="muted">faster-whisper belum terpasang di server</span>`;
    if (t.status === "done") html += `<a class="btn small" href="/api/media/${m.id}/transcript?format=srt">⬇ SRT</a><a class="btn small" href="/api/media/${m.id}/transcript?format=json">⬇ JSON kata</a><a class="btn small" href="/api/media/${m.id}/transcript?format=txt">⬇ TXT</a>`;
    html += `</div>`;
    if (tj) html += `<div class="bar"><div style="width:${(tj.progress * 100).toFixed(1)}%"></div></div><div class="muted">${esc(tj.message)}</div>`;
    else if (t.status === "failed") html += `<div class="err">Transkripsi gagal: ${esc(t.error || "?")}</div>`;
    else if (t.status === "done") {
      html += `<div class="muted">${t.model} · bahasa ${esc(t.language)} · ${t.words} kata · ${t.segments} segmen (klik untuk lompat)</div><div class="silences transcript">` +
        (t.preview || []).map((sg) => `<div data-t="${sg.start}"><span>${fmtTime(sg.start)}</span><span style="flex:1;text-align:left;margin-left:8px">${esc(sg.text)}</span></div>`).join("") + `</div>`;
    }
    return html;
  }

  function bindDetail(m) {
    const player = $("#player");
    $("#btn-recheck")?.addEventListener("click", async () => { await api(`/api/media/${m.id}/analyze`, {method: "POST", body: JSON.stringify({deep: true})}); refreshMedia(); });
    $("#btn-del-media")?.addEventListener("click", async () => {
      if (!confirm(`Hapus ${m.filename} beserta proxy dan analisisnya?`)) return;
      try { await api(`/api/media/${m.id}`, {method: "DELETE"}); state.current = null; refreshMedia(); renderDetail(); }
      catch (e) { alert(e.message); }
    });
    if (!player) return;
    const inVal = $("#in-val"), outVal = $("#out-val");
    $("#btn-in").addEventListener("click", () => { inVal.value = player.currentTime.toFixed(2); });
    $("#btn-out").addEventListener("click", () => { outVal.value = player.currentTime.toFixed(2); });
    inVal.addEventListener("change", () => { player.currentTime = Number(inVal.value) || 0; });
    $("#btn-add").addEventListener("click", () => addClip(m, Number(inVal.value) || 0, Number(outVal.value) || m.duration));
    $("#btn-add-all").addEventListener("click", () => addClip(m, 0, m.duration));
    $("#btn-autocut").addEventListener("click", async () => {
      const margin = Number($("#s-margin").value) || 0.2;
      const r = await api(`/api/media/${m.id}/autocut`, {method: "POST", body: JSON.stringify({margin, min_segment: 0.5, start: Number(inVal.value) || 0, end: Number(outVal.value) || m.duration})});
      if (!r.clips.length) return alert("Tidak ada bagian bersuara yang ditemukan.");
      if (!confirm(`Buat ${r.clips.length} klip, buang ${fmtTime(r.removed_seconds)} keheningan, sisa ${fmtTime(r.kept_seconds)}?`)) return;
      r.clips.forEach((c) => state.project.clips.push(c));
      saveProject();
    });
    document.querySelectorAll(".scene").forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.classList.contains("add-scene")) return;
      inVal.value = el.dataset.s; outVal.value = el.dataset.e; player.currentTime = Number(el.dataset.s);
    }));
    document.querySelectorAll(".add-scene").forEach((el) => el.addEventListener("click", () => addClip(m, Number(el.dataset.s), Number(el.dataset.e))));
    document.querySelectorAll(".silences div[data-t]").forEach((el) => el.addEventListener("click", () => { player.currentTime = Number(el.dataset.t); player.play(); }));
    bindTranscriptBlock(m);
  }

  function bindTranscriptBlock(m) {
    const player = $("#player");
    $("#btn-transcribe")?.addEventListener("click", async () => {
      try {
        await api(`/api/media/${m.id}/transcribe`, {method: "POST", body: JSON.stringify({model: $("#tr-model").value, language: $("#tr-lang").value})});
        await refreshMedia(); updateTranscriptBlock();
      } catch (e) { alert(e.message); }
    });
    document.querySelectorAll(".transcript div[data-t]").forEach((el) => el.addEventListener("click", () => { if (player) { player.currentTime = Number(el.dataset.t); player.play(); } }));
  }

  function updateTranscriptBlock() {
    const m = state.media.find((x) => x.id === state.current);
    const block = $("#transcript-block");
    if (!m || !block) return;
    block.innerHTML = renderTranscriptBlock(m);
    bindTranscriptBlock(m);
  }

  // ------------------------------------------------------------------ projects / timeline
  async function refreshProjects(keepId) {
    state.projects = await api("/api/projects");
    const sel = $("#project-select");
    if (!state.projects.length) {
      const p = await api("/api/projects", {method: "POST", body: JSON.stringify({name: "Project 1"})});
      state.projects = [p];
    }
    sel.innerHTML = state.projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    const id = keepId || (state.project && state.project.id) || state.projects[0].id;
    sel.value = state.projects.some((p) => p.id === id) ? id : state.projects[0].id;
    state.project = state.projects.find((p) => p.id === sel.value);
    renderTimeline();
  }
  $("#project-select").addEventListener("change", (e) => { state.project = state.projects.find((p) => p.id === e.target.value); renderTimeline(); });
  $("#project-new").addEventListener("click", async () => {
    const name = prompt("Nama project:", `Project ${state.projects.length + 1}`);
    if (name === null) return;
    const p = await api("/api/projects", {method: "POST", body: JSON.stringify({name})});
    await refreshProjects(p.id);
  });
  $("#project-delete").addEventListener("click", async () => {
    if (!state.project || !confirm(`Hapus project "${state.project.name}"?`)) return;
    try { await api(`/api/projects/${state.project.id}`, {method: "DELETE"}); state.project = null; await refreshProjects(); }
    catch (e) { alert(e.message); }
  });

  function addClip(m, start, end) {
    if (!state.project) return;
    if (end <= start) return alert("OUT harus lebih besar dari IN");
    state.project.clips.push({media_id: m.id, in: Number(start.toFixed(3)), out: Number(end.toFixed(3)), label: m.filename, speed: 1, remove_silence: null});
    saveProject();
  }

  let saveTimer = null;
  function saveProject(immediate) {
    clearTimeout(saveTimer);
    const doSave = async () => {
      const p = state.project;
      const s = p.settings;
      const saved = await api(`/api/projects/${p.id}`, {method: "PUT", body: JSON.stringify({clips: p.clips, settings: s})});
      state.project = saved;
      const i = state.projects.findIndex((x) => x.id === saved.id); if (i >= 0) state.projects[i] = saved;
      renderTimeline();
    };
    if (immediate) return doSave();
    saveTimer = setTimeout(doSave, 300);
    renderTimeline();
  }

  function readSettingsFromForm() {
    const s = state.project.settings;
    s.preset = $("#s-preset").value; s.transition = $("#s-transition").value;
    s.transition_duration = Number($("#s-tdur").value) || 0.5;
    s.remove_silence = $("#s-silence").checked; s.silence_margin = Number($("#s-margin").value) || 0.2;
    s.normalize = $("#s-normalize").checked; s.lufs = Number($("#s-lufs").value) || -14;
    s.title = $("#s-title").value; s.title_seconds = Number($("#s-title-seconds").value) || 3;
  }
  ["#s-preset", "#s-transition", "#s-tdur", "#s-silence", "#s-margin", "#s-normalize", "#s-lufs", "#s-title", "#s-title-seconds"].forEach((id) =>
    $(id).addEventListener("change", () => { if (!state.project) return; readSettingsFromForm(); saveProject(); }));

  function renderTimeline() {
    const p = state.project;
    const box = $("#clips");
    if (!p) { box.innerHTML = ""; return; }
    const s = p.settings || {};
    $("#s-preset").value = s.preset || "youtube"; $("#s-transition").value = s.transition || "none";
    $("#s-tdur").value = s.transition_duration ?? 0.5; $("#s-silence").checked = !!s.remove_silence;
    $("#s-margin").value = s.silence_margin ?? 0.2; $("#s-normalize").checked = s.normalize !== false;
    $("#s-lufs").value = s.lufs ?? -14; $("#s-title").value = s.title || ""; $("#s-title-seconds").value = s.title_seconds ?? 3;
    if (!p.clips.length) { box.innerHTML = '<p class="muted">Belum ada klip. Pilih media, tentukan IN/OUT, lalu "Tambah ke timeline".</p>'; }
    else {
      let total = 0;
      box.innerHTML = p.clips.map((c, i) => {
        const m = state.media.find((x) => x.id === c.media_id);
        const dur = ((c.out ?? (m ? m.duration : 0)) - (c.in || 0)) / (c.speed || 1); total += Math.max(0, dur);
        return `<div class="clip" data-i="${i}"><div class="top"><span class="muted">${i + 1}</span><span class="name">${esc(c.label || (m ? m.filename : c.media_id))}</span>
          <button class="btn small mv" data-d="-1" title="Naik">↑</button><button class="btn small mv" data-d="1" title="Turun">↓</button><button class="btn small danger rm" title="Hapus">✕</button></div>
          <div class="fields"><label>IN <input type="number" step="0.1" class="f-in" value="${c.in ?? 0}"></label>
          <label>OUT <input type="number" step="0.1" class="f-out" value="${c.out ?? ""}"></label>
          <label>×<input type="number" step="0.05" min="0.25" max="4" class="f-speed" value="${c.speed ?? 1}" title="kecepatan"></label>
          <span class="muted">${fmtTime(dur)}</span></div></div>`;
      }).join("") + `<div class="muted" style="text-align:right">Total ± ${fmtTime(total)}${s.transition && s.transition !== "none" && p.clips.length > 1 ? " − transisi" : ""}</div>`;
      box.querySelectorAll(".clip").forEach((el) => {
        const i = Number(el.dataset.i);
        el.querySelectorAll(".mv").forEach((b) => b.addEventListener("click", () => {
          const j = i + Number(b.dataset.d); if (j < 0 || j >= p.clips.length) return;
          [p.clips[i], p.clips[j]] = [p.clips[j], p.clips[i]]; saveProject();
        }));
        $(".rm", el).addEventListener("click", () => { p.clips.splice(i, 1); saveProject(); });
        $(".f-in", el).addEventListener("change", (e) => { p.clips[i].in = Number(e.target.value) || 0; saveProject(); });
        $(".f-out", el).addEventListener("change", (e) => { p.clips[i].out = e.target.value === "" ? null : Number(e.target.value); saveProject(); });
        $(".f-speed", el).addEventListener("change", (e) => { p.clips[i].speed = Number(e.target.value) || 1; saveProject(); });
      });
    }
    renderRenderStatus();
  }

  function renderRenderStatus() {
    const p = state.project, box = $("#render-status");
    if (!p) { box.innerHTML = ""; return; }
    const job = p.job, lr = p.last_render;
    $("#btn-render").disabled = !!job;
    if (job) {
      box.innerHTML = `<div class="bar render"><div style="width:${(job.progress * 100).toFixed(1)}%"></div></div><div class="muted">${Math.round(job.progress * 100)} % · ${esc(job.message)} <button class="btn small" id="btn-cancel">Batal</button></div>`;
      $("#btn-cancel").addEventListener("click", () => api(`/api/jobs/${job.id}/cancel`, {method: "POST"}).catch(() => {}));
      return;
    }
    if (lr && lr.status === "done") {
      const v = lr.video || {};
      box.innerHTML = `<div class="result"><strong>✔ Hasil:</strong> ${fmtTime(lr.duration)} · ${v.width}×${v.height} ${v.fps}fps · ${fmtBytes(lr.size)}${lr.loudness && lr.loudness.integrated_lufs != null ? " · " + lr.loudness.integrated_lufs + " LUFS" : ""}${lr.removed_silence ? " · keheningan dibuang " + fmtTime(lr.removed_silence) : ""}
        <div class="row"><a class="btn primary" href="/api/projects/${p.id}/output" download>⬇ Unduh video</a></div>
        <video src="/api/projects/${p.id}/output?t=${lr.job_id}" controls preload="metadata"></video>
        ${(lr.plan && lr.plan.warnings || []).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("")}</div>`;
    } else if (lr && lr.status === "failed") {
      box.innerHTML = `<div class="err">Render gagal: ${esc(lr.error)}</div>`;
    } else box.innerHTML = "";
  }

  $("#btn-plan").addEventListener("click", async () => {
    if (!state.project) return;
    readSettingsFromForm(); await saveProject(true);
    const pb = $("#plan-box");
    try {
      const plan = await api(`/api/projects/${state.project.id}/plan`);
      const lines = [`Frame: ${plan.frame.width}×${plan.frame.height} @ ${plan.frame.fps} fps (${plan.preset})`,
        `Transisi: ${plan.transition} ${plan.transition !== "none" ? plan.transition_duration + "s" : ""}`,
        `Perkiraan durasi: ${fmtTime(plan.estimated_duration)}`, ""];
      plan.items.forEach((it) => lines.push(`${it.index + 1}. ${it.filename}  IN ${fmtTime(it.in)} OUT ${fmtTime(it.out)}  → ${it.segments.length} segmen, ${fmtTime(it.duration)}${it.removed_silence ? ", buang " + it.removed_silence.toFixed(1) + "s hening" : ""}`));
      plan.warnings.forEach((w) => lines.push("⚠ " + w));
      pb.textContent = lines.join("\n");
    } catch (e) { pb.textContent = "Tidak bisa merencanakan: " + e.message; }
    pb.classList.remove("hidden");
  });

  $("#btn-render").addEventListener("click", async () => {
    if (!state.project) return;
    readSettingsFromForm(); await saveProject(true);
    try { await api(`/api/projects/${state.project.id}/render`, {method: "POST"}); await refreshProjects(); }
    catch (e) { alert("Render ditolak: " + e.message); }
  });

  // ------------------------------------------------------------------ polling
  async function tick() {
    try {
      const busyMedia = state.media.some((m) => m.status === "queued" || m.status === "analyzing" || m.transcribe_job);
      const busyProject = state.project && state.project.job;
      if (busyMedia || busyProject || !state.media.length) {
        await refreshMedia();
        if (state.current) {
          const m = state.media.find((x) => x.id === state.current);
          if (m && (m.status !== "ready" || !$("#player"))) renderDetail();
          else if (m && (m.transcribe_job || $("#btn-transcribe:disabled"))) updateTranscriptBlock();
        }
      }
      if (busyProject) {
        const keep = state.project.id;
        state.projects = await api("/api/projects");
        state.project = state.projects.find((p) => p.id === keep) || state.project;
        renderRenderStatus();
      }
    } catch (e) { /* server sibuk; coba lagi */ }
    setTimeout(tick, 1500);
  }

  (async () => { await refreshMedia(); await refreshProjects(); tick(); })();
})();
