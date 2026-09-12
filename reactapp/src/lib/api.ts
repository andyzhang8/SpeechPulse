import { io } from "socket.io-client";
import type { Report, SessionStatus } from "@/types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the server. Make sure backend is running.", 0);
  }
  const body = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new ApiError(body.error ?? `Request failed (${response.status})`, response.status);
  return body as T;
}

export const api = {
  camera: () => request<{ error: string | null }>("/api/camera"),

  startSession: (kind: string) =>
    request<SessionStatus>("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    }),

  finishSession: (id: string, audio: Blob | null) => {
    const form = new FormData();
    if (audio) {
      const extension = audio.type.includes("ogg") ? "ogg" : audio.type.includes("mp4") ? "m4a" : "webm";
      form.append("audio", audio, `recording.${extension}`);
    }
    return request<SessionStatus>(`/api/sessions/${id}/finish`, { method: "POST", body: form });
  },

  // keepalive
  abandonSession: (id: string) => request<object>(`/api/sessions/${id}`, { method: "DELETE", keepalive: true }),

  status: (id: string) => request<SessionStatus>(`/api/sessions/${id}`),

  report: (id: string) => request<Report>(`/api/sessions/${id}/report`),
};

// same origin Flask serves build, Vite proxies /socket.io in dev
export const socket = io();

// join room now and on every reconnect so no progress events missed
export function joinSession(sessionId: string, onStatus: (status: SessionStatus) => void) {
  const join = () =>
    socket.emit("join", { session_id: sessionId }, (reply: SessionStatus | { error: string }) => {
      if ("status" in reply) onStatus(reply);
    });
  if (socket.connected) join();
  socket.on("connect", join);
  return () => {
    socket.off("connect", join);
  };
}
