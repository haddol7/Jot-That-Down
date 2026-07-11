/**
 * Editor.js ↔ Python(QWebChannel) 글루.
 *
 * Python → JS:  boot(doc), setBlockTime(id, label), scrollToBlock(id),
 *               insertQuote(text, caption, tMs)
 * JS → Python:  jsReady(), blockAdded(id), stampBlock(id, tMs),
 *               docSaved(json), gutterClicked(id)
 *
 * qwebchannel.js 는 Python 쪽에서 DocumentCreation 시점에 주입한다.
 */
"use strict";

let editor = null;
let editorReady = false; // 초기 렌더 중 블록 삭제(프루닝) 방지
let composing = false;   // 한글 IME 조합 중 — 저장/직렬화를 미룬다
let py = null;
let undoInstance = null;
const blockTimes = new Map(); // blockId -> "14:23" 라벨
let saveTimer = null;

new QWebChannel(qt.webChannelTransport, (channel) => {
  py = channel.objects.bridge;
  py.jsReady();
});

// 블록 드래그 시 반투명 스냅샷(고스트)이 커서를 따라다니는 것을 숨긴다 —
// 위치 피드백은 파란 드롭 선이 담당한다
const dragGhostBlank = new Image();
dragGhostBlank.src =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
document.addEventListener("dragstart", (e) => {
  if (e.dataTransfer) e.dataTransfer.setDragImage(dragGhostBlank, 0, 0);
}, true);

// Python이 저장된 문서(또는 null)로 에디터를 기동한다.
// 세션 전환 시 재호출되므로 기존 인스턴스는 파괴한다.
// allowPage: 페이지 깊이는 1단계까지만 — 하위 페이지 안에서는 false
function boot(doc, allowPage) {
  window._pageAllowed = allowPage !== false;
  if (editor) {
    try { editor.destroy(); } catch (e) { /* 이미 파괴됨 */ }
    editor = null;
  }
  editorReady = false;
  clearTimeout(saveTimer);
  blockTimes.clear();
  document.getElementById("gutter").innerHTML = "";
  const initialData = doc && doc.blocks && doc.blocks.length ? doc : undefined;
  editor = new EditorJS({
    holder: "holder",
    autofocus: true,
    data: initialData,
    tools: {
      // preserveBlank: 빈 문단(일부러 띄운 엔터)도 저장 — 기본값은 저장 시 버려진다
      paragraph: { inlineToolbar: true, config: { preserveBlank: true } },
      header: { class: Header, inlineToolbar: true, config: { levels: [1, 2, 3], defaultLevel: 2 } },
      list: { class: window.EditorjsList || window.List, inlineToolbar: true },
      quote: { class: Quote, inlineToolbar: true },
      inlineCode: { class: InlineCode, shortcut: "CMD+E" },
      marker: { class: Marker, shortcut: "CMD+SHIFT+H" },
      code: { class: HljsCodeTool },
      toggle: { class: ToggleBlock, inlineToolbar: true },
      indent: IndentTune,
      // 이미지는 붙여넣기로만 생성 — 크기 조절 핸들 + 정렬(좌/중/우) 지원
      image: { class: NoteImageTool },
      // 하위 페이지 안에서는 페이지 만들기를 숨긴다 (깊이 1단계 제한)
      pageLink: window._pageAllowed
        ? PageLinkTool
        : { class: PageLinkTool, toolbox: false },
      // list 도구가 체크리스트를 제공하므로 툴박스에서 숨긴다 (기존 문서 로드용으로만 유지)
      checklist: { class: Checklist, inlineToolbar: true, toolbox: false },
    },
    tunes: ["indent"],
    onChange: (api, events) => {
      const list = Array.isArray(events) ? events : [events];
      let moved = false;
      for (const ev of list) {
        if (ev && ev.type === "block-added" && ev.detail && ev.detail.target) {
          py.blockAdded(ev.detail.target.id);
        }
        if (ev && ev.type === "block-moved") moved = true;
      }
      // 이미지 이동 후 남는 빈/로딩 이미지 블록을 정리 (붙여넣기 전용이라 URL 없는 건 찌꺼기)
      setTimeout(pruneStrayImageBlocks, moved ? 60 : 400);
      scheduleSave();
    },
    onReady: () => {
      // debounceTimer 500: 타이핑(특히 한글 조합) 중 문서 전체 직렬화가
      // 200ms마다 돌면 조합 글자가 깜빡인다 — 저장 주기를 늦춘다
      undoInstance = new (window.Undo && window.Undo.default || window.Undo)(
        { editor, config: { debounceTimer: 500 } }
      );
      // 조합 중에는 undo 상태 저장(문서 직렬화)도 미룬다 —
      // 조합 확정 시 mutation이 다시 오므로 저장을 놓치지는 않는다
      const origRegister = undoInstance.registerChange.bind(undoInstance);
      undoInstance.registerChange = function () {
        if (composing) return;
        origRegister();
      };
      if (initialData) undoInstance.initialize(initialData);   // Ctrl+Z 기준점
      // 원본 insertDeletedBlock은 빠진 블록 '하나'만 넣고 break 해서,
      // 여러 블록을 한 번에 지운 undo가 부분 복원된다 — 전부 넣도록 교체
      undoInstance.insertDeletedBlock = function (state, compState, index) {
        // id가 양쪽에 있으면 id로, 없으면(초기 상태 등) 내용으로 같은 블록 판별
        const same = (x, y) => !!x && !!y && (
          x.id && y.id
            ? x.id === y.id
            : x.type === y.type && JSON.stringify(x.data) === JSON.stringify(y.data)
        );
        const current = compState.slice();  // 스택 상태를 건드리지 않게 복사
        for (let i = 0; i < state.length; i += 1) {
          if (!same(state[i], current[i])) {
            this.blocks.insert(state[i].type, state[i].data, {}, i, true, false, state[i].id);
            current.splice(i, 0, state[i]);
          }
        }
        // 전부 삭제 후 에디터가 만들어둔 빈 문단이 뒤에 남았으면 정리
        let count = this.blocks.getBlocksCount();
        while (count > state.length) {
          const extra = this.blocks.getBlockByIndex(count - 1);
          const text = extra && extra.holder ? (extra.holder.textContent || "").trim() : "x";
          if (extra && extra.name === "paragraph" && text === "") {
            this.blocks.delete(count - 1);
            count -= 1;
          } else break;
        }
        try { this.caret.setToBlock(index, "end"); } catch (e) { /* 인덱스 초과 */ }
      };
      // redo도 한 블록 삭제만 가정(blocks.delete() 한 번) — 일괄 삭제를
      // 다시 적용할 때는 그 상태 전체를 렌더해서 정확히 맞춘다
      const origRedo = undoInstance.redo.bind(undoInstance);
      undoInstance.redo = async function () {
        if (!this.canRedo()) return;
        const target = this.stack[this.position + 1];
        const prev = this.stack[this.position];
        if (Math.abs(target.state.length - prev.state.length) > 1) {
          this.position += 1;
          this.shouldSaveHistory = false;
          await this.blocks.render({ blocks: target.state.slice() });
          try {
            this.caret.setToBlock(
              Math.max(0, Math.min(target.index, target.state.length - 1)), "end"
            );
          } catch (e) { /* 캐럿 실패는 무시 */ }
          this.onUpdate();
          return;
        }
        return origRedo();
      };
      // ⋮⋮ 핸들 드래그 이동 — 드롭 위치는 노션처럼 파란 실선으로
      new (window.DragDrop && window.DragDrop.default || window.DragDrop)(
        editor, "3px solid #2383e2"
      );
      renderGutter();
      editorReady = true;
      setTimeout(pruneStrayImageBlocks, 300);  // 저장돼 있던 빈/깨진 이미지 블록 정리
    },
  });
}

// 페이지 전환 직전 등 — 디바운스 없이 즉시 저장
function saveNow() {
  if (!editor) return;
  clearTimeout(saveTimer);
  editor.save().then((data) => py.docSaved(JSON.stringify(data)));
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (composing) { scheduleSave(); return; }  // 조합이 끝난 뒤로 미룬다
    editor.save().then((data) => {
      py.docSaved(JSON.stringify(data));
      renderGutter();
    });
  }, 700);
}

document.getElementById("holder").addEventListener(
  "compositionstart", () => { composing = true; }, true
);
document.getElementById("holder").addEventListener(
  "compositionend", () => { composing = false; }, true
);

// --- 타임스탬프 거터 ---

function setBlockTime(blockId, label) {
  blockTimes.set(blockId, label);
  renderGutter();
}

// 코드 블록 높이를 내용에 맞춘다 (수동 리사이즈 대신)
function fitCodeArea(textarea) {
  textarea.style.height = "0px";        // 먼저 줄여야 scrollHeight가 실제 내용 높이
  textarea.style.height = textarea.scrollHeight + "px";
}

function fitAllCodeAreas() {
  document.querySelectorAll(".ce-code__textarea").forEach(fitCodeArea);
  // 레이아웃이 늦게 잡히는 경우 대비 한 번 더
  setTimeout(() => {
    document.querySelectorAll(".ce-code__textarea").forEach(fitCodeArea);
  }, 60);
}

function renderGutter() {
  if (!editor || !editor.blocks) return;
  fitAllCodeAreas(); // 블록 높이가 곧 거터 위치를 정하므로 먼저 맞춘다
  const gutter = document.getElementById("gutter");
  const wrapRect = document.getElementById("wrap").getBoundingClientRect();
  gutter.innerHTML = "";
  const count = editor.blocks.getBlocksCount();
  for (let i = 0; i < count; i++) {
    const block = editor.blocks.getBlockByIndex(i);
    if (!block || !blockTimes.has(block.id) || !block.holder) continue;
    const stamp = document.createElement("div");
    stamp.className = "stamp";
    stamp.textContent = blockTimes.get(block.id);
    stamp.title = "이 시각의 자막 보기";
    stamp.style.top = (block.holder.getBoundingClientRect().top - wrapRect.top) + "px";
    stamp.onclick = () => py.gutterClicked(block.id);
    gutter.appendChild(stamp);
  }
}

window.addEventListener("resize", renderGutter);

// Python이 테마·글꼴 크기를 적용한다 (설정 변경 시 즉시 반영)
function setTheme(name, fontPx) {
  document.body.dataset.theme = name;
  document.body.style.setProperty("--font-size", fontPx + "px");
  renderGutter(); // 글꼴 크기가 바뀌면 블록 위치도 변한다
}

// --- 페이지 블록: 노션처럼 노트 안에 하위 페이지를 만들고 들어간다 ---

class PageLinkTool {
  static get toolbox() {
    return { title: "페이지", icon: "\u{1F4C4}" };
  }

  constructor({ data }) {
    this.data = data && data.pageId ? data : { pageId: null, title: "새 페이지" };
  }

  render() {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "page-link";
    if (!this.data.pageId) {
      // 방금 삽입된 블록 — Python이 하위 페이지를 만들어준다
      this.wrapper.textContent = "페이지 만드는 중…";
      py.createSubPage(this.data.title, (result) => {
        const info = result ? JSON.parse(result) : null;
        if (info && info.id) {
          this.data.pageId = info.id;
          this.data.title = info.title;
          this._fill();
          scheduleSave();
        } else {
          this.wrapper.textContent = "페이지를 만들 수 없습니다";
        }
      });
    } else {
      this._fill();
      // 이름이 바뀌었을 수 있으니 현재 제목을 물어본다
      py.pageTitle(this.data.pageId, (title) => {
        if (title && title !== this.data.title) {
          this.data.title = title;
          this._fill();
        }
      });
    }
    return this.wrapper;
  }

  _fill() {
    this.wrapper.innerHTML = "";
    const icon = document.createElement("span");
    icon.className = "page-link__icon";
    icon.textContent = "\u{1F4C4}";
    const title = document.createElement("span");
    title.className = "page-link__title";
    title.textContent = this.data.title;
    this.wrapper.append(icon, title);
    this.wrapper.onclick = () => {
      if (this.data.pageId) py.openPage(this.data.pageId);
    };
  }

  save() {
    return this.data;
  }
}

// --- 토글 제목에서 Enter → 안의 내용으로 (플러그인 자체 처리가 죽어 있어 직접 구현) ---

function enterToggleContent(input) {
  const wrapper = input.closest('div[id^="fk-"]') || input.parentElement;
  const fk = wrapper.id;
  let index = -1;
  const count = editor.blocks.getBlocksCount();
  for (let i = 0; i < count; i++) {
    const block = editor.blocks.getBlockByIndex(i);
    if (block && block.holder && block.holder.contains(wrapper)) {
      index = i;
      break;
    }
  }
  if (index < 0) return;
  const children = document.querySelectorAll(`div[foreignKey="${fk}"]`);
  if (children.length) {
    editor.caret.setToBlock(index + 1, "start");  // 이미 내용이 있으면 첫 줄로
    return;
  }
  editor.blocks.insert("paragraph", {}, {}, index + 1, false);
  const child = editor.blocks.getBlockByIndex(index + 1);
  if (child && child.holder) {
    // 플러그인이 자식으로 인식하도록 표식을 단다 (접기/펼치기·저장 호환)
    child.holder.setAttribute("foreignKey", fk);
    child.holder.classList.add("toggle-block__item");
  }
  editor.caret.setToBlock(index + 1, "start");
  scheduleSave();
}

// 토글 자식 블록에서 Enter: 내용이 있으면 토글 안에 새 줄, 빈 줄이면 토글 밖으로
function handleToggleChildEnter(holder) {
  const fk = holder.getAttribute("foreignKey");
  let index = -1;
  const count = editor.blocks.getBlocksCount();
  for (let i = 0; i < count; i++) {
    const block = editor.blocks.getBlockByIndex(i);
    if (block && block.holder === holder) { index = i; break; }
  }
  if (index < 0) return;
  const empty = !(holder.textContent || "").trim();
  if (empty) {
    // 빈 줄에서 한 번 더 Enter → 토글 밖으로 (표식 제거, 일반 문단이 됨)
    holder.removeAttribute("foreignKey");
    holder.classList.remove("toggle-block__item");
    editor.caret.setToBlock(index, "start");
  } else {
    // 내용이 있으면 토글 안에 새 줄 추가 (표식 유지)
    editor.blocks.insert("paragraph", {}, {}, index + 1, false);
    const child = editor.blocks.getBlockByIndex(index + 1);
    if (child && child.holder) {
      child.holder.setAttribute("foreignKey", fk);
      child.holder.classList.add("toggle-block__item");
    }
    editor.caret.setToBlock(index + 1, "start");
  }
  scheduleSave();
}

// (슬래시 메뉴는 제거 — 블록 변환은 전부 마크다운 단축("* " 등)으로,
//  페이지만 "/page"("/페이지") 입력으로 만든다)

// --- 코드 블록: highlight.js로 C/C++ 문법 색칠 (textarea 위에 하이라이트 pre) ---

class HljsCodeTool {
  static get toolbox() {
    return { title: "코드", icon: "&lt;/&gt;" };
  }
  static get enableLineBreaks() { return true; }

  constructor({ data }) {
    this.code = (data && data.code) || "";
  }

  render() {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "hljs-code";
    this.pre = document.createElement("pre");
    this.codeEl = document.createElement("code");
    this.codeEl.className = "hljs language-cpp";
    this.pre.appendChild(this.codeEl);
    this.ta = document.createElement("textarea");
    this.ta.className = "hljs-code__input";
    this.ta.value = this.code;
    this.ta.spellcheck = false;
    this.ta.setAttribute("placeholder", "C/C++ 코드");

    this.ta.addEventListener("input", () => {
      this.code = this.ta.value;
      this._render();
    });
    this.ta.addEventListener("scroll", () => {
      this.pre.scrollTop = this.ta.scrollTop;
      this.pre.scrollLeft = this.ta.scrollLeft;
    });
    this.ta.addEventListener("keydown", (e) => {
      e.stopPropagation();  // 에디터 전역 단축키(슬래시 등)와 충돌 방지
      if (e.key === "Tab") {
        e.preventDefault();
        const s = this.ta.selectionStart, en = this.ta.selectionEnd;
        this.ta.value = this.ta.value.slice(0, s) + "  " + this.ta.value.slice(en);
        this.ta.selectionStart = this.ta.selectionEnd = s + 2;
        this.code = this.ta.value;
        this._render();
      }
    });

    this.wrapper.append(this.pre, this.ta);
    setTimeout(() => this._render(), 0);
    return this.wrapper;
  }

  _render() {
    let html = this.code;
    if (window.hljs) {
      try {
        html = window.hljs.highlight(this.code, { language: "cpp" }).value;
      } catch (e) { html = this._escape(this.code); }
    } else {
      html = this._escape(this.code);
    }
    this.codeEl.innerHTML = html + "\n";  // 마지막 줄도 보이게 개행 하나
    // 내용에 맞춰 높이 자동
    this.ta.style.height = "0px";
    const h = this.ta.scrollHeight;
    this.ta.style.height = h + "px";
    this.pre.style.height = h + "px";
  }

  _escape(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  save() {
    return { code: this.code };
  }
}

// --- 범용 들여쓰기 (Tab / Shift+Tab, 제목·리스트 제외) ---
// Block Tune으로 블록마다 level을 저장하므로 문서와 함께 영속된다.

class IndentTune {
  static get isTune() { return true; }

  constructor({ data, block }) {
    this.block = block;
    this.level = (data && data.level) || 0;
    this.wrapper = null;
  }

  render() {
    return [
      { icon: "→", title: "들여쓰기 늘리기", closeOnActivate: true, onActivate: () => this.delta(1) },
      { icon: "←", title: "들여쓰기 줄이기", closeOnActivate: true, onActivate: () => this.delta(-1) },
    ];
  }

  wrap(blockContent) {
    this.wrapper = document.createElement("div");
    this.wrapper.classList.add("indent-wrap");
    this.wrapper.appendChild(blockContent);
    this.wrapper.addEventListener("indent-delta", (e) => this.delta(e.detail));
    this._apply();
    return this.wrapper;
  }

  save() {
    return { level: this.level };
  }

  delta(amount) {
    this.level = Math.max(0, Math.min(6, this.level + amount));
    this._apply();
    if (this.block && this.block.dispatchChange) this.block.dispatchChange();
  }

  _apply() {
    if (this.wrapper) this.wrapper.style.paddingLeft = this.level * 26 + "px";
  }
}

function handleTabIndent(event) {
  if (event.target.tagName === "TEXTAREA") return; // 코드 블록은 자체 Tab 처리
  const index = editor.blocks.getCurrentBlockIndex();
  if (index < 0) return;
  const block = editor.blocks.getBlockByIndex(index);
  if (!block) return;
  if (block.name === "list" || block.name === "checklist") return; // 자체 들여쓰기
  event.preventDefault();
  if (block.name === "header") return; // 제목은 들여쓰기 제외
  const wrap = block.holder.querySelector(".indent-wrap");
  if (wrap) {
    wrap.dispatchEvent(
      new CustomEvent("indent-delta", { detail: event.shiftKey ? -1 : 1 })
    );
  }
}

// --- 이미지 붙여넣기: 클립보드 → Python이 data/attachments에 저장 ---

let imageUploading = 0;

function uploadImage(file) {
  imageUploading++;
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const ext = file.name && file.name.includes(".")
        ? file.name.split(".").pop() : "png";
      py.saveImage(reader.result, ext, (url) => {
        imageUploading--;
        resolve(url ? { success: 1, file: { url: url } } : { success: 0 });
      });
    };
    reader.onerror = () => { imageUploading--; resolve({ success: 0 }); };
    reader.readAsDataURL(file);
  });
}

// --- 노트 이미지 도구: 붙여넣기 전용 + 크기 조절 핸들 + 정렬(좌/중/우) ---

class NoteImageTool {
  static get toolbox() { return { title: "이미지", icon: "" }; }
  static get pasteConfig() {
    return { tags: ["img"], files: { mimeTypes: ["image/*"] } };
  }

  constructor({ data }) {
    data = data || {};
    this.url = data.url || (data.file && data.file.url) || "";
    // 폭 % (20~100). null = 원본 크기 (화면보다 크면 CSS max-width가 막는다)
    this.width = data.width || null;
    this.align = data.align || "center"; // left | center | right — 기본 가운데
  }

  render() {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "note-image align-" + this.align;
    // 클릭하면 포커스를 받아 Tab 들여쓰기 키가 에디터에 전달되게
    this.wrapper.tabIndex = -1;
    this.wrapper.addEventListener("mousedown", (e) => {
      if (e.target.classList && e.target.classList.contains("note-image__handle")) return;
      setTimeout(() => this.wrapper.focus(), 0);
    });
    // blob: URL은 세션이 끝나면 죽어서 깨진 아이콘이 되므로 채우지 않는다
    // (빈 채로 두면 onReady/onChange의 프루닝이 지운다 — 붙여넣기 직후의
    //  빈 블록을 여기서 바로 지우면 업로드가 끝나기 전에 사라진다)
    if (this.url && !this.url.startsWith("blob:")) this._fill();
    return this.wrapper;
  }

  // 붙여넣기 처리 (파일/이미지 태그)
  onPaste(event) {
    if (event.type === "file") {
      const file = event.detail.file;
      uploadImage(file).then((res) => {
        if (res && res.success) { this.url = res.file.url; this._fill(); scheduleSave(); }
        else pruneStrayImageBlocks();
      });
    } else if (event.type === "tag") {
      const src = event.detail.data.src;
      if (src) { this.url = src; this._fill(); }
    }
  }

  _fill() {
    this.wrapper.innerHTML = "";
    this.wrapper.className = "note-image align-" + this.align;
    const frame = document.createElement("div");
    frame.className = "note-image__frame";
    if (this.width) frame.style.width = this.width + "%";  // 없으면 원본 크기
    const img = document.createElement("img");
    img.className = "note-image__img";
    img.onerror = () => {   // 로드 실패(죽은 URL) → 깨진 아이콘 대신 블록 제거
      img.dataset.broken = "1";
      setTimeout(pruneStrayImageBlocks, 0);
    };
    img.src = this.url;
    frame.appendChild(img);
    // 오른쪽 아래 크기 조절 핸들
    const handle = document.createElement("div");
    handle.className = "note-image__handle";
    handle.addEventListener("mousedown", (e) => this._startResize(e, frame));
    frame.appendChild(handle);
    this.wrapper.appendChild(frame);
  }

  _startResize(e, frame) {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const parentWidth = this.wrapper.clientWidth || 1;
    const startWidth = frame.clientWidth;
    const onMove = (ev) => {
      const delta = ev.clientX - startX;
      let pct = Math.round(((startWidth + delta) / parentWidth) * 100);
      pct = Math.max(20, Math.min(100, pct));
      this.width = pct;
      frame.style.width = pct + "%";
      renderGutter();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      scheduleSave();
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // 블록 설정(⋮⋮)에 정렬 버튼
  renderSettings() {
    const items = [
      { align: "left", label: "왼쪽 정렬", icon: "⬅" },
      { align: "center", label: "가운데 정렬", icon: "⬍" },
      { align: "right", label: "오른쪽 정렬", icon: "➡" },
    ];
    return items.map((it) => ({
      icon: it.icon,
      label: it.label,
      closeOnActivate: true,
      isActive: this.align === it.align,
      onActivate: () => {
        this.align = it.align;
        this.wrapper.className = "note-image align-" + this.align;
        scheduleSave();
      },
    }));
  }

  save() {
    // MD 내보내기 호환을 위해 file.url 유지 + width/align 추가
    return { file: { url: this.url }, url: this.url, width: this.width, align: this.align };
  }
}

// 이미지가 실제로 채워지지 않은(빈/로딩) 블록 제거 — 이동 시 남는 찌꺼기 정리.
// 붙여넣기 중(imageUploading>0)에는 건너뛴다.
function pruneStrayImageBlocks() {
  if (!editorReady || imageUploading > 0 || !editor || !editor.blocks) return;
  const count = editor.blocks.getBlocksCount();
  for (let i = count - 1; i >= 0; i--) {
    const block = editor.blocks.getBlockByIndex(i);
    if (!block || block.name !== "image" || !block.holder) continue;
    const img = block.holder.querySelector(".note-image__img");
    if (!img || img.dataset.broken === "1") {
      editor.blocks.delete(i);  // 사진이 없거나 깨진 이미지 블록은 찌꺼기
    }
  }
}

// --- 마크다운 단축 입력: 패턴 + 스페이스로 블록 변환 ---

const MD_SHORTCUTS = {
  "#":   { type: "header", data: { text: "", level: 1 } },
  "##":  { type: "header", data: { text: "", level: 2 } },
  "###": { type: "header", data: { text: "", level: 3 } },
  "```": { type: "code",   data: { code: "" } },
  ">":   { type: "toggle", data: { text: "", status: "open" } },
  "*":   { type: "list",   data: { style: "unordered", items: [{ content: "", meta: {}, items: [] }] } },
  "1.":  { type: "list",   data: { style: "ordered",   items: [{ content: "", meta: {}, items: [] }] } },
  "|":   { type: "quote",  data: { text: "", caption: "" } },
  "/page":   { type: "pageLink", data: { title: "새 페이지" } },
  "/페이지": { type: "pageLink", data: { title: "새 페이지" } },
};

function caretTextOffset(el) {
  const sel = window.getSelection();
  if (!sel.rangeCount) return -1;
  const range = sel.getRangeAt(0).cloneRange();
  range.selectNodeContents(el);
  range.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
  return range.toString().length;
}

function maybeConvertMarkdown(event) {
  if (!editor || !editor.blocks) return;
  const index = editor.blocks.getCurrentBlockIndex();
  if (index < 0) return;
  const block = editor.blocks.getBlockByIndex(index);
  if (!block || block.name !== "paragraph" || !block.holder) return;
  const text = block.holder.textContent || "";
  let hit = MD_SHORTCUTS[text.trim()];
  let rest = "";
  if (hit && hit.type === "pageLink" && !window._pageAllowed) return;
  if (!hit) {
    // 내용이 있는 줄: 맨 앞에 패턴을 치고 스페이스 → 내용을 담은 채 변환
    // (캐럿이 정확히 패턴 바로 뒤에 있을 때만 — 본문 중간 스페이스는 무시)
    const offset = caretTextOffset(block.holder);
    const patterns = Object.keys(MD_SHORTCUTS).sort((a, b) => b.length - a.length);
    for (const pattern of patterns) {
      if (text.length > pattern.length && text.startsWith(pattern)
          && offset === pattern.length) {
        hit = MD_SHORTCUTS[pattern];
        rest = text.slice(pattern.length).trim();
        break;
      }
    }
    if (!hit) return;
    if (hit.type === "pageLink" && !window._pageAllowed) return;
  }
  event.preventDefault();
  event.stopPropagation();
  const data = JSON.parse(JSON.stringify(hit.data));
  if (rest) {
    if (hit.type === "code") data.code = rest;
    else if (hit.type === "list") data.items[0].content = rest;
    else if (hit.type === "pageLink") data.title = rest;
    else data.text = rest;  // header / toggle / quote
  }
  convertBlockTo(index, hit.type, data);
}

function maybeConvertPageOnEnter(event) {
  // "/page" 상태에서 엔터로도 페이지 생성 (스페이스 없이)
  if (!editor || !editor.blocks || !window._pageAllowed) return false;
  const index = editor.blocks.getCurrentBlockIndex();
  if (index < 0) return false;
  const block = editor.blocks.getBlockByIndex(index);
  if (!block || block.name !== "paragraph" || !block.holder) return false;
  const hit = MD_SHORTCUTS[(block.holder.textContent || "").trim()];
  if (!hit || hit.type !== "pageLink") return false;
  event.preventDefault();
  event.stopPropagation();
  convertBlockTo(index, hit.type, JSON.parse(JSON.stringify(hit.data)));
  return true;
}

// 블록을 다른 타입으로 교체 — 토글 자식이면 foreignKey 표식을 유지한다
function convertBlockTo(index, type, data) {
  const old = editor.blocks.getBlockByIndex(index);
  const fk = old && old.holder ? old.holder.getAttribute("foreignKey") : null;
  editor.blocks.delete(index);
  editor.blocks.insert(type, JSON.parse(JSON.stringify(data)), {}, index, true);
  const fresh = editor.blocks.getBlockByIndex(index);
  if (fk && fresh && fresh.holder) {
    fresh.holder.setAttribute("foreignKey", fk);
    fresh.holder.classList.add("toggle-block__item");
  }
  setTimeout(() => focusBlock(index), 0);
}

function focusBlock(index) {
  const block = editor.blocks.getBlockByIndex(index);
  if (!block || !block.holder) return;
  try { editor.caret.setToBlock(index, "start"); } catch (e) { /* 캐럿 비대응 블록 */ }
  const inner = block.holder.querySelector("textarea, .toggle-block__input");
  if (inner) inner.focus();
}

// --- 괄호·따옴표 자동 닫기 ---

const AUTOCLOSE_PAIRS = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" };
const CLOSING_CHARS = new Set([")", "]", "}", '"', "'"]);
let pendingCloses = []; // 자동 삽입된 닫힘 문자 스택 — 오버타입 1회 허용 근거

function autoClose(event, open, close) {
  const target = event.target;
  if (target.tagName === "TEXTAREA") { // 코드 블록
    event.preventDefault();
    const start = target.selectionStart, end = target.selectionEnd;
    target.value = target.value.slice(0, start) + open + close + target.value.slice(end);
    target.selectionStart = target.selectionEnd = start + 1;
    target.dispatchEvent(new Event("input", { bubbles: true })); // 저장 트리거
    pendingCloses.push(close);
    return;
  }
  if (!target.isContentEditable) return;
  event.preventDefault();
  document.execCommand("insertText", false, open + close);
  const selection = window.getSelection();
  if (selection && selection.rangeCount) {
    selection.modify("move", "backward", "character");
  }
  pendingCloses.push(close);
}

function nextCharAtCaret(target) {
  if (target.tagName === "TEXTAREA") {
    return target.value[target.selectionStart] || "";
  }
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || !selection.isCollapsed) return "";
  const range = selection.getRangeAt(0);
  const node = range.startContainer;
  if (node.nodeType !== Node.TEXT_NODE) return "";
  return node.textContent[range.startOffset] || "";
}

function maybeOvertypeClose(event) {
  const key = event.key;
  if (!CLOSING_CHARS.has(key)) return false;
  if (!pendingCloses.length || pendingCloses[pendingCloses.length - 1] !== key) return false;
  if (nextCharAtCaret(event.target) !== key) return false;
  // 자동 삽입된 닫힘 문자 위에서 같은 문자를 치면 삽입 대신 한 칸 건너뛴다
  event.preventDefault();
  pendingCloses.pop();
  const target = event.target;
  if (target.tagName === "TEXTAREA") {
    target.selectionStart = target.selectionEnd = target.selectionStart + 1;
  } else {
    const selection = window.getSelection();
    if (selection) selection.modify("move", "forward", "character");
  }
  return true;
}

// 클릭·블록 이동 시에는 오버타입 근거가 사라진 것으로 본다
document.addEventListener("mousedown", () => { pendingCloses = []; });

// --- 화살표 자동 변환: -> → / <- ← / ←> ↔ ---

function maybeArrowReplace(event) {
  if (event.key !== ">" && event.key !== "-") return false;
  if (event.target.tagName === "TEXTAREA" || !event.target.isContentEditable) {
    return false; // 코드 블록에서는 화살표 변환 안 함
  }
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || !selection.isCollapsed) return false;
  const range = selection.getRangeAt(0);
  const node = range.startContainer;
  if (node.nodeType !== Node.TEXT_NODE || range.startOffset === 0) return false;
  const prev = node.textContent[range.startOffset - 1];
  let replacement = null;
  if (event.key === ">" && prev === "-") replacement = "→";      // →
  else if (event.key === ">" && prev === "←") replacement = "↔"; // ↔
  else if (event.key === "-" && prev === "<") replacement = "←"; // ←
  if (!replacement) return false;
  event.preventDefault();
  range.setStart(node, range.startOffset - 1); // 직전 글자를 선택해서 치환
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("insertText", false, replacement);
  return true;
}

// --- 노트 아래 빈 공간 클릭 → 마지막 위치로 캐럿 이동 ---

function focusEnd() {
  if (!editor || !editor.blocks) return;
  const count = editor.blocks.getBlocksCount();
  const last = editor.blocks.getBlockByIndex(count - 1);
  const lastEmpty =
    last && last.name === "paragraph" && !(last.holder.textContent || "").trim();
  if (lastEmpty) {
    editor.caret.setToBlock(count - 1, "end");
  } else {
    editor.blocks.insert("paragraph", {}, {}, count, true);
    editor.caret.setToBlock(count, "end");
  }
}

document.getElementById("wrap").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) focusEnd(); // 여백 직접 클릭만
});
document.body.addEventListener("click", (event) => {
  if (event.target === document.body) focusEnd();
});

// 점 6개(⋮⋮) 툴 → 선택된 블록(들)을 Backspace/Delete로 삭제.
// 여러 블록 선택 시 한 번에 지우고, Ctrl+Z 한 번으로 전부 복원되게 묶는다.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Backspace" && event.key !== "Delete") return;
  if (!editor || !editor.blocks) return;
  const selectedHolders = [...document.querySelectorAll(".ce-block--selected")];
  if (!selectedHolders.length) return;

  const indices = [];
  const count = editor.blocks.getBlocksCount();
  for (let i = 0; i < count; i++) {
    const block = editor.blocks.getBlockByIndex(i);
    if (block && selectedHolders.includes(block.holder)) indices.push(i);
  }
  if (!indices.length) return;
  event.preventDefault();
  event.stopPropagation();

  // 삭제 도중의 중간 상태가 undo 스택에 쌓이지 않게 잠시 히스토리를 멈춘다
  if (undoInstance) undoInstance.shouldSaveHistory = false;
  indices.sort((a, b) => b - a).forEach((i) => editor.blocks.delete(i)); // 뒤에서부터
  if (undoInstance) {
    // 삭제로 인한 변경 이벤트가 전부 흘러간 뒤에 히스토리를 다시 켜고,
    // 최종 상태를 한 개의 undo 지점으로 등록 (Ctrl+Z 한 번에 전부 복원)
    editor.save().then((data) => py.docSaved(JSON.stringify(data)));
    setTimeout(() => {
      undoInstance.shouldSaveHistory = true;
      editor.save().then((data) => {
        const blocks = (data && data.blocks) || [];
        if (blocks.length) {
          if (undoInstance.registerChange) undoInstance.registerChange();
        } else {
          // 전부 삭제(Ctrl+A 등): 플러그인이 빈 상태 기록을 거부하므로 직접 push
          undoInstance.stack = undoInstance.stack.slice(0, undoInstance.position + 1);
          undoInstance.stack.push({ index: 0, state: [], caretIndex: null });
          undoInstance.position += 1;
          if (undoInstance.onUpdate) undoInstance.onUpdate();
        }
      });
    }, 250);
  }
  // 포커스를 에디터로 되돌린다 — 안 그러면 undo 단축키가 holder에 안 닿는다
  const remaining = editor.blocks.getBlocksCount();
  if (remaining > 0) {
    const target = Math.max(0, Math.min(Math.min(...indices), remaining - 1));
    try { editor.caret.setToBlock(target, "end"); } catch (e) { focusEnd(); }
  } else {
    focusEnd();
  }
  renderGutter();
}, true);

// 포커스가 에디터 밖(body 등)에 있어도 Ctrl+Z/Y가 되게 전달.
// 주의: undo 플러그인 리스너와 중복 실행되면 한 번에 두 단계를 되돌리므로,
// 플러그인이 처리한 이벤트(preventDefault 됨)는 건드리지 않는다.
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key !== "z" && key !== "y") return;
  if (!undoInstance) return;
  if (event.defaultPrevented) return;  // 플러그인이 이미 처리함
  const holder = document.getElementById("holder");
  if (holder && holder.contains(event.target)) return;  // 플러그인 담당 영역
  event.preventDefault();
  event.stopImmediatePropagation();  // 플러그인 리스너와 이중 실행 방지
  if (key === "y" || (key === "z" && event.shiftKey)) undoInstance.redo();
  else undoInstance.undo();
});

document.getElementById("holder").addEventListener(
  "input",
  (event) => {
    if (event.target.classList && event.target.classList.contains("ce-code__textarea")) {
      fitCodeArea(event.target);
    }
  },
  true
);

document.getElementById("holder").addEventListener(
  "keydown",
  (event) => {
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    // "/" 는 그대로 입력되게 두되, 네이티브 툴박스가 열리지 않도록 전파만 막는다
    if (event.key === "/") { event.stopPropagation(); return; }
    if (event.key === "Tab") {
      handleTabIndent(event);
      return;
    }
    if (event.key === " ") {
      maybeConvertMarkdown(event);
      return;
    }
    if (event.key === "Enter") {
      pendingCloses = [];
      const target = event.target;
      if (maybeConvertPageOnEnter(event)) return;  // "/page" + 엔터
      // 인용 블록: 빈 줄에서 엔터 → 인용을 끝내고 아래 새 문단으로
      const quoteText = target.closest && target.closest(".cdx-quote__text");
      if (quoteText) {
        if (quoteCaretOnEmptyLine(quoteText)) {
          event.preventDefault();
          event.stopPropagation();
          exitQuote(quoteText);
        }
        return; // 그 외에는 인용 안 줄바꿈 (기본 동작)
      }
      if (target.classList && target.classList.contains("toggle-block__input")) {
        event.preventDefault();
        event.stopPropagation();
        enterToggleContent(target);
        return;
      }
      const childHolder = target.closest && target.closest(".ce-block[foreignKey]");
      if (childHolder) {  // 토글 자식 블록에서의 Enter
        event.preventDefault();
        event.stopPropagation();
        handleToggleChildEnter(childHolder);
      }
      return;
    }
    if (maybeArrowReplace(event)) return;
    if (maybeOvertypeClose(event)) return; // 닫힘 문자 건너뛰기가 자동 삽입보다 우선
    const close = AUTOCLOSE_PAIRS[event.key];
    if (close) autoClose(event, event.key, close);
  },
  true
);

// --- 인용 블록: 빈 줄 엔터로 빠져나가기 ---

function quoteCaretOnEmptyLine(el) {
  // 인용의 줄바꿈은 줄마다 <div>가 생긴다 (<div data-empty><br></div>)
  const sel = window.getSelection();
  if (!sel.rangeCount || !sel.isCollapsed) return false;
  const range = sel.getRangeAt(0);
  const after = range.cloneRange();
  after.selectNodeContents(el);
  after.setStart(range.endContainer, range.endOffset);
  if (after.toString().trim() !== "") return false;  // 캐럿 뒤에 내용 있음
  // 캐럿이 속한 '줄'(el 직속 자식)을 찾는다
  let node = range.startContainer;
  while (node !== el && node.parentNode !== el) node = node.parentNode;
  if (node === el) {  // 캐럿이 el 바로 아래 — 직전 형제가 <br>이거나 맨 앞이면 빈 줄
    const prev = el.childNodes[range.startOffset - 1];
    return !prev || prev.nodeName === "BR";
  }
  if (node.nodeType === Node.TEXT_NODE) {
    const before = range.cloneRange();
    before.selectNodeContents(el);
    before.setEnd(range.endContainer, range.endOffset);
    const b = before.toString();
    return b.trim() === "" || /\n[ \t]*$/.test(b);
  }
  return (node.textContent || "").trim() === "";  // 줄 div가 비어 있음
}

function exitQuote(quoteTextEl) {
  // 인용 끝의 빈 줄(빈 div / <br> / 개행)을 지우고 아래에 새 문단을 만든다
  const nodes = quoteTextEl.childNodes;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const emptyDiv = n.nodeType === Node.ELEMENT_NODE && !(n.textContent || "").trim();
    if (n.nodeName === "BR" || emptyDiv) { n.remove(); break; }
    if (n.nodeType === Node.TEXT_NODE) {
      const t = n.textContent || "";
      if (!t.trim()) { n.remove(); continue; }
      const stripped = t.replace(/\n[ \t]*$/, "");
      if (stripped !== t) n.textContent = stripped;
      break;
    }
    break;
  }
  const index = editor.blocks.getCurrentBlockIndex();
  editor.blocks.insert("paragraph", { text: "" }, {}, index + 1, true);
  try { editor.caret.setToBlock(index + 1, "start"); } catch (e) { /* no-op */ }
  scheduleSave();
}


// --- 노트 ↔ 자막 동기화 진입점 (Python이 호출) ---

function scrollToBlock(blockId) {
  const count = editor.blocks.getBlocksCount();
  for (let i = 0; i < count; i++) {
    const block = editor.blocks.getBlockByIndex(i);
    if (block && block.id === blockId && block.holder) {
      block.holder.scrollIntoView({ behavior: "smooth", block: "center" });
      block.holder.classList.remove("flash");
      void block.holder.offsetWidth; // 애니메이션 재시작 트릭
      block.holder.classList.add("flash");
      return;
    }
  }
}

function insertQuote(text, caption, tMs) {
  const index = editor.blocks.getBlocksCount();
  const block = editor.blocks.insert(
    "quote", { text: text, caption: caption, alignment: "left" }, {}, index, true
  );
  if (block && block.id) {
    // onChange의 blockAdded(현재 시각)보다 인용 원본 시각이 우선해야 한다
    py.stampBlock(block.id, tMs);
    scrollToBlock(block.id);
  }
  scheduleSave();
}
