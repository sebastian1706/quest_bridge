// pano boot shim -- MUST run before three.js executes (classic script
// in <head>; module scripts are deferred, so this always wins the race).
//
// three.js ships a devtools hook: every WebGLRenderer dispatches an
// 'observe' CustomEvent on window.__THREE_DEVTOOLS__ at construction.
// We provide that hook and collect the renderer so pano_sphere.js can add
// a 360-video sphere to the live scene without touching the React bundle.
(function () {
  var hook = (window.__THREE_DEVTOOLS__ =
    window.__THREE_DEVTOOLS__ || new EventTarget());
  window.__PANO_RENDERERS__ = [];
  window.__PANO_EVENTS__ = [];
  hook.addEventListener("register", function (e) {
    window.__PANO_EVENTS__.push({ type: "register", detail: e.detail });
  });
  hook.addEventListener("observe", function (e) {
    var d = e.detail;
    window.__PANO_EVENTS__.push({
      type: "observe",
      kind: d && (d.isWebGLRenderer ? "renderer" : d.isScene ? "scene" : d.type || typeof d),
    });
    if (d && d.isWebGLRenderer) {
      window.__PANO_RENDERERS__.push(d);
      window.dispatchEvent(
        new CustomEvent("pano-renderer", { detail: d })
      );
    }
  });
})();
