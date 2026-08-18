import React, { useState } from 'react';
import {
  Languages,
  Sparkles,
  Edit3,
  CheckCircle2,
  AlertCircle,
  FileCode,
  Layers,
  Save,
  ArrowRight,
  Eye,
  RefreshCw,
  Terminal,
  Code2,
} from 'lucide-react';
import { TranslationPage, Glossary } from '../types';

interface TranslationStudioProps {
  pages: Record<number, TranslationPage>;
  currentPage: number;
  onSelectPage: (pg: number) => void;
  onSaveManualTranslation: (pg: number, text: string) => void;
  onTranslateAi: (pg: number, sourceText: string) => Promise<void>;
  onAssembleBook?: () => Promise<void>;
  glossary: Glossary;
  isAiTranslating: boolean;
  isAssembling?: boolean;
  assembleResult?: { status: string; download_url?: string } | null;
}

export const TranslationStudio: React.FC<TranslationStudioProps> = ({
  pages,
  currentPage,
  onSelectPage,
  onSaveManualTranslation,
  onTranslateAi,
  onAssembleBook,
  glossary,
  isAiTranslating,
  isAssembling,
  assembleResult,
}) => {
  const pageList = Object.values(pages).sort((a, b) => a.page_number - b.page_number);
  const activePage = pages[currentPage] || pageList[0] || {
    page_number: currentPage,
    source_text: '',
    original_translation: '',
    autofix_translation: '',
    manual_fixed_translation: '',
    final_translation: '',
    issues: [],
    is_valid: true,
    has_code: false,
    has_table: false,
    has_debug_session: false,
  };

  const [activeLayer, setActiveLayer] = useState<'merged' | 'manual' | 'autofix' | 'original'>('merged');
  const [editText, setEditText] = useState(
    activePage.manual_fixed_translation || activePage.final_translation || activePage.original_translation || ''
  );
  const [isSaved, setIsSaved] = useState(false);

  // Sync state when page changes
  React.useEffect(() => {
    setEditText(
      activePage.manual_fixed_translation ||
        activePage.final_translation ||
        activePage.original_translation ||
        ''
    );
    setIsSaved(false);
  }, [currentPage, activePage]);

  const handleSave = () => {
    onSaveManualTranslation(currentPage, editText);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const handleAutoWrapDebug = () => {
    const wrapped = editText.replace(
      /(C:\\DOS>DEBUG[\s\S]*?-q)/g,
      '```\n$1\n```'
    );
    setEditText(wrapped);
    onSaveManualTranslation(currentPage, wrapped);
  };

  const handleApplySubscript = () => {
    const fixed = editText
      .replace(/\[1000H\]/g, '[1000H]')
      .replace(/PA =/g, 'PA₁₆ =')
      .replace(/1010b/gi, '1010₂');
    setEditText(fixed);
    onSaveManualTranslation(currentPage, fixed);
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100">
      {/* Top Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 bg-slate-900/80 border-b border-slate-800">
        {/* Page selector pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-full lg:max-w-2xl">
          <span className="text-xs font-semibold text-slate-400 shrink-0">Pages:</span>
          {pageList.map((p) => {
            const isSelected = p.page_number === currentPage;
            const hasManual = !!p.manual_fixed_translation;
            return (
              <button
                key={p.page_number}
                onClick={() => onSelectPage(p.page_number)}
                className={`px-2.5 py-1 rounded-lg text-xs font-mono font-medium shrink-0 transition flex items-center gap-1 ${
                  isSelected
                    ? 'bg-blue-600 text-white shadow-md shadow-blue-500/30 font-bold'
                    : 'bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700/50'
                }`}
              >
                <span>p.{p.page_number}</span>
                {hasManual && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
                {p.has_debug_session && <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />}
              </button>
            );
          })}
        </div>

        {/* Translation Actions */}
        <div className="flex items-center gap-2">
          {/* Layer switcher */}
          <div className="bg-slate-950 border border-slate-800 rounded-lg p-0.5 flex text-xs">
            <button
              onClick={() => setActiveLayer('merged')}
              className={`px-2 py-1 rounded ${
                activeLayer === 'merged' ? 'bg-blue-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Merged
            </button>
            <button
              onClick={() => setActiveLayer('manual')}
              className={`px-2 py-1 rounded ${
                activeLayer === 'manual' ? 'bg-amber-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Manual Fix
            </button>
            <button
              onClick={() => setActiveLayer('original')}
              className={`px-2 py-1 rounded ${
                activeLayer === 'original' ? 'bg-slate-800 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Original
            </button>
          </div>

          <button
            onClick={() => onTranslateAi(currentPage, activePage.source_text)}
            disabled={isAiTranslating}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md shadow-blue-500/20 transition"
          >
            {isAiTranslating ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            <span>Translate with AI</span>
          </button>

          <button
            onClick={handleSave}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition shadow-md shadow-emerald-500/20"
          >
            <Save className="w-3.5 h-3.5" />
            <span>{isSaved ? 'Saved!' : 'Save Page'}</span>
          </button>

          {onAssembleBook && (
            <button
              onClick={onAssembleBook}
              disabled={isAssembling}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white text-xs font-semibold transition shadow-md shadow-amber-500/20"
            >
              {isAssembling ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Layers className="w-3.5 h-3.5" />
              )}
              <span>{isAssembling ? 'Сборка…' : 'Собрать книгу'}</span>
            </button>
          )}
          {assembleResult?.download_url && (
            <a
              href={assembleResult.download_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold hover:bg-emerald-600/30 transition"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Скачать PDF
            </a>
          )}
        </div>
      </div>

      {/* Main Split View: Source PDF Extract vs 3-Layer Translation & Editor */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-4 flex-1 overflow-y-auto">
        {/* Left Column: English Extracted Text & Glossary Hints */}
        <div className="flex flex-col bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileCode className="w-4 h-4 text-blue-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                Source PDF Text (Page {currentPage})
              </span>
            </div>
            <div className="flex items-center gap-2">
              {activePage.has_table && (
                <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-semibold">
                  Table detected
                </span>
              )}
              {activePage.has_debug_session && (
                <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 text-[10px] font-semibold">
                  DEBUG session
                </span>
              )}
            </div>
          </div>

          <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap selection:bg-blue-600/40">
            {activePage.source_text || '// Нет извлеченного текста для данной страницы'}
          </div>

          {/* Quick Glossary Inspector */}
          <div className="p-3 bg-slate-950/70 border-t border-slate-800/80 text-xs">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Languages className="w-3.5 h-3.5 text-emerald-400" />
              Active Glossary Matches on this Page:
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(glossary.terms)
                .filter(([en]) => activePage.source_text.toLowerCase().includes(en.toLowerCase()))
                .slice(0, 8)
                .map(([en, data]) => (
                  <span
                    key={en}
                    className="px-2 py-1 rounded bg-slate-800/80 text-slate-200 border border-slate-700/60 flex items-center gap-1 text-[11px]"
                  >
                    <span className="font-semibold text-blue-300">{en}</span>
                    <ArrowRight className="w-3 h-3 text-slate-500" />
                    <span className="text-emerald-300">{data.translation}</span>
                  </span>
                ))}
            </div>
          </div>
        </div>

        {/* Right Column: Russian Translation Layer & Live Editor */}
        <div className="flex flex-col bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Edit3 className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                Target Translation (RU) — {activeLayer.toUpperCase()}
              </span>
            </div>

            {/* Quick formatting buttons */}
            <div className="flex items-center gap-1.5">
              {activePage.has_debug_session && (
                <button
                  onClick={handleAutoWrapDebug}
                  className="px-2 py-1 rounded bg-purple-950/60 hover:bg-purple-900/80 text-purple-300 border border-purple-800/60 text-[11px] font-medium flex items-center gap-1"
                >
                  <Terminal className="w-3 h-3" />
                  Wrap DEBUG
                </button>
              )}
              <button
                onClick={handleApplySubscript}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-[11px] font-medium flex items-center gap-1"
              >
                <Code2 className="w-3 h-3" />
                Subscripts
              </button>
            </div>
          </div>

          <div className="flex-1 p-2 flex flex-col">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              placeholder="Введите или отредактируйте перевод..."
              className="w-full flex-1 p-3 bg-slate-950/80 border border-slate-800 rounded-xl text-xs font-mono text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none leading-relaxed"
            />
          </div>

          {/* Validation Status Footer */}
          <div className="px-4 py-2.5 bg-slate-950/90 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
            <div className="flex items-center gap-2">
              {activePage.is_valid ? (
                <span className="flex items-center gap-1 text-emerald-400 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Validation Passed
                </span>
              ) : (
                <span className="flex items-center gap-1 text-amber-400 font-medium">
                  <AlertCircle className="w-3.5 h-3.5" />
                  {activePage.issues.length} Warning(s)
                </span>
              )}
            </div>
            <div className="text-[11px] text-slate-500 font-mono">
              Char count: {editText.length} • Lines: {editText.split('\n').length}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
