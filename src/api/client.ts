/**
 * KAE (Knowledge Assembly Engine) Typed REST & WebSocket API Client
 */

import {
  GraphVisualizationData,
  HITLTask,
  KAEJobEvent,
  SEPProvider,
  SEPRemoteFile,
} from '../types';

const API_BASE = '/api/v1';

export class KAEApiClient {
  /**
   * Upload a document file or raw text payload to start processing.
   */
  async uploadDocument(
    file?: File,
    content?: string,
    sourceUri?: string
  ): Promise<{ job_id: string; status: string; source_uri: string }> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        throw new Error(`Upload failed with status ${res.status}`);
      }
      return res.json();
    } else {
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: content || '',
          source_uri: sourceUri || 'upload://document.txt',
        }),
      });
      if (!res.ok) {
        throw new Error(`Document upload failed: ${res.statusText || `HTTP ${res.status}`}`);
      }
      return res.json();
    }
  }

  /**
   * Import file from a Storage Endpoint Provider (SEP)
   */
  async importFromSEP(
    providerId: string,
    fileId: string
  ): Promise<{ job_id: string; status: string; source_uri: string }> {
    const res = await fetch(`${API_BASE}/sep/providers/${providerId}/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to import file from SEP provider');
    }
    return res.json();
  }

  /**
   * Retrieve list of HITL tasks requiring human verification/correction
   */
  async getHITLTasks(): Promise<HITLTask[]> {
    const res = await fetch(`${API_BASE}/hitl/pending`);
    if (!res.ok) {
      throw new Error(`Failed to fetch HITL tasks: ${res.statusText || `HTTP ${res.status}`}`);
    }
    return res.json();
  }

  /**
   * Submit human correction for a flagged HITL task item
   */
  async submitCorrection(
    taskId: string,
    reviewerId: string,
    payload: Record<string, any>
  ): Promise<{ status: string; task_id: string; reviewer_id: string }> {
    const res = await fetch(`${API_BASE}/hitl/correct`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: taskId,
        reviewer_id: reviewerId,
        correction_payload: payload,
      }),
    });
    if (!res.ok) {
      throw new Error(`Correction submission failed: ${res.statusText || `HTTP ${res.status}`}`);
    }
    return res.json();
  }

  /**
   * Fetch Knowledge Graph (KG) and Reading Graph (RG) visualization payloads
   */
  async getGraphData(jobId: string): Promise<GraphVisualizationData> {
    const res = await fetch(`${API_BASE}/graph/${jobId}`);
    if (!res.ok) {
      throw new Error(`Failed to fetch graph data for job ${jobId}`);
    }
    return res.json();
  }

  /**
   * Get job status and metadata by job_id
   */
  async getJobStatus(
    jobId: string
  ): Promise<{
    job_id: string;
    status: string;
    source_uri: string;
    created_at: string;
    updated_at: string;
    error_message?: string;
  }> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/status`);
    if (!res.ok) {
      throw new Error(`Failed to fetch job status: ${res.statusText || `HTTP ${res.status}`}`);
    }
    return res.json();
  }

  /**
   * List all configured Storage Endpoint Providers (SEP)
   */
  async getSEPProviders(): Promise<SEPProvider[]> {
    const res = await fetch(`${API_BASE}/sep/providers`);
    if (!res.ok) {
      throw new Error(`Failed to fetch SEP providers: ${res.statusText || `HTTP ${res.status}`}`);
    }
    return res.json();
  }

  /**
   * Create/register a new Storage Endpoint Provider
   */
  async createSEPProvider(data: {
    name: string;
    sep_type: string;
    credentials?: Record<string, string>;
    options?: Record<string, any>;
  }): Promise<SEPProvider> {
    const res = await fetch(`${API_BASE}/sep/providers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to create SEP provider');
    }
    return res.json();
  }

  /**
   * Browse file tree / list directory for a SEP provider
   */
  async browseSEPProvider(
    providerId: string,
    folderPath = '/'
  ): Promise<SEPRemoteFile[]> {
    const url = `${API_BASE}/sep/providers/${providerId}/browse?path=${encodeURIComponent(folderPath)}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`Failed to browse SEP provider folder: ${res.statusText || `HTTP ${res.status}`}`);
    }
    return res.json();
  }

  /**
   * List all processed documents
   */
  async listDocuments(): Promise<any[]> {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) throw new Error(`Failed to fetch documents: ${res.statusText}`);
    return res.json();
  }

  /**
   * Get parsed KRM result for a job
   */
  async getJobResult(jobId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/result`);
    if (!res.ok) throw new Error(`Failed to fetch job result: ${res.statusText}`);
    return res.json();
  }

  async getChunks(jobId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/chunks`);
    if (!res.ok) throw new Error(`Failed to fetch chunks: ${res.statusText}`);
    return res.json();
  }

  async getJobProgress(jobId: string): Promise<{
    job_id: string;
    status: string;
    step: number;
    total: number;
    stage: string;
    error?: string;
  }> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/progress`);
    if (!res.ok) throw new Error(`Failed to fetch progress: ${res.statusText}`);
    return res.json();
  }

  async refineNode(jobId: string, nodeId: string, mode: 'agent' | 'manual', patch?: Record<string, any>): Promise<{ status: string; node_id: string; confidence?: number; llm_result?: { type: string; confidence: number } }> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node_id: nodeId, mode, patch }),
    });
    if (!res.ok) throw new Error(`Failed to refine node: ${res.statusText}`);
    return res.json();
  }

  async translatePage(jobId: string, pageNumber: number, sourceText: string): Promise<{ translated_text: string; page_number: number }> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_number: pageNumber, source_text: sourceText }),
    });
    if (!res.ok) throw new Error(`Failed to translate: ${res.statusText}`);
    return res.json();
  }

  async deleteJob(jobId: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`Failed to delete: ${res.statusText}`);
    return res.json();
  }

  async getAgentConfig(): Promise<{ agents: Array<{ name: string; host: string; models: string[]; active_model: string; available: boolean }> }> {
    const res = await fetch(`${API_BASE}/agents/config`);
    if (!res.ok) throw new Error(`Failed to get agent config: ${res.statusText}`);
    return res.json();
  }

  async addAgent(name: string, host: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/agents/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, host }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to add agent');
    }
    return res.json();
  }

  async updateAgent(name: string, host: string, active_model: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/agents/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, host, active_model }),
    });
    if (!res.ok) throw new Error(`Failed to update agent: ${res.statusText}`);
    return res.json();
  }

  async deleteAgent(host: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(host)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`Failed to delete agent: ${res.statusText}`);
    return res.json();
  }

  /**
   * Subscribe to Server-Sent Events (SSE) broadcasting all PyJobKit job progress events
   */
  subscribeToJobStream(onEvent: (event: KAEJobEvent) => void): () => void {
    const eventSource = new EventSource(`${API_BASE}/jobs/stream`);

    eventSource.onmessage = (e) => {
      try {
        if (!e.data || e.data.trim() === '') return;
        const parsed = JSON.parse(e.data);
        onEvent(parsed);
      } catch (err) {
        console.warn('SSE parse error:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.warn('SSE connection warning:', err);
    };

    return () => {
      eventSource.close();
    };
  }

  /**
   * Connect to WebSocket tracking real-time status and progress events for a specific job_id
   */
  subscribeToJobWebSocket(
    jobId: string,
    onEvent: (event: KAEJobEvent) => void
  ): () => void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API_BASE}/ws/jobs/${jobId}`;
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        onEvent(parsed);
      } catch (err) {
        console.warn('WebSocket message parse error:', err);
      }
    };

    socket.onerror = (err) => {
      console.warn('WebSocket error:', err);
    };

    return () => {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    };
  }
}

export const kaeApi = new KAEApiClient();
export default kaeApi;
