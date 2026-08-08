import React from 'react';
import {
  Terminal,
  Play,
  CheckCircle,
  Clock,
  AlertOctagon,
  Trash2,
  X,
  RefreshCw,
  Layers,
} from 'lucide-react';
import { JobTask } from '../types';

interface JobsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  jobs: JobTask[];
  onRunWorker: () => Promise<void>;
  onCancelJob: (jobId: string) => void;
  isRunningWorker: boolean;
}

export const JobsDrawer: React.FC<JobsDrawerProps> = ({
  isOpen,
  onClose,
  jobs,
  onRunWorker,
  onCancelJob,
  isRunningWorker,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-end">
      <div className="bg-slate-900 border-l border-slate-800 w-full max-w-xl h-full flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-right duration-300">
        {/* Header */}
        <div className="p-4 bg-slate-950/90 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                pyjobkit Task Queue
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                  {jobs.length} jobs
                </span>
              </h2>
              <p className="text-[11px] text-slate-400">
                Idempotent background executors with SQLite task backend.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onRunWorker}
              disabled={isRunningWorker}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-indigo-500/20 transition"
            >
              {isRunningWorker ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5 fill-current" />
              )}
              <span>Run Worker</span>
            </button>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Jobs List */}
        <div className="flex-1 p-4 overflow-y-auto space-y-3">
          {jobs.length === 0 ? (
            <div className="text-center py-12 text-slate-500 text-xs">
              No active or queued jobs in database.
            </div>
          ) : (
            jobs.map((job) => {
              const isCompleted = job.status === 'completed';
              const isRunning = job.status === 'running';
              const isFailed = job.status === 'failed';

              return (
                <div
                  key={job.id}
                  className="p-4 bg-slate-950/70 border border-slate-800/80 rounded-2xl space-y-2.5 text-xs shadow-lg"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-6 h-6 rounded-lg flex items-center justify-center text-xs ${
                          isCompleted
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : isRunning
                            ? 'bg-blue-500/20 text-blue-400'
                            : isFailed
                            ? 'bg-rose-500/20 text-rose-400'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {isCompleted ? (
                          <CheckCircle className="w-3.5 h-3.5" />
                        ) : isRunning ? (
                          <Clock className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Terminal className="w-3.5 h-3.5" />
                        )}
                      </span>
                      <span className="font-bold text-white font-mono">{job.kind}</span>
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-mono">
                        Ch. {job.chapter}
                      </span>
                    </div>

                    <button
                      onClick={() => onCancelJob(job.id)}
                      className="text-slate-500 hover:text-rose-400 p-1 transition"
                      title="Cancel/delete job"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <div className="text-[11px] text-slate-400 font-mono bg-slate-900/60 p-2 rounded-lg truncate">
                    key: {job.idempotency_key}
                  </div>

                  {/* Logs */}
                  <div className="bg-slate-950 p-2.5 rounded-xl border border-slate-900 font-mono text-[11px] text-slate-300 space-y-1">
                    {job.logs.map((log, idx) => (
                      <div key={idx} className="flex items-start gap-1.5">
                        <span className="text-slate-600">›</span>
                        <span>{log}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
