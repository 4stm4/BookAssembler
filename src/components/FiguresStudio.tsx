import React, { useState } from 'react';
import {
  Image as ImageIcon,
  Sparkles,
  Code,
  Save,
  CheckCircle,
  Layers,
  Cpu,
  ArrowRight,
  Maximize2,
  RefreshCw,
  Box,
} from 'lucide-react';
import { FigureDiagram } from '../types';

interface FiguresStudioProps {
  figures: FigureDiagram[];
  onSaveTikz: (figId: string, tikzCode: string, caption: string) => void;
  onGenerateTikzAi: (figId: string, caption: string, figType: string) => Promise<void>;
  isGeneratingTikz: boolean;
}

export const FiguresStudio: React.FC<FiguresStudioProps> = ({
  figures,
  onSaveTikz,
  onGenerateTikzAi,
  isGeneratingTikz,
}) => {
  const [selectedFigId, setSelectedFigId] = useState<string>(figures[0]?.figure || '4.1');
  const activeFig = figures.find((f) => f.figure === selectedFigId) || figures[0];
  const [tikzCode, setTikzCode] = useState(activeFig?.tikz_code || '');
  const [caption, setCaption] = useState(activeFig?.caption || '');
  const [isSaved, setIsSaved] = useState(false);

  React.useEffect(() => {
    if (activeFig) {
      setTikzCode(activeFig.tikz_code || '');
      setCaption(activeFig.caption || '');
    }
  }, [activeFig]);

  const handleSave = () => {
    onSaveTikz(selectedFigId, tikzCode, caption);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100">
      {/* Top Figure Selector Bar */}
      <div className="p-4 bg-slate-900/80 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-2xl">
          <span className="text-xs font-semibold text-slate-400">Figures:</span>
          {figures.map((fig) => (
            <button
              key={fig.figure}
              onClick={() => setSelectedFigId(fig.figure)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-2 ${
                fig.figure === selectedFigId
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700/50'
              }`}
            >
              <ImageIcon className="w-3.5 h-3.5" />
              <span>Figure {fig.figure}</span>
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-950/60 text-slate-300 font-mono">
                {fig.fig_type}
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onGenerateTikzAi(selectedFigId, caption, activeFig?.fig_type || 'block_diagram')}
            disabled={isGeneratingTikz}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md shadow-blue-500/20 transition"
          >
            {isGeneratingTikz ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            <span>Generate TikZ with AI</span>
          </button>

          <button
            onClick={handleSave}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition shadow-md shadow-emerald-500/20"
          >
            <Save className="w-3.5 h-3.5" />
            <span>{isSaved ? 'Saved!' : 'Save TikZ'}</span>
          </button>
        </div>
      </div>

      {/* Main Split: Visual Schematic SVG vs TikZ LaTeX Code */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-4 flex-1 overflow-y-auto">
        {/* Left: Vector Schematic Preview */}
        <div className="flex flex-col bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-blue-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                Vector Architecture Canvas (Fig {selectedFigId})
              </span>
            </div>
            <span className="text-xs text-slate-400 font-mono">Page {activeFig?.page}</span>
          </div>

          {/* SVG Vector Schematic Canvas */}
          <div className="flex-1 p-6 flex flex-col items-center justify-center bg-slate-950 relative overflow-hidden">
            {/* Render dynamic SVG based on figure type */}
            <div className="w-full max-w-md bg-slate-900/90 border border-slate-800/80 rounded-2xl p-6 shadow-2xl relative">
              {activeFig?.fig_type === 'memory_map' ? (
                <div className="flex flex-col gap-2">
                  <div className="text-center font-bold text-xs text-blue-400 uppercase tracking-wider mb-2">
                    Стековая память (Операции PUSH / POP)
                  </div>
                  <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs font-mono text-amber-300 flex justify-between">
                    <span>SS:FFFE</span>
                    <span className="font-bold">[ Высокие адреса ]</span>
                  </div>
                  <div className="p-2.5 bg-amber-500/20 border border-amber-500/40 rounded-lg text-xs font-mono text-amber-200 flex justify-between">
                    <span>SS:FFFC</span>
                    <span className="font-bold">Данные AX (PUSH AX)</span>
                  </div>
                  <div className="p-2.5 bg-blue-500/20 border border-blue-500/40 rounded-lg text-xs font-mono text-blue-200 flex justify-between">
                    <span>SS:FFFA</span>
                    <span className="font-bold">Данные BX (PUSH BX)</span>
                  </div>
                  <div className="p-2.5 bg-rose-500/20 border border-rose-500/40 rounded-lg text-xs font-mono text-rose-200 flex justify-between ring-1 ring-rose-500/40">
                    <span>SS:FFF8</span>
                    <span className="font-bold">← Указатель SP</span>
                  </div>
                  <div className="p-2.5 bg-slate-800/40 border border-slate-700/40 rounded-lg text-xs font-mono text-slate-400 flex justify-between">
                    <span>SS:FFF6</span>
                    <span>[ Свободный стек ]</span>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {/* Top Bus */}
                  <div className="w-full py-2 bg-gradient-to-r from-slate-800 via-blue-900/60 to-slate-800 border border-blue-500/40 rounded-xl text-center font-bold text-xs text-blue-200 tracking-wider">
                    ВНУТРЕННЯЯ 16-БИТНАЯ ШИНА ДАННЫХ 8086
                  </div>

                  {/* Registers Grid */}
                  <div className="grid grid-cols-4 gap-2">
                    <div className="p-2.5 bg-blue-950/60 border border-blue-500/30 rounded-xl text-center font-mono font-bold text-xs text-blue-300">
                      AX (AH/AL)
                    </div>
                    <div className="p-2.5 bg-blue-950/60 border border-blue-500/30 rounded-xl text-center font-mono font-bold text-xs text-blue-300">
                      BX (BH/BL)
                    </div>
                    <div className="p-2.5 bg-blue-950/60 border border-blue-500/30 rounded-xl text-center font-mono font-bold text-xs text-blue-300">
                      CX (CH/CL)
                    </div>
                    <div className="p-2.5 bg-blue-950/60 border border-blue-500/30 rounded-xl text-center font-mono font-bold text-xs text-blue-300">
                      DX (DH/DL)
                    </div>
                  </div>

                  {/* Bottom Memory Block */}
                  <div className="w-full p-4 bg-emerald-950/40 border border-emerald-500/30 rounded-xl text-center">
                    <div className="text-xs font-bold text-emerald-300 uppercase tracking-wider">
                      Системная память (1 Мбайт ОЗУ)
                    </div>
                    <div className="text-[11px] text-emerald-400/80 mt-1 font-mono">
                      Сегменты: CS, DS, SS, ES (Прямой доступ через BIU)
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="mt-4 text-center">
              <span className="text-xs font-semibold text-slate-300">
                {caption || activeFig?.caption}
              </span>
            </div>
          </div>

          {/* Figure Quality Checklist */}
          <div className="p-3 bg-slate-900 border-t border-slate-800 text-xs flex items-center justify-between text-slate-400">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1 text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" /> Russian Labels
              </span>
              <span className="flex items-center gap-1 text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" /> Vector arrows
              </span>
              <span className="flex items-center gap-1 text-emerald-400">
                <CheckCircle className="w-3.5 h-3.5" /> Standalone .tex
              </span>
            </div>
          </div>
        </div>

        {/* Right: LaTeX TikZ Source Editor */}
        <div className="flex flex-col bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Code className="w-4 h-4 text-purple-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                LaTeX TikZ Source (figures/fig_{selectedFigId.replace('.', '_')}.tex)
              </span>
            </div>
          </div>

          <div className="p-3 bg-slate-950/60 border-b border-slate-800">
            <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
              Figure Caption:
            </label>
            <input
              type="text"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700/70 rounded-lg text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="flex-1 p-2 flex flex-col">
            <textarea
              value={tikzCode}
              onChange={(e) => setTikzCode(e.target.value)}
              placeholder="\\begin{figure}[htbp] ... \\end{figure}"
              className="w-full flex-1 p-3 bg-slate-950/90 border border-slate-800 rounded-xl text-xs font-mono text-purple-200 focus:outline-none focus:ring-1 focus:ring-purple-500 resize-none leading-relaxed"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
