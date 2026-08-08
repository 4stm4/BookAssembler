import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  Percent,
  Sparkles,
  RefreshCw,
  ArrowUpRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { ValidationReport } from '../types';

interface ValidationDashboardProps {
  report: ValidationReport;
  onRefresh: () => void;
  onAutoFixAll: () => void;
  onJumpToPage: (page: number) => void;
  isFixing: boolean;
}

const CATEGORY_TITLES: Record<string, { title: string; desc: string }> = {
  untranslated: { title: 'Непереведенные маркеры', desc: 'Слова EXAMPLE, Solution, Figure в основном тексте' },
  corrupt_text: { title: 'Поврежденный текст / OCR', desc: 'Символы U+FFFD, искаженные таблицы кодировок' },
  problematic_unicode: { title: 'Проблемный Unicode', desc: 'Невидимые нулевые пробелы, лишние BOM' },
  missing_tables: { title: 'Пропущенные таблицы', desc: 'Сводные таблицы инструкций без LaTeX tabular' },
  broken_tables: { title: 'Искаженные таблицы', desc: 'Несовпадение колонок |l|c|r| в таблицах' },
  tikz_duplicates: { title: 'Дубликаты TikZ', desc: 'Таблица, дублирующая рядом стоящий рисунок' },
  numbered_lists: { title: 'Нумерованные списки', desc: 'Списки, не обернутые в \\begin{enumerate}' },
  unformatted_code: { title: 'Неотформатированный код', desc: 'Мнемоники MOV, ADD без моноширинного шрифта' },
  debug_blocks: { title: 'DEBUG-сессии', desc: 'Сессии MS-DOS без \\begin{lstlisting}[style=debug]' },
  missing_examples: { title: 'Пропущенные примеры', desc: 'Примеры без \\begin{examplebox}' },
  latex_formatting: { title: 'Ошибки LaTeX', desc: 'Спецсимволы %, _, $, & без экранирования' },
};

export const ValidationDashboard: React.FC<ValidationDashboardProps> = ({
  report,
  onRefresh,
  onAutoFixAll,
  onJumpToPage,
  isFixing,
}) => {
  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 p-4 lg:p-6 overflow-y-auto space-y-6">
      {/* Top Banner: Scorecard */}
      <div className="bg-gradient-to-br from-slate-900 via-slate-900 to-slate-950 border border-slate-800 rounded-3xl p-6 shadow-2xl relative overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div
              className={`w-14 h-14 rounded-2xl flex items-center justify-center text-white shadow-xl ${
                report.errors === 0
                  ? 'bg-emerald-600 shadow-emerald-500/20'
                  : 'bg-amber-600 shadow-amber-500/20'
              }`}
            >
              {report.errors === 0 ? (
                <ShieldCheck className="w-8 h-8" />
              ) : (
                <AlertTriangle className="w-8 h-8" />
              )}
            </div>
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                11-Category Quality Verification Scorecard
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full font-bold uppercase ${
                    report.errors === 0
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  }`}
                >
                  {report.errors === 0 ? 'Passed ✅' : 'Warnings Found'}
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Evaluated {report.pages.found} pages in chapter {report.chapter} across 11 architectural validation rules.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onRefresh}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Re-check</span>
            </button>
            <button
              onClick={onAutoFixAll}
              disabled={isFixing}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold shadow-lg shadow-emerald-500/20 transition"
            >
              {isFixing ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Zap className="w-3.5 h-3.5" />
              )}
              <span>Auto-Fix All Warnings</span>
            </button>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-6 border-t border-slate-800/80">
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Critical Errors
            </div>
            <div className="text-2xl font-bold text-rose-400 mt-1">{report.errors}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Warnings
            </div>
            <div className="text-2xl font-bold text-amber-400 mt-1">{report.warnings}</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Russian Cyrillic %
            </div>
            <div className="text-2xl font-bold text-emerald-400 mt-1">{report.russian_pct}%</div>
          </div>
          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-2xl">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              English Code/Mnemonics %
            </div>
            <div className="text-2xl font-bold text-blue-400 mt-1">{report.english_pct}%</div>
          </div>
        </div>
      </div>

      {/* 11 Rules Category Cards */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 px-1">
          Detailed Category Audits (11 Categories)
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(CATEGORY_TITLES).map(([catKey, info]) => {
            const issues = report.categories[catKey] || [];
            const hasIssues = issues.length > 0;
            const hasErrors = issues.some((i) => i.severity === 'error');

            return (
              <div
                key={catKey}
                className={`p-4 rounded-2xl border transition flex flex-col justify-between ${
                  hasErrors
                    ? 'bg-rose-950/20 border-rose-800/40 text-rose-200'
                    : hasIssues
                    ? 'bg-amber-950/20 border-amber-800/40 text-amber-200'
                    : 'bg-slate-900/60 border-slate-800/80 text-slate-300'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold">{info.title}</span>
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        hasErrors
                          ? 'bg-rose-500/20 text-rose-300'
                          : hasIssues
                          ? 'bg-amber-500/20 text-amber-300'
                          : 'bg-emerald-500/20 text-emerald-300'
                      }`}
                    >
                      {issues.length === 0 ? 'Clean' : `${issues.length} issue(s)`}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1">{info.desc}</p>
                </div>

                {hasIssues && (
                  <div className="mt-3 pt-3 border-t border-slate-800/60 space-y-1.5">
                    {issues.slice(0, 2).map((issue, idx) => (
                      <div
                        key={idx}
                        className="text-[11px] flex items-center justify-between gap-1 text-slate-300 bg-slate-950/50 p-1.5 rounded-lg"
                      >
                        <span className="truncate">{issue.message}</span>
                        {issue.page && (
                          <button
                            onClick={() => onJumpToPage(issue.page!)}
                            className="shrink-0 text-[10px] font-bold text-blue-400 hover:text-blue-300 underline flex items-center gap-0.5"
                          >
                            p.{issue.page} <ArrowUpRight className="w-2.5 h-2.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
