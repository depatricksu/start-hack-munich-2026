export type Notice = {
  id: string;
  ts: number; // seconds
  severity: "critical" | "warning";
  title: string;
  detail: string;
  context: string; // lane + booking, or who it is about
  action: string;
  href: string;
  simulated?: boolean; // a test mail (raw.simulated): always labelled in the UI
};
