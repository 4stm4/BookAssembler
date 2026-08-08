import React, { useState, useEffect } from 'react';
import { Network, X, RefreshCw, Layers, ArrowRight } from 'lucide-react';
import kaeApi from '../api/client';
import { GraphVisualizationData } from '../types';

interface KnowledgeGraphModalProps {
  jobId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

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
      // Fallback mock graph representation for visual preview
      setGraphData({
        job_id: id,
        knowledge_graph: {
          nodes: [
            { id: 'n1', type: 'Concept', confidence: 0.98, label: '8086 Microprocessor' },
            { id: 'n2', type: 'Instruction', confidence: 0.99, label: 'MOV Instruction' },
            { id: 'n3', type: 'Register', confidence: 0.95, label: 'AX Register' },
            { id: 'n4', type: 'MemorySegment', confidence: 0.91, label: 'Data Segment (DS)' },
          ],
          edges: [
            { source: 'n1', target: 'n2', relation: 'supports' },
            { source: 'n2', target: 'n3', relation: 'uses_operand' },
            { source: 'n2', target: 'n4', relation: 'accesses_segment' },
          ],
        },
        reading_graph: {
          reading_order: ['n1', 'n2', 'n3', 'n4'],
          sequence: [
            { step: 1, title: 'Введение в архитектуру 8086' },
            { step: 2, title: 'Синтаксис и операнды MOV' },
            { step: 3, title: 'Регистры AX/AL и сегментация DS' },
          ],
        },
      });
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

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
            Граф знаний (Knowledge Graph)
          </button>
          <button
            onClick={() => setActiveTab('reading')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              activeTab === 'reading' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            Граф чтения (Reading Order Graph)
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 font-mono text-xs">
          {isLoading ? (
            <div className="py-12 text-center text-slate-500 flex flex-col items-center space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
              <span>Построение визуальной топологии графа...</span>
            </div>
          ) : graphData ? (
            activeTab === 'knowledge' ? (
              <div className="space-y-6">
                <div>
                  <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                    Узлы понятий и сущностей KRM
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {graphData.knowledge_graph.nodes.map((n) => (
                      <div
                        key={n.id}
                        className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-cyan-400 font-semibold">{n.label || n.id}</span>
                          <span className="text-emerald-400 text-[10px]">{(n.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <div className="text-slate-500 text-[10px]">Тип: {n.type}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                    Связи и семантические ребра
                  </div>
                  <div className="space-y-2">
                    {graphData.knowledge_graph.edges.map((e, idx) => (
                      <div
                        key={idx}
                        className="p-3 bg-slate-950/60 border border-slate-800/80 rounded-xl flex items-center justify-between text-slate-300"
                      >
                        <span className="text-cyan-400">{e.source}</span>
                        <div className="flex items-center space-x-2 text-slate-500 text-[10px]">
                          <span>[{e.relation || 'relates_to'}]</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </div>
                        <span className="text-indigo-400">{e.target}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="text-[11px] font-sans font-semibold uppercase tracking-wider text-slate-400 mb-3">
                  Линейная последовательность чтения главы (Reading Sequence)
                </div>
                {graphData.reading_graph.sequence.map((stepItem, idx) => (
                  <div
                    key={idx}
                    className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl flex items-center space-x-3 text-slate-200"
                  >
                    <span className="w-6 h-6 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 flex items-center justify-center text-xs font-bold shrink-0">
                      {stepItem.step}
                    </span>
                    <span className="text-xs">{stepItem.title}</span>
                  </div>
                ))}
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
