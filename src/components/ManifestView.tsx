import React from 'react';
import {
  ListTree,
  FileCode,
  Image as ImageIcon,
  HelpCircle,
  Table,
  Terminal,
  ListOrdered,
  Layers,
} from 'lucide-react';
import { ChapterManifest } from '../types';

interface ManifestViewProps {
  manifest: ChapterManifest;
  onSelectPage: (page: number) => void;
}

export const ManifestView: React.FC<ManifestViewProps> = ({ manifest, onSelectPage }) => {
  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 p-4 lg:p-6 overflow-y-auto space-y-6">
      {/* Top Header */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-6 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <ListTree className="w-5 h-5 text-blue-400" />
              Chapter {manifest.chapter} Manifest &amp; Structure Inventory
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Ground-truth extracted hierarchy for pages {manifest.pages.start}–{manifest.pages.end} ({manifest.pages.count} pages total).
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="px-3 py-1.5 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 font-bold">
              v{manifest.manifest_version} Manifest Contract
            </span>
          </div>
        </div>

        {/* Quick Inventory Summary Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-6 pt-6 border-t border-slate-800">
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl text-center">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Sections
            </div>
            <div className="text-xl font-bold text-blue-400 mt-1">{manifest.sections.length}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl text-center">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Figures
            </div>
            <div className="text-xl font-bold text-emerald-400 mt-1">{manifest.figures.length}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl text-center">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Examples
            </div>
            <div className="text-xl font-bold text-amber-400 mt-1">{manifest.examples.length}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl text-center">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Tables
            </div>
            <div className="text-xl font-bold text-indigo-400 mt-1">{manifest.tables.length}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl text-center">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              DEBUG Sessions
            </div>
            <div className="text-xl font-bold text-purple-400 mt-1">
              {manifest.debug_sessions.length}
            </div>
          </div>
        </div>
      </div>

      {/* Grid of Extracted Structures */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sections List */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-4 flex items-center gap-2">
            <FileCode className="w-4 h-4" />
            Chapter Sections
          </h3>
          <div className="space-y-2">
            {manifest.sections.map((sec) => (
              <div
                key={sec.number}
                className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-xl flex items-center justify-between gap-2 text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <span className="font-mono font-bold text-blue-400">{sec.number}</span>
                  <span className="font-semibold text-slate-200">{sec.title}</span>
                </div>
                <button
                  onClick={() => onSelectPage(sec.page)}
                  className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 font-mono"
                >
                  p.{sec.page}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Figures Inventory */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-4 flex items-center gap-2">
            <ImageIcon className="w-4 h-4" />
            Figures &amp; Diagrams
          </h3>
          <div className="space-y-2">
            {manifest.figures.map((fig) => (
              <div
                key={fig.number}
                className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-xl flex items-center justify-between gap-2 text-xs"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-emerald-400">Fig. {fig.number}</span>
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 font-mono">
                      {fig.type}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{fig.caption}</p>
                </div>
                <button
                  onClick={() => onSelectPage(fig.page)}
                  className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 font-mono shrink-0"
                >
                  p.{fig.page}
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
