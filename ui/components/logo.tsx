// Relay mark: two overlapping angular blades, Agent Kit style.
export function RelayMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path d="M3.5 15.2 L9.8 6.4 L12.4 8.2 L6.1 17 Z" fill="currentColor" />
      <path d="M11.6 6.4 L17.9 15.2 L14.2 17 L7.9 8.2 Z" fill="currentColor" opacity="0.5" />
    </svg>
  );
}

// Sidebar toggle: rounded panel with the left compartment filled (macOS style).
export function SidebarToggleIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="3.6" stroke="currentColor" strokeWidth="1.8" />
      <path d="M6 6 H9.8 V18 H6 A2.3 2.3 0 0 1 3.7 15.7 V8.3 A2.3 2.3 0 0 1 6 6 Z" fill="currentColor" />
    </svg>
  );
}
