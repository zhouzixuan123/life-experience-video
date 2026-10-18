// Gemini 网页端人生副本批量生图脚本。
// 由 build_gemini_f12_script.py 注入当前项目配置；只支持 gemini.google.com。
(async () => {
  "use strict";

  const CONFIG = /*__PROJECT_CONFIG__*/;
  const PANEL_ID = "__life_video_gemini_batch__";
  const MAX_GENERATE_ATTEMPTS = 6;
  const MAX_DEFER_ROUNDS = 3;
  const IMAGE_TIMEOUT_MS = 12 * 60 * 1000;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  if (location.hostname !== "gemini.google.com") {
    throw new Error("本脚本只允许在 gemini.google.com 网页端运行。");
  }
  if (!CONFIG?.title || !Array.isArray(CONFIG.shots) || !CONFIG.shots.length) {
    throw new Error("项目配置无效：缺少标题或分镜。");
  }

  try { window.__lifeVideoGeminiStop?.(); } catch (_) {}
  document.getElementById(PANEL_ID)?.remove();

  const state = {
    running: false,
    stopped: false,
    directory: null,
    existingIds: new Set(),
    hashes: new Map(),
    currentId: "",
    completed: 0,
    total: 0
  };
  window.__lifeVideoGeminiStop = () => { state.stopped = true; };

  const normalize = value => String(value || "").replace(/\s+/g, " ").trim();
  const errorText = error => normalize(error?.message || error || "未知错误");
  const visible = node => {
    const rect = node?.getBoundingClientRect?.();
    return Boolean(rect && rect.width > 0 && rect.height > 0);
  };

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "text") node.textContent = value;
      else if (key === "style") node.style.cssText = value;
      else if (key in node) node[key] = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  const panel = el("div", {
    id: PANEL_ID,
    style: "position:fixed;right:20px;bottom:20px;z-index:2147483647;width:370px;padding:16px;border-radius:14px;background:#1e1f22;color:#f2f3f5;box-shadow:0 12px 40px rgba(0,0,0,.55);font:13px/1.5 'Segoe UI','Microsoft YaHei',sans-serif;border:1px solid #35373c"
  });
  const heading = el("div", { text: "🎨 Gemini 批量生图 · 专用版", style: "font-size:16px;font-weight:700" });
  const summary = el("div", { text: CONFIG.title + " · " + CONFIG.shots.length + " 个分镜", style: "color:#aaa;margin:3px 0 10px" });
  const status = el("div", { text: "选择本期项目文件夹开始。", style: "min-height:44px;padding:9px;border-radius:8px;background:#292c31;white-space:pre-wrap" });
  const progress = el("progress", { max: 1, value: 0, style: "width:100%;height:12px;margin:9px 0" });
  const onlyMissing = el("input", { type: "checkbox", checked: true });
  const missingLabel = el("label", { style: "display:flex;gap:8px;margin:5px 0 8px" }, [onlyMissing, document.createTextNode("只生成文件夹中缺失的镜头")]);
  const startButton = el("button", { text: "📁 选择项目文件夹并开始", style: "width:100%;padding:10px;border:0;border-radius:8px;background:#5865f2;color:white;font-weight:700;cursor:pointer" });
  const stopButton = el("button", { text: "⏹ 暂停", style: "width:100%;margin-top:8px;padding:9px;border:1px solid #a44;border-radius:8px;background:#38272b;color:#ffb2b2;cursor:pointer" });
  panel.append(heading, summary, missingLabel, progress, status, startButton, stopButton);
  document.body.append(panel);

  function setStatus(message, ratio) {
    status.textContent = message;
    if (Number.isFinite(ratio)) progress.value = Math.max(0, Math.min(1, ratio));
  }

  function promptInput() {
    return [...document.querySelectorAll("rich-textarea [contenteditable='true'],div.ql-editor[contenteditable='true'],textarea,[contenteditable='true'][role='textbox']")]
      .find(node => visible(node) && !node.closest("#" + PANEL_ID)) || null;
  }

  function stopGeneratingButton() {
    return [...document.querySelectorAll("button[aria-label*='Stop response'],button[aria-label*='停止回答'],button[data-test-id='stop-button']")].find(visible) || null;
  }

  function enabled(node) {
    return visible(node) && !node.disabled && node.getAttribute("aria-disabled") !== "true" && !node.closest("#" + PANEL_ID);
  }

  function promptText(input) {
    return normalize("value" in input ? input.value : (input.innerText || input.textContent));
  }

  function elementHint(node) {
    return normalize([
      node.getAttribute("aria-label"), node.getAttribute("title"), node.getAttribute("data-test-id"),
      node.getAttribute("data-testid"), node.className, node.textContent
    ].join(" ")).toLowerCase();
  }

  function composerForInput(input) {
    let node = input;
    for (let depth = 0; node && depth < 9; depth++, node = node.parentElement) {
      const controls = [...node.querySelectorAll("button,[role='button']")].filter(enabled);
      if (controls.length >= 2) return node;
    }
    return input.parentElement || document.body;
  }

  function sendButton(input = promptInput()) {
    const explicitSelectors = [
      "button[type='submit']", "button[aria-label*='Send' i]", "button[aria-label*='发送']",
      "button[aria-label*='提交']", "button[title*='Send' i]", "button[title*='发送']",
      "button[data-test-id*='send' i]", "button[data-testid*='send' i]",
      "button[class*='send' i]", "[role='button'][aria-label*='Send' i]", "[role='button'][aria-label*='发送']"
    ];
    const explicit = [...document.querySelectorAll(explicitSelectors.join(","))]
      .filter(enabled)
      .filter(node => !/stop|停止|cancel|取消/.test(elementHint(node)));
    if (explicit.length) return explicit[explicit.length - 1];
    if (!input) return null;

    // Gemini 会不定期改掉发送按钮的 aria-label。兜底只在当前输入组件内寻找右下角小按钮，
    // 因而不依赖深色/浅色主题、按钮颜色、SVG 路径或具体类名。
    const composer = composerForInput(input);
    const composerRect = composer.getBoundingClientRect();
    const excluded = /microphone|mic|麦克风|voice|语音|image|图片|upload|上传|add|添加|model|模型|expand|展开|fullscreen|全屏|stop|停止|cancel|取消/;
    const candidates = [...composer.querySelectorAll("button,[role='button']")].filter(node => {
      if (!enabled(node) || excluded.test(elementHint(node))) return false;
      const rect = node.getBoundingClientRect();
      return rect.width >= 24 && rect.width <= 88 && rect.height >= 24 && rect.height <= 88 &&
        rect.left >= composerRect.right - 190 && rect.right <= composerRect.right + 20 &&
        rect.top >= composerRect.top - 10 && rect.bottom <= composerRect.bottom + 20;
    });
    candidates.sort((left, right) => {
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();
      const score = rect => rect.right * 2 - Math.abs(composerRect.bottom - rect.bottom) * 5;
      return score(b) - score(a);
    });
    return candidates[0] || null;
  }

  function fillPrompt(text) {
    const input = promptInput();
    if (!input) return false;
    input.focus();
    if ("value" in input) {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
      setter ? setter.call(input, text) : (input.value = text);
    } else {
      input.replaceChildren(document.createTextNode(text));
    }
    input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return input;
  }

  function pressEnter(input) {
    input.focus();
    for (const type of ["keydown", "keypress", "keyup"]) {
      input.dispatchEvent(new KeyboardEvent(type, {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true
      }));
    }
  }

  async function waitForSubmission(beforeUserTurns, originalText) {
    const started = Date.now();
    while (!state.stopped && Date.now() - started < 5000) {
      const input = promptInput();
      if (stopGeneratingButton() || userTurns().length > beforeUserTurns || !input || !promptText(input)) return true;
      if (promptText(input) !== normalize(originalText)) return true;
      await sleep(200);
    }
    return false;
  }

  async function waitUntilReady(shotId, ratio) {
    const started = Date.now();
    let readyPolls = 0;
    while (!state.stopped && Date.now() - started < IMAGE_TIMEOUT_MS) {
      const ready = Boolean(promptInput()) && !stopGeneratingButton();
      readyPolls = ready ? readyPolls + 1 : 0;
      if (readyPolls >= 3) return true;
      setStatus("等待 Gemini 输入区空闲，再生成 " + shotId + "…", ratio);
      await sleep(1000);
    }
    return false;
  }

  function assistantTurns() {
    return [...document.querySelectorAll("message-content,[data-test-id='model-response'],[data-test-id*='model-response'],.model-response-text")];
  }

  function userTurns() {
    return [...document.querySelectorAll("user-query,[data-test-id='user-query'],[data-test-id*='user-query']")];
  }

  function imageCandidates(root = document) {
    return [...root.querySelectorAll("img")].filter(image => {
      if (image.closest("#" + PANEL_ID)) return false;
      const hint = normalize([image.alt, image.className, image.getAttribute("aria-label")].join(" ")).toLowerCase();
      if (/avatar|emoji|icon|logo|profile/.test(hint)) return false;
      const rect = image.getBoundingClientRect();
      return visible(image) && rect.width >= 300 && rect.height >= 160 &&
        image.complete && image.naturalWidth >= 512 && image.naturalHeight >= 288;
    });
  }

  function latestGeneratedImage() {
    const turns = assistantTurns();
    for (let i = turns.length - 1; i >= 0; i--) {
      const found = imageCandidates(turns[i]);
      if (found.length) return found[found.length - 1];
    }
    const all = imageCandidates();
    return all.length ? all[all.length - 1] : null;
  }

  function inferLastShotId() {
    for (const turn of userTurns().reverse()) {
      const match = normalize(turn.innerText || turn.textContent).match(/Shot ID:\s*((?:H|I)\d{2}|S\d{3})\b/i);
      if (match) return match[1].toUpperCase();
    }
    return "";
  }

  function buildPrompt(shot, retry, retryReason = "") {
    const freeze = shot.id === "I10"
      ? "Keep the subject and key prop entirely in the left 35-45 percent. Keep the right 50-55 percent dark, clean and low-detail for later title typesetting. Generate no text."
      : "";
    return [
      retry
        ? "Regenerate this exact shot from scratch. The previous result was unusable" + (retryReason ? " because " + retryReason : "") + ". Use a clearly different camera angle, framing, pose and spatial arrangement. Never reuse or resend an earlier image."
        : "Generate exactly one finished image now.",
      CONFIG.style,
      CONFIG.characters,
      "Project theme: " + CONFIG.title + ".",
      "Shot ID: " + shot.id + ".",
      "Narrative purpose: " + shot.task + ".",
      "Narration context: " + shot.narration + ".",
      "Scene, action and emotion: " + shot.scene + ".",
      "Composition: " + shot.layout + ".",
      "Continuity and exclusions: " + shot.rules + ".",
      freeze,
      CONFIG.negative,
      "Native full-frame 16:9 horizontal composition. Fill the whole canvas naturally. Do not reserve subtitle space and do not leave a blank strip at the bottom. No explanation; return one image only."
    ].filter(Boolean).join("\n");
  }

  async function sendPrompt(text, shotId, ratio) {
    for (let attempt = 1; attempt <= 20 && !state.stopped; attempt++) {
      const input = fillPrompt(text);
      if (!input) {
        setStatus("等待 Gemini 输入框（" + attempt + "/20）…", ratio);
        await sleep(1000);
        continue;
      }
      await sleep(500);
      const beforeUserTurns = userTurns().length;
      const button = sendButton(input);
      let method = "Enter";
      if (button && attempt % 3 !== 0) {
        method = "发送按钮";
        button.click();
      } else {
        pressEnter(input);
      }
      setStatus("已尝试用" + method + "发送 " + shotId + "，正在确认页面已接收（" + attempt + "/20）…", ratio);
      if (await waitForSubmission(beforeUserTurns, text)) return true;
      setStatus("Gemini 未响应本次" + method + "触发，正在重新定位发送控件（" + attempt + "/20）…", ratio);
      await sleep(500);
    }
    setStatus("⚠️ " + shotId + "：Gemini 输入框可见，但按钮点击和 Enter 发送都未被页面接收，已暂停。请保留页面并更新固定模板，不要手改本期脚本。");
    return false;
  }

  async function waitForNewImage(beforeImages, beforeTurns, shotId, ratio) {
    const started = Date.now();
    let stableImage = null;
    let stablePolls = 0;
    while (!state.stopped && Date.now() - started < IMAGE_TIMEOUT_MS) {
      const turns = assistantTurns();
      const newTurns = turns.filter(turn => !beforeTurns.has(turn));
      const scope = newTurns.length ? newTurns[newTurns.length - 1] : document;
      const scopedFresh = imageCandidates(scope).filter(image => !beforeImages.has(image));
      const pageFresh = imageCandidates(document).filter(image => !beforeImages.has(image));
      const fresh = scopedFresh.length ? scopedFresh : pageFresh;
      const image = fresh.length ? fresh[fresh.length - 1] : null;

      if (image) {
        if (image === stableImage) stablePolls++;
        else { stableImage = image; stablePolls = 0; }
        if (stablePolls >= 2) return { ok: true, image };
      }

      const elapsed = Math.floor((Date.now() - started) / 1000);
      if (!stopGeneratingButton() && newTurns.length && elapsed >= 8 && !image) {
        const reply = normalize(newTurns[newTurns.length - 1].innerText || newTurns[newTurns.length - 1].textContent);
        if (/unable|can't|cannot|failed|error|try again|无法|不能|失败|错误|重试/i.test(reply)) {
          return { ok: false, reason: reply.slice(0, 180) };
        }
      }
      if (elapsed % 5 === 0) setStatus("等待 " + shotId + " 的新回复图片… " + elapsed + " 秒", ratio);
      await sleep(1000);
    }
    return { ok: false, reason: state.stopped ? "用户暂停" : "等待图片超时" };
  }

  async function blobFromImage(image) {
    const source = image.currentSrc || image.src;
    for (let attempt = 1; attempt <= 6; attempt++) {
      // Prefer the pixels currently painted on screen. Gemini may keep a stale lazy-load
      // URL on an IMG node even after showing a newer generated image.
      try {
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        canvas.getContext("2d").drawImage(image, 0, 0);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
        if (blob?.size > 10000) return blob;
      } catch (_) {}
      try {
        const response = await fetch(source, { credentials: "include" });
        if (response.ok) {
          const blob = await response.blob();
          if (blob.size > 10000) return blob;
        }
      } catch (_) {}
      await sleep(attempt * 1000);
    }
    return null;
  }

  async function toPng(blob) {
    if (blob.type === "image/png") return blob;
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0);
    bitmap.close?.();
    return await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  }

  async function sha256(blob) {
    const bytes = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
  }

  async function outputFolder(id) {
    const group = /^[HI]/.test(id) ? "开头" : "正文";
    if (CONFIG.selected_ids?.length) {
      if (["画面", "开头", "正文"].includes(state.directory.name)) {
        throw new Error("返工时请选择单期项目根目录，候选将保存到 work/repair-candidates。");
      }
      const work = await state.directory.getDirectoryHandle("work", { create: true });
      const candidates = await work.getDirectoryHandle("repair-candidates", { create: true });
      return candidates.getDirectoryHandle(group, { create: true });
    }
    if (state.directory.name === group) return state.directory;
    if (state.directory.name === "画面") return state.directory.getDirectoryHandle(group, { create: true });
    const images = await state.directory.getDirectoryHandle("画面", { create: true });
    return images.getDirectoryHandle(group, { create: true });
  }

  async function scanExisting() {
    state.existingIds.clear();
    state.hashes.clear();
    for (const sample of ["H01", "S001"]) {
      const folder = await outputFolder(sample);
      for await (const [name, handle] of folder.entries()) {
        if (handle.kind !== "file" || !/^(?:H|I)\d{2}\.(?:png|jpe?g|webp)$|^S\d{3}\.(?:png|jpe?g|webp)$/i.test(name)) continue;
        const file = await handle.getFile();
        state.existingIds.add(name.replace(/\.[^.]+$/, "").toUpperCase());
        state.hashes.set(await sha256(file), name);
      }
    }
  }

  async function saveImage(image, id) {
    const source = await blobFromImage(image);
    let png = null;
    try { png = source ? await toPng(source) : null; } catch (_) {}
    if (!png || png.size <= 10000) return { ok: false, kind: "capture", reason: "无法取得有效原图" };
    const hash = await sha256(png);
    if (state.hashes.has(hash)) {
      return { ok: false, kind: "duplicate", reason: "与已有图片 " + state.hashes.get(hash) + " 完全重复" };
    }
    const folder = await outputFolder(id);
    try {
      await folder.getFileHandle(id + ".png");
      return { ok: false, kind: "exists", reason: id + ".png 已存在" };
    } catch (error) {
      if (error.name !== "NotFoundError") throw error;
    }
    let written = false;
    let lastWriteError = "";
    for (let attempt = 1; attempt <= 3 && !written; attempt++) {
      try {
        const handle = await folder.getFileHandle(id + ".png", { create: true });
        const writable = await handle.createWritable();
        await writable.write(png);
        await writable.close();
        written = true;
      } catch (error) {
        lastWriteError = errorText(error);
        await sleep(attempt * 1000);
      }
    }
    if (!written) return { ok: false, kind: "write", reason: "写入失败：" + lastWriteError };
    state.existingIds.add(id);
    state.hashes.set(hash, id + ".png");
    return { ok: true };
  }

  async function autoRecoverVisibleImage() {
    const id = inferLastShotId();
    if (!id || state.existingIds.has(id) || !CONFIG.shots.some(shot => shot.id === id)) return false;
    const image = latestGeneratedImage();
    if (!image) return false;
    setStatus("检测到页面中尚未保存的 " + id + "，正在自动接管…");
    const result = await saveImage(image, id);
    if (result.ok) {
      setStatus("✅ 已自动接管并保存 " + id + "，继续其余缺失镜头。", 0);
      return true;
    }
    setStatus("页面当前图片未能自动接管（" + result.reason + "），将自动重新生成 " + id + "。", 0);
    return false;
  }

  async function chooseDirectory() {
    if (!window.showDirectoryPicker) throw new Error("请使用最新版 Chrome 或 Edge。");
    return window.showDirectoryPicker({ id: "life-video-gemini-output", mode: "readwrite" });
  }

  async function run(directory) {
    if (state.running) return;
    state.running = true;
    state.stopped = false;
    state.directory = directory;
    state.completed = 0;
    startButton.disabled = true;
    try {
      await scanExisting();
      await autoRecoverVisibleImage();
      await scanExisting();
      let tasks = CONFIG.selected_ids?.length
        ? CONFIG.shots.filter(shot => CONFIG.selected_ids.includes(shot.id))
        : [...CONFIG.shots];
      if (onlyMissing.checked) tasks = tasks.filter(shot => !state.existingIds.has(shot.id));
      state.total = tasks.length;
      if (!tasks.length) {
        setStatus("🎉 所有镜头文件都已存在。", 1);
        return;
      }

      const queue = tasks.map(shot => ({ shot, round: 0 }));
      const permanentlyFailed = [];
      while (queue.length && !state.stopped) {
        const job = queue.shift();
        const shot = job.shot;
        state.currentId = shot.id;
        const ratio = state.completed / state.total;
        let saved = false;
        let lastReason = job.round ? "earlier automatic attempts failed" : "";

        for (let attempt = 1; attempt <= MAX_GENERATE_ATTEMPTS && !state.stopped; attempt++) {
          if (!await waitUntilReady(shot.id, ratio)) {
            lastReason = "Gemini input area did not become ready";
            break;
          }
          const beforeImages = new Set(imageCandidates());
          const beforeTurns = new Set(assistantTurns());
          setStatus("生成 " + shot.id + " · 已完成 " + state.completed + "/" + state.total + " · 自动尝试 " + attempt + "/" + MAX_GENERATE_ATTEMPTS + (job.round ? " · 延后轮次 " + (job.round + 1) : ""), ratio);
          if (!await sendPrompt(buildPrompt(shot, attempt > 1 || job.round > 0, lastReason), shot.id, ratio)) {
            lastReason = "input or send button unavailable";
            break;
          }
          const result = await waitForNewImage(beforeImages, beforeTurns, shot.id, ratio);
          if (result.ok) {
            const saveResult = await saveImage(result.image, shot.id);
            if (saveResult.ok || saveResult.kind === "exists") {
              saved = true;
              break;
            }
            lastReason = saveResult.reason;
            setStatus("⚠️ " + shot.id + " 本次结果无效：" + lastReason + "。将自动换构图重做。", ratio);
          } else {
            lastReason = result.reason || "no usable image returned";
          }
          if (attempt < MAX_GENERATE_ATTEMPTS && !state.stopped) {
            setStatus(shot.id + " 未通过，5 秒后自动重试。原因：" + lastReason, ratio);
            await sleep(5000);
          }
        }

        if (state.stopped) break;
        if (!saved) {
          if (job.round + 1 < MAX_DEFER_ROUNDS) {
            queue.push({ shot, round: job.round + 1 });
            setStatus("↪ " + shot.id + " 连续失败，已自动移到队尾；先生成其他镜头，稍后再试。", ratio);
            continue;
          }
          permanentlyFailed.push(shot.id);
          setStatus("⚠️ " + shot.id + " 已完成 " + (MAX_GENERATE_ATTEMPTS * MAX_DEFER_ROUNDS) + " 次自动尝试仍失败，继续处理其他镜头。", ratio);
          continue;
        }
        state.completed++;
        setStatus("✅ 已保存 " + shot.id + " · 本轮 " + state.completed + "/" + state.total, state.completed / state.total);
        await sleep(1200);
      }
      if (!state.stopped && !permanentlyFailed.length && state.completed === state.total) {
        setStatus("🎉 全部完成，共保存 " + state.completed + " 张。", 1);
      } else if (!state.stopped && permanentlyFailed.length) {
        setStatus("⚠️ 自动批次已完成；仅以下镜头在 " + (MAX_GENERATE_ATTEMPTS * MAX_DEFER_ROUNDS) + " 次尝试后仍失败：" + permanentlyFailed.join(", ") + "。再次启动会只补这些缺失项。", state.completed / state.total);
      }
    } catch (error) {
      state.stopped = true;
      console.error("[Gemini 人生副本批量生图]", error);
      setStatus("⚠️ " + (state.currentId ? state.currentId + "：" : "") + errorText(error) + "。进度已保留，可从缺失镜头续跑。");
    } finally {
      state.running = false;
      startButton.disabled = false;
    }
  }

  startButton.onclick = async () => {
    try { await run(await chooseDirectory()); }
    catch (error) { if (error.name !== "AbortError") setStatus(errorText(error)); }
  };

  stopButton.onclick = () => {
    state.stopped = true;
    setStatus("🛑 已请求暂停；不会再发送下一条提示。");
  };
})();
