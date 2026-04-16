import type { ActionType, Direction, VariantResult } from "../types";
import { ACTION_DIMS } from "../types";
import { PortraitCell, SpriteCell } from "./SpriteCell";

interface Props {
  variants: VariantResult[];
  selectedActions: ActionType[];
}

const WALK_FRAME_RATE = 10;
const WALK_ROW = 2;
const DIR_ORDER: Direction[] = ["right", "up", "left", "down"];

export function CharacterResultGrid({ variants, selectedActions }: Props) {
  if (variants.length === 0) return null;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 8 }}>
        <thead>
          <tr>
            <th style={{ color: "#888", fontSize: 12 }}>#</th>
            <th style={{ color: "#888", fontSize: 12 }}>Portrait</th>
            <th style={{ color: "#888", fontSize: 12 }}>Walk</th>
            {selectedActions.map((a) => (
              <th key={a} style={{ color: "#888", fontSize: 12, textTransform: "capitalize" }}>
                {a}
              </th>
            ))}
            <th style={{ color: "#888", fontSize: 12 }}>Save</th>
          </tr>
        </thead>
        <tbody>
          {variants.map((v) => (
            <tr key={v.index}>
              <td style={{ color: "#666", verticalAlign: "top", paddingTop: 16 }}>
                {v.index + 1}
              </td>
              <td>
                {v.portraitUrl ? (
                  <PortraitCell imageUrl={v.portraitUrl} />
                ) : (
                  <Placeholder label="Portrait" status={v.status} />
                )}
              </td>
              <td>
                {v.walkSheetUrl && v.walkDims ? (
                  <SpriteCell
                    sheetUrl={v.walkSheetUrl}
                    cellW={v.walkDims.cell[0]}
                    cellH={v.walkDims.cell[1]}
                    framesPerDir={v.walkDims.frames_per_dir}
                    frameRate={WALK_FRAME_RATE}
                    directionOrder={DIR_ORDER}
                    rowIndex={WALK_ROW}
                    label="Walk"
                  />
                ) : (
                  <Placeholder label="Walk" status={v.status} />
                )}
              </td>
              {selectedActions.map((action) => {
                const url = v.actionSheets[action];
                const dims = ACTION_DIMS[action];
                return (
                  <td key={action}>
                    {url && dims ? (
                      <SpriteCell
                        sheetUrl={url}
                        cellW={dims.frameWidth}
                        cellH={dims.frameHeight}
                        framesPerDir={dims.framesPerDir}
                        frameRate={dims.frameRate}
                        directionOrder={DIR_ORDER}
                        rowIndex={0}
                        label={action}
                      />
                    ) : (
                      <Placeholder label={action} status={v.status} />
                    )}
                  </td>
                );
              })}
              <td style={{ verticalAlign: "top", paddingTop: 16 }}>
                {v.status === "done" && (
                  <button
                    style={{
                      padding: "6px 12px",
                      background: "#4a4aff",
                      color: "#fff",
                      border: "none",
                      borderRadius: 4,
                      cursor: "pointer",
                    }}
                  >
                    Save
                  </button>
                )}
                {v.status === "error" && (
                  <span style={{ color: "#ff4444", fontSize: 12 }}>
                    {v.error || "Error"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Placeholder({ label, status }: { label: string; status: string }) {
  return (
    <div
      style={{
        width: 128,
        height: 128,
        background: "#222",
        border: "1px solid #333",
        borderRadius: 4,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#666",
        fontSize: 11,
        flexDirection: "column",
        gap: 4,
      }}
    >
      <span>{label}</span>
      {status === "generating" && <span>...</span>}
    </div>
  );
}
