// Minimal, safe Markdown renderer for assistant messages.
//
// Renders a known subset of Markdown to REACT ELEMENTS ONLY — it never uses
// dangerouslySetInnerHTML and never emits raw HTML, so model output cannot inject
// markup or scripts. Supported: paragraphs (with soft line breaks), unordered and
// ordered lists, ATX headings, **bold**, *italic*, `inline code`, and [links](url)
// restricted to http(s)/mailto. Anything unrecognised renders as literal text, so
// partial Markdown mid-stream (e.g. an unclosed `**`) degrades to plain text until
// it completes.

import { Fragment } from "react";
import type { ReactNode } from "react";

const SAFE_URL = /^(https?:|mailto:)/i;

function safeHref(url: string): string | null {
  const trimmed = url.trim();
  return SAFE_URL.test(trimmed) ? trimmed : null;
}

interface InlineRule {
  regex: RegExp;
  render: (match: RegExpMatchArray, key: number) => ReactNode;
}

// Order matters: opaque `code` and links are matched before emphasis, and bold (**)
// before italic (*), so ties at the same index resolve to the stronger construct.
const INLINE_RULES: InlineRule[] = [
  {
    regex: /`([^`]+)`/,
    render: (m, key) => (
      <code key={key} className="cadre-md-code">
        {m[1]}
      </code>
    ),
  },
  {
    regex: /\[([^\]]+)\]\(([^)\s]+)\)/,
    render: (m, key) => {
      const href = safeHref(m[2]);
      // Unsafe scheme → drop the link but keep its visible text.
      return href ? (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow">
          {m[1]}
        </a>
      ) : (
        <Fragment key={key}>{m[1]}</Fragment>
      );
    },
  },
  {
    // **bold** — content has non-space boundaries; may contain a nested *italic*.
    // The (?!\*) stops the close from matching the first two stars of a `***`
    // sequence (bold + italic), so "**bold *x***" nests correctly.
    regex: /\*\*(\S(?:.*?\S)?)\*\*(?!\*)/,
    render: (m, key) => <strong key={key}>{parseInline(m[1])}</strong>,
  },
  {
    // *italic* — no inner '*', non-space boundaries (so "a * b" is not emphasised).
    regex: /\*(\S(?:[^*]*?\S)?)\*/,
    render: (m, key) => <em key={key}>{parseInline(m[1])}</em>,
  },
];

export function parseInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let key = 0;

  while (rest.length > 0) {
    let best: { index: number; rule: InlineRule; match: RegExpMatchArray } | null = null;
    for (const rule of INLINE_RULES) {
      const match = rule.regex.exec(rest);
      if (match && match.index !== undefined && (best === null || match.index < best.index)) {
        best = { index: match.index, rule, match };
      }
    }
    if (best === null) {
      out.push(rest);
      break;
    }
    if (best.index > 0) out.push(rest.slice(0, best.index));
    out.push(best.rule.render(best.match, key));
    key += 1;
    rest = rest.slice(best.index + best.match[0].length);
  }

  return out;
}

type Block =
  | { type: "p"; lines: string[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "h"; text: string };

const UL_ITEM = /^\s*[-*+]\s+/;
const OL_ITEM = /^\s*\d+[.)]\s+/;
const HEADING = /^(#{1,6})\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ type: "h", text: heading[2] });
      i += 1;
      continue;
    }

    if (UL_ITEM.test(line)) {
      const items: string[] = [];
      while (i < lines.length && UL_ITEM.test(lines[i])) {
        items.push(lines[i].replace(UL_ITEM, ""));
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (OL_ITEM.test(line)) {
      const items: string[] = [];
      while (i < lines.length && OL_ITEM.test(lines[i])) {
        items.push(lines[i].replace(OL_ITEM, ""));
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const pLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !UL_ITEM.test(lines[i]) &&
      !OL_ITEM.test(lines[i]) &&
      !HEADING.test(lines[i])
    ) {
      pLines.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: "p", lines: pLines });
  }

  return blocks;
}

function renderParagraph(lines: string[], key: number): ReactNode {
  const nodes: ReactNode[] = [];
  lines.forEach((line, j) => {
    if (j > 0) nodes.push(<br key={`br-${j}`} />);
    nodes.push(<Fragment key={`ln-${j}`}>{parseInline(line)}</Fragment>);
  });
  return (
    <p key={key} className="cadre-md-p">
      {nodes}
    </p>
  );
}

/** Render assistant Markdown as safe React elements. */
export function Markdown({ text }: { text: string }): ReactNode {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((block, i) => {
        switch (block.type) {
          case "h":
            return (
              <p key={i} className="cadre-md-h">
                {parseInline(block.text)}
              </p>
            );
          case "ul":
            return (
              <ul key={i} className="cadre-md-ul">
                {block.items.map((item, j) => (
                  <li key={j}>{parseInline(item)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="cadre-md-ol">
                {block.items.map((item, j) => (
                  <li key={j}>{parseInline(item)}</li>
                ))}
              </ol>
            );
          case "p":
          default:
            return renderParagraph(block.lines, i);
        }
      })}
    </>
  );
}
