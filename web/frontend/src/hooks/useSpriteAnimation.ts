import { useEffect, useRef, useState } from "react";

export interface SpriteAnimationParams {
  framesPerDir: number;
  frameRate: number;
  playing: boolean;
}

export interface SpriteAnimationResult {
  frameIndex: number;
}

export function useSpriteAnimation(
  params: SpriteAnimationParams,
): SpriteAnimationResult {
  const { framesPerDir, frameRate, playing } = params;
  const [frameIndex, setFrameIndex] = useState(0);
  const lastTickRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    if (!playing || framesPerDir <= 0 || frameRate <= 0) {
      setFrameIndex(0);
      return;
    }
    const msPerFrame = 1000 / frameRate;
    lastTickRef.current = performance.now();

    const tick = (now: number) => {
      const elapsed = now - lastTickRef.current;
      if (elapsed >= msPerFrame) {
        const steps = Math.floor(elapsed / msPerFrame);
        lastTickRef.current += steps * msPerFrame;
        setFrameIndex((prev) => (prev + steps) % framesPerDir);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [framesPerDir, frameRate, playing]);

  return { frameIndex };
}
