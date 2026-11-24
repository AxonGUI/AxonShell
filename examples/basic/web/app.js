/* 示例的全部胶水：初始化、三个按钮、状态显示。 */
(function () {
  "use strict";

  const demo = { connected: false, drag: false, regions: 0, platform: "", lastMenu: null };
  globalThis.__demo = demo;

  const $ = (id) => document.getElementById(id);
  const out = (id, text) => ($(id).textContent = text);

  (async function boot() {
    demo.connected = false;

    const status = await window.axon.AxonInit();
    if (!status.ready) {
      out("state", `没有连上 Python 后端：${status.reason || status.error}`);
      return;
    }
    demo.connected = true;

    // 接上拖拽区、窗口按钮、状态事件
    window.AxonShell.init();
    demo.drag = !!document.querySelector("[data-axon-drag]");
    demo.regions = window.AxonShell.drag.regions().length;
    demo.platform = await window.axon.Axon.Window.platform();

    window.AxonShell.window.onState((s) => {
      render(s);
    });

    render(window.AxonShell.window.state());

    $("btnEcho").addEventListener("click", async () => {
      const text = await window.axon.Axon.App.echo("你好，Axon");
      out("echoOut", text);
    });

    $("btnAbout").addEventListener("click", async () => {
      const info = await window.axon.Axon.App.about();
      out("aboutOut", `Python ${info.python} · Qt ${info.qt} · ${info.platform}`);
    });

    // 原生菜单是 Qt 画的，和网页自己写的菜单是两条路
    $("btnNative").addEventListener("click", async () => {
      const rid = await window.AxonShell.menu.native({
        id: "demo",
        items: [
          { id: "a", label: "第一项" },
          { id: "b", label: "第二项", shortcut: "Ctrl+B" },
        ],
      });
      out("nativeOut", `requestId = ${rid}`);
    });

    window.AxonShell.menu.onSelect((payload) => {
      demo.lastMenu = payload.id;
      out("nativeOut", `选中 ${payload.id} (${payload.requestId})`);
    });
  })();

  function render(s) {
    demo.state = s;
    $("state").textContent = [
      `platform   ${demo.platform}`,
      `frame      ${s.frame?.width ?? "?"} × ${s.frame?.height ?? "?"}  @ (${s.frame?.x ?? "?"}, ${s.frame?.y ?? "?"})`,
      `maximized  ${!!s.maximized}`,
      `fullScreen ${!!s.fullScreen}`,
      `drag area  ${demo.drag} · ${demo.regions} 段`,
    ].join("\n");
  }
})();
