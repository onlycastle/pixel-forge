import { useCallback, useRef, useState } from "react";
import type { ActionType, Backend, VariantResult } from "../types";
import { ACTIONS } from "../types";
import { startGenerate } from "../api";
import { CharacterResultGrid } from "./CharacterResultGrid";
import "./PersonForge.css";

export function PersonForge() {
  const [prompt, setPrompt] = useState("");
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
      (_result) => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, "Generation complete."]);
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
            placeholder="a young woman in a yellow sundress and white sneakers, shoulder-length brown hair"
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
