// How an Ask Relay answer is shown. The assistant writes plain sentences and "- " bullets only,
// so this small parser is all the formatting needed.
import { Fragment, ReactNode } from "react";
import Link from "next/link";

// "Counting, Counting, Reading #5" -> "Counting ×2 · Reading #5": the same lookup is named once.
export function tally(steps: string[]): string {
  const n = new Map<string, number>();
  for (const x of steps) n.set(x, (n.get(x) ?? 0) + 1);
  return [...n.entries()].map(([x, c]) => (c > 1 ? `${x} ×${c}` : x)).join(" · ");
}

// Inline pieces: #1234 becomes a link to the request, **x** becomes bold.
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(#\d{3,6}\b|\*\*[^*]+\*\*)/g).map((p, i) => {
    if (/^#\d{3,6}$/.test(p))
      return (
        <Link key={`${key}-${i}`} href={`/v2/requests?id=${p.slice(1)}`}
          className="tnum rounded-[5px] border border-[var(--hair-2)] px-1.5 py-px text-[13px] text-[var(--fg)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]">
          {p}
        </Link>
      );
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={`${key}-${i}`} className="font-semibold text-[var(--fg)]">{p.slice(2, -2)}</strong>;
    return <Fragment key={`${key}-${i}`}>{p}</Fragment>;
  });
}

export function Answer({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = (k: string) => {
    if (!list.length) return;
    out.push(
      <ul key={k} className="my-2 space-y-1.5 pl-5">
        {list.map((x, i) => <li key={i} className="list-disc marker:text-[var(--fg-3)]">{inline(x, `${k}-${i}`)}</li>)}
      </ul>,
    );
    list = [];
  };
  text.split("\n").forEach((line, i) => {
    const b = /^\s*[-•]\s+(.*)$/.exec(line);
    if (b) { list.push(b[1]); return; }
    flush(`l${i}`);
    if (line.trim()) out.push(<p key={`p${i}`} className="my-2 whitespace-pre-wrap first:mt-0">{inline(line, `p${i}`)}</p>);
  });
  flush("end");
  return <div className="text-[15px] leading-[1.7] text-[var(--fg)]/90">{out}</div>;
}
