import React, { useState } from 'react';
import {
  FileCode2,
  Download,
  Copy,
  CheckCircle,
  Play,
  FileCheck,
  Terminal,
  RefreshCw,
  Eye,
} from 'lucide-react';

interface LatexBuildViewProps {
  chapterLatex: string;
  masterLatex: string;
  filename: string;
  masterFilename: string;
  chapter: number;
  onCompileXeLatex: () => Promise<void>;
  isCompiling: boolean;
  compilationLogs: string[];
  pdfReady: boolean;
}

export const LatexBuildView: React.FC<LatexBuildViewProps> = ({
  chapterLatex,
  masterLatex,
  filename,
  masterFilename,
  chapter,
  onCompileXeLatex,
  isCompiling,
  compilationLogs,
  pdfReady,
}) => {
  const [activeTab, setActiveTab] = useState<'chapter' | 'master' | 'logs'>('chapter');
  const [copied, setCopied] = useState(false);

  const currentCode = activeTab === 'master' ? masterLatex : chapterLatex;

  const handleCopy = () => {
    navigator.clipboard.writeText(currentCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([currentCode], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = activeTab === 'master' ? masterFilename : filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100">
      {/* Top Header & Actions */}
      <div className="p-4 bg-slate-900/80 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-1 flex text-xs">
            <button
              onClick={() => setActiveTab('chapter')}
              className={`px-3 py-1.5 rounded-lg font-mono font-medium transition ${
                activeTab === 'chapter'
                  ? 'bg-blue-600 text-white font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {filename}
            </button>
            <button
              onClick={() => setActiveTab('master')}
              className={`px-3 py-1.5 rounded-lg font-mono font-medium transition ${
                activeTab === 'master'
                  ? 'bg-blue-600 text-white font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {masterFilename}
            </button>
            <button
              onClick={() => setActiveTab('logs')}
              className={`px-3 py-1.5 rounded-lg font-mono font-medium transition flex items-center gap-1.5 ${
                activeTab === 'logs'
                  ? 'bg-indigo-600 text-white font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Build Logs</span>
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition"
          >
            {copied ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied!' : 'Copy TeX'}</span>
          </button>

          <button
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download .tex</span>
          </button>

          <button
            onClick={onCompileXeLatex}
            disabled={isCompiling}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition"
          >
            {isCompiling ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>Compile XeLaTeX</span>
          </button>
        </div>
      </div>

      {/* Main Content: LaTeX Code or XeLaTeX Logs */}
      <div className="flex-1 p-4 overflow-y-auto">
        {activeTab === 'logs' ? (
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 font-mono text-xs text-slate-300 space-y-1 overflow-x-auto shadow-2xl">
            <div className="text-emerald-400 font-bold mb-3 flex items-center gap-2">
              <Terminal className="w-4 h-4" />
              XeLaTeX Engine Output Stream &amp; Font Metrics:
            </div>
            {compilationLogs.map((line, idx) => (
              <div
                key={idx}
                className={
                  line.includes('SUCCEEDED')
                    ? 'text-emerald-400 font-bold bg-emerald-950/40 p-1.5 rounded'
                    : line.includes('error') || line.includes('Error')
                    ? 'text-rose-400 font-bold'
                    : 'text-slate-300'
                }
              >
                {line}
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-4 font-mono text-xs text-blue-200/90 whitespace-pre-wrap leading-relaxed overflow-x-auto selection:bg-blue-600/40">
            {currentCode}
          </div>
        )}
      </div>
    </div>
  );
};
