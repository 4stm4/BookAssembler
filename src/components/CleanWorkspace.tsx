import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Copy,
  Check,
  Code2,
  FileText,
  SlidersHorizontal,
  HardDriveUpload,
  Activity,
  Layers,
  Edit3,
  ShieldCheck,
  Download,
  Eye,
  ChevronDown,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import kaeApi from '../api/client';
import { HITLTask, KAEJobEvent, KRMNode } from '../types';
import SEPSourcesDialog from './SEPSourcesDialog';

const TYPE_COLORS: Record<string, string> = {
  ContainerUnit: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  ParagraphBlock: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  CodeBlock: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  FigureBlock: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  FormulaBlock: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  TableBlock: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
};

const KRMNodeView: React.FC<{ node: KRMNode; depth: number }> = ({ node, depth }) => {
  const [collapsed, setCollapsed] = useState(depth > 1);
  const isContainer = node.type === 'ContainerUnit';
  const hasChildren = node.children && node.children.length > 0;
  const label = node.title || node.text?.slice(0, 80) || node.type;
  const confPct = (node.confidence_score * 100).toFixed(0);
  const isLow = node.confidence_score < 0.80;
  const typeColor = TYPE_COLORS[node.type] || 'bg-slate-500/10 text-slate-400 border-slate-500/20';

  return (
    <div className={`${depth > 0 ? 'pl-4 border-l-2 border-slate-800/50' : ''}`}>
      <div
        className={`p-2.5 rounded-lg border text-xs font-sans mb-1.5 transition-all ${
          isLow ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-900/60 border-slate-800/80'
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center space-x-2 min-w-0">
            {hasChildren && (
              <button
                onClick={() => setCollapsed(!collapsed)}
                className="text-slate-500 hover:text-white text-[10px] shrink-0 w-4"
              >
                {collapsed ? '▶' : '▼'}
              </button>
            )}
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono border shrink-0 ${typeColor}`}>
              {node.type === 'ContainerUnit' ? `L${node.level || 1}` : node.type.replace('Block', '')}
            </span>
            <span className={`truncate ${isContainer ? 'font-semibold text-white' : 'text-slate-300'}`}>
              {label}
            </span>
          </div>
          <span className={`text-[10px] font-mono shrink-0 ${isLow ? 'text-amber-400' : 'text-emerald-400'}`}>
            {confPct}%
          </span>
        </div>
      </div>
      {hasChildren && !collapsed && (
        <div className="space-y-1 mt-1">
          {node.children!.map((child: KRMNode) => (
            <KRMNodeView key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

interface CleanWorkspaceProps {
  activeJobId?: string | null;
  onJobCreated?: (jobId: string) => void;
}

export const CleanWorkspace: React.FC<CleanWorkspaceProps> = ({
  activeJobId: initialJobId,
  onJobCreated,
}) => {
  const [activeJobId, setActiveJobId] = useState<string | null>(initialJobId || null);
  const [jobStatus, setJobStatus] = useState<string>('IDLE');
  const [jobProgress, setJobProgress] = useState<number>(0);
  const [jobMessage, setJobMessage] = useState<string>('Готов к обработке');
  const [activeTabLeft, setActiveTabLeft] = useState<'krm' | 'source'>('krm');
  const [activeTabRight, setActiveTabRight] = useState<'preview' | 'editor'>('preview');

  // Document Content States
  const [sourceText, setSourceText] = useState<string>('');
  const [targetMarkdown, setTargetMarkdown] = useState<string>('');
  const [krmNodes, setKrmNodes] = useState<KRMNode[]>([]);

  // HITL Verification Banner State
  const [pendingHitlTasks, setPendingHitlTasks] = useState<HITLTask[]>([]);
  const [activeHitlTask, setActiveHitlTask] = useState<HITLTask | null>(null);
  const [isHitlEditing, setIsHitlEditing] = useState<boolean>(false);
  const [hitlEditText, setHitlEditText] = useState<string>('');
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const [isSepDialogOpen, setIsSepDialogOpen] = useState<boolean>(false);

  useEffect(() => {
    if (initialJobId) {
      setActiveJobId(initialJobId);
    }
  }, [initialJobId]);

  // Fetch real KRM data when job is active
  useEffect(() => {
    if (!activeJobId) return;
    const fetchResult = async () => {
      try {
        const res = await fetch(`/api/v1/jobs/${activeJobId}/result`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.containers) {
          setKrmNodes(data.containers);
        }
        // Build source text from KRM tree
        const texts: string[] = [];
        const extractText = (node: any) => {
          if (node.text) texts.push(node.text);
          if (node.children) node.children.forEach(extractText);
        };
        (data.containers || []).forEach(extractText);
        setSourceText(texts.join('\n\n'));
        setTargetMarkdown(''); // Translation not yet available in Phase 1
      } catch (err) {
        console.warn('Failed to fetch job result:', err);
      }
    };
    fetchResult();
  }, [activeJobId]);

  // Subscribe to reactive SSE job stream
  useEffect(() => {
    const unsubscribeSSE = kaeApi.subscribeToJobStream((event: KAEJobEvent) => {
      if (activeJobId && event.job_id && event.job_id !== activeJobId) return;

      if (event.event === 'job_started') {
        setJobStatus('RUNNING');
        setJobProgress(event.progress || 0.1);
        setJobMessage(`Запуск задачи ${event.job_type}...`);
      } else if (event.event === 'job_progress') {
        setJobStatus('RUNNING');
        setJobProgress(event.progress || 0.5);
        if (event.data?.message) {
          setJobMessage(event.data.message);
        }
      } else if (event.event === 'job_completed') {
        setJobStatus('COMPLETED');
        setJobProgress(1.0);
        setJobMessage('Обработка pyjobkit успешно завершена');
        fetchPendingHitl();
      } else if (event.event === 'job_failed') {
        setJobStatus('FAILED');
        setJobMessage(event.error || 'Ошибка исполнения задачи');
      }
    });

    return () => {
      unsubscribeSSE();
    };
  }, [activeJobId]);

  // Fetch pending HITL tasks
  const fetchPendingHitl = async () => {
    try {
      const tasks = await kaeApi.getHITLTasks();
      setPendingHitlTasks(tasks);
      setActiveHitlTask(null);
    } catch (err) {
      console.warn('Failed to fetch HITL tasks:', err);
    }
  };

  useEffect(() => {
    fetchPendingHitl();
  }, []);

  // Handle 1-Click Approve HITL
  const handleApproveHITL = async (task: HITLTask) => {
    try {
      await kaeApi.submitCorrection(task.task_id, 'lead_reviewer', {
        action: 'APPROVE',
        applied_text: task.suggested_fix?.suggested_text,
      });

      // Update KRM low confidence node
      setKrmNodes((prev) =>
        prev.map((node) => ({
          ...node,
          confidence_score: 0.99,
          children: node.children?.map((c) =>
            c.id === task.target_krm_id ? { ...c, confidence_score: 0.99 } : c
          ),
        }))
      );

      // Remove approved task
      setPendingHitlTasks((prev) => prev.filter((t) => t.task_id !== task.task_id));
      setActiveHitlTask(null);
      setIsHitlEditing(false);
    } catch (err) {
      console.error('Failed to submit HITL approval:', err);
    }
  };

  // Handle Manual Save HITL Correction
  const handleSaveHITLCorrection = async (task: HITLTask) => {
    try {
      await kaeApi.submitCorrection(task.task_id, 'lead_reviewer', {
        action: 'MANUAL_EDIT',
        applied_text: hitlEditText,
      });

      // Update Target Markdown
      setTargetMarkdown((prev) =>
        prev.replace(
          task.suggested_fix?.original_text || '',
          hitlEditText
        )
      );

      setPendingHitlTasks((prev) => prev.filter((t) => t.task_id !== task.task_id));
      setActiveHitlTask(null);
      setIsHitlEditing(false);
    } catch (err) {
      console.error('Failed to submit HITL correction:', err);
    }
  };

  const handleStartProcessing = async () => {
    try {
      setJobStatus('RUNNING');
      setJobProgress(0.15);
      setJobMessage('Запуск сборщика знаний KAE (pyjobkit)...');

      const res = await kaeApi.uploadDocument(
        undefined,
        sourceText,
        'workspace://document_ch4.txt'
      );

      setActiveJobId(res.job_id);
      if (onJobCreated) onJobCreated(res.job_id);

      // Connect WS for specific job
      kaeApi.subscribeToJobWebSocket(res.job_id, (evt) => {
        if (evt.event === 'job_progress') {
          setJobProgress(evt.progress || 0.6);
        } else if (evt.event === 'job_completed') {
          setJobStatus('COMPLETED');
          setJobProgress(1.0);
          setJobMessage('Сборка графа знаний и перевода завершена');
          fetchPendingHitl();
        }
      });
    } catch (err) {
      console.error('Error initiating processing:', err);
      setJobStatus('FAILED');
      setJobMessage('Не удалось запустить процесс');
    }
  };

  const handleCopyTarget = () => {
    navigator.clipboard.writeText(targetMarkdown);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] bg-slate-950 text-slate-100 overflow-hidden relative">
      {/* Subtle pyjobkit Active Progress Bar in Header */}
      <div className="bg-slate-900/90 border-b border-slate-800/80 px-6 py-2.5 flex items-center justify-between text-xs backdrop-blur-md z-10">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2">
            <Activity className="w-4 h-4 text-cyan-400 animate-pulse" />
            <span className="font-semibold tracking-wide text-slate-200">KAE Assembly Pipeline</span>
          </div>

          <div className="h-4 w-px bg-slate-800" />

          <div className="flex items-center space-x-2">
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                jobStatus === 'RUNNING'
                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                  : jobStatus === 'COMPLETED'
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : jobStatus === 'FAILED'
                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                  : 'bg-slate-800 text-slate-400'
              }`}
            >
              {jobStatus === 'RUNNING' && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping mr-1.5" />}
              {jobStatus}
            </span>
            <span className="text-slate-400 truncate max-w-xs">{jobMessage}</span>
          </div>
        </div>

        {/* Header Action Controls */}
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setIsSepDialogOpen(true)}
            className="px-3 py-1.5 bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg flex items-center space-x-1.5 border border-slate-700/60 transition-all font-medium text-xs shadow-sm"
          >
            <HardDriveUpload className="w-3.5 h-3.5 text-indigo-400" />
            <span>Импорт из SEP</span>
          </button>

          <button
            onClick={handleStartProcessing}
            disabled={jobStatus === 'RUNNING'}
            className="px-3.5 py-1.5 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white rounded-lg font-medium flex items-center space-x-1.5 transition-all shadow-md shadow-indigo-950/50 disabled:opacity-50 text-xs"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Запустить сборку</span>
          </button>
        </div>
      </div>

      {/* Thin Active Job Progress Bar */}
      {jobStatus === 'RUNNING' && (
        <div className="w-full bg-slate-900 h-1 overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400"
            initial={{ width: '0%' }}
            animate={{ width: `${Math.round(jobProgress * 100)}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>
      )}

      {/* Main Dual-Pane Workspace */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-800/80 overflow-hidden">
        {/* LEFT BLOCK: Source / KRM Model View */}
        <div className="flex flex-col h-full bg-slate-950/60 overflow-hidden">
          {/* Pane Header */}
          <div className="px-5 py-3 border-b border-slate-800/80 bg-slate-900/40 flex items-center justify-between text-xs">
            <div className="flex items-center space-x-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              <span className="font-medium text-slate-300">Исходные данные / KRM Модель</span>
            </div>

            <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5">
              <button
                onClick={() => setActiveTabLeft('krm')}
                className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                  activeTabLeft === 'krm'
                    ? 'bg-slate-800 text-cyan-300 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                KRM Структура
              </button>
              <button
                onClick={() => setActiveTabLeft('source')}
                className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                  activeTabLeft === 'source'
                    ? 'bg-slate-800 text-cyan-300 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Исходный текст
              </button>
            </div>

            {pendingHitlTasks.length > 0 && (
              <button
                onClick={() => {
                  const task = pendingHitlTasks[0];
                  setActiveHitlTask(task);
                  setHitlEditText(task.suggested_fix?.suggested_text || task.suggested_fix?.original_text || '');
                }}
                className="px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[10px] font-medium hover:bg-amber-500/20 transition-colors"
              >
                HITL: {pendingHitlTasks.length} задач
              </button>
            )}
          </div>

          {/* Pane Content */}
          <div className="flex-1 overflow-y-auto p-5 font-mono text-xs leading-relaxed text-slate-300">
            {activeTabLeft === 'krm' ? (
              <div className="space-y-4">
                <div className="text-[11px] text-slate-400 uppercase tracking-wider font-sans font-semibold">
                  Иерархия узлов KRM (Knowledge Representation Model)
                </div>
                {krmNodes.map((node) => (
                  <KRMNodeView key={node.id} node={node} depth={0} />
                ))}
              </div>
            ) : (
              <textarea
                value={sourceText}
                onChange={(e) => setSourceText(e.target.value)}
                className="w-full h-full bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 text-slate-200 focus:outline-none focus:border-indigo-500/60 resize-none font-mono text-xs leading-relaxed"
                placeholder="Вставьте исходный текст для обработки KAE..."
              />
            )}
          </div>
        </div>

        {/* RIGHT BLOCK: Target Result / Markdown View */}
        <div className="flex flex-col h-full bg-slate-950/40 overflow-hidden">
          {/* Pane Header */}
          <div className="px-5 py-3 border-b border-slate-800/80 bg-slate-900/40 flex items-center justify-between text-xs">
            <div className="flex items-center space-x-2">
              <FileText className="w-4 h-4 text-indigo-400" />
              <span className="font-medium text-slate-300">Результат сборки (Target Markdown)</span>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={handleCopyTarget}
                className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors flex items-center space-x-1"
                title="Копировать Markdown"
              >
                {isCopied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{isCopied ? 'Скопировано' : 'Копировать'}</span>
              </button>

              <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5">
                <button
                  onClick={() => setActiveTabRight('preview')}
                  className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                    activeTabRight === 'preview'
                      ? 'bg-slate-800 text-indigo-300 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Превью
                </button>
                <button
                  onClick={() => setActiveTabRight('editor')}
                  className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                    activeTabRight === 'editor'
                      ? 'bg-slate-800 text-indigo-300 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Редактор
                </button>
              </div>
            </div>
          </div>

          {/* Pane Content */}
          <div className="flex-1 overflow-y-auto p-6 text-sm text-slate-200 leading-relaxed">
            {activeTabRight === 'preview' ? (
              <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-slate-900 prose-pre:border prose-pre:border-slate-800 prose-headings:text-slate-100">
                <ReactMarkdown>{targetMarkdown}</ReactMarkdown>
              </div>
            ) : (
              <textarea
                value={targetMarkdown}
                onChange={(e) => setTargetMarkdown(e.target.value)}
                className="w-full h-full bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 text-slate-200 focus:outline-none focus:border-indigo-500/60 resize-none font-mono text-xs leading-relaxed"
              />
            )}
          </div>
        </div>
      </div>

      {/* Interactive HITL Banner (Only Pops Up When PENDING_HUMAN_REVIEW task is present) */}
      <AnimatePresence>
        {activeHitlTask && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
            className="absolute bottom-4 left-4 right-4 md:left-auto md:right-6 md:max-w-2xl bg-slate-900/95 border border-amber-500/40 rounded-2xl shadow-2xl p-4 text-xs z-30 backdrop-blur-xl"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center space-x-2.5">
                <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-400">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-white">Требуется HITL проверка человеком</span>
                    <span className="px-2 py-0.5 bg-amber-500/20 text-amber-300 font-mono text-[10px] rounded-full border border-amber-500/30">
                      Уверенность: {(activeHitlTask.current_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-slate-400 text-[11px]">
                    Узел KRM <span className="font-mono text-cyan-400">{activeHitlTask.target_krm_id}</span> требует верификации перед финальной сборкой
                  </p>
                </div>
              </div>
            </div>

            {/* Suggested Fix Payload Preview or Edit Mode */}
            {isHitlEditing ? (
              <div className="mb-3 space-y-2">
                <label className="block text-slate-300 font-medium text-[11px]">Ручная коррекция KRM узла:</label>
                <textarea
                  value={hitlEditText}
                  onChange={(e) => setHitlEditText(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-slate-200 font-mono text-xs focus:outline-none focus:border-amber-500"
                  rows={3}
                />
              </div>
            ) : (
              <div className="mb-3 p-3 bg-slate-950/80 border border-slate-800/80 rounded-xl space-y-1">
                <div className="text-[11px] text-slate-400">Предлагаемый фикс модели:</div>
                <div className="font-mono text-xs text-emerald-300 bg-emerald-500/5 p-2 rounded border border-emerald-500/10">
                  {activeHitlTask.suggested_fix?.suggested_text || 'Подтвердить структуру ассемблера'}
                </div>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center justify-end space-x-2">
              {isHitlEditing ? (
                <>
                  <button
                    onClick={() => setIsHitlEditing(false)}
                    className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
                  >
                    Отмена
                  </button>
                  <button
                    onClick={() => handleSaveHITLCorrection(activeHitlTask)}
                    className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg flex items-center space-x-1"
                  >
                    <Check className="w-3.5 h-3.5" />
                    <span>Сохранить правку</span>
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => setIsHitlEditing(true)}
                    className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg flex items-center space-x-1 transition-colors"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>Редактировать</span>
                  </button>
                  <button
                    onClick={() => handleApproveHITL(activeHitlTask)}
                    className="px-4 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-medium rounded-lg flex items-center space-x-1.5 shadow-md shadow-emerald-950/40"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Одобрить (1-click)</span>
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Dialog Modal for SEP Storage Selection */}
      <SEPSourcesDialog
        isOpen={isSepDialogOpen}
        onClose={() => setIsSepDialogOpen(false)}
        onImportSuccess={(newJobId) => {
          setActiveJobId(newJobId);
          if (onJobCreated) onJobCreated(newJobId);
        }}
      />
    </div>
  );
};

export default CleanWorkspace;
