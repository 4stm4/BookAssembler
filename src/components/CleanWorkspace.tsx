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
  LayoutTemplate,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import kaeApi from '../api/client';
import { HITLTask, KAEJobEvent, KRMNode, PageLayout } from '../types';
import PageCanvas from './PageCanvas';
import SEPSourcesDialog from './SEPSourcesDialog';

const TYPE_COLORS: Record<string, string> = {
  ContainerUnit: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  ParagraphBlock: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  CodeBlock: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  FigureBlock: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  FormulaBlock: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  TableBlock: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
  CaptionBlock: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  TitlePageBlock: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  BlankPageBlock: 'bg-slate-600/10 text-slate-500 border-slate-600/20',
};

const PagePreviewModal: React.FC<{
  jobId: string;
  pageIndex: number;
  bbox?: [number, number, number, number];
  onClose: () => void;
}> = ({ jobId, pageIndex, bbox, onClose }) => {
  const imgRef = React.useRef<HTMLImageElement>(null);
  const [imgSize, setImgSize] = React.useState<{ w: number; h: number } | null>(null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className="relative max-w-[90vw] max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute -top-3 -right-3 z-10 bg-slate-800 text-white rounded-full w-7 h-7 text-sm hover:bg-red-600 border border-slate-600">
          ✕
        </button>
        <div className="relative inline-block">
          <img
            ref={imgRef}
            src={`/api/v1/jobs/${jobId}/page-image/${pageIndex}`}
            alt={`Страница ${pageIndex + 1}`}
            className="max-w-[90vw] max-h-[90vh] rounded shadow-2xl"
            onLoad={() => {
              if (imgRef.current) setImgSize({ w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight });
            }}
          />
          {bbox && imgSize && (
            <div
              className="absolute border-2 border-cyan-400 bg-cyan-400/10 rounded pointer-events-none"
              style={{
                left: `${bbox[0] * 100}%`,
                top: `${bbox[1] * 100}%`,
                width: `${(bbox[2] - bbox[0]) * 100}%`,
                height: `${(bbox[3] - bbox[1]) * 100}%`,
              }}
            />
          )}
        </div>
        <div className="text-center text-slate-400 text-xs mt-2">Страница {pageIndex + 1}</div>
      </div>
    </div>
  );
};

const NODE_TYPE_OPTIONS = [
  'ParagraphBlock', 'CodeBlock', 'FigureBlock', 'FormulaBlock',
  'TableBlock', 'CaptionBlock', 'TitlePageBlock', 'BlankPageBlock', 'ContainerUnit',
];

// Group a container's children into runs sharing the same page_index. Containers
// (they can span pages) and blocks without a page go into their own "un-paged"
// group so we don't wrap them under a misleading page header.
function groupChildrenByPage(children: KRMNode[]): Array<{ page: number | null; items: KRMNode[] }> {
  const groups: Array<{ page: number | null; items: KRMNode[] }> = [];
  for (const ch of children) {
    const isContainer = ch.type === 'ContainerUnit';
    const page: number | null = isContainer || ch.page_index == null ? null : ch.page_index;
    const last = groups[groups.length - 1];
    if (last && last.page === page) last.items.push(ch);
    else groups.push({ page, items: [ch] });
  }
  return groups;
}

/** Page-layout map from the server. A context, not a prop, because the node
 *  tree is rendered recursively and threading it through every level would be
 *  noise. */
const PageLayoutCtx = React.createContext<Record<number, PageLayout>>({});

const PageGroup: React.FC<{
  page: number;
  jobId?: string;
  onRefinePage?: (page: number) => Promise<void>;
  items?: KRMNode[];
  children: React.ReactNode;
}> = ({ page, jobId, onRefinePage, items, children }) => {
  const layout = React.useContext(PageLayoutCtx)[page]?.layout;
  const [status, setStatus] = useState<'idle' | 'running' | 'done'>('idle');
  const [showPreview, setShowPreview] = useState(false);
  // Positional pages (cover, title, toc) open reconstructed — that layout is
  // the information. Text pages stay a list, which reads better than a scan.
  const canReconstruct = !!jobId && !!items?.some((n) => n.bbox);
  const [view, setView] = useState<'list' | 'canvas'>(
    layout === 'positional' ? 'canvas' : 'list'
  );
  useEffect(() => {
    setView(layout === 'positional' ? 'canvas' : 'list');
  }, [layout]);

  return (
    <div className="border border-slate-800/70 rounded-lg bg-slate-950/40">
      <div className="flex items-center justify-between px-2 py-1 border-b border-slate-800/70 bg-slate-900/40">
        <div className="text-[11px] font-mono text-slate-400 uppercase tracking-wide flex items-center gap-1.5">
          Страница {page + 1}
          {layout === 'positional' && (
            <span className="px-1 rounded text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20">
              позиционная
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {canReconstruct && (
            <button
              onClick={() => setView((v) => (v === 'canvas' ? 'list' : 'canvas'))}
              className={`px-1.5 py-0.5 rounded text-[9px] font-mono border flex items-center gap-1 ${
                view === 'canvas'
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:bg-slate-700/60'
              }`}
              title="Восстановить страницу по координатам блоков"
            >
              <LayoutTemplate className="w-3 h-3" />
              {view === 'canvas' ? 'страница' : 'список'}
            </button>
          )}
          {jobId && (
            <button
              onClick={() => setShowPreview(true)}
              className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 flex items-center gap-1"
              title={`Открыть превью страницы ${page + 1}`}
            >
              <Eye className="w-3 h-3" />
              превью
            </button>
          )}
          {jobId && onRefinePage && (
            <button
              onClick={async () => {
                setStatus('running');
                try { await onRefinePage(page); setStatus('done'); }
                catch { setStatus('idle'); }
              }}
              disabled={status === 'running'}
              className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-violet-500/10 text-violet-300 border border-violet-500/20 hover:bg-violet-500/20 flex items-center gap-1 disabled:opacity-50"
              title="Агент: пересобрать и уточнить эту страницу"
            >
              <Sparkles className="w-3 h-3" />
              {status === 'running' ? '…' : status === 'done' ? '✓' : 'Агент'}
            </button>
          )}
        </div>
      </div>
      <div className="p-2 space-y-1">
        {view === 'canvas' && canReconstruct ? (
          <PageCanvas jobId={jobId!} pageIndex={page} nodes={items!} />
        ) : (
          children
        )}
      </div>
      {showPreview && jobId && (
        <PagePreviewModal jobId={jobId} pageIndex={page} onClose={() => setShowPreview(false)} />
      )}
    </div>
  );
};

const KRMNodeView: React.FC<{
  node: KRMNode; depth: number; jobId?: string;
  onRefineRequest?: (nodeId: string, mode: 'agent' | 'manual', patch?: Partial<KRMNode>) => Promise<void>;
  onRefinePage?: (page: number) => Promise<void>;
}> = ({ node, depth, jobId, onRefineRequest, onRefinePage }) => {
  const [collapsed, setCollapsed] = useState(depth > 1);
  const [expanded, setExpanded] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editType, setEditType] = useState(node.type);
  const [editText, setEditText] = useState(node.title || node.text || '');
  const [refineStatus, setRefineStatus] = useState<'idle' | 'sending' | 'done'>('idle');
  const isContainer = node.type === 'ContainerUnit';
  const isTable = node.type === 'TableBlock';
  const hasChildren = node.children && node.children.length > 0;
  const isDiagram = node.type === 'DiagramBlock';
  const fullText = node.title || node.text || (node as any).caption_text || (isDiagram ? 'Схема' : '');
  const isLong = !isContainer && fullText.length > 80;
  const label = expanded || !isLong ? fullText : fullText.slice(0, 80) + '…';
  const confPct = (node.confidence_score * 100).toFixed(0);
  const isLow = node.confidence_score < 0.85;
  const typeColor = TYPE_COLORS[node.type] || 'bg-slate-500/10 text-slate-400 border-slate-500/20';
  const hasPage = node.page_index !== undefined && node.page_index !== null;

  const handleAgentRefine = async () => {
    if (!onRefineRequest) return;
    setRefineStatus('sending');
    try {
      await onRefineRequest(node.id, 'agent');
      setRefineStatus('done');
    } catch {
      setRefineStatus('idle');
    }
  };

  const handleManualSave = () => {
    if (!onRefineRequest) return;
    onRefineRequest(node.id, 'manual', { type: editType, text: editText, title: isContainer ? editText : undefined });
    setEditMode(false);
    setRefineStatus('done');
  };

  return (
    <div className={`${depth > 0 ? 'pl-4 border-l-2 border-slate-800/50' : ''}`}>
      <div
        onClick={isLong ? () => setExpanded(!expanded) : isTable ? () => setCollapsed(!collapsed) : undefined}
        className={`p-2.5 rounded-lg border text-xs font-sans mb-1.5 transition-all ${
          isLow ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-900/60 border-slate-800/80'
        } ${isLong || isTable ? 'cursor-pointer hover:border-slate-700' : ''}`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-start space-x-2 min-w-0">
            {(hasChildren || isTable) && (
              <button
                onClick={(e) => { e.stopPropagation(); setCollapsed(!collapsed); }}
                className="text-slate-500 hover:text-white text-[10px] shrink-0 w-4 mt-0.5"
              >
                {collapsed ? '▶' : '▼'}
              </button>
            )}
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono border shrink-0 ${node.metadata?.llm_suggested_type ? 'bg-violet-500/15 text-violet-300 border-violet-500/30' : typeColor}`}>
              {node.metadata?.llm_suggested_type
                ? node.metadata.llm_suggested_type
                : node.type === 'ContainerUnit'
                ? (node.semantic_type === 'toc' ? 'TOC' : node.semantic_type === 'example' ? 'Example' : `L${node.level || 1}`)
                : node.type === 'TitlePageBlock' ? (node.page_role === 'cover' ? 'Обложка' : 'Title Page')
                : node.type === 'BlankPageBlock' ? 'Blank'
                : node.type === 'DiagramBlock' ? 'Схема'
                : node.type.replace('Block', '')}
            </span>
            <span className={`${expanded ? 'whitespace-pre-wrap break-words' : 'truncate'} ${isContainer ? 'font-semibold text-white' : 'text-slate-300'}`}>
              {isTable ? `Таблица (${node.rows?.length || 0} строк)` : (label || node.type)}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {hasPage && jobId && (
              <button
                onClick={(e) => { e.stopPropagation(); setShowPreview(true); }}
                className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 flex items-center gap-1"
                title={`Открыть превью страницы ${node.page_index! + 1}`}
              >
                <Eye className="w-3 h-3" />
              </button>
            )}
            <span
              className={`text-[10px] font-mono mt-0.5 ${isLow ? 'text-amber-400' : 'text-emerald-400'}`}
              title={`Извлечение: ${((node.extraction_confidence ?? 1) * 100).toFixed(0)}% | Классификация: ${((node.classification_confidence ?? 1) * 100).toFixed(0)}%`}
            >
              {confPct}%
            </span>
          </div>
        </div>
        {isLow && refineStatus === 'idle' && (
          <div className="flex items-center gap-1.5 mt-1.5 pl-6">
            <button
              onClick={(e) => { e.stopPropagation(); handleAgentRefine(); }}
              className="px-2 py-1 rounded text-[10px] font-mono bg-violet-500/15 text-violet-400 border border-violet-500/30 hover:bg-violet-500/25 flex items-center gap-1"
              title="Уточнить тип через LLM-агент"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Агент
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setEditMode(!editMode); }}
              className="px-2 py-1 rounded text-[10px] font-mono bg-slate-700/50 text-slate-300 border border-slate-600/30 hover:bg-slate-700 flex items-center gap-1"
              title="Исправить вручную"
            >
              <Edit3 className="w-3.5 h-3.5" />
              Редактировать
            </button>
          </div>
        )}
        {isDiagram && jobId && (
          <div className="mt-2 pl-6">
            <img
              src={`/api/v1/jobs/${jobId}/diagram/${node.id}`}
              alt={fullText}
              className="max-w-md w-full rounded-lg border border-slate-700 bg-white"
              loading="lazy"
            />
            {(node as any).labels?.length > 0 && (
              <div className="mt-1 text-[10px] text-slate-500">{(node as any).labels.length} надписей сохранено</div>
            )}
          </div>
        )}
        {refineStatus === 'sending' && (
          <div className="mt-1.5 pl-6 text-[10px] text-violet-400 animate-pulse">Запрос к агенту…</div>
        )}
        {refineStatus === 'done' && (
          <div className="mt-1.5 pl-6 flex items-center gap-1.5 text-[10px] text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Уточнено
            {node.metadata?.llm_suggested_type && (
              <span className="px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/20">
                LLM: {node.metadata.llm_suggested_type}
              </span>
            )}
          </div>
        )}
        {editMode && (
          <div className="mt-2 pt-2 border-t border-slate-800/50 space-y-2" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2">
              <label className="text-[10px] text-slate-500 shrink-0">Тип:</label>
              <select
                value={editType}
                onChange={(e) => setEditType(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                {NODE_TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t.replace('Block', '')}</option>
                ))}
              </select>
            </div>
            <div className="flex items-start gap-2">
              <label className="text-[10px] text-slate-500 shrink-0 mt-1">Текст:</label>
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                rows={2}
                className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 resize-none"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setEditMode(false)}
                className="px-2 py-1 rounded text-[10px] bg-slate-800 text-slate-400 hover:text-white border border-slate-700"
              >
                Отмена
              </button>
              <button
                onClick={handleManualSave}
                className="px-2 py-1 rounded text-[10px] bg-indigo-600 text-white hover:bg-indigo-500 flex items-center gap-1"
              >
                <Check className="w-3 h-3" />
                Сохранить
              </button>
            </div>
          </div>
        )}
      </div>
      {isTable && node.rows && !collapsed && (
        <div className="overflow-x-auto mt-1 mb-1.5 ml-4">
          <table className="text-[11px] font-mono border-collapse">
            <tbody>
              {node.rows.map((row, ri) => (
                <tr key={ri} className={ri === 0 ? 'text-slate-400 font-semibold' : ''}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1 border border-slate-800/60 text-slate-300 whitespace-nowrap">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hasChildren && !collapsed && (
        <div className="space-y-1 mt-1">
          {groupChildrenByPage(node.children!).map((group, gi) => (
            group.page == null ? (
              // Un-paged children (containers, etc.) — render inline.
              <React.Fragment key={`ung-${gi}`}>
                {group.items.map((child) => (
                  <KRMNodeView key={child.id} node={child} depth={depth + 1} jobId={jobId} onRefineRequest={onRefineRequest} onRefinePage={onRefinePage} />
                ))}
              </React.Fragment>
            ) : (
              <PageGroup key={`pg-${group.page}-${gi}`} page={group.page} jobId={jobId} onRefinePage={onRefinePage} items={group.items}>
                {group.items.map((child) => (
                  <KRMNodeView key={child.id} node={child} depth={depth + 1} jobId={jobId} onRefineRequest={onRefineRequest} onRefinePage={onRefinePage} />
                ))}
              </PageGroup>
            )
          ))}
        </div>
      )}
      {showPreview && jobId && hasPage && (
        <PagePreviewModal
          jobId={jobId}
          pageIndex={node.page_index!}
          bbox={isTable ? node.bbox : undefined}
          onClose={() => setShowPreview(false)}
        />
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
  // Per-page render strategy from the assembler (RFC 0021 §3), keyed by page.
  const [pageLayouts, setPageLayouts] = useState<Record<number, PageLayout>>({});

  // HITL Verification Banner State
  const [pendingHitlTasks, setPendingHitlTasks] = useState<HITLTask[]>([]);
  const [activeHitlTask, setActiveHitlTask] = useState<HITLTask | null>(null);
  const [isHitlEditing, setIsHitlEditing] = useState<boolean>(false);
  const [hitlEditText, setHitlEditText] = useState<string>('');
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const [isSepDialogOpen, setIsSepDialogOpen] = useState<boolean>(false);

  const handleRefineRequest = async (nodeId: string, mode: 'agent' | 'manual', patch?: Partial<KRMNode>) => {
    if (!activeJobId) return;
    try {
      const result = await kaeApi.refineNode(activeJobId, nodeId, mode, patch as Record<string, any>);
      if (mode === 'manual' && patch) {
        setKrmNodes((prev) => {
          const updateNode = (nodes: KRMNode[]): KRMNode[] =>
            nodes.map((n) => {
              if (n.id === nodeId) return { ...n, ...patch, confidence_score: 1.0 };
              if (n.children) return { ...n, children: updateNode(n.children) };
              return n;
            });
          return updateNode(prev);
        });
      } else if (mode === 'agent' && result?.confidence) {
        setKrmNodes((prev) => {
          const updateNode = (nodes: KRMNode[]): KRMNode[] =>
            nodes.map((n) => {
              if (n.id === nodeId) return { ...n, confidence_score: result.confidence, metadata: { ...n.metadata, llm_suggested_type: result.llm_result?.type } };
              if (n.children) return { ...n, children: updateNode(n.children) };
              return n;
            });
          return updateNode(prev);
        });
      }
    } catch (err) {
      console.error('Refine failed:', err);
    }
  };

  const handleRefinePage = async (page: number) => {
    if (!activeJobId) return;
    await kaeApi.refinePage(activeJobId, page);
    // Reload the KRM tree so rebuilt structures (title/diagram/table) show up.
    const data = await kaeApi.getJobResult(activeJobId);
    if (data?.containers) setKrmNodes(data.containers);
  };

  useEffect(() => {
    if (initialJobId) {
      setActiveJobId(initialJobId);
    }
  }, [initialJobId]);

  // Refresh the page-layout map whenever the tree changes: re-running a page
  // can turn it from reflow into positional (or back).
  useEffect(() => {
    let cancelled = false;
    if (!activeJobId || krmNodes.length === 0) {
      setPageLayouts({});
      return;
    }
    kaeApi
      .getPageLayouts(activeJobId)
      .then((res) => {
        if (cancelled) return;
        const byPage: Record<number, PageLayout> = {};
        for (const p of res.pages) byPage[p.page_index] = p;
        setPageLayouts(byPage);
      })
      .catch(() => {
        // Layout is an enhancement; the list view stands on its own.
        if (!cancelled) setPageLayouts({});
      });
    return () => {
      cancelled = true;
    };
  }, [activeJobId, krmNodes]);

  // Fetch real KRM data when job is active
  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const fetchResult = async () => {
      try {
        const res = await fetch(`/api/v1/jobs/${activeJobId}/result`);
        if (!res.ok) {
          // Job may still be processing — start polling progress
          const progRes = await fetch(`/api/v1/jobs/${activeJobId}/progress`);
          if (progRes.ok) {
            const prog = await progRes.json();
            setJobStatus(prog.status === 'COMPLETED' ? 'COMPLETED' : prog.status === 'FAILED' ? 'FAILED' : 'RUNNING');
            setJobProgress(prog.total > 0 ? prog.step / prog.total : 0);
            setJobMessage(prog.stage || 'Обработка...');

            if (prog.status === 'RUNNING' && !pollTimer) {
              pollTimer = setInterval(async () => {
                if (cancelled) return;
                try {
                  const p = await fetch(`/api/v1/jobs/${activeJobId}/progress`);
                  if (!p.ok) return;
                  const pd = await p.json();
                  setJobProgress(pd.total > 0 ? pd.step / pd.total : 0);
                  setJobMessage(pd.stage || 'Обработка...');
                  if (pd.status === 'COMPLETED') {
                    setJobStatus('COMPLETED');
                    setJobMessage('Обработка завершена');
                    if (pollTimer) clearInterval(pollTimer);
                    // Reload KRM data
                    const r2 = await fetch(`/api/v1/jobs/${activeJobId}/result`);
                    if (r2.ok) {
                      const d2 = await r2.json();
                      if (d2.containers) setKrmNodes(d2.containers);
                    }
                  } else if (pd.status === 'FAILED') {
                    setJobStatus('FAILED');
                    setJobMessage(pd.error || 'Ошибка');
                    if (pollTimer) clearInterval(pollTimer);
                  }
                } catch {}
              }, 3000);
            }
          }
          return;
        }
        const data = await res.json();
        if (data.containers) {
          setKrmNodes(data.containers);
        }
        setJobStatus('COMPLETED');
        const texts: string[] = [];
        const extractText = (node: any) => {
          if (node.text) texts.push(node.text);
          if (node.children) node.children.forEach(extractText);
        };
        (data.containers || []).forEach(extractText);
        setSourceText(texts.join('\n\n'));
        setTargetMarkdown('');
      } catch (err) {
        console.warn('Failed to fetch job result:', err);
      }
    };
    fetchResult();
    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
    };
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
              <PageLayoutCtx.Provider value={pageLayouts}>
              <div className="space-y-4">
                <div className="text-[11px] text-slate-400 uppercase tracking-wider font-sans font-semibold">
                  Иерархия узлов KRM (Knowledge Representation Model)
                </div>
                {groupChildrenByPage(krmNodes).map((group, gi) => (
                  group.page == null ? (
                    <React.Fragment key={`root-ung-${gi}`}>
                      {group.items.map((node) => (
                        <KRMNodeView key={node.id} node={node} depth={0} jobId={activeJobId || undefined} onRefineRequest={handleRefineRequest} onRefinePage={handleRefinePage} />
                      ))}
                    </React.Fragment>
                  ) : (
                    <PageGroup key={`root-pg-${group.page}-${gi}`} page={group.page} jobId={activeJobId || undefined} onRefinePage={handleRefinePage} items={group.items}>
                      {group.items.map((node) => (
                        <KRMNodeView key={node.id} node={node} depth={0} jobId={activeJobId || undefined} onRefineRequest={handleRefineRequest} onRefinePage={handleRefinePage} />
                      ))}
                    </PageGroup>
                  )
                ))}
              </div>
              </PageLayoutCtx.Provider>
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
