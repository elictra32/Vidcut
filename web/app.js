import { canRedo, canUndo, flush, getProject, loadProject, onHistory, redo, ui, undo } from "./state.js";
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
import { initCovers } from "./covers.js";
import { initQueuePanel } from "./queue_panel.js";
import { initColorPanel } from "./color_panel.js";
import { $ } from "./util.js";

async function main() {
  fetch("/api/ping").then((r) => r.json()).then((p) => { if (p.version) $("#app-version").textContent = p.version; }).catch(() => {});
  initClipsPanel();
  initCovers();
  initSilencePanel();
  initCutStrip();
  initTimelineView();
  initTransport();
  initStage();
  initSubtitles();
  initHighlights();
  initStylePanel();
  initColorPanel();
  initOverlays();
  initExportPanel();
  initEpisodes();
  initQueuePanel();
  $("#btn-queue").addEventListener("click", () => $("#queue-panel").scrollIntoView({ behavior: "smooth", block: "start" }));
  // Desktop mode: tell the server this window is still open, and that it is closing. The server exits by itself a few
  // seconds after the last window closes (unless an export is still running).
  const ping = () => fetch("/api/ping").catch(() => {});
  ping();
  setInterval(ping, 5000);
  window.addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/bye"); } catch { /* closing anyway */ } });
  $("#btn-quit").addEventListener("click", async () => {
    let busy = false;
    try { busy = (await (await fetch("/api/queue")).json()).items.some((i) => i.state === "running" || i.state === "queued"); } catch { /* ignore */ }
    if (!confirm(busy ? "Jobs are still waiting or running. Quit anyway? They continue the next time you open Vidcut." : "Close Vidcut?")) return;
    await flush().catch(() => {});
    await fetch("/api/quit", { method: "POST" }).catch(() => {});
    document.body.innerHTML = "<p style='font:16px system-ui;padding:32px'>Vidcut has closed. You can close this window.</p>";
    window.close();
  });
  $("#btn-add").addEventListener("click", addClipFromDialog);
  const syncHistory = () => { $("#btn-undo").disabled = !canUndo(); $("#btn-redo").disabled = !canRedo(); };
  $("#btn-undo").addEventListener("click", undo);
  $("#btn-redo").addEventListener("click", redo);
  onHistory(syncHistory);
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
