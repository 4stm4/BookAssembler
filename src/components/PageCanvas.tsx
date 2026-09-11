import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Image as ImageIcon, Type } from 'lucide-react';
import type { KRMNode, KRMStyle } from '../types';

/**
 * Reconstructs a source page from KRM: blocks placed by their normalized bbox,
 * styled from the StyleDescriptor the adapter preserved (RFC 0021 §3,
 * positional strategy).
 *
 * Which pages get this treatment is decided server-side and delivered as
 * `layout: "positional"` by GET /api/v1/jobs/:id/pages — this component does
 * not re-derive that rule, so it cannot drift from the one that builds the PDF.
 *
 * The page is drawn at its real size (width_pt/height_pt from that same
 * endpoint), not A4: a bbox and a font size in points only mean something
 * against the page they came from. A scan drawn on A4 came out with every
 * line too small and the scan stretched under it.
 */

// Only when the adapter recorded no size (documents processed before it did).
const A4_PT = { w: 595.28, h: 841.89 };

// A line is drawn in the browser's face, not the source's, so its natural
// width differs. It is stretched to its source box — within limits: past
// them the text would be unreadable, and something else is wrong.
const MIN_FIT = 0.6;
const MAX_FIT = 1.6;

// A style's typeface, resolved to a real stack. Falling through to
// `undefined` would inherit the page container's serif, so a block the source
// set in a sans or typewriter face would still render as Georgia.
function familyOf(st?: KRMStyle): string | undefined {
  if (st?.is_monospace) return 'ui-monospace, "SFMono-Regular", Menlo, monospace';
  const fam = (st?.font_family ?? '').toLowerCase();
  if (!fam) return undefined;
  if (fam.includes('mono') || fam.includes('courier')) {
    return 'ui-monospace, "SFMono-Regular", Menlo, monospace';
  }
  if (fam.includes('sans') || fam.includes('helvetica') || fam.includes('arial')) {
    return '"Helvetica Neue", Arial, sans-serif';
  }
  if (fam.includes('serif') || fam.includes('times') || fam.includes('georgia')) {
    return 'Georgia, "Times New Roman", serif';
  }
  return undefined;
}

function nodeText(node: KRMNode): string {
  if (node.caption_text) return node.caption_text;
  if (node.text) return node.text;
  if (node.title) return node.title;
  return '';
}

function rgb(c?: [number, number, number]): string | undefined {
  if (!c || c.length !== 3) return undefined;
  // Near-black source text would vanish on the dark canvas; let CSS win there.
  if (c[0] < 40 && c[1] < 40 && c[2] < 40) return undefined;
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/** One source line, stretched to the width of its box. */
const FittedLine: React.FC<{ text: string; boxWidth: number }> = ({ text, boxWidth }) => {
  const ref = useRef<HTMLSpanElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !boxWidth) return;
    const natural = el.scrollWidth;
    if (natural > 0) {
      setScale(Math.min(MAX_FIT, Math.max(MIN_FIT, boxWidth / natural)));
    }
  }, [text, boxWidth]);
  return (
    <span
      ref={ref}
      className="inline-block whitespace-nowrap origin-left"
      style={{ transform: `scaleX(${scale})` }}
    >
      {text}
    </span>
  );
};

const PageCanvas: React.FC<{
  jobId: string;
  pageIndex: number;
  nodes: KRMNode[];
  pageSizePt?: { w: number; h: number };
  selectedId?: string;
  onSelect?: (node: KRMNode) => void;
}> = ({ jobId, pageIndex, nodes, pageSizePt, selectedId, onSelect }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [showScan, setShowScan] = useState(false);
  const page = pageSizePt ?? A4_PT;

  // Font sizes and line widths are fractions of the page, so they need the
  // rendered size.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      setBox({ w: r.width, h: r.height });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // A block that kept its lines' geometry is drawn line by line, each line in
  // its own box; a block without it is one box its text wraps in.
  type Placed = {
    key: string; nodeId: string; text: string; single: boolean;
    bbox: [number, number, number, number]; style?: KRMStyle; type: string;
  };
  const placed: Placed[] = [];
  for (const n of nodes) {
    if (n.lines?.length) {
      n.lines.forEach((ln, i) =>
        placed.push({
          key: `${n.id}:${i}`, nodeId: n.id, text: ln.text, single: true,
          bbox: ln.bbox, style: ln.style, type: n.type,
        })
      );
    } else if (n.bbox) {
      placed.push({
        key: n.id, nodeId: n.id, text: nodeText(n), single: false,
        bbox: n.bbox, style: n.style, type: n.type,
      });
    }
  }
  const unplaced = nodes.filter((n) => !n.bbox && !n.lines?.length && nodeText(n));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-mono text-slate-400 uppercase tracking-wide">
          Реконструкция страницы {pageIndex + 1}
        </div>
        <button
          onClick={() => setShowScan((v) => !v)}
          className={`px-1.5 py-0.5 rounded text-[9px] font-mono border flex items-center gap-1 ${
            showScan
              ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
              : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:bg-slate-700/60'
          }`}
          title="Показать исходный скан под текстом"
        >
          {showScan ? <ImageIcon className="w-3 h-3" /> : <Type className="w-3 h-3" />}
          {showScan ? 'скан' : 'текст'}
        </button>
      </div>

      <div
        ref={ref}
        className="relative w-full bg-white rounded shadow-inner overflow-hidden"
        style={{
          aspectRatio: `${page.w} / ${page.h}`,
          // The editor pane is font-mono; a reconstructed page must not inherit
          // that or every block renders in the wrong typeface.
          fontFamily: 'Georgia, "Times New Roman", serif',
        }}
      >
        {showScan && (
          <img
            src={`/api/v1/jobs/${jobId}/page-image/${pageIndex}`}
            alt=""
            className="absolute inset-0 w-full h-full object-fill opacity-40"
          />
        )}

        {placed.map((item) => {
          const [x0, y0, x1, y1] = item.bbox;
          const text = item.text;
          const st = item.style;
          const pt = st?.font_size_pt ?? 11;
          const fontPx = box.h ? (pt / page.h) * box.h : 0;
          const boxWidth = (x1 - x0) * box.w;
          // A block without per-line geometry is fitted too when it is one
          // line tall; taller, it can only wrap.
          const fit = item.single || (fontPx > 0 && (y1 - y0) * box.h < 1.6 * fontPx);
          const selected = selectedId === item.nodeId;
          const node = nodes.find((n) => n.id === item.nodeId)!;
          return (
            <div
              key={item.key}
              onClick={() => onSelect?.(node)}
              title={`${item.type} · ${(x0 * 100).toFixed(1)}%, ${(y0 * 100).toFixed(1)}%`}
              className={`absolute leading-none cursor-pointer transition-colors ${
                fit ? 'overflow-visible' : 'overflow-hidden leading-tight'
              } ${selected ? 'ring-2 ring-cyan-400 bg-cyan-400/10' : 'hover:bg-cyan-400/10'}`}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
                fontSize: fontPx ? `${fontPx}px` : undefined,
                fontWeight: st?.is_bold ? 700 : 400,
                fontStyle: st?.is_italic ? 'italic' : 'normal',
                fontFamily: familyOf(st),
                color: rgb(st?.text_color_rgb) ?? '#111',
              }}
            >
              {text ? (
                fit ? <FittedLine text={text} boxWidth={boxWidth} /> : text
              ) : (
                // Figures and other textless blocks still occupy the page —
                // an empty div would make them look like nothing is there.
                <span className="block w-full h-full border border-dashed border-slate-400 rounded-sm text-[8px] text-slate-500 px-0.5">
                  {item.type.replace('Block', '')}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {unplaced.length > 0 && (
        <div className="text-[10px] text-slate-500 font-mono">
          без координат: {unplaced.length} — показаны в списке ниже
        </div>
      )}
    </div>
  );
};

export default PageCanvas;
