/*
 * Cadre AI widget loader.
 *
 * Drop this one <script> onto any host page to embed the chat widget:
 *
 *   <script
 *     src="https://cdn.cadre.example/loader.js"
 *     data-cadre-src="https://widget.cadre.example"></script>
 *
 * It creates a fixed, bottom-right iframe pointing at `data-cadre-src` (default
 * "http://localhost:5273" for local dev) and resizes it in response to the
 * widget's own postMessage events (widget.open / widget.close / widget.resize).
 *
 * Security: every inbound message is validated against the widget's exact origin
 * and must carry `source: "cadre-widget"`. Anything else is ignored.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var WIDGET_SRC = (script && script.getAttribute("data-cadre-src")) || "http://localhost:5273";
  var WIDGET_ORIGIN = new URL(WIDGET_SRC, window.location.href).origin;

  // Collapsed footprint (just the round launcher + its margin) and the expanded
  // width. Expanded height is driven by the widget's reported height.
  var CLOSED_SIZE = 92;
  var OPEN_WIDTH = 428;
  var MARGIN = 40; // room for the panel's drop shadow + bottom offset
  var MOBILE_BREAKPOINT = 480;

  var isOpen = false;
  var lastHeight = CLOSED_SIZE;

  var iframe = document.createElement("iframe");
  iframe.src = WIDGET_SRC;
  iframe.title = "Cadre AI Assistant";
  iframe.setAttribute("allowtransparency", "true");
  iframe.setAttribute("scrolling", "no");
  var style = iframe.style;
  style.position = "fixed";
  style.right = "0";
  style.bottom = "0";
  style.width = CLOSED_SIZE + "px";
  style.height = CLOSED_SIZE + "px";
  style.border = "0";
  style.background = "transparent";
  style.colorScheme = "normal";
  style.zIndex = "2147483000";

  function layout() {
    var mobile = window.innerWidth <= MOBILE_BREAKPOINT;
    if (isOpen && mobile) {
      // Full-screen the iframe so the widget's full-screen mobile panel fits.
      style.top = "0";
      style.left = "0";
      style.right = "0";
      style.bottom = "0";
      style.width = "100%";
      style.height = "100%";
    } else if (isOpen) {
      style.top = "auto";
      style.left = "auto";
      style.right = "0";
      style.bottom = "0";
      style.width = OPEN_WIDTH + "px";
      style.height = Math.min(lastHeight + MARGIN, window.innerHeight) + "px";
    } else {
      style.top = "auto";
      style.left = "auto";
      style.right = "0";
      style.bottom = "0";
      style.width = CLOSED_SIZE + "px";
      style.height = CLOSED_SIZE + "px";
    }
  }

  function onMessage(event) {
    // Explicit origin check — never trust a message from an unexpected origin.
    if (event.origin !== WIDGET_ORIGIN) return;
    var data = event.data;
    if (!data || data.source !== "cadre-widget") return;

    var payload = data.payload;
    var height =
      payload && typeof payload.height === "number" ? payload.height : lastHeight;

    switch (data.type) {
      case "widget.open":
        isOpen = true;
        lastHeight = height;
        break;
      case "widget.close":
        isOpen = false;
        break;
      case "widget.resize":
        lastHeight = height;
        break;
      default:
        return;
    }
    layout();
  }

  function mount() {
    document.body.appendChild(iframe);
    layout();
  }

  window.addEventListener("message", onMessage);
  window.addEventListener("resize", layout);

  if (document.body) {
    mount();
  } else {
    document.addEventListener("DOMContentLoaded", mount);
  }
})();
