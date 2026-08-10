import React, { useState, useEffect } from 'react';
import {
  Layers,
  FileText,
  HardDriveUpload,
  Activity,
  Network,
  Sparkles,
  ChevronRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import CleanWorkspace from './components/CleanWorkspace';
import DocumentDashboard from './components/DocumentDashboard';
import SEPSourcesDialog from './components/SEPSourcesDialog';
import KnowledgeGraphModal from './components/KnowledgeGraphModal';
import kaeApi from './api/client';
import { KAEJobEvent } from './types';

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<'workspace' | 'documents'>('workspace');
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isSepDialogOpen, setIsSepDialogOpen] = useState<boolean>(false);
  const [graphModalJobId, setGraphModalJobId] = useState<string | null>(null);
  const [isGraphModalOpen, setIsGraphModalOpen] = useState<boolean>(false);

  // Global PyJobKit SSE Stream Status
  const [globalJobStatus, setGlobalJobStatus] = useState<string>('pyjobkit Active');
  const [activeEventCount, setActiveEventCount] = useState<number>(0);

  useEffect(() => {
    const unsubscribe = kaeApi.subscribeToJobStream((event: KAEJobEvent) => {
      setActiveEventCount((prev) => prev + 1);
      if (event.event === 'job_started' || event.event === 'job_progress') {
        setGlobalJobStatus(`pyjobkit: ${event.job_type || 'processing'}`);
      } else if (event.event === 'job_completed') {
        setGlobalJobStatus('pyjobkit: Completed');
      } else if (event.event === 'job_failed') {
        setGlobalJobStatus('pyjobkit: Error');
      }
    });

    return () => {
      unsubscribe();
    };
  }, []);

  const handleOpenGraph = (jobId: string) => {
    setGraphModalJobId(jobId);
    setIsGraphModalOpen(true);
  };

  const handleOpenWorkspaceForJob = (jobId: string) => {
    setActiveJobId(jobId);
    setActiveView('workspace');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-cyan-500/30 selection:text-cyan-200">
      {/* Top Header Navigation */}
      <header className="h-16 bg-slate-900/90 border-b border-slate-800/80 px-6 flex items-center justify-between backdrop-blur-xl sticky top-0 z-40">
        {/* Brand & Logo */}
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-gradient-to-tr from-indigo-600 to-cyan-500 rounded-xl shadow-md shadow-indigo-950/50 text-white">
            <Zap className="w-5 h-5 fill-current" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-base text-white tracking-tight">KAE Platform</span>
              <span className="px-2 py-0.5 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[10px] font-mono font-medium rounded-full">
                Knowledge Assembly Engine
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Минималистичный контент-ориентированный интерфейс</p>
          </div>
        </div>

        {/* View Switching Tabs */}
        <nav className="flex items-center bg-slate-950/80 border border-slate-800 p-1 rounded-xl text-xs font-medium">
          <button
            onClick={() => setActiveView('workspace')}
            className={`px-4 py-2 rounded-lg flex items-center space-x-2 transition-all ${
              activeView === 'workspace'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Рабочая область (Workspace)</span>
          </button>

          <button
            onClick={() => setActiveView('documents')}
            className={`px-4 py-2 rounded-lg flex items-center space-x-2 transition-all ${
              activeView === 'documents'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Документы и Книги</span>
          </button>

          <button
            onClick={() => setIsSepDialogOpen(true)}
            className="px-4 py-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 flex items-center space-x-2 transition-all"
          >
            <HardDriveUpload className="w-3.5 h-3.5 text-indigo-400" />
            <span>Хранилища SEP</span>
          </button>
        </nav>

        {/* Right Status Badge */}
        <div className="flex items-center space-x-3 text-xs">
          <div className="flex items-center space-x-2 px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-xl font-mono text-[11px] text-slate-300">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            <span className="text-cyan-300 font-medium">{globalJobStatus}</span>
          </div>
        </div>
      </header>

      {/* Main Active View */}
      <main className="flex-1 overflow-hidden">
        {activeView === 'workspace' ? (
          <CleanWorkspace
            activeJobId={activeJobId}
            onJobCreated={(id) => setActiveJobId(id)}
          />
        ) : (
          <DocumentDashboard
            onOpenWorkspace={handleOpenWorkspaceForJob}
            onOpenGraph={handleOpenGraph}
          />
        )}
      </main>

      {/* Global Modals */}
      <SEPSourcesDialog
        isOpen={isSepDialogOpen}
        onClose={() => setIsSepDialogOpen(false)}
        onImportSuccess={(jobId) => handleOpenWorkspaceForJob(jobId)}
      />

      <KnowledgeGraphModal
        jobId={graphModalJobId}
        isOpen={isGraphModalOpen}
        onClose={() => setIsGraphModalOpen(false)}
      />
    </div>
  );
};

export default App;
