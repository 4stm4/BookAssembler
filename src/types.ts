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

export interface KRMStyle {
  font_family?: string;
  font_size_pt?: number;
  is_bold?: boolean;
  is_italic?: boolean;
  is_monospace?: boolean;
  text_color_rgb?: [number, number, number];
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
  page_end?: number;
  page_role?: string;
  metadata?: Record<string, any>;
  caption_text?: string;
  labels?: Array<{ text: string; x0: number; y0: number; x1: number; y1: number }>;
  bbox?: [number, number, number, number];
  /** Per-line geometry kept from the sources a merged block absorbed
   *  (RFC 0021 §5.4). Present on title pages; absent on ordinary blocks. */
  lines?: Array<{
    text: string;
    bbox: [number, number, number, number];
    style?: KRMStyle;
  }>;
  style?: KRMStyle;
  target_type?: string;
  label_number?: string;
  target_block_id?: string;
}

/** Per-page render strategy, decided server-side (RFC 0021 §3). */
export interface PageLayout {
  page_index: number;
  role: string;
  layout: 'positional' | 'reflow' | 'blank';
  block_ids: string[];
  /** The source page's size in points, when the adapter recorded it. */
  width_pt?: number;
  height_pt?: number;
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
  stage?: string;
}
