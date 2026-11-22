// A train marker drawn once to a canvas: a circle with a point showing the direction of travel. Used as a mask,
// so deck.gl colours it per train
export const ARROW_SIZE = 64;

export function arrowAtlas(): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = ARROW_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const c = ARROW_SIZE / 2;
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  ctx.arc(c, c + 6, 20, 0, Math.PI * 2);
  ctx.moveTo(c - 15, c - 7);
  ctx.lineTo(c, c - 30);
  ctx.lineTo(c + 15, c - 7);
  ctx.closePath();
  ctx.fill();
  return canvas;
}

export const ARROW_MAPPING = {
  arrow: { x: 0, y: 0, width: ARROW_SIZE, height: ARROW_SIZE, anchorY: ARROW_SIZE / 2 + 6, mask: true },
};
