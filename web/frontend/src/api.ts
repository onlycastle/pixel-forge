import type { AnalysisResult, Backend, PlaceableSuggestion, ProgressEvent } from "./types";
import { BACKEND_CLI_NAME } from "./types";

export interface GenerateParams {
  prompt: string;
  actions: string[];
  variants: number;
  backend: Backend;
  reference?: File;
}

export function startGenerate(
  params: GenerateParams,
  onEvent: (event: ProgressEvent) => void,
  onDone: (result: unknown) => void,
  onError: (error: string) => void,
): AbortController {
  const ctrl = new AbortController();
  const form = new FormData();
  form.append("prompt", params.prompt);
  form.append("actions", params.actions.join(","));
  form.append("variants", String(params.variants));
  form.append("backend", BACKEND_CLI_NAME[params.backend]);
  if (params.reference) {
    form.append("reference", params.reference);
  }

  fetch("/api/generate", { method: "POST", body: form, signal: ctrl.signal })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6)) as ProgressEvent;
              if (parsed.event === "done") {
                onDone(parsed.result ?? parsed);
              } else if (parsed.event === "error") {
                onError(JSON.stringify(parsed));
              } else {
                onEvent(parsed);
              }
            } catch {
              // skip unparseable
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return ctrl;
}

export async function analyzeMap(mapImage: File): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("map_image", mapImage);

  const res = await fetch("/api/analyze-map", { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Analysis failed: HTTP ${res.status} — ${text}`);
  }
  return res.json();
}

export interface GeneratePlaceablesParams {
  items: PlaceableSuggestion[];
  mapImage?: File;
  variants: number;
}

export function startGeneratePlaceables(
  params: GeneratePlaceablesParams,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void,
  onError: (error: string) => void,
): AbortController {
  const ctrl = new AbortController();
  const form = new FormData();
  form.append("items", JSON.stringify(params.items));
  form.append("variants", String(params.variants));
  if (params.mapImage) {
    form.append("map_image", params.mapImage);
  }

  fetch("/api/generate-placeables", { method: "POST", body: form, signal: ctrl.signal })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6)) as ProgressEvent;
              if (parsed.event === "done") {
                onDone();
              } else {
                onEvent(parsed);
              }
            } catch {
              // skip unparseable
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return ctrl;
}
