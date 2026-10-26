import { getProject, loadProject, ui } from "./state.js";
import * as player from "./player.js";
import { showError } from "./toast.js";
import { addClipFromDialog, addClipFromPath, initClipsPanel } from "./clips_panel.js";
import { initSilencePanel } from "./silence_panel.js";
import { initCutStrip } from "./cut_strip.js";
import { initTimelineView } from "./timeline_view.js";
import { initTransport } from "./transport.js";
import { initStage } from "./stage.js";
import { initSubtitles } from "./subtitles.js";
import { initStylePanel } from "./style_panel.js";
import { initExportPanel } from "./export_panel.js";
import { $ } from "./util.js";

async function main() {
  initClipsPanel();
  initSilencePanel();
  initCutStrip();
  initTimelineView();
  initTransport();
  initStage();
  initSubtitles();
  initStylePanel();
  initExportPanel();
  $("#btn-add").addEventListener("click", addClipFromDialog);
  $("#btn-add-path").addEventListener("click", () => addClipFromPath($("#path-input").value));
  $("#path-input").addEventListener("keydown", (e) => e.key === "Enter" && addClipFromPath(e.target.value));
  try {
    await loadProject();
    if (getProject().clips.length) await player.showClip(ui.currentClipId); // show a frame instead of a black stage
  } catch (e) {
    showError(e);
  }
}

main();
