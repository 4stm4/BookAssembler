import React, { useState, useEffect } from 'react';
import {
  FileText,
  Search,
  Filter,
  Play,
  CheckCircle2,
  AlertTriangle,
  HardDriveUpload,
  Upload,
  Sparkles,
  ChevronRight,
  Plus,
  BarChart2,
  Clock,
  RefreshCw,
} from 'lucide-react';
import { KAEDocumentItem } from '../types';
import SEPSourcesDialog from './SEPSourcesDialog';

interface DocumentDashboardProps {
  onOpenWorkspace: (jobId: string) => void;
  onOpenGraph?: (jobId: string) => void;
}

export const DocumentDashboard: React.FC<DocumentDashboardProps> = ({
  onOpenWorkspace,
  onOpenGraph,
}) => {
  const [documents, setDocuments] = useState<KAEDocumentItem[]>([]);

  useEffect(() => {
    const fetchDocs = async () => {
      try {
        const res = await fetch('/api/v1/documents');
        if (res.ok) {
          const data = await res.json();
          setDocuments(data.map((d: any) => ({
            job_id: d.job_id,
            title: d.title || 'Untitled',
            source_uri: d.source_uri || '',
            status: d.status || 'UNKNOWN',
            progress: d.status === 'COMPLETED' ? 1.0 : 0,
            created_at: d.created_at || '',
            updated_at: d.updated_at || '',
            node_count: d.node_count || 0,
            confidence_avg: 1.0,
          })));
        }
      } catch (err) {
        console.warn('Failed to fetch documents:', err);
      }
    };
    fetchDocs();
  }, []);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [isSepDialogOpen, setIsSepDialogOpen] = useState(false);

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch =
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.job_id.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'ALL' || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
            Завершено
          </span>
        );
      case 'PENDING_HUMAN_REVIEW':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-3.5 h-3.5 mr-1" />
            Требует HITL
          </span>
        );
      case 'RUNNING':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping mr-1.5" />
            Сборка pyjobkit
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
            Ожидание
          </span>
        );
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <span>Документы & Книги KAE</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Мониторинг фоновых задач сборщика знаний <code className="text-indigo-400 font-mono">pyjobkit</code> и импорт из хранилищ SEP
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
            onClick={() => onOpenWorkspace('job-kae-new-' + Date.now())}
            className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white rounded-xl font-medium text-xs flex items-center space-x-2 transition-all shadow-md shadow-indigo-950/50"
          >
            <Plus className="w-4 h-4" />
            <span>Новая сборка KAE</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Поиск по названию или ID..."
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
            <option value="PENDING_HUMAN_REVIEW">Требуют HITL</option>
            <option value="RUNNING">Выполняются</option>
          </select>
        </div>
      </div>

      {/* Document Cards List */}
      <div className="grid grid-cols-1 gap-4">
        {filteredDocs.map((doc) => (
          <div
            key={doc.job_id}
            className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col space-y-3 group"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex items-start space-x-4 min-w-0">
                <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-400 shrink-0">
                  <FileText className="w-6 h-6" />
                </div>

                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center space-x-3 flex-wrap gap-y-1">
                    <h3 className="font-semibold text-white text-sm truncate">{doc.title}</h3>
                    {getStatusBadge(doc.status)}
                  </div>

                  <div className="flex items-center space-x-3 text-xs text-slate-400 font-mono flex-wrap gap-y-1">
                    <span className="text-slate-300 truncate max-w-md">{doc.source_uri}</span>
                    <span>•</span>
                    <span>KRM Узлов: {doc.node_count}</span>
                    <span>•</span>
                    <span>Avg Conf: {((doc.confidence_avg || 0.9) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center space-x-2 shrink-0">
                {onOpenGraph && (
                  <button
                    onClick={() => onOpenGraph(doc.job_id)}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-medium flex items-center space-x-1.5 transition-colors border border-slate-700/60"
                  >
                    <BarChart2 className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Граф знаний</span>
                  </button>
                )}

                <button
                  onClick={() => onOpenWorkspace(doc.job_id)}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-medium flex items-center space-x-1.5 transition-all shadow-md shadow-indigo-950/40"
                >
                  <span>Открыть в Редакторе</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* pyjobkit Progress Bar for running or pending items */}
            {doc.status === 'RUNNING' && (
              <div className="pt-2 border-t border-slate-800/60">
                <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                  <span className="font-mono text-cyan-400">pyjobkit сборка в процессе...</span>
                  <span className="font-mono font-medium text-slate-200">{Math.round(doc.progress * 100)}%</span>
                </div>
                <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden border border-slate-800/80">
                  <div
                    className="h-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-300"
                    style={{ width: `${Math.round(doc.progress * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <SEPSourcesDialog
        isOpen={isSepDialogOpen}
        onClose={() => setIsSepDialogOpen(false)}
        onImportSuccess={(newJobId) => onOpenWorkspace(newJobId)}
      />
    </div>
  );
};

export default DocumentDashboard;
