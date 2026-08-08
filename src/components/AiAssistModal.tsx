import React, { useState } from 'react';
import {
  Sparkles,
  Send,
  X,
  Bot,
  User,
  RefreshCw,
  Code,
  Terminal,
  HelpCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';

interface AiAssistModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSendMessage: (msg: string) => Promise<string>;
}

export const AiAssistModal: React.FC<AiAssistModalProps> = ({
  isOpen,
  onClose,
  onSendMessage,
}) => {
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([
    {
      role: 'assistant',
      content: `Здравствуйте! Я ассистент по пайплайну **BookAssembler**.\n\nЧем я могу помочь?\n- Поиск и исправление ошибок в LaTeX/TikZ схемах\n- Автоматическое форматирование сессий MS-DOS DEBUG в \`lstlisting\`\n- Настройка правил глоссария для мнемоник x86 и регистров\n- Подготовка и сборка книги в XeLaTeX`,
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userText = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userText }]);
    setLoading(true);

    try {
      const reply = await onSendMessage(userText);
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Ошибка: ${e.message || 'Не удалось выполнить запрос'}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-3xl w-full max-w-2xl h-[75vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center text-white shadow-lg shadow-purple-500/20">
              <Sparkles className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                BookAssembler AI Assistant
              </h2>
              <p className="text-xs text-slate-400">
                Powered by Gemini 2.5 • LaTeX, TikZ, and Assembly translation expert
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

        {/* Message Stream */}
        <div className="flex-1 p-6 overflow-y-auto space-y-4">
          {messages.map((m, idx) => (
            <div
              key={idx}
              className={`flex items-start gap-3 text-xs ${
                m.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {m.role === 'assistant' && (
                <div className="w-7 h-7 rounded-lg bg-blue-600/20 text-blue-400 border border-blue-500/30 flex items-center justify-center shrink-0">
                  <Bot className="w-4 h-4" />
                </div>
              )}
              <div
                className={`max-w-[85%] p-4 rounded-2xl leading-relaxed whitespace-pre-wrap ${
                  m.role === 'user'
                    ? 'bg-blue-600 text-white font-medium'
                    : 'bg-slate-950/80 border border-slate-800 text-slate-200 shadow-lg'
                }`}
              >
                <ReactMarkdown>{m.content}</ReactMarkdown>
              </div>
              {m.role === 'user' && (
                <div className="w-7 h-7 rounded-lg bg-slate-800 text-slate-300 flex items-center justify-center shrink-0">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-blue-400" />
              <span>Генерация ответа...</span>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <form onSubmit={handleSubmit} className="p-4 bg-slate-950/90 border-t border-slate-800 flex gap-2">
          <input
            type="text"
            placeholder="Спросите об ошибках в XeLaTeX, TikZ или правилах перевода..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="flex-1 px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-1.5 transition shadow-lg shadow-blue-500/20"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </form>
      </div>
    </div>
  );
};
