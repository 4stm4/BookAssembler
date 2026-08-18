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

export interface KAEJobEvent {
  event: 'job_started' | 'job_progress' | 'job_completed' | 'job_failed';
  job_id: string;
  job_type: string;
  payload?: Record<string, any>;
  progress?: number;
  status?: string;
  data?: {
    value?: number;
    message?: string;
  };
  result?: Record<string, any>;
  timestamp_utc?: string;
  error?: string;
}

export interface HITLTask {
  task_id: string;
  target_krm_id: string;
  current_confidence: number;
  status: 'PENDING_HUMAN_REVIEW' | 'VERIFIED_CORRECT' | 'HUMAN_OVERRIDDEN' | string;
  suggested_fix: {
    node_type?: string;
    original_text?: string;
    suggested_text?: string;
    reason?: string;
    [key: string]: any;
  };
  reviewer_id?: string | null;
}

export interface SEPProvider {
  provider_id: string;
  name: string;
  sep_type: 'local_nvme' | 's3_minio' | 'webdav' | 'gdrive' | string;
  is_active: boolean;
}

export interface SEPRemoteFile {
  file_id: string;
  name: string;
  is_directory: boolean;
  size_bytes: number;
  mime_type: string;
  path: string;
  modified_at_utc: string;
}

export interface KRMNode {
  id: string;
  type: string;
  confidence_score: number;
  extraction_confidence?: number;
  classification_confidence?: number;
  title?: string;
  text?: string;
  level?: number;
  semantic_type?: string;
  children?: KRMNode[];
  rows?: string[][];
  page_index?: number;
  page_role?: string;
  bbox?: [number, number, number, number];
  target_type?: string;
  label_number?: string;
  target_block_id?: string;
}

export interface GraphVisualizationData {
  job_id: string;
  knowledge_graph: {
    graph_version?: string;
    entities: Array<{ id: string; name: string; entity_type: string; canonical_name?: string; description?: string }>;
    edges: Array<{ source_id: string; target_id: string; relation_type: string; confidence: number; provenance_analyzer?: string }>;
  };
  reading_graph: {
    graph_version?: string;
    edges: Array<{ source_id: string; target_id: string; track: string; confidence: number; provenance_analyzer?: string }>;
  };
}

export interface KAEDocumentItem {
  job_id: string;
  title: string;
  source_uri: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'PENDING_HUMAN_REVIEW' | 'FAILED';
  progress: number;
  created_at: string;
  updated_at: string;
  node_count?: number;
  confidence_avg?: number;
}
