(function () {
  "use strict";
  const TOKEN = document.querySelector('meta[name="studio-token"]').content;
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const chars = t => [...String(t).replace(/\s/g, "")].length;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const S = { cfg: null, env: [], projects: [], p: null, gate: null, bgm: [], view: "projects", selectedSeg: 0, pendingFiles: [] };
  const RULES = { srWarn: 5, srFail: 7, goldMax: 0.35 };
  const STATUS = {
    new: ["idle", "等待分析素材"], scanning: ["idle", "素材分析中"], draft: ["idle", "草稿：編輯字幕"],
    building: ["idle", "輸出中"], review: ["warn", "待你看片確認"], done: ["ok", "可以發布"], error: ["bad", "需要處理"]
  };

  /* ---------------------------------------------------------------- api */
  async function api(method, path, body, raw) {
    const opt = { method, headers: { "X-Studio-Token": TOKEN } };
    if (raw !== undefined) opt.body = raw;
    else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    const res = await fetch(path, opt);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "發生錯誤（" + res.status + "）");
    return data;
  }
  function upload(path, file, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("PUT", path);
      x.setRequestHeader("X-Studio-Token", TOKEN);
      x.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total);
      x.onload = () => {
        let d = {}; try { d = JSON.parse(x.responseText); } catch (e) { /* not json */ }
        x.status < 300 ? resolve(d) : reject(new Error(d.error || "上傳失敗"));
      };
      x.onerror = () => reject(new Error("上傳失敗，請確認 Reels 工作室還開著"));
      x.send(file);
    });
  }
  async function waitJob(job, onTick) {
    while (job.state === "running") {
      onTick && onTick(job);
      await sleep(700);
      job = await api("GET", "/api/jobs/" + job.id);
    }
    onTick && onTick(job);
    return job;
  }

  /* ---------------------------------------------------------------- ui helpers */
  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
    $("#toasts").appendChild(t); setTimeout(() => t.remove(), 2600);
  }
  function fail(err) { toast(err.message || String(err)); }
  function setNav(name) {
    document.querySelectorAll(".nav button").forEach(b => b.dataset.go === name ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  }
  const envMissing = () => S.env.filter(e => e.required && !e.ok);
  function refreshChrome() {
    const b = $("#envbadge"), m = envMissing();
    if (!S.env.length) { b.className = "envbadge"; b.textContent = "檢查中…"; }
    else { b.className = "envbadge " + (m.length ? "bad" : "ok"); b.textContent = m.length ? "缺少 " + m.length + " 個必要軟體" : "環境已就緒"; }
    $("#ws-label").textContent = S.cfg && S.cfg.workspace || "尚未選擇素材資料夾";
    $("#ws-label").title = $("#ws-label").textContent;
    const tag = S.cfg && S.cfg.profile.tagline;
    $("#brand-sub").textContent = tag || "IG Reels 9:16";
  }
  function dialog(html) {
    $("#layer").innerHTML = `<div class="scrim"><div class="dialog" role="dialog" aria-modal="true">${html}</div></div>`;
    const f = $("#layer [data-autofocus]") || $("#layer button.primary") || $("#layer button");
    f && f.focus();
  }
  const closeDialog = () => { $("#layer").innerHTML = ""; };
  function stepsHtml(steps) {
    return `<div class="progress"><i id="pbar"></i></div><ol class="steps" id="psteps">${steps.map(s => `<li><span class="ic"></span>${esc(s)}</li>`).join("")}</ol>`;
  }
  function paintSteps(job) {
    const lis = document.querySelectorAll("#psteps li"), bar = $("#pbar");
    if (!lis.length) return;
    const done = job.state === "done" ? lis.length : job.step;
    lis.forEach((li, j) => { li.className = j < done ? "done" : j === done && job.state === "running" ? "now" : ""; li.querySelector(".ic").textContent = j < done ? "✓" : ""; });
    bar.style.width = Math.max(4, done / lis.length * 100) + "%";
    const log = $("#joblog"); if (log) log.textContent = (job.log || []).join("\n");
  }

  /* ---------------------------------------------------------------- navigation */
  async function go(view, arg) {
    S.view = view;
    try {
      if (view === "projects") await loadProjects();
      if (view === "editor" || view === "result") { S.p = await api("GET", "/api/projects/" + arg); if (view === "editor") { S.bgm = (await api("GET", "/api/bgm")).folders; } }
      if (view === "music") S.bgm = S.cfg.workspace && kitReady() ? (await api("GET", "/api/bgm")).folders : [];
    } catch (e) { fail(e); }
    $("#view").innerHTML = V[view](arg);
    $("#view").focus({ preventScroll: true });
    window.scrollTo(0, 0);
    if (view === "editor") runCheck();
    if (view === "result") paintQa();
    location.hash = arg ? view + "/" + arg : view;
  }
  const kitReady = () => S.env.some(e => e.id === "kit" && e.ok);
  async function loadProjects() { S.projects = (await api("GET", "/api/projects")).projects; }
  async function loadEnv() { S.env = (await api("GET", "/api/env")).items; refreshChrome(); }

  /* ---------------------------------------------------------------- views */
  const V = {};

  V.projects = () => {
    setNav("projects");
    const miss = envMissing();
    const cards = S.projects.map(p => {
      const [cls, label] = STATUS[p.status] || STATUS.draft;
      const bg = p.thumb ? `style="background-image:url('/api/projects/${p.id}/thumb/0')"` : "";
      return `<button class="card" data-open="${esc(p.id)}" data-status="${esc(p.status)}"><div class="thumb ${p.thumb ? "" : "blank"}" ${bg}><span>${esc(p.title)}</span></div>
        <div class="meta"><span class="pill ${cls}">${label}</span><span class="muted">${esc(p.updated || p.created || "")}${p.score ? " · 品質 " + Math.round(p.score) + " 分" : ""}</span></div></button>`;
    }).join("");
    return `
    <div class="head"><div><h1>我的 Reels</h1><p class="sub">把同一個景點拍的片段丟進來，自動排成 IG Reels。</p></div>
      <button class="btn primary" data-act="new" ${kitReady() ? "" : "disabled"}>＋ 新增 Reels</button></div>
    ${miss.length ? `<div class="banner alert"><p><b>缺少 ${esc(miss.map(m => m.name).join("、"))}</b>，${kitReady() ? "現在還不能輸出影片" : "還不能開始剪片"}。</p><button class="btn sm primary" data-go="env">前往安裝</button></div>` : ""}
    ${kitReady() ? `<div class="grid"><button class="card new" data-act="new"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v8M8 12h8"/></svg><b>新增一支 Reels</b><span>mp4／mov，手機直拍橫拍都可以</span></button>${cards}</div>`
      : `<div class="panel empty"><b>安裝剪輯引擎後就能開始</b><span>到「環境檢查」安裝 video-autopilot-kit，大約 10 MB。</span><button class="btn primary" data-go="env">前往環境檢查</button></div>`}`;
  };

  V.new = () => {
    setNav("projects");
    return `
    <div class="crumb"><button data-go="projects">我的 Reels</button>›<span>新增</span></div>
    <div class="head"><div><h1>新增一支 Reels</h1><p class="sub">同一個景點的片段放在一起，3–8 段最剛好。原始檔不會被修改。</p></div></div>
    <div class="panel"><div class="form">
      <div class="field"><label for="np-title">地點名稱</label><input id="np-title" type="text" placeholder="例如：名古屋城" data-autofocus><span class="hint">會變成開場的大字</span></div>
      <div class="field"><label for="np-what">一句話說這是什麼</label><input id="np-what" type="text" placeholder="例如：全家第一次來看天守閣"></div>
      <div class="field"><label for="np-addr">地址（選填）</label><input id="np-addr" type="text" placeholder="例如：愛知縣名古屋市中區本丸1-1"><span class="hint">放進 IG 文案</span></div>
    </div></div>
    <label class="drop" id="drop" for="file-in">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg>
      <b>把影片拖到這裡，或點一下選擇檔案</b>
      <span class="muted">支援 mp4、mov。直拍、橫拍混著放沒關係，會自動轉成直式。</span>
      <input id="file-in" type="file" accept=".mp4,.mov,video/mp4,video/quicktime" multiple hidden>
    </label>
    <div id="file-list"></div>
    <div class="row"><button class="btn primary" data-act="create" id="create-btn" disabled>上傳並自動排片</button><span class="muted" id="create-hint">先填地點名稱並加入影片</span></div>`;
  };
  function renderFiles() {
    const fl = $("#file-list"); if (!fl) return;
    fl.innerHTML = S.pendingFiles.length ? `<div class="files">${S.pendingFiles.map((f, i) => `<div><span>${esc(f.name)}</span><span class="muted mono">${(f.size / 1048576).toFixed(1)} MB</span><button class="icon-btn" data-rmfile="${i}" aria-label="移除 ${esc(f.name)}">✕</button></div>`).join("")}</div>` : "";
    updateCreate();
  }
  function updateCreate() {
    const ok = S.pendingFiles.length > 0 && ($("#np-title").value.trim() !== "");
    $("#create-btn").disabled = !ok;
    $("#create-hint").textContent = ok ? S.pendingFiles.length + " 個檔案" : "先填地點名稱並加入影片";
  }
  async function createProject() {
    const title = $("#np-title").value.trim(), what = $("#np-what").value.trim(), addr = $("#np-addr").value.trim();
    const files = S.pendingFiles.slice();
    $("#view").innerHTML = `<div class="head"><div><h1>上傳「${esc(title)}」的素材</h1><p class="sub">檔案會複製到素材資料夾，原始檔不動。</p></div></div>
      <div class="panel"><div class="files">${files.map((f, i) => `<div><span>${esc(f.name)}</span><span class="muted mono" id="up-${i}">等待中</span><span></span></div>`).join("")}</div></div>`;
    let p;
    try {
      p = await api("POST", "/api/projects", { title, what, addr });
      for (let i = 0; i < files.length; i++) {
        await upload(`/api/projects/${p.id}/clips?name=${encodeURIComponent(files[i].name)}`, files[i],
          r => { $("#up-" + i).textContent = Math.round(r * 100) + "%"; });
        $("#up-" + i).textContent = "完成";
      }
      S.pendingFiles = [];
      await scanProject(p.id, title);
    } catch (e) {
      fail(e);
      if (p) go("projects"); else go("new");
    }
  }
  async function scanProject(id, title) {
    $("#view").innerHTML = `<div class="head"><div><h1>正在分析「${esc(title)}」的素材</h1><p class="sub">挑出最清楚、最穩的畫面當開場，再排成適合 Reels 的節奏。大約需要 1 分鐘。</p></div></div>
      <div class="panel">${stepsHtml(["轉成 9:16 直式", "產生縮圖", "挑選開場畫面並排片段", "準備字幕表"])}<details class="log"><summary>詳細紀錄</summary><pre id="joblog"></pre></details></div>`;
    const job = await waitJob(await api("POST", `/api/projects/${id}/scan`), paintSteps);
    if (job.state === "failed") {
      $("#view").insertAdjacentHTML("beforeend", `<div class="errorbox">${esc(job.error)}</div><div class="row"><button class="btn" data-go="projects">回到我的 Reels</button></div>`);
      return;
    }
    go("editor", id);
  }

  V.editor = () => {
    setNav("projects");
    const p = S.p;
    if (!p) return `<p>找不到這個專案。</p>`;
    if (!p.segs.length) {
      return `<div class="crumb"><button data-go="projects">我的 Reels</button>›<span>${esc(p.title)}</span></div>
        <div class="head"><div><h1>${esc(p.title)}</h1><p class="sub">${p.clips.length} 個檔案，還沒分析</p></div></div>
        ${p.error ? `<div class="errorbox">${esc(p.error)}</div>` : ""}
        <div class="row"><button class="btn primary" data-act="rescan">分析素材</button><button class="btn danger" data-act="delete">刪除這支</button></div>`;
    }
    const total = p.segs.reduce((a, s) => a + s.dur, 0);
    let acc = 0;
    const hasBgm = S.bgm.some(f => f.tracks.length);
    return `
    <div class="crumb"><button data-go="projects">我的 Reels</button>›<span>${esc(p.title)}</span></div>
    <div class="head"><div><h1>${esc(p.title)}</h1><p class="sub">${esc(p.what || "")}</p></div>
      <div class="row">${p.has_output ? `<button class="btn" data-act="show-result">看上次的成品</button>` : ""}
      <button class="btn primary" data-act="build" id="build-btn" disabled>輸出影片</button></div></div>
    ${p.error ? `<div class="errorbox">${esc(p.error)}</div>` : ""}
    <div class="panel">
      <div class="between"><h2>片段</h2><span class="muted mono" id="total">${total.toFixed(1)} 秒 · ${p.segs.length} 段</span></div>
      <div class="strip-wrap"><div class="strip">${p.segs.map((s, i) => `<button class="seg" style="flex:${s.dur} 1 0;background-image:url('/api/projects/${p.id}/thumb/${i}')" aria-pressed="${i === S.selectedSeg}" data-seg="${i}"><span class="tag">${i === 0 ? "開場" : i === p.segs.length - 1 ? "循環" : "片段 " + i}</span><span class="lbl">${esc(s.label)}<br><span class="mono" id="segdur-${i}">${s.dur.toFixed(1)}s</span></span></button>`).join("")}</div>
      <div class="ruler mono">${p.segs.map(s => { const a = acc; acc += s.dur; return `<span>${a.toFixed(1)}s</span>`; }).join("")}<span>${total.toFixed(1)}s</span></div></div>
      ${segControl(p)}
    </div>
    <div class="split">
      <div class="panel">
        <div class="between"><h2>字幕</h2><div class="legend"><span class="l-ok">讀得完</span><span class="l-warn">偏快</span><span class="l-bad">讀不完，會擋下</span></div></div>
        <div id="caps">${capsHtml(p)}</div>
        <div class="row"><button class="btn sm" data-act="addcap">＋ 在「${esc(p.segs[S.selectedSeg].label)}」加字幕</button><span class="hint">最後一段會接回開場循環播放，不放字幕。</span></div>
      </div>
      <div class="panel">
        <h2>輸出前檢查</h2>
        <div class="meter" id="goldmeter"></div>
        <ul class="checks" id="checks"><li class="muted">檢查中…</li></ul>
        <hr style="border:0;border-top:1px solid var(--line);margin:0">
        <h3>背景音樂</h3>
        ${hasBgm ? `<select id="bgm-sel" aria-label="背景音樂分類"><option value="">選擇分類…</option>${S.bgm.filter(f => f.tracks.length).map(f => `<option value="${esc(f.folder)}" ${f.folder === p.bgm_folder ? "selected" : ""}>${esc(f.folder)}（${f.tracks.length} 首）</option>`).join("")}</select>
          <select id="bgm-prefer" aria-label="音樂風格"><option value="energetic" ${p.bgm_prefer !== "chill" ? "selected" : ""}>輕快</option><option value="chill" ${p.bgm_prefer === "chill" ? "selected" : ""}>放鬆</option></select>
          <span class="hint">會從分類裡挑長度最合適的一首，自動淡出或接續。</span>`
        : `<p class="muted">音樂庫是空的。</p><button class="btn sm" data-go="music">到音樂庫加入音樂</button>`}
      </div>
    </div>
    <div class="row"><button class="btn danger sm" data-act="delete">刪除這支 Reels</button></div>`;
  };
  function segControl(p) {
    const s = p.segs[S.selectedSeg];
    return `<div class="form" style="align-items:end">
      <div class="field"><label for="seg-dur">「${esc(s.label)}」長度：<span class="mono" id="seg-dur-v">${s.dur.toFixed(1)}</span> 秒</label>
        <input id="seg-dur" type="range" min="0.6" max="${Math.max(6, s.orig_dur || s.dur).toFixed(1)}" step="0.1" value="${s.dur}"></div>
      <span class="hint">${S.selectedSeg === 0 ? "開場片段建議 2 秒以內。自動挑選了畫面最清楚、最穩的一段。" : S.selectedSeg === p.segs.length - 1 ? "這段會接回開場畫面，讓影片無縫循環。" : "拖動調整這段畫面的長度。"}</span>
    </div>`;
  }
  function capsHtml(p) {
    if (!p.caps.length) return `<p class="muted">還沒有字幕。選一個片段後按「加字幕」。</p>`;
    return `<div class="caprow head-row"><span>片段</span><span>字幕文字</span><span>閱讀速度</span><span>顏色</span><span></span></div>` +
      p.caps.map((c, i) => `<div class="caprow">
        <div class="mini" style="background-image:url('/api/projects/${p.id}/thumb/${c.seg}')" title="${esc(p.segs[c.seg].label)}"></div>
        <input type="text" id="cap-${i}" class="${c.color === "gold" ? "gold" : ""}" value="${esc(c.text)}" data-captext="${i}" aria-label="第 ${i + 1} 條字幕">
        <div class="speed" id="sp-${i}"><b class="mono">—</b><span class="bar"><i style="width:0"></i></span></div>
        <select id="col-${i}" data-capcol="${i}" aria-label="字幕顏色"><option value="white" ${c.color !== "gold" ? "selected" : ""}>白色</option><option value="gold" ${c.color === "gold" ? "selected" : ""}>金色重點</option></select>
        <button class="icon-btn" data-delcap="${i}" aria-label="刪除這條字幕"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button>
      </div>`).join("");
  }

  /* live checks: estimate instantly, then confirm with the kit's own gate */
  function estimateSpeeds(p) {
    return p.caps.map(c => {
      const n = p.caps.filter(x => x.seg === c.seg && x.text.trim()).length || 1;
      return chars(c.text) / (p.segs[c.seg].dur * 0.8 / n);
    });
  }
  function gateSpeeds(p, rep) {
    if (!rep || !rep.caps || !rep.caps.length) return null;
    const pool = rep.caps.filter(c => c.kind !== "chip" && c.kind !== "addr").slice();
    return p.caps.map(c => {
      const k = pool.findIndex(r => r.text === c.text.trim());
      if (k < 0) return null;
      const r = pool.splice(k, 1)[0];
      return chars(r.text) / Math.max(0.1, r.end - r.start);
    });
  }
  function paintSpeeds() {
    const p = S.p; if (!p || !$("#caps")) return;
    const est = estimateSpeeds(p), exact = gateSpeeds(p, S.gate) || [];
    p.caps.forEach((c, i) => {
      const el = $("#sp-" + i); if (!el) return;
      if (!c.text.trim()) { el.className = "speed"; el.querySelector("b").textContent = "空白"; el.querySelector("i").style.width = "0"; return; }
      const sp = exact[i] != null ? exact[i] : est[i];
      el.className = "speed " + (sp > RULES.srFail ? "bad" : sp > RULES.srWarn ? "warn" : "ok");
      el.querySelector("b").textContent = sp.toFixed(1) + " 字/秒";
      el.querySelector("i").style.width = Math.min(100, sp / 9 * 100) + "%";
      el.title = exact[i] != null ? "依實際字幕時間計算" : "預估值，檢查完成後會更新";
    });
    const all = p.caps.reduce((a, c) => a + chars(c.text), 0), gold = p.caps.filter(c => c.color === "gold").reduce((a, c) => a + chars(c.text), 0);
    const ratio = all ? gold / all : 0;
    $("#goldmeter").innerHTML = `<span>金色字佔 <b class="mono">${Math.round(ratio * 100)}%</b>（上限 35%）</span><div class="progress"><i style="width:${Math.min(100, ratio / RULES.goldMax * 100)}%;background:${ratio > RULES.goldMax ? "var(--bad)" : "var(--gold)"}"></i></div>`;
    $("#total").textContent = p.segs.reduce((a, s) => a + s.dur, 0).toFixed(1) + " 秒 · " + p.segs.length + " 段";
  }
  function paintChecks() {
    const rep = S.gate, ul = $("#checks"); if (!ul) return;
    const items = [];
    if (!rep) items.push(`<li class="muted">檢查中…</li>`);
    else {
      rep.fails.forEach(f => items.push(`<li class="bad"><span class="ic">✕</span><span><b>${esc(f)}</b></span></li>`));
      rep.warns.forEach(w => items.push(`<li class="warn"><span class="ic">!</span><span>${esc(w.replace(/（不影響輸出）$/, ""))}<small>可以輸出，改善後效果更好</small></span></li>`));
      if (rep.ok) items.unshift(`<li class="ok"><span class="ic">✓</span><span><b>可以輸出</b><small>片長 ${Number(rep.dur || 0).toFixed(1)} 秒，符合 IG Reels 13–60 秒</small></span></li>`);
    }
    ul.innerHTML = items.join("");
    const btn = $("#build-btn"), miss = envMissing();
    if (btn) {
      btn.disabled = !rep || !rep.ok || miss.length > 0;
      btn.title = miss.length ? "缺少 " + miss.map(m => m.name).join("、") + "，請先到環境檢查安裝" : rep && !rep.ok ? "先修好紅色項目才能輸出" : "";
    }
  }
  let saveTimer = null, checkSeq = 0;
  function scheduleSave(patch) {
    Object.assign(pendingPatch, patch);
    S.gate = null; paintChecks(); paintSpeeds();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 500);
  }
  const pendingPatch = {};
  async function flushSave() {
    const patch = Object.assign({}, pendingPatch);
    Object.keys(pendingPatch).forEach(k => delete pendingPatch[k]);
    if (!Object.keys(patch).length) return;
    try { const p = await api("POST", "/api/projects/" + S.p.id, patch); S.p.status = p.status; S.p.error = ""; await runCheck(); }
    catch (e) { fail(e); }
  }
  async function runCheck() {
    if (!S.p || !S.p.segs.length) return;
    const seq = ++checkSeq;
    try {
      const rep = await api("POST", `/api/projects/${S.p.id}/check`);
      if (seq !== checkSeq || S.view !== "editor") return;
      S.gate = rep; paintChecks(); paintSpeeds();
    } catch (e) { fail(e); }
  }

  async function buildProject() {
    clearTimeout(saveTimer); await flushSave();
    const p = S.p;
    $("#view").innerHTML = `<div class="head"><div><h1>正在輸出「${esc(p.title)}」</h1><p class="sub">大約需要 1–3 分鐘，可以先去做別的事，回到這裡就能看到進度。</p></div></div>
      <div class="panel">${stepsHtml(["輸出前檢查", "剪接片段並燒入字幕", "混音", "畫面、聲音與循環檢查", "完成"])}<details class="log"><summary>詳細紀錄</summary><pre id="joblog"></pre></details></div>`;
    try {
      const job = await waitJob(await api("POST", `/api/projects/${p.id}/build`), paintSteps);
      if (job.state === "failed") {
        $("#view").insertAdjacentHTML("beforeend", `<div class="errorbox">${esc(job.error)}</div><div class="row"><button class="btn primary" data-act="back-edit">回去修改</button></div>`);
        return;
      }
      go("result", p.id);
    } catch (e) { fail(e); go("editor", p.id); }
  }

  V.result = () => {
    setNav("projects");
    const p = S.p;
    return `
    <div class="crumb"><button data-go="projects">我的 Reels</button>›<button data-act="back-edit">${esc(p.title)}</button>›<span>成品</span></div>
    <div class="head"><div><h1>${p.status === "done" ? "已確認，可以發布" : "成品完成"}</h1><p class="sub">${p.status === "done" ? "已於 " + esc(p.approved || "") + " 確認。" : "技術檢查已通過，請看過一次再發布。"}</p></div>
      <div class="row"><button class="btn" data-act="back-edit">回去修改</button><button class="btn" data-act="reveal">開啟檔案位置</button></div></div>
    <div class="result">
      <video controls loop playsinline preload="metadata" poster="/api/projects/${p.id}/thumb/0" src="/api/projects/${p.id}/video?v=${encodeURIComponent(p.updated || "")}"></video>
      <div style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <div class="panel" id="qa"><p class="muted">讀取品質報告…</p></div>
        <div class="panel"><div class="between"><h2>IG 文案</h2><button class="btn sm" data-act="copy">複製文案</button></div>
          <textarea id="copy-text" aria-label="IG 文案">${esc(p.copy || "")}</textarea><span class="hint">修改後會自動儲存。</span></div>
      </div>
    </div>`;
  };
  async function paintQa() {
    try {
      const qa = await api("GET", `/api/projects/${S.p.id}/qa`);
      if (!$("#qa")) return;
      const done = S.p.status === "done";
      $("#qa").innerHTML = qa.score == null ? `<p class="muted">沒有品質報告。</p>` : `
        <div class="between"><div class="score"><b class="mono">${done ? 100 : Math.round(qa.score)}</b><span class="muted">/ 100 品質分數</span></div>
        ${done ? `<span class="pill ok">已確認</span>` : `<button class="btn primary sm" data-act="approve">我看過了，可以發布</button>`}</div>
        <div class="dims">${qa.dims.map(d => `<span>${esc(d.label)}</span><span class="mono ${d.points < d.max && !(done && d.key === "human_aesthetic_review") ? "muted" : ""}">${done && d.key === "human_aesthetic_review" ? d.max : d.points} / ${d.max}</span>`).join("")}</div>`;
    } catch (e) { fail(e); }
  }

  V.env = () => {
    setNav("env");
    const miss = envMissing();
    const row = e => {
      const st = e.busy ? "busy" : e.ok ? "ok" : e.required ? "bad" : "opt";
      const mark = e.busy ? "…" : e.ok ? "✓" : e.required ? "✕" : "–";
      let acts = "";
      if (e.busy) acts = `<span class="muted">安裝中…</span>`;
      else if (e.ok) acts = `<span class="muted mono">${esc(e.version || "已安裝")}</span>${e.updatable ? `<button class="btn sm" data-act="kit-update">檢查更新</button>` : ""}`;
      else if (e.blocked) acts = `<button class="btn sm" data-go="settings">先選資料夾</button>`;
      else if (e.install) acts = `<button class="btn sm ${e.required ? "primary" : ""}" data-envask="${e.id}">安裝</button>`;
      else if (e.manual_url) acts = `<a class="btn sm" href="${esc(e.manual_url)}" target="_blank" rel="noopener">說明</a>`;
      const note = e.ok ? e.why : e.blocked || (e.install ? e.why + (e.size ? " · " + e.size : "") : (e.manual || e.why));
      return `<div class="envrow ${st}"><span class="ic">${mark}</span><span><b>${esc(e.name)}</b>${e.required ? "" : ' <span class="pill idle">選用</span>'}<small>${esc(note)}</small></span><span class="acts">${acts}</span></div>`;
    };
    const installable = miss.filter(e => e.install && !e.blocked);
    return `<div class="head"><div><h1>環境檢查</h1><p class="sub">每次開啟會自動檢查。缺少的軟體會先問你，同意後才安裝。</p></div>
      <div class="row"><button class="btn" data-act="recheck">重新檢查</button>${installable.length ? `<button class="btn primary" data-act="install-all">安裝全部必要項目（${installable.length}）</button>` : ""}</div></div>
    ${!S.env.length ? `<p class="muted">檢查中…</p>` : miss.length ? `<div class="banner alert"><p><b>還不能輸出影片。</b>缺少 ${esc(miss.map(m => m.name).join("、"))}。</p></div>` : `<div class="banner"><p><b>都準備好了。</b>必要軟體全部就緒。</p></div>`}
    <div class="panel"><h2>必要</h2><div>${S.env.filter(e => e.required).map(row).join("")}</div></div>
    <div class="panel"><h2>選用</h2><div>${S.env.filter(e => !e.required).map(row).join("")}</div></div>
    <div id="envjob"></div>`;
  };
  function askInstall(ids) {
    const items = ids.map(id => S.env.find(e => e.id === id));
    dialog(`<h2>要安裝 ${esc(items.map(i => i.name).join("、"))} 嗎？</h2>
      <p class="muted">會依序執行下面的動作。字型和 Python 套件只安裝給目前的使用者，不需要系統管理員權限；ffmpeg 可能會跳出 Windows 確認視窗。</p>
      ${items.map(i => `<div><b>${esc(i.name)}</b> <span class="muted">${esc(i.size || "")}</span><div class="cmd" style="margin-top:6px">${esc(i.install)}</div></div>`).join("")}
      <div class="foot"><button class="btn" data-envno="1">先不要</button><button class="btn primary" data-envyes="${esc(ids.join(","))}">同意並安裝</button></div>`);
  }
  async function installItems(ids) {
    closeDialog();
    for (const id of ids) {
      const item = S.env.find(e => e.id === id); item.busy = true;
      if (S.view === "env") $("#view").innerHTML = V.env();
      try {
        const job = await waitJob(await api("POST", "/api/env/install", { item: id }), j => {
          const box = $("#envjob"); if (!box) return;
          box.innerHTML = `<div class="panel"><h3>${esc(j.label)}</h3>${stepsHtml(j.steps)}<details class="log"><summary>詳細紀錄</summary><pre id="joblog"></pre></details></div>`;
          paintSteps(j);
        });
        if (job.state === "failed") { await loadEnv(); if (S.view === "env") $("#view").innerHTML = V.env(); dialog(`<h2>${esc(item.name)} 安裝沒有成功</h2><div class="errorbox">${esc(job.error)}</div><details class="log"><summary>詳細紀錄</summary><pre>${esc(job.log.join("\n"))}</pre></details><div class="foot"><span></span><button class="btn primary" data-close="1">知道了</button></div>`); return; }
        toast(item.name + " 安裝完成");
      } catch (e) { fail(e); }
      await loadEnv();
      if (S.view === "env") $("#view").innerHTML = V.env();
    }
    if (!envMissing().length) toast("必要軟體都裝好了，可以開始剪片");
  }

  V.music = () => {
    setNav("music");
    if (!kitReady()) return `<div class="head"><div><h1>音樂庫</h1></div></div><div class="panel empty"><b>先安裝剪輯引擎</b><button class="btn primary" data-go="env">前往環境檢查</button></div>`;
    return `<div class="head"><div><h1>音樂庫</h1><p class="sub">依情緒分類，例如「旅遊」「走路散步」「美食」。輸出時會從選定分類挑長度最合適的一首。</p></div></div>
    <div class="panel"><h2>加入音樂</h2><div class="form">
      <div class="field"><label for="bgm-folder">放到哪個分類</label><input id="bgm-folder" type="text" list="bgm-folders" value="${esc(S.bgm[0] ? S.bgm[0].folder : "旅遊")}"><datalist id="bgm-folders">${S.bgm.map(f => `<option value="${esc(f.folder)}">`).join("")}</datalist><span class="hint">輸入新名稱會建立新分類</span></div>
    </div>
    <label class="drop" id="drop" for="bgm-in"><b>把 mp3、m4a、wav 拖到這裡，或點一下選擇</b><span class="muted">請使用你有權使用的音樂</span><input id="bgm-in" type="file" accept=".mp3,.m4a,.wav,.aac,.flac,.ogg,audio/*" multiple hidden></label>
    <div id="bgm-progress"></div></div>
    ${S.bgm.length ? S.bgm.map(f => `<div class="panel"><div class="between"><h2>${esc(f.folder)}</h2><span class="muted">${f.tracks.length} 首</span></div>
      ${f.tracks.length ? `<div class="files">${f.tracks.map(t => `<div><span>${esc(t)}</span><audio controls preload="none" src="/api/bgm/file?folder=${encodeURIComponent(f.folder)}&name=${encodeURIComponent(t)}"></audio><span></span></div>`).join("")}</div>` : `<p class="muted">這個分類還沒有音樂。</p>`}</div>`).join("")
      : `<div class="panel empty"><b>還沒有音樂</b><span>輸出影片需要至少一首背景音樂。</span></div>`}`;
  };
  async function uploadBgm(files) {
    const folder = $("#bgm-folder").value.trim();
    if (!folder) return toast("請先輸入分類名稱");
    const box = $("#bgm-progress");
    for (const f of files) {
      box.textContent = "上傳 " + f.name + "…";
      try { await upload(`/api/bgm?folder=${encodeURIComponent(folder)}&name=${encodeURIComponent(f.name)}`, f, r => { box.textContent = "上傳 " + f.name + " " + Math.round(r * 100) + "%"; }); }
      catch (e) { fail(e); }
    }
    toast("已加入 " + files.length + " 首");
    go("music");
  }

  V.settings = () => {
    setNav("settings");
    const pr = S.cfg.profile;
    return `<div class="head"><div><h1>設定</h1><p class="sub">這些內容原本要手動寫在 profiles 和 config.py。</p></div><button class="btn" data-act="wizard">重新執行設定精靈</button></div>
    <div class="panel"><h2>素材資料夾</h2>
      <div class="field"><label for="st-ws">剪輯引擎、音樂和每支 Reels 的素材都放在這裡</label>
        <div class="row" style="flex-wrap:nowrap"><input id="st-ws" type="text" class="mono" value="${esc(S.cfg.workspace)}" placeholder="${esc(S.defaultWs)}"><button class="btn" data-act="browse" data-target="st-ws">瀏覽…</button></div>
        <span class="hint">原始影片會被複製進來，不會修改你原本的檔案。</span></div></div>
    <div class="panel"><h2>頻道</h2><div class="form">
      <div class="field"><label for="st-tag">一句話定位</label><input id="st-tag" type="text" value="${esc(pr.tagline)}"></div>
      <div class="field"><label for="st-face">出鏡</label><select id="st-face">${["會露臉", "不露臉", "偶爾露臉"].map(o => `<option ${o === pr.face ? "selected" : ""}>${o}</option>`).join("")}</select></div>
      <div class="field"><label for="st-niche">內容類型</label><select id="st-niche">${NICHES.map(([v, l]) => `<option value="${v}" ${v === pr.niche ? "selected" : ""}>${l}</option>`).join("")}</select><span class="hint">決定字幕字體與配色，旅遊類使用霞鶩文楷</span></div>
    </div></div>
    <div class="row"><button class="btn primary" data-act="save-settings">儲存設定</button></div>`;
  };
  const NICHES = [["travel", "旅遊"], ["food", "美食"], ["cafe", "咖啡廳"], ["nature", "自然"], ["auto", "自動判斷"]];

  /* ---------------------------------------------------------------- wizard */
  let wiz = null;
  const WIZ = [
    { k: "tagline", q: "用一句話介紹你的頻道", type: "text", hint: "例如：卷家 2027 名古屋家庭旅遊" },
    { k: "face", q: "你會在影片裡露臉嗎？", type: "pick", opts: [["會露臉", "開頭結尾對鏡頭講話"], ["不露臉", "改用畫面加字卡"], ["偶爾露臉", "部分段落出鏡"]] },
    { k: "niche", q: "主要拍哪一類內容？", type: "pick", opts: [["travel", "旅遊"], ["food", "美食"], ["cafe", "咖啡廳"], ["nature", "自然"]] },
    { k: "workspace", q: "素材要放在哪個資料夾？", type: "folder", hint: "剪輯引擎、音樂和每支 Reels 的素材都會放在這裡" }
  ];
  function wizard() {
    const w = WIZ[wiz.i], v = wiz.data[w.k];
    let body;
    if (w.type === "text") body = `<input id="wiz-in" type="text" value="${esc(v || "")}" placeholder="${esc(w.hint)}" data-autofocus>`;
    else if (w.type === "folder") body = `<div class="row" style="flex-wrap:nowrap"><input id="wiz-in" type="text" class="mono" value="${esc(v || S.defaultWs)}" data-autofocus><button class="btn" data-act="browse" data-target="wiz-in">瀏覽…</button></div><span class="hint">${esc(w.hint)}</span>`;
    else body = `<div class="choices">${w.opts.map(([o, d]) => `<button class="choice" data-wpick="${esc(o)}" aria-pressed="${v === o}"><b>${esc(w.k === "niche" ? d : o)}</b>${w.k === "niche" ? "" : `<small>${esc(d)}</small>`}</button>`).join("")}</div>`;
    dialog(`<div class="dots">${WIZ.map((_, i) => `<i class="${i <= wiz.i ? "on" : ""}"></i>`).join("")}</div>
      <span class="muted">第 ${wiz.i + 1} 題，共 ${WIZ.length} 題</span><h2>${esc(w.q)}</h2>${body}
      <div class="foot"><button class="btn" data-wiz="prev">${wiz.i ? "上一題" : S.cfg.setup_done ? "取消" : "稍後再說"}</button><button class="btn primary" data-wiz="next">${wiz.i === WIZ.length - 1 ? "完成設定" : "下一題"}</button></div>`);
  }
  async function finishWizard() {
    const { workspace, ...profile } = wiz.data;
    try {
      S.cfg = await api("POST", "/api/config", { workspace, profile, setup_done: true });
      wiz = null; closeDialog(); refreshChrome();
      await loadEnv();
      if (envMissing().length) { go("env"); const ids = envMissing().filter(e => e.install && !e.blocked).map(e => e.id); if (ids.length) askInstall(ids); }
      else go("projects");
    } catch (e) { fail(e); }
  }

  /* ---------------------------------------------------------------- events */
  document.addEventListener("click", async e => {
    const el = e.target.closest("button, [data-go]");
    if (!el) return;
    const d = el.dataset;
    if (d.go) return go(d.go);
    if (d.open) {
      const st = d.status;
      return go(st === "review" || st === "done" ? "result" : "editor", d.open);
    }
    if (d.seg !== undefined) { S.selectedSeg = +d.seg; $("#view").innerHTML = V.editor(); paintChecks(); paintSpeeds(); return; }
    if (d.delcap !== undefined) { S.p.caps.splice(+d.delcap, 1); $("#caps").innerHTML = capsHtml(S.p); return scheduleSave({ caps: S.p.caps }); }
    if (d.rmfile !== undefined) { S.pendingFiles.splice(+d.rmfile, 1); return renderFiles(); }
    if (d.envask) return askInstall([d.envask]);
    if (d.envno) { closeDialog(); return toast("已略過，之後可以在「環境檢查」安裝"); }
    if (d.envyes) return installItems(d.envyes.split(","));
    if (d.close) return closeDialog();
    if (d.wpick !== undefined) { wiz.data[WIZ[wiz.i].k] = d.wpick; return wizard(); }
    if (d.wiz) {
      const inp = $("#wiz-in"); if (inp) wiz.data[WIZ[wiz.i].k] = inp.value.trim();
      if (d.wiz === "prev") { if (!wiz.i) { wiz = null; return closeDialog(); } wiz.i--; return wizard(); }
      if (wiz.i < WIZ.length - 1) { wiz.i++; return wizard(); }
      return finishWizard();
    }
    try {
      switch (d.act) {
        case "new": S.pendingFiles = []; return go("new");
        case "create": return createProject();
        case "rescan": return scanProject(S.p.id, S.p.title);
        case "addcap": {
          const seg = Math.min(S.selectedSeg, S.p.segs.length - 2);
          S.p.caps.push({ seg: Math.max(0, seg), text: "", color: "white" });
          S.p.caps.sort((a, b) => a.seg - b.seg);
          $("#caps").innerHTML = capsHtml(S.p); paintSpeeds();
          const idx = S.p.caps.findIndex(c => c.text === "" && c.seg === Math.max(0, seg));
          const inp = $("#cap-" + idx); inp && inp.focus();
          return;
        }
        case "build": return buildProject();
        case "back-edit": return go("editor", S.p.id);
        case "show-result": return go("result", S.p.id);
        case "delete":
          return dialog(`<h2>刪除「${esc(S.p.title)}」？</h2><p>會刪除素材資料夾裡這支 Reels 的複製檔、字幕和成品。你原本的影片不受影響。</p>
            <div class="foot"><button class="btn" data-close="1">取消</button><button class="btn primary" data-act="delete-yes">刪除</button></div>`);
        case "delete-yes": await api("DELETE", "/api/projects/" + S.p.id); closeDialog(); toast("已刪除"); return go("projects");
        case "approve": S.p = await api("POST", `/api/projects/${S.p.id}/approve`); toast("已標記為可以發布"); $("#view").innerHTML = V.result(); return paintQa();
        case "reveal": await api("POST", `/api/projects/${S.p.id}/reveal`); return;
        case "copy": {
          const ta = $("#copy-text");
          const fallback = () => { ta.focus(); ta.select(); toast("已選取文字，請按 Ctrl+C 複製"); };
          try { await navigator.clipboard.writeText(ta.value); toast("文案已複製"); } catch (err) { fallback(); }
          return;
        }
        case "recheck": S.env = []; $("#view").innerHTML = V.env(); await loadEnv(); $("#view").innerHTML = V.env(); return toast("檢查完成");
        case "install-all": return askInstall(envMissing().filter(x => x.install && !x.blocked).map(x => x.id));
        case "kit-update": {
          toast("正在檢查更新…");
          const r = await api("POST", "/api/env/kit-update");
          return toast(r.status === "CURRENT" ? "剪輯引擎已是最新版" : r.status === "UPDATE_AVAILABLE" || r.latest ? "有新版本 " + (r.latest || "") + "，重新安裝即可更新" : "目前無法檢查更新");
        }
        case "browse": {
          const r = await api("POST", "/api/pick-folder");
          if (r.path) $("#" + d.target).value = r.path; else toast("沒有選擇資料夾，也可以直接輸入路徑");
          return;
        }
        case "wizard": wiz = { i: 0, data: Object.assign({ workspace: S.cfg.workspace }, S.cfg.profile) }; return wizard();
        case "save-settings": {
          S.cfg = await api("POST", "/api/config", { workspace: $("#st-ws").value.trim(), profile: { tagline: $("#st-tag").value.trim(), face: $("#st-face").value, niche: $("#st-niche").value } });
          refreshChrome(); toast("設定已儲存"); await loadEnv(); return;
        }
      }
    } catch (err) { fail(err); }
  });

  document.addEventListener("input", e => {
    const t = e.target;
    if (t.id === "np-title") return updateCreate();
    if (t.dataset.captext !== undefined) { S.p.caps[+t.dataset.captext].text = t.value; return scheduleSave({ caps: S.p.caps }); }
    if (t.id === "seg-dur") {
      const s = S.p.segs[S.selectedSeg]; s.dur = +t.value;
      $("#seg-dur-v").textContent = s.dur.toFixed(1); $("#segdur-" + S.selectedSeg).textContent = s.dur.toFixed(1) + "s";
      document.querySelector(`[data-seg="${S.selectedSeg}"]`).style.flex = `${s.dur} 1 0`;
      return scheduleSave({ durs: S.p.segs.map(x => x.dur) });
    }
  });
  document.addEventListener("change", e => {
    const t = e.target;
    if (t.dataset.capcol !== undefined) { S.p.caps[+t.dataset.capcol].color = t.value; $("#cap-" + t.dataset.capcol).className = t.value === "gold" ? "gold" : ""; return scheduleSave({ caps: S.p.caps }); }
    if (t.id === "bgm-sel") { S.p.bgm_folder = t.value; return scheduleSave({ bgm_folder: t.value }); }
    if (t.id === "bgm-prefer") return scheduleSave({ bgm_prefer: t.value });
    if (t.id === "copy-text") return api("POST", "/api/projects/" + S.p.id, { copy: t.value }).then(() => toast("文案已儲存"), fail);
    if (t.id === "file-in") { addFiles(t.files); t.value = ""; return; }
    if (t.id === "bgm-in") { uploadBgm([...t.files]); t.value = ""; }
  });
  function addFiles(list) {
    const ok = [...list].filter(f => /\.(mov|mp4)$/i.test(f.name));
    const bad = [...list].length - ok.length;
    if (bad) toast(bad + " 個檔案不是 mp4／mov，已略過");
    S.pendingFiles = S.pendingFiles.concat(ok);
    renderFiles();
  }
  ["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => {
    const d = e.target.closest && e.target.closest("#drop"); if (!d) return; e.preventDefault(); d.classList.add("over");
  }));
  ["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => {
    const d = e.target.closest && e.target.closest("#drop"); if (!d) return; e.preventDefault(); d.classList.remove("over");
    if (ev === "drop") $("#bgm-in") ? uploadBgm([...e.dataTransfer.files]) : addFiles(e.dataTransfer.files);
  }));
  document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#layer").innerHTML) { wiz = null; closeDialog(); } });

  /* ---------------------------------------------------------------- boot */
  async function boot() {
    const st = await api("GET", "/api/state");
    S.cfg = st.config; S.defaultWs = st.default_workspace;
    refreshChrome();
    if (!S.cfg.setup_done) {
      $("#view").innerHTML = `<div class="panel empty"><b>歡迎使用 Reels 工作室</b><span>先回答 4 個問題完成設定。</span><button class="btn primary" data-act="wizard">開始設定</button></div>`;
      wiz = { i: 0, data: Object.assign({ workspace: S.cfg.workspace || S.defaultWs }, S.cfg.profile) };
      return wizard();
    }
    await loadEnv();
    const [view, arg] = (location.hash.slice(1) || "projects").split("/");
    if (envMissing().length) {
      await go("env");
      const ids = envMissing().filter(e => e.install && !e.blocked).map(e => e.id);
      if (ids.length) askInstall(ids);
      return;
    }
    await go(V[view] && (arg || !["editor", "result", "new"].includes(view)) ? view : "projects", arg);
  }
  boot().catch(fail);
})();
