import React, { useState, useEffect } from 'react';
import {
  HardDrive,
  Cloud,
  Folder,
  FileText,
  Plus,
  RefreshCw,
  CheckCircle2,
  X,
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  Database,
  Globe,
  HardDriveUpload,
  Download,
} from 'lucide-react';
import kaeApi from '../api/client';
import { SEPProvider, SEPRemoteFile } from '../types';

interface SEPSourcesDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onImportSuccess?: (jobId: string, sourceUri: string) => void;
}

type DialogView = 'providers' | 'browse' | 'add';

export const SEPSourcesDialog: React.FC<SEPSourcesDialogProps> = ({
  isOpen,
  onClose,
  onImportSuccess,
}) => {
  const [providers, setProviders] = useState<SEPProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<SEPProvider | null>(null);
  const [currentFolderPath, setCurrentFolderPath] = useState<string>('/');
  const [files, setFiles] = useState<SEPRemoteFile[]>([]);
  const [isLoadingProviders, setIsLoadingProviders] = useState<boolean>(false);
  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const [confirmImport, setConfirmImport] = useState<SEPRemoteFile | null>(null);
  const [view, setView] = useState<DialogView>('providers');
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Add Provider form state
  const [newProviderName, setNewProviderName] = useState('');
  const [newProviderType, setNewProviderType] = useState<'local_nvme' | 's3_minio' | 'webdav' | 'gdrive'>('local_nvme');
  const [newS3Bucket, setNewS3Bucket] = useState('kae-documents-bucket');
  const [newS3Endpoint, setNewS3Endpoint] = useState('https://minio.local:9000');
  const [newWebDavUrl, setNewWebDavUrl] = useState('https://webdav.storage.internal');
  const [newLocalPath, setNewLocalPath] = useState('/mnt/ssd');
  const [isAddingProvider, setIsAddingProvider] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setView('providers');
      setSelectedProvider(null);
      setConfirmImport(null);
      setFeedbackMsg(null);
      loadProviders();
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedProvider && view === 'browse') {
      loadFiles(selectedProvider.provider_id, currentFolderPath);
    }
  }, [selectedProvider, currentFolderPath, view]);

  const loadProviders = async () => {
    setIsLoadingProviders(true);
    try {
      const data = await kaeApi.getSEPProviders();
      setProviders(data);
    } catch (err: any) {
      console.error('Failed to load SEP providers:', err);
    } finally {
      setIsLoadingProviders(false);
    }
  };

  const loadFiles = async (providerId: string, path: string) => {
    setIsLoadingFiles(true);
    try {
      const items = await kaeApi.browseSEPProvider(providerId, path);
      setFiles(items);
    } catch (err: any) {
      console.error('Failed to browse folder:', err);
      setFiles([]);
    } finally {
      setIsLoadingFiles(false);
    }
  };

  const handleOpenBrowser = (provider: SEPProvider) => {
    setSelectedProvider(provider);
    setCurrentFolderPath('/');
    setView('browse');
  };

  const handleImportFile = async (fileItem: SEPRemoteFile) => {
    if (!selectedProvider) return;
    setIsImporting(true);
    setFeedbackMsg(null);
    setConfirmImport(null);
    try {
      const res = await kaeApi.importFromSEP(selectedProvider.provider_id, fileItem.file_id);
      setFeedbackMsg({
        type: 'success',
        text: `"${fileItem.name}" импортирован в KAE (Job: ${res.job_id.slice(0, 8)}…)`,
      });
      if (onImportSuccess) {
        onImportSuccess(res.job_id, res.source_uri);
      }
      setTimeout(onClose, 1500);
    } catch (err: any) {
      setFeedbackMsg({
        type: 'error',
        text: err.message || 'Ошибка импорта',
      });
    } finally {
      setIsImporting(false);
    }
  };

  const handleCreateProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProviderName.trim()) return;
    setIsAddingProvider(true);
    try {
      const opts: Record<string, any> = {};
      if (newProviderType === 's3_minio') {
        opts['bucket'] = newS3Bucket;
        opts['endpoint'] = newS3Endpoint;
      } else if (newProviderType === 'webdav') {
        opts['url'] = newWebDavUrl;
      } else if (newProviderType === 'local_nvme') {
        opts['root_path'] = newLocalPath;
      }

      const created = await kaeApi.createSEPProvider({
        name: newProviderName,
        sep_type: newProviderType,
        credentials: {},
        options: opts,
      });

      setProviders((prev) => [...prev, created]);
      setNewProviderName('');
      setFeedbackMsg({ type: 'success', text: `"${created.name}" подключено.` });
      setView('providers');
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Не удалось подключить провайдер' });
    } finally {
      setIsAddingProvider(false);
    }
  };

  const getProviderIcon = (type: string) => {
    switch (type) {
      case 'local_nvme':
      case 'LOCAL_FS':
        return <HardDrive className="w-5 h-5 text-emerald-400" />;
      case 's3_minio':
        return <Database className="w-5 h-5 text-amber-400" />;
      case 'webdav':
        return <Globe className="w-5 h-5 text-sky-400" />;
      case 'gdrive':
        return <Cloud className="w-5 h-5 text-purple-400" />;
      default:
        return <Cloud className="w-5 h-5 text-slate-400" />;
    }
  };

  const getProviderTypeLabel = (type: string) => {
    switch (type) {
      case 'local_nvme':
      case 'LOCAL_FS':
        return 'Local NVMe SSD';
      case 's3_minio':
        return 'S3 / MinIO';
      case 'webdav':
        return 'WebDAV';
      case 'gdrive':
        return 'Google Drive';
      default:
        return type;
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden text-slate-100">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center space-x-3">
            {view !== 'providers' && (
              <button
                onClick={() => { setView('providers'); setConfirmImport(null); }}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors mr-1"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-xl">
              <HardDriveUpload className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">
                {view === 'providers' && 'Хранилища SEP'}
                {view === 'browse' && selectedProvider?.name}
                {view === 'add' && 'Подключить хранилище'}
              </h2>
              <p className="text-xs text-slate-400">
                {view === 'providers' && 'Подключённые источники данных (RFC 0013 L3)'}
                {view === 'browse' && `${getProviderTypeLabel(selectedProvider?.sep_type || '')} — обзор файлов`}
                {view === 'add' && 'Local NVMe, S3/MinIO, WebDAV или Google Drive'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Feedback */}
        {feedbackMsg && (
          <div className={`px-6 py-2.5 text-xs flex items-center justify-between ${
            feedbackMsg.type === 'success'
              ? 'bg-emerald-500/10 text-emerald-300 border-b border-emerald-500/20'
              : 'bg-rose-500/10 text-rose-300 border-b border-rose-500/20'
          }`}>
            <div className="flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4" />
              <span>{feedbackMsg.text}</span>
            </div>
            <button onClick={() => setFeedbackMsg(null)} className="hover:opacity-80">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* ===== PROVIDERS LIST ===== */}
          {view === 'providers' && (
            <div className="p-6 space-y-4">
              {isLoadingProviders ? (
                <div className="py-12 text-center text-xs text-slate-500 flex flex-col items-center space-y-2">
                  <RefreshCw className="w-5 h-5 animate-spin text-indigo-400" />
                  <span>Загрузка провайдеров...</span>
                </div>
              ) : providers.length === 0 ? (
                <div className="py-12 text-center space-y-3">
                  <HardDrive className="w-10 h-10 text-slate-700 mx-auto" />
                  <p className="text-sm text-slate-400">Нет подключённых хранилищ</p>
                  <button
                    onClick={() => setView('add')}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-xl inline-flex items-center space-x-2"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Подключить первое хранилище</span>
                  </button>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {providers.map((p) => (
                      <button
                        key={p.provider_id}
                        onClick={() => handleOpenBrowser(p)}
                        className="flex items-center justify-between p-4 rounded-xl border bg-slate-900/60 border-slate-800/80 hover:border-indigo-500/40 hover:bg-indigo-500/5 text-left transition-all group"
                      >
                        <div className="flex items-center space-x-3 min-w-0">
                          {getProviderIcon(p.sep_type)}
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-white truncate">{p.name}</div>
                            <div className="text-[11px] text-slate-400">{getProviderTypeLabel(p.sep_type)}</div>
                          </div>
                        </div>
                        <div className="flex items-center space-x-2 shrink-0">
                          <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
                          <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-indigo-400 transition-colors" />
                        </div>
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() => setView('add')}
                    className="w-full p-3 rounded-xl border border-dashed border-slate-700 text-slate-400 hover:text-white hover:border-indigo-500/40 text-xs flex items-center justify-center space-x-2 transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Подключить ещё хранилище</span>
                  </button>
                </>
              )}
            </div>
          )}

          {/* ===== FILE BROWSER ===== */}
          {view === 'browse' && selectedProvider && (
            <div className="flex flex-col h-full">
              {/* Breadcrumbs + refresh */}
              <div className="px-5 py-2.5 border-b border-slate-800/80 bg-slate-950/30 flex items-center justify-between text-xs">
                <div className="flex items-center space-x-2 text-slate-400">
                  <span className="font-medium">Путь:</span>
                  <button
                    onClick={() => setCurrentFolderPath('/')}
                    className="hover:text-indigo-400 font-mono transition-colors"
                  >
                    /
                  </button>
                  {currentFolderPath !== '/' &&
                    currentFolderPath
                      .split('/')
                      .filter(Boolean)
                      .map((part, idx, arr) => (
                        <React.Fragment key={idx}>
                          <ChevronRight className="w-3.5 h-3.5 text-slate-600" />
                          <button
                            onClick={() => setCurrentFolderPath('/' + arr.slice(0, idx + 1).join('/'))}
                            className="hover:text-indigo-400 font-mono transition-colors"
                          >
                            {part}
                          </button>
                        </React.Fragment>
                      ))}
                </div>
                <button
                  onClick={() => selectedProvider && loadFiles(selectedProvider.provider_id, currentFolderPath)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-1 transition-colors"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isLoadingFiles ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {/* File list */}
              <div className="flex-1 overflow-y-auto p-4">
                {isLoadingFiles ? (
                  <div className="py-12 text-center text-xs text-slate-500 flex flex-col items-center space-y-2">
                    <RefreshCw className="w-5 h-5 animate-spin text-indigo-400" />
                    <span>Чтение директории...</span>
                  </div>
                ) : files.length === 0 ? (
                  <div className="py-12 text-center text-xs text-slate-500 flex flex-col items-center space-y-2">
                    <Folder className="w-8 h-8 text-slate-700" />
                    <span>Папка пуста</span>
                  </div>
                ) : (
                  <div className="space-y-1">
                    {files.map((file) => (
                      <div
                        key={file.file_id}
                        onClick={() => {
                          if (file.is_directory) {
                            setCurrentFolderPath(file.path);
                          } else {
                            setConfirmImport(file);
                          }
                        }}
                        className="flex items-center justify-between p-2.5 rounded-xl border bg-slate-900/50 border-slate-800/60 text-xs cursor-pointer hover:bg-slate-800/60 hover:text-white text-slate-300 transition-all"
                      >
                        <div className="flex items-center space-x-3 min-w-0">
                          {file.is_directory ? (
                            <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                          ) : (
                            <FileText className="w-4 h-4 text-indigo-400 shrink-0" />
                          )}
                          <span className="font-mono text-slate-200 truncate">{file.name}</span>
                        </div>
                        <div className="flex items-center space-x-3 shrink-0 text-slate-400 text-[11px]">
                          <span>{file.is_directory ? 'Папка' : formatBytes(file.size_bytes)}</span>
                          {file.is_directory && <ChevronRight className="w-3.5 h-3.5" />}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Import confirmation bar */}
              {confirmImport && (
                <div className="px-5 py-3 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between">
                  <div className="flex items-center space-x-3 min-w-0 text-xs">
                    <Download className="w-4 h-4 text-indigo-400 shrink-0" />
                    <span className="text-slate-300 truncate">
                      Импортировать <span className="text-white font-medium">{confirmImport.name}</span> ({formatBytes(confirmImport.size_bytes)}) в KAE?
                    </span>
                  </div>
                  <div className="flex items-center space-x-2 shrink-0">
                    <button
                      onClick={() => setConfirmImport(null)}
                      className="px-3 py-1.5 text-xs text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
                    >
                      Отмена
                    </button>
                    <button
                      onClick={() => handleImportFile(confirmImport)}
                      disabled={isImporting}
                      className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg flex items-center space-x-1.5 transition-all disabled:opacity-50"
                    >
                      {isImporting ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <>
                          <span>Импортировать</span>
                          <ArrowRight className="w-3 h-3" />
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ===== ADD PROVIDER FORM ===== */}
          {view === 'add' && (
            <form onSubmit={handleCreateProvider} className="p-6 space-y-5">
              <div className="space-y-4 text-xs">
                <div>
                  <label className="block text-slate-300 font-medium mb-1.5">Название подключения</label>
                  <input
                    type="text"
                    value={newProviderName}
                    onChange={(e) => setNewProviderName(e.target.value)}
                    placeholder="например: RPi5 NVMe SSD"
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-medium mb-1.5">Тип хранилища</label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 'local_nvme', label: 'Local NVMe SSD', icon: HardDrive },
                      { id: 's3_minio', label: 'S3 / MinIO', icon: Database },
                      { id: 'webdav', label: 'WebDAV', icon: Globe },
                      { id: 'gdrive', label: 'Google Drive', icon: Cloud },
                    ].map((item) => {
                      const Icon = item.icon;
                      const isSel = newProviderType === item.id;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setNewProviderType(item.id as any)}
                          className={`flex items-center space-x-2.5 p-3 rounded-xl border text-left transition-all ${
                            isSel
                              ? 'bg-indigo-600/20 border-indigo-500 text-white font-medium'
                              : 'bg-slate-950/60 border-slate-800/80 text-slate-400 hover:text-slate-200'
                          }`}
                        >
                          <Icon className={`w-4 h-4 ${isSel ? 'text-indigo-400' : 'text-slate-500'}`} />
                          <span>{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {newProviderType === 's3_minio' && (
                  <div className="space-y-3 pt-2">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">S3 Bucket</label>
                      <input
                        type="text"
                        value={newS3Bucket}
                        onChange={(e) => setNewS3Bucket(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Endpoint URL</label>
                      <input
                        type="text"
                        value={newS3Endpoint}
                        onChange={(e) => setNewS3Endpoint(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                      />
                    </div>
                  </div>
                )}

                {newProviderType === 'webdav' && (
                  <div className="pt-2">
                    <label className="block text-slate-300 font-medium mb-1">WebDAV URL</label>
                    <input
                      type="text"
                      value={newWebDavUrl}
                      onChange={(e) => setNewWebDavUrl(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                    />
                  </div>
                )}

                {newProviderType === 'local_nvme' && (
                  <div className="pt-2">
                    <label className="block text-slate-300 font-medium mb-1">Путь к хранилищу</label>
                    <input
                      type="text"
                      value={newLocalPath}
                      onChange={(e) => setNewLocalPath(e.target.value)}
                      placeholder="/mnt/ssd"
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                    />
                  </div>
                )}
              </div>

              <div className="pt-4 flex items-center justify-end space-x-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setView('providers')}
                  className="px-4 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors text-xs"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={isAddingProvider || !newProviderName.trim()}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-xl flex items-center space-x-2 transition-all disabled:opacity-50 text-xs"
                >
                  {isAddingProvider ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Подключение...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      <span>Подключить</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default SEPSourcesDialog;
