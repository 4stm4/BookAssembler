export type StageName =
  | 'extract'
  | 'detect'
  | 'manifest'
  | 'figures'
  | 'translate'
  | 'autofix'
  | 'validate'
  | 'build'
  | 'compile';

export interface StageState {
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  started?: number;
  finished?: number;
  error?: string;
  meta?: Record<string, any>;
  input_hashes?: Record<string, string>;
  output_hashes?: Record<string, string>;
}

export interface PipelineState {
  chapter: number;
  stages: Record<StageName, StageState>;
  created: number;
  updated?: number;
}

export interface ChapterConfig {
  pages: [number, number];
  title: string;
}

export interface BookConfig {
  title: string;
  pdf: string;
  source_lang: string;
  target_lang: string;
  chapters: Record<number, ChapterConfig>;
}

export interface TableIndicator {
  pattern: string;
  type: string;
}

export interface BookProfile {
  book_description: string;
  translation_prompt_intro: string;
  asm_mnemonics: string[];
  debug_indicators: string[];
  debug_line_patterns: string[];
  debug_flag_strings: string[];
  section_pattern: string;
  section_flags: number;
  table_indicators: TableIndicator[];
  figure_categories: Record<string, string[]>;
  subscript_bases: number[];
}

export interface TermEntry {
  translation: string;
  context?: string;
  category?: string;
}

export interface GlossarySuggestion {
  count: number;
  status: 'pending' | 'approved' | 'rejected';
  context?: string;
}

export interface Glossary {
  terms: Record<string, TermEntry>;
  keep_as_is: Record<string, string[]>;
  formatting_rules: Record<string, string>;
  suggestions: Record<string, GlossarySuggestion>;
}

export interface ManifestSection {
  page: number;
  number: string;
  title: string;
}

export interface ManifestFigure {
  page: number;
  number: string;
  caption: string;
  type: string;
  sub?: string;
  has_tikz?: boolean;
}

export interface ManifestExample {
  page: number;
  number: string;
}

export interface ManifestTable {
  page: number;
  type: string;
}

export interface ManifestDebugSession {
  page: number;
}

export interface ManifestNumberedList {
  page: number;
  items: number;
  first_item: string;
}

export interface ElementOrderItem {
  type: string;
  id: string;
  pos?: number;
}

export interface ChapterManifest {
  manifest_version: number;
  chapter: number;
  pages: {
    start: number;
    end: number;
    count: number;
  };
  sections: ManifestSection[];
  figures: ManifestFigure[];
  examples: ManifestExample[];
  tables: ManifestTable[];
  debug_sessions: ManifestDebugSession[];
  numbered_lists: ManifestNumberedList[];
  element_order: Record<string, ElementOrderItem[]>;
}

export interface ValidationIssue {
  page: number | null;
  message: string;
  severity: 'error' | 'warning';
  category?: string;
}

export interface ValidationReport {
  chapter: string;
  pages: {
    start: number;
    end: number;
    found: number;
    missing: number[];
  };
  errors: number;
  warnings: number;
  categories: Record<string, ValidationIssue[]>;
  russian_pct: number;
  english_pct: number;
  passed: boolean;
}

export interface TranslationPage {
  page_number: number;
  source_text: string;
  original_translation: string;
  autofix_translation: string;
  manual_fixed_translation: string;
  final_translation: string;
  issues: string[];
  is_valid: boolean;
  has_code: boolean;
  has_table: boolean;
  has_debug_session: boolean;
  has_figure_ref?: string | null;
}

export interface JobTask {
  id: string;
  kind: 'translate-batch' | 'analyze-figure' | 'render-figure-page' | 'build-chapter' | 'compile-book';
  chapter: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  idempotency_key: string;
  created_at: number;
  finished_at?: number;
  progress?: number;
  logs: string[];
  payload: Record<string, any>;
  result?: Record<string, any>;
  error?: string;
}

export interface FigureDiagram {
  figure: string;
  page: number;
  fig_type: string;
  caption: string;
  image?: string;
  tikz_code?: string;
  primitives?: {
    type: 'box' | 'text' | 'arrow' | 'circle' | 'table' | 'register';
    x: number;
    y: number;
    w?: number;
    h?: number;
    label?: string;
    props?: Record<string, any>;
  }[];
  connections?: {
    from: string;
    to: string;
    label?: string;
    style?: 'solid' | 'dashed' | 'double';
  }[];
  reviews?: string[];
  image_size?: [number, number];
}
