// Animated great-circle flight path over a dotted map. No JS needed (SMIL + CSS).
export function FlightPath({ from, to, parcel, className = "" }: { from: string; to: string; parcel?: string; className?: string }) {
  // Fixed geometry: origin lower-left, destination upper-right, arced between.
  const path = "M46,150 C150,70 300,70 404,96";
  const o = { x: 46, y: 150 };
  const d = { x: 404, y: 96 };
  return (
    <div className={`relative overflow-hidden ${className}`}>
      <div className="map-dots absolute inset-0" />
      <svg viewBox="0 0 460 190" preserveAspectRatio="xMidYMid meet" className="relative h-full w-full">
        {/* arc */}
        <path d={path} fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth="1.6" />
        {/* origin (hollow) */}
        <circle cx={o.x} cy={o.y} r="4.5" fill="#0a0a0b" stroke="white" strokeWidth="1.8" />
        {/* destination (filled) */}
        <circle cx={d.x} cy={d.y} r="4.5" fill="white" />
        {/* dashed tail to parcel */}
        {parcel && (
          <>
            <line x1={d.x} y1={d.y} x2={d.x + 26} y2={d.y + 30} stroke="rgba(255,255,255,0.4)" strokeWidth="1.4" strokeDasharray="2 3" />
            <rect x={d.x + 22} y={d.y + 26} width="10" height="10" rx="2" fill="none" stroke="rgba(255,255,255,0.6)" strokeWidth="1.4" />
          </>
        )}
        {/* labels */}
        <text x={o.x} y={o.y + 24} fill="rgba(255,255,255,0.85)" fontSize="14" fontWeight="600" textAnchor="middle" fontFamily="var(--font-geist-mono), monospace">{from}</text>
        <text x={d.x} y={d.y - 14} fill="rgba(255,255,255,0.9)" fontSize="14" fontWeight="600" textAnchor="middle" fontFamily="var(--font-geist-mono), monospace">{to}</text>
        {parcel && <text x={d.x + 27} y={d.y + 50} fill="rgba(255,255,255,0.4)" fontSize="11" textAnchor="middle" fontFamily="var(--font-geist-mono), monospace">{parcel}</text>}
      </svg>
    </div>
  );
}
