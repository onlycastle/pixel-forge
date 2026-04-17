import type { PlaceableSuggestion } from "../types";

interface SuggestionListProps {
  suggestions: PlaceableSuggestion[];
  selected: Set<number>;
  onToggle: (index: number) => void;
  mapDescription: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  nature: "#5a9e3e",
  furniture: "#b08050",
  structure: "#888",
  decor: "#c06080",
};

export function SuggestionList({
  suggestions,
  selected,
  onToggle,
  mapDescription,
}: SuggestionListProps) {
  return (
    <div className="suggestion-list">
      <p className="suggestion-list__description">{mapDescription}</p>
      <div className="suggestion-list__items">
        {suggestions.map((s, i) => (
          <label key={i} className="suggestion-list__item">
            <input
              type="checkbox"
              checked={selected.has(i)}
              onChange={() => onToggle(i)}
            />
            <span className="suggestion-list__name">{s.name}</span>
            <span className="suggestion-list__footprint">
              {s.footprint[0]}x{s.footprint[1]}
            </span>
            <span
              className="suggestion-list__category"
              style={{ background: CATEGORY_COLORS[s.category] ?? "#555" }}
            >
              {s.category}
            </span>
          </label>
        ))}
      </div>
      <p className="suggestion-list__count">
        {selected.size} of {suggestions.length} selected
      </p>
    </div>
  );
}
