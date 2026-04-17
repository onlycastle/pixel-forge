import { useCallback, useRef, useState } from "react";
import type { PlaceableItemResult, PlaceableSuggestion, ProgressEvent } from "../types";
import { analyzeMap, startGeneratePlaceables } from "../api";
import { MapUploader } from "./MapUploader";
import { SuggestionList } from "./SuggestionList";
import { PlaceableResultGrid } from "./PlaceableResultGrid";
import "./PlaceableForge.css";

type Step = "upload" | "select" | "results";

export function PlaceableForge() {
  const [step, setStep] = useState<Step>("upload");
  const [mapFile, setMapFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [suggestions, setSuggestions] = useState<PlaceableSuggestion[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mapDescription, setMapDescription] = useState("");
  const [variants, setVariants] = useState(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [results, setResults] = useState<PlaceableItemResult[]>([]);
  const [progressLog, setProgressLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleUpload = useCallback((file: File) => {
    setMapFile(file);
    setError(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!mapFile) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeMap(mapFile);
      setSuggestions(result.suggestions);
      setMapDescription(result.map_description);
      setSelected(new Set(result.suggestions.map((_, i) => i)));
      setStep("select");
    } catch (err) {
      setError(String(err));
    } finally {
      setIsAnalyzing(false);
    }
  }, [mapFile]);

  const handleToggle = useCallback((index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const handleGenerate = useCallback(() => {
    const items = suggestions.filter((_, i) => selected.has(i));
    if (items.length === 0) return;

    setIsGenerating(true);
    setProgressLog([]);
    setResults(
      items.map((s) => ({
        name: s.name,
        footprint: s.footprint,
        ok: false,
        variants: [],
      })),
    );
    setStep("results");

    abortRef.current = startGeneratePlaceables(
      { items, mapImage: mapFile ?? undefined, variants },
      (event: ProgressEvent) => {
        setProgressLog((prev) => [...prev, JSON.stringify(event)]);
        if (event.event === "item_done") {
          const itemResult = (event as Record<string, unknown>).result as PlaceableItemResult;
          const idx = (event as Record<string, unknown>).index as number;
          setResults((prev) =>
            prev.map((r, i) => (i === idx ? { ...r, ...itemResult } : r)),
          );
        }
      },
      () => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, "All items generated."]);
      },
      (err) => {
        setIsGenerating(false);
        setError(err);
      },
    );
  }, [suggestions, selected, mapFile, variants]);

  const handleSave = useCallback(
    async (index: number) => {
      const r = results[index];
      if (!r?.ok) return;
      for (const v of r.variants) {
        const form = new FormData();
        form.append("source", v.path);
        const slug = v.path.split("/").pop()?.replace(".png", "") ?? r.name;
        form.append(
          "destination",
          `/Users/sungmancho/projects/sunny-street/public/placeables/generated/${slug}.png`,
        );
        await fetch("/api/save", { method: "POST", body: form });
      }
    },
    [results],
  );

  const handleSaveAll = useCallback(async () => {
    for (let i = 0; i < results.length; i++) {
      if (results[i].ok) await handleSave(i);
    }
  }, [results, handleSave]);

  const handleBack = useCallback(() => {
    if (step === "select") setStep("upload");
    else if (step === "results") {
      setStep("select");
      setResults([]);
      setProgressLog([]);
    }
  }, [step]);

  return (
    <div className="placeable-forge">
      {step !== "upload" && (
        <button className="placeable-forge__back" onClick={handleBack} disabled={isGenerating}>
          &larr; Back
        </button>
      )}

      {error && <div className="placeable-forge__error">{error}</div>}

      {step === "upload" && (
        <div className="placeable-forge__upload">
          <MapUploader onUpload={handleUpload} disabled={isAnalyzing} />
          <button
            className="placeable-forge__analyze-btn"
            disabled={!mapFile || isAnalyzing}
            onClick={handleAnalyze}
          >
            {isAnalyzing ? "Analyzing..." : "Analyze Map"}
          </button>
        </div>
      )}

      {step === "select" && (
        <div className="placeable-forge__select">
          <SuggestionList
            suggestions={suggestions}
            selected={selected}
            onToggle={handleToggle}
            mapDescription={mapDescription}
          />
          <div className="placeable-forge__gen-controls">
            <label className="placeable-forge__label">
              Variants per item: {variants}
              <input
                type="range"
                min={1}
                max={4}
                value={variants}
                onChange={(e) => setVariants(Number(e.target.value))}
              />
            </label>
            <button
              className="placeable-forge__generate-btn"
              disabled={selected.size === 0}
              onClick={handleGenerate}
            >
              Generate {selected.size} Items
            </button>
          </div>
        </div>
      )}

      {step === "results" && (
        <>
          <PlaceableResultGrid
            results={results}
            onSave={handleSave}
            onSaveAll={handleSaveAll}
          />
          {progressLog.length > 0 && (
            <details className="placeable-forge__log" open={isGenerating}>
              <summary>Progress ({progressLog.length} events)</summary>
              <pre>{progressLog.join("\n")}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
