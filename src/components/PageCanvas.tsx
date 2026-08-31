import React, { useEffect, useRef, useState } from 'react';
import { Image as ImageIcon, Type } from 'lucide-react';
import type { KRMNode } from '../types';

/**
 * Reconstructs a source page from KRM: blocks placed by their normalized bbox,
 * styled from the StyleDescriptor the adapter preserved (RFC 0021 §3,
 * positional strategy).
 *
 * Which pages get this treatment is decided server-side and delivered as
 * `layout: "positional"` by GET /api/v1/jobs/:id/pages — this component does
 * not re-derive that rule, so it cannot drift from the one that builds the PDF.
 */

// A4 in mm; bbox is normalized to the page, so only the ratio matters here.
const PAGE_W_MM = 210;
const PAGE_H_MM = 297;
// 297mm at 72dpi ≈ 842pt — converts font_size_pt into a fraction of page height.
const PAGE_H_PT = 842;

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

const PageCanvas: React.FC<{
  jobId: string;
  pageIndex: number;
  nodes: KRMNode[];
  selectedId?: string;
  onSelect?: (node: KRMNode) => void;
}> = ({ jobId, pageIndex, nodes, selectedId, onSelect }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(0);
  const [showScan, setShowScan] = useState(false);

  // Font sizes are a fraction of page height, so they need the rendered size.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setHeight(el.getBoundingClientRect().height);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const placed = nodes.filter((n) => n.bbox);
  const unplaced = nodes.filter((n) => !n.bbox && nodeText(n));

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
        style={{ aspectRatio: `${PAGE_W_MM} / ${PAGE_H_MM}` }}
      >
        {showScan && (
          <img
            src={`/api/v1/jobs/${jobId}/page-image/${pageIndex}`}
            alt=""
            className="absolute inset-0 w-full h-full object-fill opacity-40"
          />
        )}

        {placed.map((node) => {
          const [x0, y0, x1, y1] = node.bbox!;
          const text = nodeText(node);
          const st = node.style;
          const pt = st?.font_size_pt ?? 11;
          const selected = selectedId === node.id;
          return (
            <div
              key={node.id}
              onClick={() => onSelect?.(node)}
              title={`${node.type} · ${(x0 * 100).toFixed(1)}%, ${(y0 * 100).toFixed(1)}%`}
              className={`absolute overflow-hidden leading-tight cursor-pointer transition-colors ${
                selected ? 'ring-2 ring-cyan-400 bg-cyan-400/10' : 'hover:bg-cyan-400/10'
              }`}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
                fontSize: height ? `${(pt / PAGE_H_PT) * height}px` : undefined,
                fontWeight: st?.is_bold ? 700 : 400,
                fontStyle: st?.is_italic ? 'italic' : 'normal',
                fontFamily: st?.is_monospace ? 'ui-monospace, monospace' : undefined,
                color: rgb(st?.text_color_rgb) ?? '#111',
              }}
            >
              {text}
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
