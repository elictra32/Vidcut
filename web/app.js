import { loadProject } from "./state.js";
import { showError } from "./toast.js";
import { addClipFromDialog, addClipFromPath, initClipsPanel } from "./clips_panel.js";
import { initSilencePanel } from "./silence_panel.js";
import { initCutStrip } from "./cut_strip.js";
import { initTimelineView } from "./timeline_view.js";
import { initTransport } from "./transport.js";
import { $ } from "./util.js";

async function main() {
  initClipsPanel();
  initSilencePanel();
  initCutStrip();
  initTimelineView();
  initTransport();
  $("#btn-add").addEventListener("click", addClipFromDialog);
  $("#btn-add-path").addEventListener("click", () => addClipFromPath($("#path-input").value));
  $("#path-input").addEventListener("keydown", (e) => e.key === "Enter" && addClipFromPath(e.target.value));
  try {
    await loadProject();
  } catch (e) {
    showError(e);
  }
}

main();
