import React, { useState } from 'react';
import {
  BookOpen,
  Plus,
  Trash2,
  Check,
  X,
  Sparkles,
  Shield,
  Search,
} from 'lucide-react';
import { Glossary } from '../types';

interface GlossaryModalProps {
  isOpen: boolean;
  onClose: () => void;
  glossary: Glossary;
  onAddTerm: (term: string, translation: string, context?: string, category?: string) => void;
  onDeleteTerm: (term: string) => void;
  onApproveSuggestion: (term: string) => void;
  onRejectSuggestion: (term: string) => void;
}

export const GlossaryModal: React.FC<GlossaryModalProps> = ({
  isOpen,
  onClose,
  glossary,
  onAddTerm,
  onDeleteTerm,
  onApproveSuggestion,
  onRejectSuggestion,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [newTerm, setNewTerm] = useState('');
  const [newTranslation, setNewTranslation] = useState('');
  const [newContext, setNewContext] = useState('');
  const [activeTab, setActiveTab] = useState<'terms' | 'keep_as_is' | 'suggestions' | 'rules'>('terms');

  if (!isOpen) return null;

  const filteredTerms = Object.entries(glossary.terms).filter(([en, data]) =>
    en.toLowerCase().includes(searchTerm.toLowerCase()) ||
    data.translation.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTerm || !newTranslation) return;
    onAddTerm(newTerm, newTranslation, newContext);
    setNewTerm('');
    setNewTranslation('');
    setNewContext('');
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-3xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="px-6 py-4 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                Technical Glossary &amp; Protected Terminology
              </h2>
              <p className="text-xs text-slate-400">
                Dictionary enforced across translation engines, regex scanners, and LaTeX formatting rules.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="px-6 py-2.5 bg-slate-950/40 border-b border-slate-800/80 flex gap-2">
          <button
            onClick={() => setActiveTab('terms')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'terms' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Terms Dictionary ({Object.keys(glossary.terms).length})
          </button>
          <button
            onClick={() => setActiveTab('keep_as_is')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'keep_as_is' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Keep As-Is Rules
          </button>
          <button
            onClick={() => setActiveTab('suggestions')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 ${
              activeTab === 'suggestions' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>AI Suggestions ({Object.keys(glossary.suggestions || {}).length})</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-4">
          {activeTab === 'terms' && (
            <>
              {/* Add New Term Bar */}
              <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-4 gap-2 bg-slate-950/60 p-3 rounded-2xl border border-slate-800">
                <input
                  type="text"
                  placeholder="English Term (e.g. instruction pointer)"
                  value={newTerm}
                  onChange={(e) => setNewTerm(e.target.value)}
                  className="px-3 py-1.5 bg-slate-900 border border-slate-700/80 rounded-lg text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <input
                  type="text"
                  placeholder="Russian Translation"
                  value={newTranslation}
                  onChange={(e) => setNewTranslation(e.target.value)}
                  className="px-3 py-1.5 bg-slate-900 border border-slate-700/80 rounded-lg text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <input
                  type="text"
                  placeholder="Context / Registers note"
                  value={newContext}
                  onChange={(e) => setNewContext(e.target.value)}
                  className="px-3 py-1.5 bg-slate-900 border border-slate-700/80 rounded-lg text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center justify-center gap-1 transition"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Add Term</span>
                </button>
              </form>

              {/* Search Bar */}
              <div className="relative">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Search technical dictionary..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {/* Terms Table */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {filteredTerms.map(([en, data]) => (
                  <div
                    key={en}
                    className="p-3 bg-slate-950/80 border border-slate-800/80 rounded-xl flex items-center justify-between gap-3 text-xs"
                  >
                    <div>
                      <div className="font-bold text-blue-300 capitalize">{en}</div>
                      <div className="font-semibold text-emerald-400">{data.translation}</div>
                      {data.context && (
                        <div className="text-[10px] text-slate-400 mt-0.5">{data.context}</div>
                      )}
                    </div>
                    <button
                      onClick={() => onDeleteTerm(en)}
                      className="text-slate-500 hover:text-rose-400 p-1 transition"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          {activeTab === 'keep_as_is' && (
            <div className="space-y-4">
              <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-2">
                  ASM Mnemonics (Strictly Untranslated)
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {glossary.keep_as_is.mnemonics?.map((m) => (
                    <span
                      key={m}
                      className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-xs font-mono font-bold text-slate-200"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </div>

              <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2">
                  Hardware Registers
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {glossary.keep_as_is.registers?.map((r) => (
                    <span
                      key={r}
                      className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-xs font-mono font-bold text-emerald-300"
                    >
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'suggestions' && (
            <div className="space-y-3">
              {Object.entries(glossary.suggestions || {}).map(([term, sug]) => (
                <div
                  key={term}
                  className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-2xl flex items-center justify-between gap-3 text-xs"
                >
                  <div>
                    <div className="font-bold text-white">{term}</div>
                    <div className="text-emerald-400 font-medium">{sug.context}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5 font-mono">
                      Occurrences in text: {sug.count} • Status: {sug.status}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onApproveSuggestion(term)}
                      className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold flex items-center gap-1 transition text-xs"
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>Approve</span>
                    </button>
                    <button
                      onClick={() => onRejectSuggestion(term)}
                      className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition text-xs"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
