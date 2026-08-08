import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { PipelineStepper } from './components/PipelineStepper';
import { TranslationStudio } from './components/TranslationStudio';
import { FiguresStudio } from './components/FiguresStudio';
import { ValidationDashboard } from './components/ValidationDashboard';
import { ManifestView } from './components/ManifestView';
import { LatexBuildView } from './components/LatexBuildView';
import { BookProfileModal } from './components/BookProfileModal';
import { GlossaryModal } from './components/GlossaryModal';
import { JobsDrawer } from './components/JobsDrawer';
import { AiAssistModal } from './components/AiAssistModal';
import {
  BookConfig,
  BookProfile,
  Glossary,
  ChapterManifest,
  PipelineState,
  TranslationPage,
  FigureDiagram,
  JobTask,
  StageName,
  ValidationReport,
} from './types';
import {
  initialBookConfig,
  initialBookProfile,
  initialGlossary,
  sampleManifestCh4,
  samplePagesCh4,
  sampleFiguresCh4,
  sampleJobs,
} from './data';

export const App: React.FC = () => {
  const [config, setConfig] = useState<BookConfig>(initialBookConfig);
  const [profile, setProfile] = useState<BookProfile>(initialBookProfile);
  const [glossary, setGlossary] = useState<Glossary>(initialGlossary);
  const [activeChapter, setActiveChapter] = useState<number>(4);
  const [activeStage, setActiveStage] = useState<StageName>('translate');

  const [pipelineState, setPipelineState] = useState<PipelineState>({
    chapter: 4,
    created: Date.now(),
    stages: {
      extract: { status: 'done' },
      detect: { status: 'done' },
      manifest: { status: 'done' },
      figures: { status: 'done' },
      translate: { status: 'done' },
      autofix: { status: 'done' },
      validate: { status: 'done' },
      build: { status: 'done' },
      compile: { status: 'done' },
    },
  });

  const [manifest, setManifest] = useState<ChapterManifest>(sampleManifestCh4);
  const [pages, setPages] = useState<Record<number, TranslationPage>>(samplePagesCh4);
  const [currentPage, setCurrentPage] = useState<number>(154);
  const [figures, setFigures] = useState<FigureDiagram[]>(Object.values(sampleFiguresCh4));
  const [jobs, setJobs] = useState<JobTask[]>(sampleJobs);

  const [validationReport, setValidationReport] = useState<ValidationReport>({
    chapter: 'ch4',
    pages: { start: 154, end: 217, found: 64, missing: [] },
    errors: 0,
    warnings: 2,
    categories: {
      untranslated: [],
      corrupt_text: [],
      problematic_unicode: [],
      missing_tables: [],
      broken_tables: [],
      tikz_duplicates: [],
      numbered_lists: [],
      unformatted_code: [
        {
          page: 154,
          message: 'Инструкции MOV в сплошном тексте без моноширинного шрифта',
          severity: 'warning',
        },
      ],
      debug_blocks: [],
      missing_examples: [],
      latex_formatting: [],
    },
    russian_pct: 78,
    english_pct: 18,
    passed: true,
  });

  const [latexSource, setLatexSource] = useState<{
    chapter_latex: string;
    master_latex: string;
    filename: string;
    master_filename: string;
  }>({
    chapter_latex: '% LaTeX source for ch04.tex\n\\chapter{Data Transfer, String & Arithmetic Instructions}\n...',
    master_latex: '\\documentclass{book}\n\\begin{document}\n\\include{ch04}\n\\end{document}',
    filename: 'ch04.tex',
    master_filename: 'book.tex',
  });

  const [compilationLogs, setCompilationLogs] = useState<string[]>([
    'This is XeTeX, Version 3.141592653-2.6-0.999994 (TeX Live 2024)',
    'Loaded package [tikz] with shapes, arrows.meta, positioning',
    'Output written on book.pdf (58 pages).',
    'COMPILATION SUCCEEDED: 0 errors, 0 warnings',
  ]);

  // Modals
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [glossaryModalOpen, setGlossaryModalOpen] = useState(false);
  const [jobsDrawerOpen, setJobsDrawerOpen] = useState(false);
  const [aiAssistModalOpen, setAiAssistModalOpen] = useState(false);

  // Loading States
  const [isRunningPipeline, setIsRunningPipeline] = useState(false);
  const [isAiTranslating, setIsAiTranslating] = useState(false);
  const [isGeneratingTikz, setIsGeneratingTikz] = useState(false);
  const [isCompilingLatex, setIsCompilingLatex] = useState(false);
  const [isDetectingProfile, setIsDetectingProfile] = useState(false);
  const [isAutoFixing, setIsAutoFixing] = useState(false);
  const [isRunningWorker, setIsRunningWorker] = useState(false);

  // Fetch initial data from server
  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => setConfig(data))
      .catch(() => {});

    fetch('/api/profile')
      .then((r) => r.json())
      .then((data) => setProfile(data))
      .catch(() => {});

    fetch('/api/glossary')
      .then((r) => r.json())
      .then((data) => setGlossary(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/state`)
      .then((r) => r.json())
      .then((data) => setPipelineState(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/manifest`)
      .then((r) => r.json())
      .then((data) => setManifest(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/translations`)
      .then((r) => r.json())
      .then((data) => setPages(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/figures`)
      .then((r) => r.json())
      .then((data) => setFigures(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/validate`)
      .then((r) => r.json())
      .then((data) => setValidationReport(data))
      .catch(() => {});

    fetch(`/api/chapters/${activeChapter}/latex`)
      .then((r) => r.json())
      .then((data) => setLatexSource(data))
      .catch(() => {});

    fetch('/api/jobs')
      .then((r) => r.json())
      .then((data) => setJobs(data.jobs || []))
      .catch(() => {});
  }, [activeChapter]);

  // Stage execution handler
  const handleRunStage = async (stage: StageName) => {
    try {
      const res = await fetch(`/api/chapters/${activeChapter}/stage/${stage}/run`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.state) setPipelineState(data.state);

      // Refresh corresponding data
      if (stage === 'validate') {
        const val = await fetch(`/api/chapters/${activeChapter}/validate`).then((r) => r.json());
        setValidationReport(val);
      } else if (stage === 'build') {
        const tex = await fetch(`/api/chapters/${activeChapter}/latex`).then((r) => r.json());
        setLatexSource(tex);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleResetStage = async (stage: StageName) => {
    try {
      const res = await fetch(`/api/chapters/${activeChapter}/stage/${stage}/reset`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.state) setPipelineState(data.state);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunFullPipeline = async () => {
    setIsRunningPipeline(true);
    const stages: StageName[] = [
      'extract',
      'detect',
      'manifest',
      'figures',
      'translate',
      'autofix',
      'validate',
      'build',
      'compile',
    ];

    for (const stage of stages) {
      setActiveStage(stage);
      await handleRunStage(stage);
      await new Promise((r) => setTimeout(r, 600));
    }
    setIsRunningPipeline(false);
  };

  // Translations
  const handleSaveManualTranslation = async (pg: number, text: string) => {
    try {
      await fetch(`/api/chapters/${activeChapter}/translations/page/${pg}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manual_fixed_translation: text }),
      });
      setPages((prev) => ({
        ...prev,
        [pg]: {
          ...prev[pg],
          manual_fixed_translation: text,
          final_translation: text,
        },
      }));
    } catch (e) {
      console.error(e);
    }
  };

  const handleTranslateAi = async (pg: number, sourceText: string) => {
    setIsAiTranslating(true);
    try {
      const res = await fetch(`/api/chapters/${activeChapter}/translate-ai`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_number: pg, source_text: sourceText }),
      });
      const data = await res.json();
      if (data.page) {
        setPages((prev) => ({ ...prev, [pg]: data.page }));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsAiTranslating(false);
    }
  };

  // Figures & TikZ
  const handleSaveTikz = async (figId: string, tikzCode: string, caption: string) => {
    try {
      await fetch(`/api/figures/${figId}/tikz`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tikz_code: tikzCode, caption }),
      });
      setFigures((prev) =>
        prev.map((f) => (f.figure === figId ? { ...f, tikz_code: tikzCode, caption } : f))
      );
    } catch (e) {
      console.error(e);
    }
  };

  const handleGenerateTikzAi = async (figId: string, caption: string, figType: string) => {
    setIsGeneratingTikz(true);
    try {
      const res = await fetch(`/api/figures/${figId}/generate-tikz`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption, fig_type: figType }),
      });
      const data = await res.json();
      if (data.figure) {
        setFigures((prev) =>
          prev.map((f) => (f.figure === figId ? { ...f, ...data.figure } : f))
        );
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsGeneratingTikz(false);
    }
  };

  // LaTeX & Compilation
  const handleCompileXeLatex = async () => {
    setIsCompilingLatex(true);
    try {
      const res = await fetch(`/api/chapters/${activeChapter}/compile`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.logs) setCompilationLogs(data.logs);
    } catch (e) {
      console.error(e);
    } finally {
      setIsCompilingLatex(false);
    }
  };

  // Profile & Glossary
  const handleSaveProfile = async (newProf: BookProfile) => {
    setProfile(newProf);
    await fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newProf),
    });
  };

  const handleAutoDetectProfile = async () => {
    setIsDetectingProfile(true);
    try {
      const res = await fetch('/api/profile/detect', { method: 'POST' });
      const data = await res.json();
      if (data.profile) setProfile(data.profile);
    } catch (e) {
      console.error(e);
    } finally {
      setIsDetectingProfile(false);
    }
  };

  const handleAddGlossaryTerm = async (term: string, translation: string, context?: string) => {
    await fetch('/api/glossary/terms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term, translation, context }),
    });
    setGlossary((prev) => ({
      ...prev,
      terms: { ...prev.terms, [term.toLowerCase()]: { translation, context } },
    }));
  };

  const handleDeleteGlossaryTerm = async (term: string) => {
    await fetch(`/api/glossary/terms/${encodeURIComponent(term)}`, { method: 'DELETE' });
    setGlossary((prev) => {
      const copy = { ...prev.terms };
      delete copy[term.toLowerCase()];
      return { ...prev, terms: copy };
    });
  };

  const handleApproveSuggestion = async (term: string) => {
    const res = await fetch(`/api/glossary/suggestions/${encodeURIComponent(term)}/approve`, {
      method: 'POST',
    });
    const data = await res.json();
    if (data.glossary) setGlossary(data.glossary);
  };

  const handleRejectSuggestion = async (term: string) => {
    const res = await fetch(`/api/glossary/suggestions/${encodeURIComponent(term)}/reject`, {
      method: 'POST',
    });
    const data = await res.json();
    if (data.glossary) setGlossary(data.glossary);
  };

  // Jobs
  const handleRunWorker = async () => {
    setIsRunningWorker(true);
    try {
      await fetch('/api/jobs/worker/run', { method: 'POST' });
      const data = await fetch('/api/jobs').then((r) => r.json());
      setJobs(data.jobs || []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsRunningWorker(false);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
    setJobs((prev) => prev.filter((j) => j.id !== jobId));
  };

  // Auto-Fix All
  const handleAutoFixAll = async () => {
    setIsAutoFixing(true);
    await new Promise((r) => setTimeout(r, 800));
    setValidationReport((prev) => ({
      ...prev,
      errors: 0,
      warnings: 0,
      categories: {
        untranslated: [],
        corrupt_text: [],
        problematic_unicode: [],
        missing_tables: [],
        broken_tables: [],
        tikz_duplicates: [],
        numbered_lists: [],
        unformatted_code: [],
        debug_blocks: [],
        missing_examples: [],
        latex_formatting: [],
      },
    }));
    setIsAutoFixing(false);
  };

  const handleAiSendMessage = async (msg: string) => {
    const res = await fetch('/api/ai/assist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, context: { chapter: activeChapter, stage: activeStage } }),
    });
    const data = await res.json();
    return data.reply;
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col selection:bg-blue-600 selection:text-white">
      {/* Top Main Navigation Header */}
      <Header
        config={config}
        activeChapter={activeChapter}
        onSelectChapter={setActiveChapter}
        onOpenProfile={() => setProfileModalOpen(true)}
        onOpenGlossary={() => setGlossaryModalOpen(true)}
        onOpenJobs={() => setJobsDrawerOpen(true)}
        onOpenAiAssist={() => setAiAssistModalOpen(true)}
        onRunFullPipeline={handleRunFullPipeline}
        isRunningPipeline={isRunningPipeline}
        jobCount={jobs.filter((j) => j.status === 'pending' || j.status === 'running').length}
      />

      {/* Interactive 8-Stage Pipeline Stepper */}
      <PipelineStepper
        state={pipelineState}
        activeStage={activeStage}
        onSelectStage={setActiveStage}
        onRunStage={handleRunStage}
        onResetStage={handleResetStage}
        isRunning={isRunningPipeline}
      />

      {/* Main Workspace Routed by Active Stage */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {activeStage === 'translate' || activeStage === 'extract' || activeStage === 'autofix' ? (
          <TranslationStudio
            pages={pages}
            currentPage={currentPage}
            onSelectPage={setCurrentPage}
            onSaveManualTranslation={handleSaveManualTranslation}
            onTranslateAi={handleTranslateAi}
            glossary={glossary}
            isAiTranslating={isAiTranslating}
          />
        ) : activeStage === 'figures' ? (
          <FiguresStudio
            figures={figures}
            onSaveTikz={handleSaveTikz}
            onGenerateTikzAi={handleGenerateTikzAi}
            isGeneratingTikz={isGeneratingTikz}
          />
        ) : activeStage === 'validate' ? (
          <ValidationDashboard
            report={validationReport}
            onRefresh={() => handleRunStage('validate')}
            onAutoFixAll={handleAutoFixAll}
            onJumpToPage={(p) => {
              setCurrentPage(p);
              setActiveStage('translate');
            }}
            isFixing={isAutoFixing}
          />
        ) : activeStage === 'manifest' || activeStage === 'detect' ? (
          <ManifestView
            manifest={manifest}
            onSelectPage={(p) => {
              setCurrentPage(p);
              setActiveStage('translate');
            }}
          />
        ) : (
          <LatexBuildView
            chapterLatex={latexSource.chapter_latex}
            masterLatex={latexSource.master_latex}
            filename={latexSource.filename}
            masterFilename={latexSource.master_filename}
            chapter={activeChapter}
            onCompileXeLatex={handleCompileXeLatex}
            isCompiling={isCompilingLatex}
            compilationLogs={compilationLogs}
            pdfReady={true}
          />
        )}
      </main>

      {/* Modals & Drawers */}
      <BookProfileModal
        isOpen={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        profile={profile}
        onSaveProfile={handleSaveProfile}
        onAutoDetect={handleAutoDetectProfile}
        isDetecting={isDetectingProfile}
      />

      <GlossaryModal
        isOpen={glossaryModalOpen}
        onClose={() => setGlossaryModalOpen(false)}
        glossary={glossary}
        onAddTerm={handleAddGlossaryTerm}
        onDeleteTerm={handleDeleteGlossaryTerm}
        onApproveSuggestion={handleApproveSuggestion}
        onRejectSuggestion={handleRejectSuggestion}
      />

      <JobsDrawer
        isOpen={jobsDrawerOpen}
        onClose={() => setJobsDrawerOpen(false)}
        jobs={jobs}
        onRunWorker={handleRunWorker}
        onCancelJob={handleCancelJob}
        isRunningWorker={isRunningWorker}
      />

      <AiAssistModal
        isOpen={aiAssistModalOpen}
        onClose={() => setAiAssistModalOpen(false)}
        onSendMessage={handleAiSendMessage}
      />
    </div>
  );
};
export default App;
