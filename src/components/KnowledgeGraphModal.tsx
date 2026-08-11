import React, { useState, useEffect } from 'react';
import { Network, X, RefreshCw, ArrowRight } from 'lucide-react';
import kaeApi from '../api/client';
import { GraphVisualizationData } from '../types';

interface KnowledgeGraphModalProps {
  jobId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

const TRACK_LABELS: Record<string, string> = {
  main_flow: 'Основной поток (Main Flow)',
  sidebar_flow: 'Боковая панель (Sidebar)',
  footnote_flow: 'Сноски (Footnotes)',
  caption_flow: 'Подписи (Captions)',
  code_expl: 'Пояснения кода (Code Explanation)',
};

export const KnowledgeGraphModal: React.FC<KnowledgeGraphModalProps> = ({
  jobId,
  isOpen,
  onClose,
}) => {
  const [graphData, setGraphData] = useState<GraphVisualizationData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'knowledge' | 'reading'>('knowledge');

  useEffect(() => {
    if (isOpen && jobId) {
      loadGraph(jobId);
    }
  }, [isOpen, jobId]);

  const loadGraph = async (id: string) => {
    setIsLoading(true);
    try {
      const data = await kaeApi.getGraphData(id);
      setGraphData(data);
    } catch (err) {
      console.warn('Failed to load graph data:', err);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const entityMap = new Map(
    graphData?.knowledge_graph.entities.map((e) => [e.id, e]) ?? []
  );

  const rgEdgesByTrack = new Map<string, typeof graphData extends null ? never : NonNullable<typeof graphData>['reading_graph']['edges']>();
  for (const edge of graphData?.reading_graph.edges ?? []) {
    const list = rgEdgesByTrack.get(edge.track) ?? [];
    list.push(edge);
    rgEdgesByTrack.set(edge.track, list);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden text-slate-100">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-xl">
              <Network className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Визуализация графов KAE</h2>
              <p className="text-xs text-slate-400 font-mono">Job ID: {jobId}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* View Switcher Tabs */}
        <div className="flex items-center space-x-2 px-6 py-3 border-b border-slate-800 bg-slate-950/40 text-xs">
          <button
            onClick={() => setActiveTab('knowledge')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              activeTab === 'knowledge' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            Граф знаний ({graphData?.knowledge_graph.entities.length ?? 0} сущн.)
          </button>
          <button
            onClick={() => setActiveTab('reading')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              activeTab === 'reading' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            Граф чтения ({graphData?.reading_graph.edges.length ?? 0} рёбер)
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 font-mono text-xs">
          {isLoading ? (
            <div className="py-12 text-center text-slate-500 flex flex-col items-center space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
              <span>Загрузка графов...</span>
            </div>
          ) : graphData ? (
            activeTab === 'knowledge' ? (
              <div className="space-y-6">
                <div>
                  <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                    Сущности Knowledge Graph
                  </div>
                  {graphData.knowledge_graph.entities.length === 0 ? (
                    <div className="text-slate-500 text-center py-4">Нет сущностей</div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {graphData.knowledge_graph.entities.map((entity) => (
                        <div
                          key={entity.id}
                          className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-cyan-400 font-semibold truncate">{entity.name}</span>
                            <span className="text-indigo-400 text-[10px] shrink-0 ml-2">{entity.entity_type}</span>
                          </div>
                          {entity.canonical_name && entity.canonical_name !== entity.name && (
                            <div className="text-slate-500 text-[10px]">≡ {entity.canonical_name}</div>
                          )}
                          {entity.description && (
                            <div className="text-slate-400 text-[10px]">{entity.description}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                    Связи ({graphData.knowledge_graph.edges.length})
                  </div>
                  <div className="space-y-2">
                    {graphData.knowledge_graph.edges.map((edge, idx) => {
                      const srcName = entityMap.get(edge.source_id)?.name ?? edge.source_id.slice(0, 8);
                      const tgtName = entityMap.get(edge.target_id)?.name ?? edge.target_id.slice(0, 8);
                      return (
                        <div
                          key={idx}
                          className="p-3 bg-slate-950/60 border border-slate-800/80 rounded-xl flex items-center justify-between text-slate-300"
                        >
                          <span className="text-cyan-400 truncate max-w-[30%]">{srcName}</span>
                          <div className="flex items-center space-x-2 text-slate-500 text-[10px] shrink-0">
                            <span>[{edge.relation_type}]</span>
                            <ArrowRight className="w-3.5 h-3.5" />
                          </div>
                          <span className="text-indigo-400 truncate max-w-[30%] text-right">{tgtName}</span>
                          <span className="text-emerald-400 text-[10px] ml-2 shrink-0">{(edge.confidence * 100).toFixed(0)}%</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {rgEdgesByTrack.size === 0 ? (
                  <div className="text-slate-500 text-center py-4">Нет рёбер чтения</div>
                ) : (
                  Array.from(rgEdgesByTrack.entries()).map(([track, edges]) => (
                    <div key={track}>
                      <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                        {TRACK_LABELS[track] ?? track} ({edges.length} рёбер)
                      </div>
                      <div className="space-y-1.5 max-h-60 overflow-y-auto">
                        {edges.slice(0, 100).map((edge, idx) => (
                          <div
                            key={idx}
                            className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg flex items-center space-x-3 text-slate-300"
                          >
                            <span className="w-6 h-6 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 flex items-center justify-center text-[10px] font-bold shrink-0">
                              {idx + 1}
                            </span>
                            <span className="text-[10px] text-slate-500 truncate">{edge.source_id.slice(0, 8)}</span>
                            <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />
                            <span className="text-[10px] text-slate-500 truncate">{edge.target_id.slice(0, 8)}</span>
                            <span className="text-emerald-400 text-[10px] ml-auto shrink-0">{(edge.confidence * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                        {edges.length > 100 && (
                          <div className="text-center text-slate-500 text-[10px] py-2">
                            ...и ещё {edges.length - 100} рёбер
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )
          ) : (
            <div className="text-center py-8 text-slate-500">Данные графа недоступны</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default KnowledgeGraphModal;
