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

  const allDone = results.every((r) => r.ok || r.error);

  return (
    <div className="placeable-results">
      <div className="placeable-results__grid">
        {results.map((r, i) => (
          <div key={i} className="placeable-results__card">
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
              ) : (
                <span className="placeable-results__pending">Generating...</span>
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
