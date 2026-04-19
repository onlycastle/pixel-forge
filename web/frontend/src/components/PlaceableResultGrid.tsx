import type { PlaceableItemResult } from "../types";

interface PlaceableResultGridProps {
  results: PlaceableItemResult[];
  onSave: (index: number) => void;
  onSaveAll: () => void;
}

export function PlaceableResultGrid({
  results,
  onSave,
  onSaveAll,
}: PlaceableResultGridProps) {
  if (results.length === 0) return null;

  const doneCount = results.filter((r) => r.status === "done" || r.status === "error").length;
  const allDone = doneCount === results.length;
  const currentIndex = results.findIndex((r) => r.status === "generating");

  return (
    <div className="placeable-results">
      <div className="placeable-results__status-bar">
        {allDone
          ? `All ${results.length} items complete`
          : currentIndex >= 0
            ? `Generating ${currentIndex + 1} of ${results.length}: ${results[currentIndex].name}...`
            : `${doneCount} of ${results.length} complete`}
      </div>
      <div className="placeable-results__grid">
        {results.map((r, i) => (
          <div
            key={i}
            className={`placeable-results__card ${r.status === "generating" ? "placeable-results__card--active" : ""}`}
          >
            <div className="placeable-results__header">
              <span className="placeable-results__name">{r.name}</span>
              <span className="placeable-results__fp">
                {r.footprint[0]}x{r.footprint[1]}
              </span>
            </div>
            <div className="placeable-results__preview">
              {r.ok && r.variants.length > 0 ? (
                r.variants.map((v, vi) => (
                  <img
                    key={vi}
                    src={`/api/preview?path=${encodeURIComponent(v.path)}`}
                    alt={`${r.name} v${vi + 1}`}
                    className="placeable-results__img"
                  />
                ))
              ) : r.error ? (
                <span className="placeable-results__error">{r.error}</span>
              ) : r.status === "generating" ? (
                <span className="placeable-results__generating">Generating...</span>
              ) : (
                <span className="placeable-results__pending">Waiting</span>
              )}
            </div>
            {r.ok && (
              <button
                className="placeable-results__save-btn"
                onClick={() => onSave(i)}
              >
                Save
              </button>
            )}
          </div>
        ))}
      </div>
      {allDone && (
        <button className="placeable-results__save-all" onClick={onSaveAll}>
          Save All to sunny-street
        </button>
      )}
    </div>
  );
}
