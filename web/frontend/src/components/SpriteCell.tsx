import { useState } from "react";
import { useSpriteAnimation } from "../hooks/useSpriteAnimation";
import type { Direction } from "../types";
import "./SpriteCell.css";

export interface SpriteCellProps {
  sheetUrl: string;
  cellW: number;
  cellH: number;
  framesPerDir: number;
  frameRate: number;
  directionOrder: Direction[];
  rowIndex: number;
  scale?: number;
  label?: string;
}

export function SpriteCell({
  sheetUrl,
  cellW,
  cellH,
  framesPerDir,
  frameRate,
  directionOrder,
  rowIndex,
  scale = 2,
  label,
}: SpriteCellProps) {
  const [direction, setDirection] = useState<Direction>("down");
  const { frameIndex } = useSpriteAnimation({
    framesPerDir,
    frameRate,
    playing: true,
  });

  const dirIdx = directionOrder.indexOf(direction);
  const col = dirIdx * framesPerDir + frameIndex;
  const bgX = -(col * cellW * scale);
  const bgY = -(rowIndex * cellH * scale);

  return (
    <div className="sprite-cell">
      {label && <div className="sprite-cell__label">{label}</div>}
      <div
        className="sprite-cell__canvas"
        style={{
          width: cellW * scale,
          height: cellH * scale,
          backgroundImage: `url(${sheetUrl})`,
          backgroundPosition: `${bgX}px ${bgY}px`,
          backgroundSize: "auto",
          backgroundRepeat: "no-repeat",
          imageRendering: "pixelated",
        }}
      />
      <div className="sprite-cell__dirs">
        {(["up", "left", "down", "right"] as Direction[]).map((d) => (
          <button
            key={d}
            className={`sprite-cell__dir-btn ${d === direction ? "active" : ""}`}
            onClick={() => setDirection(d)}
            title={d}
          >
            {{ up: "\u2191", left: "\u2190", down: "\u2193", right: "\u2192" }[d]}
          </button>
        ))}
      </div>
    </div>
  );
}

export function PortraitCell({
  imageUrl,
  scale = 2,
}: {
  imageUrl: string;
  scale?: number;
}) {
  return (
    <div className="sprite-cell">
      <div className="sprite-cell__label">Portrait</div>
      <img
        src={imageUrl}
        alt="Character portrait"
        className="sprite-cell__portrait"
        style={{
          width: 64 * scale,
          height: 64 * scale,
          imageRendering: "pixelated",
        }}
      />
    </div>
  );
}
