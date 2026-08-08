import React, { useState } from 'react';
import {
  Settings,
  Cpu,
  Terminal,
  Search,
  Sparkles,
  Save,
  X,
  Code,
  Layers,
} from 'lucide-react';
import { BookProfile } from '../types';

interface BookProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: BookProfile;
  onSaveProfile: (profile: BookProfile) => void;
  onAutoDetect: () => Promise<void>;
  isDetecting: boolean;
}

export const BookProfileModal: React.FC<BookProfileModalProps> = ({
  isOpen,
  onClose,
  profile,
  onSaveProfile,
  onAutoDetect,
  isDetecting,
}) => {
  const [formData, setFormData] = useState<BookProfile>(JSON.parse(JSON.stringify(profile)));
  const [newMnemonic, setNewMnemonic] = useState('');

  if (!isOpen) return null;

  const handleAddMnemonic = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMnemonic) return;
    const upper = newMnemonic.trim().toUpperCase();
    if (!formData.asm_mnemonics.includes(upper)) {
      setFormData({
        ...formData,
        asm_mnemonics: [...formData.asm_mnemonics, upper],
      });
    }
    setNewMnemonic('');
  };

  const handleRemoveMnemonic = (m: string) => {
    setFormData({
      ...formData,
      asm_mnemonics: formData.asm_mnemonics.filter((x) => x !== m),
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveProfile(formData);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-3xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center justify-center">
              <Settings className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                Book Profile &amp; Instruction Set Configuration
              </h2>
              <p className="text-xs text-slate-400">
                Customized for microprocessors, assembly mnemonics, MS-DOS debug patterns, and subscript bases.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onAutoDetect}
              disabled={isDetecting}
              className="px-3 py-1.5 rounded-lg bg-blue-600/30 hover:bg-blue-600/40 text-blue-300 border border-blue-500/40 text-xs font-semibold flex items-center gap-1.5 transition"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>{isDetecting ? 'Scanning...' : 'Auto-Detect Profile'}</span>
            </button>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 overflow-y-auto flex-1 space-y-6">
          {/* Translation Prompt Intro */}
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block mb-2">
              Translation Engine Prompt Intro:
            </label>
            <textarea
              value={formData.translation_prompt_intro}
              onChange={(e) => setFormData({ ...formData, translation_prompt_intro: e.target.value })}
              rows={3}
              className="w-full p-3 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 leading-relaxed"
            />
          </div>

          {/* ASM Mnemonics */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Instruction Set Mnemonics ({formData.asm_mnemonics.length}):
              </label>
            </div>

            <div className="flex gap-2 mb-3">
              <input
                type="text"
                placeholder="Add mnemonic (e.g. MOVSB, CMPSB)"
                value={newMnemonic}
                onChange={(e) => setNewMnemonic(e.target.value)}
                className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button
                type="button"
                onClick={handleAddMnemonic}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold"
              >
                Add
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto p-3 bg-slate-950/60 border border-slate-800/80 rounded-2xl">
              {formData.asm_mnemonics.map((m) => (
                <span
                  key={m}
                  className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-xs font-mono font-bold text-slate-200 flex items-center gap-1.5"
                >
                  <span>{m}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveMnemonic(m)}
                    className="text-slate-500 hover:text-rose-400"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>

          {/* Debug Indicators */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-950/60 border border-slate-800 rounded-2xl p-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-purple-400 mb-2 flex items-center gap-1.5">
                <Terminal className="w-3.5 h-3.5" />
                MS-DOS DEBUG Indicators:
              </h3>
              <div className="space-y-1">
                {formData.debug_indicators.map((ind, idx) => (
                  <div key={idx} className="text-xs font-mono text-slate-300 p-1 bg-slate-900 rounded">
                    {ind}
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-slate-950/60 border border-slate-800 rounded-2xl p-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2 flex items-center gap-1.5">
                <Code className="w-3.5 h-3.5" />
                Subscript Bases (Auto-Subscript):
              </h3>
              <div className="flex gap-2">
                {formData.subscript_bases.map((base) => (
                  <span
                    key={base}
                    className="px-3 py-1.5 rounded-xl bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-xs font-bold font-mono"
                  >
                    Base {base} (e.g. 1010₂, PA₁₆)
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Footer actions */}
          <div className="pt-4 border-t border-slate-800 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition flex items-center gap-1.5"
            >
              <Save className="w-3.5 h-3.5" />
              <span>Save Book Profile</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
