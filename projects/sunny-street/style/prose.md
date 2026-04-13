# Sunny Street style guide

Top-down 16x16 pixel art, grid-aligned, no anti-aliased edges. Stardew-Valley-adjacent
with softer edges and warmer midtones. Each tile is a complete cell with a 1px
implicit shadow on the bottom-right where it helps read depth, never across
transparent edges.

Line work: 1-pixel dark outlines on separable objects; tiles like grass, dirt,
and water have no outline, they blend through texture. Limit visible dithering.
Shading is at most two steps below the base color.

Color: lean on the palette's earth tones for outdoor terrain; reserve the brighter
accents (#ef7d57, #41a6f6) for focal props and highlights. Avoid pure black
(#1a1c2c is the darkest line color).

Never render text, UI chrome, borders, or watermarks in generated assets.
