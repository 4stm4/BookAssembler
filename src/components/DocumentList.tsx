import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  FileText,
  Search,
  Filter,
  CheckCircle2,
  Clock,
  AlertTriangle,
  HardDriveUpload,
  ChevronRight,
  BarChart2,
  Plus,
  Loader2,
  XCircle,
  Trash2,
} from 'lucide-react';
import kaeApi from '../api/client';
import SEPSourcesDialog from './SEPSourcesDialog';

interface DocumentListProps {
  onOpenWorkspace: (jobId: string) => void;
  onOpenGraph?: (jobId: string) => void;
}

interface DocItem {
  job_id: string;
  title: string;
  source_uri: string;
  status: string;
  created_at: string;
  updated_at: string;
  node_count: number;
  page_count: number;
  progress?: { step: number; total: number; stage: string; error?: string };
}

export const DocumentList: React.FC<DocumentListProps> = ({
  onOpenWorkspace,
  onOpenGraph,
}) => {
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [isSepDialogOpen, setIsSepDialogOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await kaeApi.listDocuments();
      const items: DocItem[] = docs.map((d: any) => ({
        job_id: d.job_id,
        title: d.title || 'Без названия',
        source_uri: d.source_uri || '',
        status: d.status || 'UNKNOWN',
        created_at: d.created_at || '',
        updated_at: d.updated_at || '',
        node_count: d.node_count || 0,
        page_count: d.page_count || 0,
      }));

      const runningJobs = items.filter(d => d.status === 'RUNNING');
      for (const job of runningJobs) {
        try {
          const prog = await kaeApi.getJobProgress(job.job_id);
          job.progress = { step: prog.step, total: prog.total, stage: prog.stage, error: prog.error };
          job.status = prog.status;
        } catch {}
      }

      setDocuments(items);
    } catch (err) {
      console.error('Failed to load documents:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    const hasRunning = documents.some(d => d.status === 'RUNNING');
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(loadDocuments, 3000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [documents, loadDocuments]);

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch = doc.title.toLowerCase().includes(searchQuery.toLowerCase()) || doc.job_id.includes(searchQuery);
    const matchesStatus = statusFilter === 'ALL' || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (doc: DocItem) => {
    switch (doc.status) {
      case 'COMPLETED':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
            Завершено
          </span>
        );
      case 'WAITING_FOR_HUMAN':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-3.5 h-3.5 mr-1" />
            Требует HITL
          </span>
        );
      case 'RUNNING':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            {doc.progress?.stage || 'Обработка...'}
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <XCircle className="w-3.5 h-3.5 mr-1" />
            Ошибка
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
            <Clock className="w-3.5 h-3.5 mr-1" />
            Ожидание
          </span>
        );
    }
  };

  const handleImportSuccess = (newJobId: string) => {
    setDocuments(prev => [{
      job_id: newJobId,
      title: 'Импорт...',
      source_uri: '',
      status: 'RUNNING',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      node_count: 0,
      page_count: 0,
      progress: { step: 0, total: 10, stage: 'Запуск...' },
    }, ...prev]);
    loadDocuments();
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Документы KAE
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            {documents.length} документ{documents.length !== 1 ? 'ов' : ''} обработано
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={() => setIsSepDialogOpen(true)}
            className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-xl font-medium text-xs flex items-center space-x-2 transition-all shadow-sm"
          >
            <HardDriveUpload className="w-4 h-4 text-indigo-400" />
            <span>Импорт из SEP</span>
          </button>

          <button
            onClick={() => onOpenWorkspace('new-job')}
            className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white rounded-xl font-medium text-xs flex items-center space-x-2 transition-all shadow-md shadow-indigo-950/50"
          >
            <Plus className="w-4 h-4" />
            <span>Новая сборка</span>
          </button>
        </div>
      </div>

      {/* Filter and Search */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Поиск по названию или Job ID..."
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/60"
          />
        </div>

        <div className="flex items-center space-x-2 w-full sm:w-auto">
          <Filter className="w-4 h-4 text-slate-500" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-300 focus:outline-none focus:border-indigo-500"
          >
            <option value="ALL">Все статусы</option>
            <option value="COMPLETED">Завершенные</option>
            <option value="RUNNING">Выполняются</option>
            <option value="FAILED">С ошибкой</option>
          </select>
        </div>
      </div>

      {/* Document Grid */}
      {isLoading ? (
        <div className="py-16 text-center">
          <Loader2 className="w-6 h-6 animate-spin text-indigo-400 mx-auto mb-2" />
          <p className="text-xs text-slate-500">Загрузка документов...</p>
        </div>
      ) : filteredDocs.length === 0 ? (
        <div className="py-16 text-center">
          <FileText className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <p className="text-sm text-slate-400">
            {documents.length === 0 ? 'Нет документов. Импортируйте PDF через SEP.' : 'Ничего не найдено'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {filteredDocs.map((doc) => (
            <div
              key={doc.job_id}
              className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 hover:border-slate-700 transition-all group"
            >
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-start space-x-4 min-w-0">
                  <div className={`p-3 rounded-xl shrink-0 ${
                    doc.status === 'RUNNING'
                      ? 'bg-cyan-500/10 border border-cyan-500/20 text-cyan-400'
                      : doc.status === 'FAILED'
                      ? 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
                      : 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-400'
                  }`}>
                    {doc.status === 'RUNNING' ? (
                      <Loader2 className="w-6 h-6 animate-spin" />
                    ) : (
                      <FileText className="w-6 h-6" />
                    )}
                  </div>

                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center space-x-3 flex-wrap gap-y-1">
                      <h3 className="font-semibold text-white text-sm truncate max-w-md">{doc.title}</h3>
                      {getStatusBadge(doc)}
                    </div>

                    <div className="flex items-center space-x-3 text-xs text-slate-500">
                      {doc.page_count > 0 && <span>{doc.page_count} стр.</span>}
                      {doc.node_count > 0 && <span>• {doc.node_count} узлов</span>}
                      <span>• {doc.job_id.slice(0, 8)}…</span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center space-x-2 shrink-0">
                  {doc.status === 'COMPLETED' && onOpenGraph && (
                    <button
                      onClick={() => onOpenGraph(doc.job_id)}
                      className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-medium flex items-center space-x-1.5 transition-colors border border-slate-700/60"
                    >
                      <BarChart2 className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Граф</span>
                    </button>
                  )}

                  <button
                    onClick={() => onOpenWorkspace(doc.job_id)}
                    disabled={doc.status === 'RUNNING'}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white rounded-xl text-xs font-medium flex items-center space-x-1.5 transition-all shadow-md shadow-indigo-950/40 disabled:shadow-none"
                  >
                    <span>{doc.status === 'RUNNING' ? 'Обработка...' : 'Открыть'}</span>
                    {doc.status !== 'RUNNING' && <ChevronRight className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={async () => {
                      if (confirm(`Удалить "${doc.title}"?`)) {
                        await kaeApi.deleteJob(doc.job_id);
                        setDocuments((prev) => prev.filter((d) => d.job_id !== doc.job_id));
                      }
                    }}
                    className="px-2 py-2 bg-red-900/30 hover:bg-red-800/50 text-red-400 hover:text-red-300 rounded-xl text-xs transition-colors border border-red-800/30"
                    title="Удалить документ"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Progress bar for RUNNING jobs */}
              {doc.status === 'RUNNING' && doc.progress && (
                <div className="mt-3 pt-3 border-t border-slate-800/60">
                  <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
                    <span>{doc.progress.stage}</span>
                    <span>{doc.progress.step}/{doc.progress.total}</span>
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-cyan-500 rounded-full transition-all duration-700 ease-out"
                      style={{ width: `${Math.max(3, (doc.progress.step / doc.progress.total) * 100)}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Error message for FAILED jobs */}
              {doc.status === 'FAILED' && doc.progress?.error && (
                <div className="mt-3 pt-3 border-t border-slate-800/60">
                  <p className="text-xs text-rose-400 font-mono truncate">{doc.progress.error}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <SEPSourcesDialog
        isOpen={isSepDialogOpen}
        onClose={() => setIsSepDialogOpen(false)}
        onImportSuccess={handleImportSuccess}
      />
    </div>
  );
};

export default DocumentList;
