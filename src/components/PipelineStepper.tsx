import React from 'react';
import {
  FileText,
  Search,
  ListTree,
  Image as ImageIcon,
  Languages,
  Wrench,
  CheckCircle,
  FileCode2,
  FileCheck,
  RotateCcw,
  Play,
  Clock,
  AlertTriangle,
} from 'lucide-react';
import { StageName, PipelineState } from '../types';

interface PipelineStepperProps {
  state: PipelineState;
  activeStage: StageName;
  onSelectStage: (stage: StageName) => void;
  onRunStage: (stage: StageName) => void;
  onResetStage: (stage: StageName) => void;
  isRunning: boolean;
}

const STAGE_CONFIG: {
  id: StageName;
  label: string;
  desc: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: 'extract', label: '1. Extract', desc: 'PDF text & layout blocks', icon: FileText },
  { id: 'detect', label: '2. Detect', desc: 'Book profile & mnemonics', icon: Search },
  { id: 'manifest', label: '3. Manifest', desc: 'Structure & elements inventory', icon: ListTree },
  { id: 'figures', label: '4. Figures', desc: 'TikZ vector generation', icon: ImageIcon },
  { id: 'translate', label: '5. Translate', desc: 'Multi-layer translation', icon: Languages },
  { id: 'autofix', label: '6. Autofix', desc: 'Code formatting & diff layer', icon: Wrench },
  { id: 'validate', label: '7. Validate', desc: '11-category quality report', icon: CheckCircle },
  { id: 'build', label: '8. Build', desc: 'LaTeX source generator', icon: FileCode2 },
  { id: 'compile', label: '9. Compile', desc: 'XeLaTeX PDF builder', icon: FileCheck },
];

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  state,
  activeStage,
  onSelectStage,
  onRunStage,
  onResetStage,
  isRunning,
}) => {
  return (
    <div className="bg-slate-900/70 border-b border-slate-800/80 px-4 py-3">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between gap-2 overflow-x-auto pb-1.5 scrollbar-thin">
          {STAGE_CONFIG.map((st, idx) => {
            const Icon = st.icon;
            const stageState = state.stages[st.id] || { status: 'pending' };
            const isActive = activeStage === st.id;
            const isDone = stageState.status === 'done';
            const isRunningStage = stageState.status === 'running';
            const isFailed = stageState.status === 'failed';

            let statusBg = 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700';
            if (isDone) {
              statusBg = isActive
                ? 'bg-emerald-950/40 border-emerald-500/80 text-emerald-300 ring-1 ring-emerald-500/50'
                : 'bg-emerald-950/20 border-emerald-700/40 text-emerald-400 hover:border-emerald-600/60';
            } else if (isRunningStage) {
              statusBg = 'bg-blue-950/40 border-blue-500 text-blue-300 animate-pulse ring-1 ring-blue-500';
            } else if (isFailed) {
              statusBg = 'bg-rose-950/40 border-rose-600 text-rose-300 ring-1 ring-rose-500/50';
            } else if (isActive) {
              statusBg = 'bg-slate-800 border-blue-500 text-white ring-1 ring-blue-500/50';
            }

            return (
              <div key={st.id} className="flex items-center shrink-0">
                <button
                  onClick={() => onSelectStage(st.id)}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-xl border text-left transition group ${statusBg}`}
                >
                  <div
                    className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-semibold ${
                      isDone
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : isRunningStage
                        ? 'bg-blue-500/20 text-blue-300'
                        : isFailed
                        ? 'bg-rose-500/20 text-rose-300'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {isDone ? (
                      <CheckCircle className="w-4 h-4 text-emerald-400" />
                    ) : isRunningStage ? (
                      <Clock className="w-4 h-4 text-blue-400 animate-spin" />
                    ) : isFailed ? (
                      <AlertTriangle className="w-4 h-4 text-rose-400" />
                    ) : (
                      <Icon className="w-4 h-4" />
                    )}
                  </div>
                  <div>
                    <div className="text-xs font-semibold flex items-center gap-1.5">
                      <span>{st.label}</span>
                    </div>
                    <div className="text-[10px] text-slate-400 truncate max-w-[110px]">
                      {st.desc}
                    </div>
                  </div>
                </button>

                {idx < STAGE_CONFIG.length - 1 && (
                  <div className="w-3 h-0.5 bg-slate-800 mx-1 shrink-0 hidden lg:block" />
                )}
              </div>
            );
          })}
        </div>

        {/* Active Stage Detail Action Bar */}
        <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-slate-200">
              Active Stage: {STAGE_CONFIG.find((s) => s.id === activeStage)?.label}
            </span>
            <span>•</span>
            <span className="capitalize text-slate-300">
              Status:{' '}
              <span
                className={`font-semibold ${
                  state.stages[activeStage]?.status === 'done'
                    ? 'text-emerald-400'
                    : state.stages[activeStage]?.status === 'running'
                    ? 'text-blue-400'
                    : state.stages[activeStage]?.status === 'failed'
                    ? 'text-rose-400'
                    : 'text-amber-400'
                }`}
              >
                {state.stages[activeStage]?.status || 'pending'}
              </span>
            </span>
            {state.stages[activeStage]?.finished && (
              <>
                <span>•</span>
                <span>
                  Finished:{' '}
                  {new Date(state.stages[activeStage]?.finished || 0).toLocaleTimeString()}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onResetStage(activeStage)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-[11px]"
              title="Reset state"
            >
              <RotateCcw className="w-3 h-3" />
              Reset
            </button>
            <button
              onClick={() => onRunStage(activeStage)}
              disabled={isRunning}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium transition text-[11px]"
            >
              <Play className="w-3 h-3 fill-current" />
              Run Stage
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
