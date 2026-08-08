import React, { useState } from 'react';
import {
  FileText,
  Search,
  Filter,
  Play,
  Share2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  HardDriveUpload,
  Upload,
  Sparkles,
  ExternalLink,
  ChevronRight,
  Layers,
  BarChart2,
  Plus,
} from 'lucide-react';
import { KAEDocumentItem } from '../types';
import SEPSourcesDialog from './SEPSourcesDialog';

interface DocumentListProps {
  onOpenWorkspace: (jobId: string) => void;
  onOpenGraph?: (jobId: string) => void;
}

export const DocumentList: React.FC<DocumentListProps> = ({
  onOpenWorkspace,
  onOpenGraph,
}) => {
  const [documents, setDocuments] = useState<KAEDocumentItem[]>([
    {
      job_id: 'job-kae-ch04-8086',
      title: 'Глава 4: Инструкции передачи данных (8086 Microprocessor)',
      source_uri: 's3://kae-documents-bucket/ch04_data_movement.pdf',
      status: 'PENDING_HUMAN_REVIEW',
      progress: 0.85,
      created_at: new Date(Date.now() - 3600000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      updated_at: 'Только что',
      node_count: 64,
      confidence_avg: 0.92,
    },
    {
      job_id: 'job-kae-ch05-arithmetic',
      title: 'Глава 5: Арифметические инструкции и Флаги процессора',
      source_uri: 'local_nvme:///storage/kae/ch05_arithmetic.docx',
      status: 'COMPLETED',
      progress: 1.0,
      created_at: new Date(Date.now() - 86400000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      updated_at: 'Вчера',
      node_count: 88,
      confidence_avg: 0.98,
    },
    {
      job_id: 'job-kae-ch06-control-flow',
      title: 'Глава 6: Инструкции ветвления, циклов и вызовов процедур',
      source_uri: 'webdav://storage.internal/docs/ch06_control_flow.pdf',
      status: 'RUNNING',
      progress: 0.42,
      created_at: '10 мин назад',
      updated_at: '1 мин назад',
      node_count: 42,
      confidence_avg: 0.89,
    },
  ]);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [isSepDialogOpen, setIsSepDialogOpen] = useState(false);

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch = doc.title.toLowerCase().includes(searchQuery.toLowerCase()) || doc.job_id.includes(searchQuery);
    const matchesStatus = statusFilter === 'ALL' || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
            Завершено
          </span>
        );
      case 'PENDING_HUMAN_REVIEW':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-3.5 h-3.5 mr-1" />
            Требует HITL
          </span>
        );
      case 'RUNNING':
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping mr-1.5" />
            Исполнение
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
            Ожидание
          </span>
        );
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Banner / Hero Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center space-x-2">
            <span>Обработанные книги и документы KAE</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Управление и сборка графов знаний через фоновый движок pyjobkit
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
            <span>Новая сборка KAE</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
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
            <option value="PENDING_HUMAN_REVIEW">Требуют HITL</option>
            <option value="RUNNING">Выполняются</option>
          </select>
        </div>
      </div>

      {/* Document Grid / Table */}
      <div className="grid grid-cols-1 gap-4">
        {filteredDocs.map((doc) => (
          <div
            key={doc.job_id}
            className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4 group"
          >
            <div className="flex items-start space-x-4 min-w-0">
              <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-400 shrink-0">
                <FileText className="w-6 h-6" />
              </div>

              <div className="space-y-1.5 min-w-0">
                <div className="flex items-center space-x-3">
                  <h3 className="font-semibold text-white text-sm truncate">{doc.title}</h3>
                  {getStatusBadge(doc.status)}
                </div>

                <div className="flex items-center space-x-4 text-xs text-slate-400 font-mono">
                  <span>URI: {doc.source_uri}</span>
                  <span>•</span>
                  <span>Узлов KRM: {doc.node_count}</span>
                  <span>•</span>
                  <span>Avg Conf: {((doc.confidence_avg || 0.9) * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center space-x-2 shrink-0">
              {onOpenGraph && (
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
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-medium flex items-center space-x-1.5 transition-all shadow-md shadow-indigo-950/40"
              >
                <span>Открыть в Workspace</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
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

export default DocumentList;
