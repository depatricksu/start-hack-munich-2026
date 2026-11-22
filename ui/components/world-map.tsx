// Small dotted world map with one arc per shipment. Pure SVG, no data files: land is a set of rough continent
// outlines, sampled into a dot grid once at module load. Positions come from lib/airports.ts.
import { AIRPORTS } from "@/lib/airports";

type P = [number, number]; // [lon, lat]
const LAND: P[][] = [
  // North America
  [[-168, 66], [-162, 70], [-140, 70], [-125, 70], [-95, 72], [-80, 73], [-62, 60], [-56, 52], [-66, 45], [-70, 41], [-76, 35], [-81, 31], [-80, 25], [-82, 27], [-84, 30], [-90, 29], [-97, 27], [-97, 22], [-92, 18], [-87, 21], [-88, 16], [-83, 10], [-77, 8], [-80, 8], [-86, 12], [-92, 14], [-105, 20], [-110, 24], [-112, 30], [-117, 32], [-122, 37], [-124, 42], [-124, 48], [-130, 55], [-140, 60], [-152, 58], [-165, 54], [-160, 59], [-166, 62]],
  // South America
  [[-77, 8], [-72, 12], [-62, 11], [-52, 5], [-50, 0], [-35, -5], [-39, -14], [-41, -22], [-48, -26], [-53, -34], [-58, -38], [-65, -41], [-66, -48], [-69, -52], [-74, -53], [-73, -45], [-72, -35], [-71, -25], [-70, -18], [-76, -14], [-81, -6], [-80, 0], [-78, 2]],
  // Eurasia (with Arabia, India, Southeast Asia)
  [[-10, 36], [-9, 43], [-2, 44], [-5, 48], [2, 51], [8, 54], [10, 57], [5, 58], [5, 62], [14, 68], [20, 70], [28, 71], [40, 68], [60, 70], [70, 73], [80, 73], [100, 77], [115, 74], [140, 72], [160, 70], [180, 68], [180, 65], [170, 60], [163, 58], [156, 51], [143, 59], [135, 55], [141, 52], [140, 46], [132, 43], [129, 40], [126, 35], [122, 40], [119, 38], [122, 31], [120, 25], [110, 21], [106, 20], [108, 11], [105, 9], [100, 13], [101, 3], [104, 1], [98, 8], [98, 16], [94, 17], [90, 22], [86, 20], [80, 15], [77, 8], [73, 17], [70, 22], [66, 25], [57, 25], [56, 27], [50, 30], [48, 29], [51, 25], [56, 26], [59, 22], [52, 16], [44, 12], [43, 15], [39, 21], [35, 28], [34, 31], [36, 36], [30, 36], [27, 37], [26, 41], [29, 41], [23, 40], [21, 37], [19, 41], [13, 45], [16, 41], [15, 38], [12, 42], [9, 44], [3, 43], [0, 39], [-6, 36]],
  // Africa
  [[-17, 21], [-17, 15], [-12, 8], [-8, 4], [0, 5], [9, 4], [9, -1], [13, -6], [12, -17], [15, -27], [18, -34], [26, -34], [33, -28], [35, -22], [40, -15], [40, -5], [43, -1], [51, 11], [43, 12], [37, 22], [33, 31], [25, 32], [20, 31], [11, 33], [10, 37], [0, 36], [-6, 36], [-10, 30]],
  // Australia
  [[114, -22], [113, -26], [115, -34], [124, -34], [132, -32], [138, -35], [141, -38], [147, -38], [150, -37], [153, -30], [153, -25], [146, -19], [142, -11], [141, -17], [136, -12], [131, -11], [126, -14], [122, -18]],
  [[-55, 60], [-45, 60], [-20, 70], [-20, 80], [-60, 82], [-72, 78], [-58, 70]], // Greenland
  [[-5, 50], [1, 51], [2, 53], [-2, 56], [-3, 59], [-6, 58], [-5, 54], [-3, 53]], // Britain
  [[-24, 64], [-14, 64], [-14, 66], [-22, 66]], // Iceland
  [[130, 31], [135, 34], [140, 35], [142, 40], [141, 45], [144, 44], [140, 41], [136, 36], [132, 34]], // Japan
  [[95, 5], [106, -6], [115, -8], [120, -9], [125, -8], [118, -3], [119, 5], [116, 7], [110, 2], [104, 1]], // Indonesia
  [[131, -1], [141, -3], [150, -10], [141, -9], [137, -5]], // New Guinea
  [[120, 18], [122, 18], [126, 7], [122, 7], [120, 14]], // Philippines
  [[44, -25], [47, -25], [50, -15], [49, -12], [44, -17]], // Madagascar
  [[172, -35], [178, -38], [174, -41], [167, -46], [172, -41]], // New Zealand
];

const TOP = 78, BOTTOM = -52, K = 2.4, STEP = 2.6;
export const MAP_W = 360 * K, MAP_H = (TOP - BOTTOM) * K;
const xy = (lat: number, lon: number): [number, number] => [(lon + 180) * K, (TOP - lat) * K];

function inside([x, y]: P, poly: P[]): boolean {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

const DOTS: [number, number][] = (() => {
  const out: [number, number][] = [];
  for (let lat = TOP; lat >= BOTTOM; lat -= STEP)
    for (let lon = -180; lon <= 180; lon += STEP)
      if (LAND.some((p) => inside([lon, lat], p))) out.push(xy(lat, lon));
  return out;
})();

export type Arc = { key: string; from: string | null; to: string | null; tone: "won" | "over" };

export function WorldMap({ arcs, className = "" }: { arcs: Arc[]; className?: string }) {
  const drawn = arcs.flatMap((a) => {
    const o = a.from ? AIRPORTS[a.from] : undefined, d = a.to ? AIRPORTS[a.to] : undefined;
    if (!o || !d) return [];
    const [x1, y1] = xy(o[0], o[1]), [x2, y2] = xy(d[0], d[1]);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, len = Math.hypot(x2 - x1, y2 - y1);
    return [{ ...a, x1, y1, x2, y2, cx: mx, cy: my - Math.min(90, len * 0.28) }];
  });
  const ports = new Map<string, [number, number]>();
  for (const a of drawn) { ports.set(a.from!, [a.x1, a.y1]); ports.set(a.to!, [a.x2, a.y2]); }
  // Label a port only if no labelled port sits right next to it (FRA, DUS, CGN, HAM are close together).
  const labelled: [number, number][] = [];
  const showLabel = new Set<string>();
  for (const [code, [x, y]] of ports) {
    if (labelled.some(([lx, ly]) => Math.abs(lx - x) < 22 && Math.abs(ly - y) < 11)) continue;
    labelled.push([x, y]);
    showLabel.add(code);
  }
  return (
    <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} preserveAspectRatio="xMidYMid meet" className={className} role="img" aria-label="Map of booked shipments">
      <g fill="rgba(255,255,255,0.22)">
        {DOTS.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={1.35} />)}
      </g>
      {drawn.map((a) => (
        <path key={a.key} d={`M${a.x1},${a.y1} Q${a.cx},${a.cy} ${a.x2},${a.y2}`} fill="none"
          stroke={a.tone === "won" ? "rgba(110,231,183,0.75)" : "rgba(161,161,170,0.45)"} strokeWidth={1.6} />
      ))}
      {[...ports.entries()].map(([code, [x, y]]) => (
        <g key={code}>
          <circle cx={x} cy={y} r={2.6} fill="#0a0a0b" stroke="rgba(255,255,255,0.85)" strokeWidth={1.2} />
          {showLabel.has(code) && <text x={x} y={y - 6} fill="rgba(255,255,255,0.55)" fontSize={9} textAnchor="middle" fontFamily="var(--font-geist-mono), monospace">{code}</text>}
        </g>
      ))}
    </svg>
  );
}
