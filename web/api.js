export class ApiError extends Error {
  constructor(payload, status) {
    super(payload?.message ?? `HTTP ${status}`);
    this.payload = payload;
    this.status = status;
  }
}

export async function api(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError({ code: "network", message: "เชื่อมต่อกับโปรแกรมไม่ได้",
      hint: "ตรวจว่าหน้าต่าง run.bat ยังเปิดอยู่ แล้วรีเฟรชหน้านี้" }, 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(data?.error ?? { code: "http", message: `HTTP ${res.status}` }, res.status);
  return data;
}

const TERMINAL = ["done", "error", "cancelled"];

/** Follow a job over SSE; resolves with the final job snapshot (any terminal state). */
export function followJob(jobId, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.onmessage = (m) => {
      const job = JSON.parse(m.data);
      onProgress(job);
      if (TERMINAL.includes(job.state)) {
        es.close();
        resolve(job);
      }
    };
    es.onerror = () => {
      es.close();
      api("GET", `/api/jobs/${jobId}`).then(resolve, reject);
    };
  });
}
