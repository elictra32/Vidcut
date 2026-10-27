import { canRedo, canUndo, getProject, loadProject, redo, subscribe, ui, undo } from "./state.js";
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
import { initOverlays } from "./overlays.js";
import { initEpisodes } from "./episodes.js";
import { initHighlights } from "./highlights.js";
import { $ } from "./util.js";

async function main() {
  initClipsPanel();
  initSilencePanel();
  initCutStrip();
  initTimelineView();
  initTransport();
  initStage();
  initSubtitles();
  initHighlights();
  initStylePanel();
  initOverlays();
  initExportPanel();
  initEpisodes();
  $("#btn-add").addEventListener("click", addClipFromDialog);
  const syncHistory = () => { $("#btn-undo").disabled = !canUndo(); $("#btn-redo").disabled = !canRedo(); };
  $("#btn-undo").addEventListener("click", undo);
  $("#btn-redo").addEventListener("click", redo);
  subscribe((why) => why === "history" && syncHistory());
  window.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]")) return; // typing keeps the browser's own undo
    const key = e.key.toLowerCase();
    if (key === "z" && !e.shiftKey) (e.preventDefault(), undo());
    else if (key === "y" || (key === "z" && e.shiftKey)) (e.preventDefault(), redo());
  });
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
