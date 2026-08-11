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
import { TranslationStudio } from './components/TranslationStudio';
import kaeApi from './api/client';
import { KAEJobEvent, TranslationPage, Glossary } from './types';

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<'workspace' | 'documents' | 'translation'>('workspace');
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isSepDialogOpen, setIsSepDialogOpen] = useState<boolean>(false);
  const [graphModalJobId, setGraphModalJobId] = useState<string | null>(null);
  const [isGraphModalOpen, setIsGraphModalOpen] = useState<boolean>(false);

  // Translation state
  const [translationPages, setTranslationPages] = useState<Record<number, TranslationPage>>({});
  const [currentTranslationPage, setCurrentTranslationPage] = useState<number>(1);
  const [isAiTranslating, setIsAiTranslating] = useState<boolean>(false);
  const emptyGlossary: Glossary = { terms: {}, keep_as_is: {}, formatting_rules: {}, suggestions: {} };

  // Load KRM pages for translation when activeJobId changes
  useEffect(() => {
    if (activeJobId) {
      kaeApi.getJobResult(activeJobId).then((result: any) => {
        const pages: Record<number, TranslationPage> = {};
        (result.containers || []).forEach((container: any, idx: number) => {
          const pageNum = idx + 1;
          const textParts: string[] = [];
          const collectText = (node: any) => {
            if (node.text) textParts.push(node.text);
            if (node.children) node.children.forEach(collectText);
          };
          collectText(container);
          pages[pageNum] = {
            page_number: pageNum,
            source_text: textParts.join('\n'),
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
        });
        setTranslationPages(pages);
        setCurrentTranslationPage(1);
      }).catch(() => {});
    }
  }, [activeJobId]);

  const handleTranslateAi = async (pg: number, sourceText: string) => {
    if (!activeJobId) return;
    setIsAiTranslating(true);
    try {
      const result = await kaeApi.translatePage(activeJobId, pg, sourceText);
      setTranslationPages((prev) => ({
        ...prev,
        [pg]: { ...prev[pg], original_translation: result.translated_text, final_translation: result.translated_text },
      }));
    } finally {
      setIsAiTranslating(false);
    }
  };

  const handleSaveManualTranslation = (pg: number, text: string) => {
    setTranslationPages((prev) => ({
      ...prev,
      [pg]: { ...prev[pg], manual_fixed_translation: text, final_translation: text },
    }));
  };

  // Global PyJobKit SSE Stream Status
  const [globalJobStatus, setGlobalJobStatus] = useState<string>('Готов');
  const [isJobRunning, setIsJobRunning] = useState<boolean>(false);
  const [eventLog, setEventLog] = useState<Array<{ time: string; text: string }>>([]);
  const [isEventLogOpen, setIsEventLogOpen] = useState<boolean>(false);

  useEffect(() => {
    const unsubscribe = kaeApi.subscribeToJobStream((event: KAEJobEvent) => {
      const time = new Date().toLocaleTimeString('ru-RU');
      if (event.event === 'job_started' || event.event === 'job_progress') {
        const label = event.job_type || 'обработка';
        setGlobalJobStatus(label);
        setIsJobRunning(true);
        setEventLog((prev) => [{ time, text: `▶ ${label}` }, ...prev].slice(0, 50));
      } else if (event.event === 'job_completed') {
        setGlobalJobStatus('Завершено');
        setIsJobRunning(false);
        setEventLog((prev) => [{ time, text: '✓ Завершено' }, ...prev].slice(0, 50));
        setTimeout(() => setGlobalJobStatus('Готов'), 3000);
      } else if (event.event === 'job_failed') {
        setGlobalJobStatus('Ошибка');
        setIsJobRunning(false);
        setEventLog((prev) => [{ time, text: '✗ Ошибка' }, ...prev].slice(0, 50));
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
            onClick={() => setActiveView('translation')}
            className={`px-4 py-2 rounded-lg flex items-center space-x-2 transition-all ${
              activeView === 'translation'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Перевод</span>
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
        <div className="flex items-center space-x-3 text-xs relative">
          <button
            onClick={() => setIsEventLogOpen(!isEventLogOpen)}
            className="flex items-center space-x-2 px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-xl font-mono text-[11px] text-slate-300 hover:border-slate-700 transition-colors"
          >
            <span className={`w-2 h-2 rounded-full ${isJobRunning ? 'bg-cyan-400 animate-pulse' : 'bg-slate-600'}`} />
            <span className={isJobRunning ? 'text-cyan-300 font-medium' : 'text-slate-400'}>{globalJobStatus}</span>
            {eventLog.length > 0 && (
              <span className="text-slate-500">{eventLog.length}</span>
            )}
          </button>

          {isEventLogOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 bg-slate-900 border border-slate-800 rounded-xl shadow-2xl overflow-hidden z-50">
              <div className="px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
                <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">Лог событий</span>
                <button onClick={() => setIsEventLogOpen(false)} className="text-slate-500 hover:text-white text-xs">✕</button>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {eventLog.length === 0 ? (
                  <div className="px-4 py-6 text-center text-slate-500 text-[11px]">Нет событий</div>
                ) : (
                  eventLog.map((entry, idx) => (
                    <div key={idx} className="px-4 py-2 border-b border-slate-800/50 flex items-center space-x-3 text-[11px]">
                      <span className="text-slate-500 font-mono shrink-0">{entry.time}</span>
                      <span className="text-slate-300">{entry.text}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Main Active View */}
      <main className="flex-1 overflow-hidden">
        {activeView === 'workspace' ? (
          <CleanWorkspace
            activeJobId={activeJobId}
            onJobCreated={(id) => setActiveJobId(id)}
          />
        ) : activeView === 'translation' ? (
          activeJobId ? (
            <TranslationStudio
              pages={translationPages}
              currentPage={currentTranslationPage}
              onSelectPage={setCurrentTranslationPage}
              onSaveManualTranslation={handleSaveManualTranslation}
              onTranslateAi={handleTranslateAi}
              glossary={emptyGlossary}
              isAiTranslating={isAiTranslating}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-500">
              <p>Выберите документ для перевода — импортируйте PDF через SEP или откройте из списка документов</p>
            </div>
          )
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
