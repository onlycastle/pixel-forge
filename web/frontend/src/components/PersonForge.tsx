import { useCallback, useRef, useState } from "react";
import type { ActionType, Backend, VariantResult } from "../types";
import { ACTIONS } from "../types";
import { startGenerate } from "../api";
import { CharacterResultGrid } from "./CharacterResultGrid";
import "./PersonForge.css";

export function PersonForge() {
  const [prompt, setPrompt] = useState("a young woman in a yellow sundress and white sneakers, shoulder-length brown hair");
  const [selectedActions, setSelectedActions] = useState<ActionType[]>([]);
  const [variants, setVariants] = useState(1);
  const [backend, setBackend] = useState<Backend>("gemini-3.1-flash");
  const [refFile, setRefFile] = useState<File | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [results, setResults] = useState<VariantResult[]>([]);
  const [progressLog, setProgressLog] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const toggleAction = (action: ActionType) => {
    setSelectedActions((prev) =>
      prev.includes(action) ? prev.filter((a) => a !== action) : [...prev, action],
    );
  };

  const handleGenerate = useCallback(() => {
    if (prompt.trim().length < 3) return;
    setIsGenerating(true);
    setProgressLog([]);

    const initial: VariantResult[] = Array.from({ length: variants }, (_, i) => ({
      index: i,
      slug: "",
      portraitUrl: null,
      walkSheetUrl: null,
      walkDims: null,
      actionSheets: {},
      status: "pending" as const,
    }));
    setResults(initial);

    abortRef.current = startGenerate(
      {
        prompt: prompt.trim(),
        actions: selectedActions,
        variants,
        backend,
        reference: refFile ?? undefined,
      },
      (event) => {
        setProgressLog((prev) => [...prev, JSON.stringify(event)]);
      },
      (result: unknown) => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, "Generation complete.", `Result: ${JSON.stringify(result)}`]);
        // Parse the pf bundle stdout payload to populate variant URLs.
        // Shape: { bundle_dir, bundles: [{ bundle_dir, pipes: { portrait, walking, actions } }], ... }
        try {
          const r = result as Record<string, unknown>;
          const bundles = (r.bundles ?? []) as Record<string, unknown>[];
          setResults((prev) =>
            prev.map((v, i) => {
              const b = bundles[i] as Record<string, unknown> | undefined;
              if (!b) return { ...v, status: "error" as const, error: "no bundle data" };
              const bdir = String(b.bundle_dir ?? "");
              const pipes = (b.pipes ?? {}) as Record<string, Record<string, unknown>>;
              const portraitPath = pipes.portrait?.ok ? `${bdir}/portrait.png` : null;
              const walkPipes = pipes.walking;
              // pipes.walking.path may be absolute or relative — always use "walk.png" relative to bdir
              const walkPath = walkPipes?.ok ? `${bdir}/walk.png` : null;
              const walkDims = walkPipes?.dims as import("../types").WalkDims | null ?? null;
              const actionSheets: Record<string, string> = {};
              if (pipes.actions) {
                for (const [key, info] of Object.entries(pipes.actions)) {
                  const ai = info as Record<string, unknown>;
                  if (ai.ok) {
                    actionSheets[key] = `${bdir}/actions/${key}.png`;
                  }
                }
              }
              return {
                ...v,
                slug: String(b.slug ?? ""),
                portraitUrl: portraitPath ? `/api/preview?path=${encodeURIComponent(portraitPath)}` : null,
                walkSheetUrl: walkPath ? `/api/preview?path=${encodeURIComponent(walkPath)}` : null,
                walkDims,
                actionSheets: Object.fromEntries(
                  Object.entries(actionSheets).map(([k, p]) => [k, `/api/preview?path=${encodeURIComponent(p)}`]),
                ),
                status: "done" as const,
              };
            }),
          );
        } catch (e) {
          setProgressLog((prev) => [...prev, `Parse error: ${e}`]);
        }
      },
      (error) => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, `Error: ${error}`]);
      },
    );
  }, [prompt, selectedActions, variants, backend, refFile]);

  return (
    <div className="person-forge">
      <div className="person-forge__form">
        <label className="person-forge__label">
          Character Description
          <textarea
            className="person-forge__textarea"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe your character..."
            rows={3}
            maxLength={4000}
          />
        </label>

        <fieldset className="person-forge__fieldset">
          <legend>Actions</legend>
          <div className="person-forge__actions">
            {ACTIONS.map((action) => (
              <label key={action} className="person-forge__action-label">
                <input
                  type="checkbox"
                  checked={selectedActions.includes(action)}
                  onChange={() => toggleAction(action)}
                />
                {action}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="person-forge__label">
          Variants: {variants}
          <input
            type="range"
            min={1}
            max={6}
            value={variants}
            onChange={(e) => setVariants(Number(e.target.value))}
          />
        </label>

        <fieldset className="person-forge__fieldset">
          <legend>Backend</legend>
          <div className="person-forge__radios">
            {(["gemini-3.1-flash", "pixellab"] as Backend[]).map((b) => (
              <label key={b}>
                <input
                  type="radio"
                  name="backend"
                  value={b}
                  checked={backend === b}
                  onChange={() => setBackend(b)}
                />
                {b}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="person-forge__label">
          Reference Image (optional)
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setRefFile(e.target.files?.[0] ?? null)}
          />
        </label>

        <button
          className="person-forge__generate-btn"
          disabled={isGenerating || prompt.trim().length < 3}
          onClick={handleGenerate}
        >
          {isGenerating ? "Generating..." : "Generate"}
        </button>
      </div>

      {progressLog.length > 0 && (
        <details className="person-forge__log" open={isGenerating}>
          <summary>Progress ({progressLog.length} events)</summary>
          <pre>{progressLog.join("\n")}</pre>
        </details>
      )}

      <CharacterResultGrid variants={results} selectedActions={selectedActions} />
    </div>
  );
}
