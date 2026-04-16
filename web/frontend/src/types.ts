export type Direction = "right" | "up" | "left" | "down";
export type Backend = "gemini-3.1-flash" | "pixellab";
export type ActionType = "chop" | "dig" | "water" | "fishing" | "harvest";

export const ACTIONS: ActionType[] = ["chop", "dig", "water", "fishing", "harvest"];
export const DIRECTIONS: Direction[] = ["right", "up", "left", "down"];

export const BACKEND_CLI_NAME: Record<Backend, string> = {
  "gemini-3.1-flash": "gemini",
  pixellab: "pixellab",
};

export const ACTION_DIMS: Record<
  ActionType,
  { frameWidth: number; frameHeight: number; framesPerDir: number; frameRate: number }
> = {
  harvest: { frameWidth: 32, frameHeight: 64, framesPerDir: 9, frameRate: 6 },
  chop: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
  dig: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
  water: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 6 },
  fishing: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
};

export interface WalkDims {
  cell: [number, number];
  cols: number;
  rows: number;
  direction_order: string[];
  locomotion_rows: Record<string, number>;
  frames_per_dir: number;
}

export interface VariantResult {
  index: number;
  slug: string;
  portraitUrl: string | null;
  walkSheetUrl: string | null;
  walkDims: WalkDims | null;
  actionSheets: Record<string, string>;
  status: "pending" | "generating" | "done" | "error";
  error?: string;
}

export interface ProgressEvent {
  event: string;
  ts_ms?: number;
  variant?: number;
  pipe?: string;
  [key: string]: unknown;
}
