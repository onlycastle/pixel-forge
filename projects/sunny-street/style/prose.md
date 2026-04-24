# Sunny Street style guide

Top-down 32×32 pixel art for a sunny coastal farm-village game. The world is
daylit, warm, and lived-in — think a coastal Stardew Valley with cobblestone
town paths, wooden farm fences, weathered piers, and sandy beaches. The
existing game draws from modern farm-sim pixel art (Modern_Farm /
modernexteriors aesthetic): soft natural shading, naturalistic color, readable
silhouettes.

## Canvas

- Tiles are exactly 32×32, grid-aligned, seamless when edges are meant to tile
  (grass, sand, stone, water, paths).
- Props are rendered on a transparent background, centered in the frame.
- Characters are rendered as a single idle frame, full body, facing the viewer,
  feet near the bottom of the sprite.
- No anti-aliasing. Every pixel is a hard, solid color drawn from the palette.
  No dithering gradients; use flat shading with 2–3 tonal steps.

## Line work

- 1-pixel dark outlines on the silhouettes of separable objects (props,
  furniture, animals, characters). Outlines use the darkest desaturated tones
  in the palette — never pure black.
- Seamless terrain tiles (grass, sand, dirt, cobblestone, water) have **no**
  outer outline. They read through internal color variation and texture.
- Internal shading is subtle: 1 base tone + 1 shadow tone + optional 1
  highlight tone. Avoid heavy contrast ramps.

## Color

- The palette is sampled from the existing game's outdoor tilesets
  (farm-tiles, exterior-tiles, serene-village-tiles). Stay within it.
- Expect warm earth tones for sand/paths/wood, muted greens for grass and
  foliage, desaturated teal/blue-gray for water and sky, and a handful of
  deeper plum/charcoal shades for outlines and shadows.
- Use accent colors sparingly — reserve the brightest reds/oranges for focal
  props (market awnings, flags, ripe fruit) so they don't fight the
  environment.

## Composition rules

- Every tile is readable in isolation. A grass tile should look like grass
  without needing context from neighbors.
- Props sit on a ground plane implied by a subtle 1-pixel shadow ellipse
  underneath them when it helps the silhouette read.
- Collision-layer tiles (tree trunks, rocks, walls, fence posts) should feel
  solid — clear vertical edges, grounded shadows.
- Object-layer decorative tiles (flowers, shells, footprints, scatter) are
  lighter and flatter; they sit *on* the ground rather than rising above it.

## Never render

Text, UI chrome, borders, watermarks, signatures, or anything that looks like
an icon frame. Characters do not carry weapons or held items unless explicitly
requested. No modern branding, logos, or real-world trademarks.
