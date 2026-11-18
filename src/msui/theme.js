/*
 * 深浅主题切换（opt-in）。由 copy_assets 每次启动落进页面目录、不入仓，和
 * tokens.css / base.css 同一条路；用法见 README §4「深浅切换按钮」。
 *
 * 页面两步：
 *   1. <head> 里在 tokens-light.css 之后**同步**引用（不加 defer / async /
 *      type="module"）：<script src="theme.js"></script>——开窗前就把主题设好，
 *      不先闪一下深色再变浅色；
 *   2. 顶栏放一颗带 data-theme-toggle 的 button.icon，里面一个 .sun、一个 .moon
 *      内联 svg（标准写法见 README）。点击由这里接管，页面不写 localStorage 逻辑。
 *
 * 偏好存在 localStorage 的 `theme` 键：
 *   'light' → 浅色（<html data-theme="light">）；
 *   ''      → 用户选了深色（删掉 data-theme 属性）；
 *   没存过（null）→ 按浅色处理（默认浅色）。
 * localStorage 读写不了（隐私模式、存储被禁）时只管这一次：读不到当没存过，
 * 写不进就算了，不报错。
 *
 * 按钮的 title / aria-label 跟着当前主题写成「切换到浅色」「切换到深色」；
 * 图标显隐归 base.css（深色显示太阳、浅色显示月亮——图标表示「点了会去哪」）。
 */
(function () {
  "use strict";
  var KEY = "theme";
  var root = document.documentElement;

  function isLight() {
    return root.getAttribute("data-theme") === "light";
  }

  function label() {
    var text = isLight() ? "切换到深色" : "切换到浅色";
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("title", text);
      buttons[i].setAttribute("aria-label", text);
    }
  }

  function apply(light) {
    if (light) root.setAttribute("data-theme", "light");
    else root.removeAttribute("data-theme");
    label();
  }

  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { saved = null; }
  apply(saved !== "");

  // 事件委托挂在 document 上：脚本在 <head> 里跑的时候按钮还没解析出来，
  // 委托不用等 DOM，按钮后来才插进页面也照样接得住。
  document.addEventListener("click", function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest("[data-theme-toggle]") : null;
    if (!button) return;
    var light = !isLight();
    apply(light);
    try { localStorage.setItem(KEY, light ? "light" : ""); } catch (e) { /* 存不住只管这一次 */ }
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", label);
  else label();
})();
