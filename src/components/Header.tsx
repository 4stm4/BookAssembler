import React from 'react';
import {
  BookOpen,
  Play,
  Cpu,
  Layers,
  FileCode,
  CheckCircle2,
  Settings,
  Sparkles,
  RefreshCw,
  Terminal,
} from 'lucide-react';
import { BookConfig } from '../types';

interface HeaderProps {
  config: BookConfig;
  activeChapter: number;
  onSelectChapter: (ch: number) => void;
  onOpenProfile: () => void;
  onOpenGlossary: () => void;
  onOpenJobs: () => void;
  onOpenAiAssist: () => void;
  onRunFullPipeline: () => void;
  isRunningPipeline: boolean;
  jobCount: number;
}

export const Header: React.FC<HeaderProps> = ({
  config,
  activeChapter,
  onSelectChapter,
  onOpenProfile,
  onOpenGlossary,
  onOpenJobs,
  onOpenAiAssist,
  onRunFullPipeline,
  isRunningPipeline,
  jobCount,
}) => {
  const currentChapter = config.chapters[activeChapter] || {
    pages: [1, 20],
    title: `Chapter ${activeChapter}`,
  };

  return (
    <header className="bg-slate-900/90 backdrop-blur-md border-b border-slate-800 sticky top-0 z-40 px-4 lg:px-6 py-3">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Left: Brand & Book Info */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20 text-white font-bold">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-tight text-white flex items-center gap-1.5">
                BookAssembler
                <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Pipeline v2.0
                </span>
              </h1>
            </div>
            <p className="text-xs text-slate-400 truncate max-w-xs sm:max-w-sm lg:max-w-md">
              {config.title}
            </p>
          </div>
        </div>

        {/* Middle: Chapter Picker */}
        <div className="flex items-center gap-2 bg-slate-950/70 border border-slate-800/80 rounded-xl px-3 py-1.5">
          <BookOpen className="w-4 h-4 text-blue-400" />
          <span className="text-xs text-slate-400 font-medium">Chapter:</span>
          <select
            value={activeChapter}
            onChange={(e) => onSelectChapter(parseInt(e.target.value, 10))}
            className="bg-transparent text-xs font-semibold text-white focus:outline-none cursor-pointer pr-1"
          >
            {Object.entries(config.chapters).map(([chNum, ch]) => (
              <option key={chNum} value={chNum} className="bg-slate-900 text-slate-100">
                Ch. {chNum}: {ch.title.length > 32 ? ch.title.substring(0, 32) + '...' : ch.title} (pp. {ch.pages[0]}-{ch.pages[1]})
              </option>
            ))}
          </select>
        </div>

        {/* Right: Action Buttons */}
        <div className="flex items-center flex-wrap gap-2">
          <button
            onClick={onOpenGlossary}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 transition"
            title="Glossary & Terminology"
          >
            <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
            <span className="hidden sm:inline">Glossary</span>
          </button>

          <button
            onClick={onOpenProfile}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 transition"
            title="Book Profile & ASM Mnemonics"
          >
            <Settings className="w-3.5 h-3.5 text-amber-400" />
            <span className="hidden sm:inline">Profile</span>
          </button>

          <button
            onClick={onOpenJobs}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 transition relative"
            title="pyjobkit Task Queue"
          >
            <Terminal className="w-3.5 h-3.5 text-indigo-400" />
            <span className="hidden sm:inline">Jobs</span>
            {jobCount > 0 && (
              <span className="w-4 h-4 rounded-full bg-blue-500 text-[10px] font-bold text-white flex items-center justify-center">
                {jobCount}
              </span>
            )}
          </button>

          <button
            onClick={onOpenAiAssist}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-gradient-to-r from-blue-600/30 to-purple-600/30 hover:from-blue-600/40 hover:to-purple-600/40 text-blue-200 border border-blue-500/30 transition"
            title="AI Pipeline Assistant"
          >
            <Sparkles className="w-3.5 h-3.5 text-blue-400 animate-pulse" />
            <span>AI Assist</span>
          </button>

          <button
            onClick={onRunFullPipeline}
            disabled={isRunningPipeline}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg shadow-md transition ${
              isRunningPipeline
                ? 'bg-blue-600/50 text-blue-200 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-500 text-white shadow-blue-500/20'
            }`}
          >
            {isRunningPipeline ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Running...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Run Pipeline</span>
              </>
            )}
          </button>
        </div>
      </div>
    </header>
  );
};
