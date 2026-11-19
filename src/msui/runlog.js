/*
 * 运行日志区（opt-in）。由 copy_assets 每次启动落进页面目录、不入仓，和
 * theme.js 同一条路；Python 半边是 msui.runlog.RunLog，用法见 README §3「运行日志区」。
 *
 * 页面两步：
 *   1. 放一段标准标记（README 里可抄）：
 *        <section class="runlog" data-runlog="get_log" aria-label="运行日志">
 *          <div class="eyebrow">…<span class="n" data-runlog-count></span>…
 *            <button data-runlog-clear>清空显示</button>
 *            <button data-runlog-folder="open_log_folder">打开日志文件夹</button>（可选）
 *            <button data-runlog-toggle aria-expanded="true">折叠</button></div>
 *          <div class="runlog-list" data-runlog-list></div>
 *        </section>
 *   2. 在 </body> 前引用：<script src="runlog.js"></script>。
 *
 * data-runlog 的值是 js_api 上取日志的方法名（空着就是 get_log）：脚本每半秒调
 * 一次 api[方法](上次的 last)，拿 RunLog.since 的返回 {lines, runs, last}；应答
 * 包在 Serializer 信封里（{busy, data}）也认，busy 就等下一轮。
 * data-runlog-folder 的值是「打开日志文件夹」调的方法名（空着就是 open_log_folder）。
 *
 * 两层折叠：
 *   - 整区：「折叠 / 展开」按钮，状态存 localStorage 的 `runlog-collapsed` 键
 *     （'1' 折叠，'' 展开；没存过 = 展开）。折叠着时来了 warn / error 自动展开，
 *     这次展开不写回——下次打开照样折叠。记得住的前提同 theme.js：run() 给了 storage_dir。
 *   - 每次运行一组：组头「时间 · 状态 · 名称 · 结果」，点组头开合。失败组、最新一组
 *     默认展开，其余收起；用户亲手开合过的组以用户为准，新数据不再改它。
 * 停在底部才跟着滚到最新；往上翻着看时不把人拽下去。
 * 「清空显示」只清页面上的显示和行数，不动 Python 里的缓冲、不删日志文件。
 */
(function () {
  "use strict";
  var KEY = "runlog-collapsed";
  var LEVEL_TEXT = { info: "信息", warn: "告警", error: "失败" };
  var STATUS_TEXT = { running: "运行中", ok: "成功", error: "失败", stopped: "已停止" };
  var INTERVAL_MS = 500;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function readCollapsed() {
    try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
  }

  function writeCollapsed(on) {
    try { localStorage.setItem(KEY, on ? "1" : ""); } catch (e) { /* 存不住只管这一次 */ }
  }

  function unwrap(reply) {
    if (reply && typeof reply === "object" && "busy" in reply) {
      return reply.busy ? null : reply.data;
    }
    return reply;
  }

  function setup(section) {
    var method = section.getAttribute("data-runlog") || "get_log";
    var list = section.querySelector("[data-runlog-list]");
    var count = section.querySelector("[data-runlog-count]");
    var toggle = section.querySelector("[data-runlog-toggle]");
    var clear = section.querySelector("[data-runlog-clear]");
    var folder = section.querySelector("[data-runlog-folder]");
    if (!list) return;

    var last = 0;
    var shown = 0;
    var busy = false;
    var collapsed = false;
    var runs = {};      // id → 最近一次收到的运行信息（清空显示也不丢：组被清掉后还有新行时用它重建组头）
    var groups = {};    // id → {node, head, body}（只管眼下页面上的）
    var userSet = {};   // id → true/false：用户亲手开合过的组
    var latest = null;  // 最新一组的 id

    function setCollapsed(on, save) {
      collapsed = on;
      section.classList.toggle("collapsed", on);
      list.hidden = on;
      if (clear) clear.hidden = on;
      if (toggle) {
        toggle.textContent = on ? "展开" : "折叠";
        toggle.setAttribute("aria-expanded", String(!on));
      }
      if (save) writeCollapsed(on);
      if (!on) list.scrollTop = list.scrollHeight;
    }

    function isOpen(id) {
      if (id in userSet) return userSet[id];
      var run = runs[id];
      return (run && run.status === "error") || id === latest;
    }

    function paintGroup(id) {
      var group = groups[id];
      var run = runs[id];
      if (!group || !run) return;
      var open = isOpen(id);
      group.node.className = "runlog-run" + (run.status === "error" ? " error" : "") + (open ? " open" : "");
      group.body.hidden = !open;
      group.head.setAttribute("aria-expanded", String(open));
      var cells = group.head.children;
      cells[0].textContent = run.start;
      cells[1].textContent = STATUS_TEXT[run.status] || run.status;
      cells[1].className = "st " + run.status;
      cells[2].textContent = run.name;
      cells[3].textContent = run.status === "running" ? "" : run.result;
    }

    function ensureGroup(id) {
      if (groups[id]) return groups[id];
      var node = el("div", "runlog-run");
      node.setAttribute("data-run", String(id));
      var head = el("div", "runlog-head");
      head.setAttribute("role", "button");
      head.setAttribute("tabindex", "0");
      head.appendChild(el("span", "tm"));
      head.appendChild(el("span", "st"));
      head.appendChild(el("span", "nm"));
      head.appendChild(el("span", "rs"));
      var body = el("div", "runlog-lines");
      node.appendChild(head);
      node.appendChild(body);
      var flip = function () {
        userSet[id] = !isOpen(id);
        paintGroup(id);
      };
      head.addEventListener("click", flip);
      head.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        flip();
      });
      list.appendChild(node);
      groups[id] = { node: node, head: head, body: body };
      var previous = latest;
      if (latest === null || id > latest) latest = id;
      if (previous !== null && previous !== latest) paintGroup(previous);
      paintGroup(id);
      return groups[id];
    }

    function lineNode(line) {
      var row = el("div", "runlog-line " + line.level);
      row.appendChild(el("span", "tm", line.time));
      row.appendChild(el("span", "lv", LEVEL_TEXT[line.level] || line.level));
      row.appendChild(el("span", "tx", line.text));
      return row;
    }

    function apply(got) {
      var i;
      var newRuns = got.runs || [];
      var lines = got.lines || [];
      for (i = 0; i < newRuns.length; i++) runs[newRuns[i].id] = newRuns[i];
      // 新开的组与新行按序号排在一起摆：运行 id 就是它开始时的序号，
      // 开始之前记的散行摆在组的前面。
      var items = [];
      for (i = 0; i < newRuns.length; i++) {
        if (!groups[newRuns[i].id]) items.push({ seq: newRuns[i].id, run: newRuns[i].id });
      }
      for (i = 0; i < lines.length; i++) items.push({ seq: lines[i].seq, line: lines[i] });
      items.sort(function (a, b) { return a.seq - b.seq; });
      if (!items.length && !newRuns.length) return;

      var atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 4;
      var alarm = false;
      for (i = 0; i < items.length; i++) {
        var item = items[i];
        if (item.line === undefined) { ensureGroup(item.run); continue; }
        var line = item.line;
        if (line.level === "warn" || line.level === "error") alarm = true;
        var row = lineNode(line);
        if (line.run !== null && line.run !== undefined && runs[line.run]) ensureGroup(line.run).body.appendChild(row);
        else list.appendChild(row);
      }
      for (i = 0; i < newRuns.length; i++) paintGroup(newRuns[i].id);
      shown += lines.length;
      if (count) count.textContent = shown ? shown + " 行" : "";
      // 折叠着来了告警 / 失败：自动展开，不写回偏好
      if (collapsed && alarm) setCollapsed(false, false);
      else if (atBottom && !collapsed) list.scrollTop = list.scrollHeight;
    }

    function poll() {
      var api = window.pywebview && window.pywebview.api;
      if (busy || !api || typeof api[method] !== "function") return;
      busy = true;
      Promise.resolve(api[method](last))
        .then(function (reply) {
          var got = unwrap(reply);
          if (!got) return;
          apply(got);
          if (typeof got.last === "number") last = got.last;
        })
        .catch(function () { /* 下一轮再取 */ })
        .then(function () { busy = false; });
    }

    if (toggle) toggle.addEventListener("click", function () { setCollapsed(!collapsed, true); });
    if (clear) {
      clear.addEventListener("click", function () {
        list.textContent = "";
        groups = {};
        userSet = {};
        latest = null;
        shown = 0;
        if (count) count.textContent = "";
      });
    }
    if (folder) {
      folder.addEventListener("click", function () {
        var api = window.pywebview && window.pywebview.api;
        var name = folder.getAttribute("data-runlog-folder") || "open_log_folder";
        if (api && typeof api[name] === "function") {
          Promise.resolve(api[name]()).catch(function () { /* 打不开就算了，不打扰 */ });
        }
      });
    }

    setCollapsed(readCollapsed(), false);
    poll();
    setInterval(poll, INTERVAL_MS);
  }

  function start() {
    var sections = document.querySelectorAll("[data-runlog]");
    for (var i = 0; i < sections.length; i++) setup(sections[i]);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
