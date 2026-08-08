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
  ArrowRight,
  ChevronRight,
  Database,
  Globe,
  HardDriveUpload,
} from 'lucide-react';
import kaeApi from '../api/client';
import { SEPProvider, SEPRemoteFile } from '../types';

interface SEPSourcesDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onImportSuccess?: (jobId: string, sourceUri: string) => void;
}

export const SEPSourcesDialog: React.FC<SEPSourcesDialogProps> = ({
  isOpen,
  onClose,
  onImportSuccess,
}) => {
  const [providers, setProviders] = useState<SEPProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>('');
  const [currentFolderPath, setCurrentFolderPath] = useState<string>('/');
  const [files, setFiles] = useState<SEPRemoteFile[]>([]);
  const [isLoadingProviders, setIsLoadingProviders] = useState<boolean>(false);
  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const [selectedFile, setSelectedFile] = useState<SEPRemoteFile | null>(null);
  const [activeTab, setActiveTab] = useState<'browse' | 'add'>('browse');

  // Add Provider form state
  const [newProviderName, setNewProviderName] = useState('');
  const [newProviderType, setNewProviderType] = useState<'local_nvme' | 's3_minio' | 'webdav' | 'gdrive'>('s3_minio');
  const [newS3Bucket, setNewS3Bucket] = useState('kae-documents-bucket');
  const [newS3Endpoint, setNewS3Endpoint] = useState('https://minio.local:9000');
  const [newWebDavUrl, setNewWebDavUrl] = useState('https://webdav.storage.internal');
  const [isAddingProvider, setIsAddingProvider] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadProviders();
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedProviderId) {
      loadFiles(selectedProviderId, currentFolderPath);
    }
  }, [selectedProviderId, currentFolderPath]);

  const loadProviders = async () => {
    setIsLoadingProviders(true);
    try {
      const data = await kaeApi.getSEPProviders();
      setProviders(data);
      if (data.length > 0 && !selectedProviderId) {
        setSelectedProviderId(data[0].provider_id);
      }
    } catch (err: any) {
      console.error('Failed to load SEP providers:', err);
    } finally {
      setIsLoadingProviders(false);
    }
  };

  const loadFiles = async (providerId: string, path: string) => {
    setIsLoadingFiles(true);
    setSelectedFile(null);
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

  const handleImportFile = async (fileItem: SEPRemoteFile) => {
    if (!selectedProviderId) return;
    setIsImporting(true);
    setFeedbackMsg(null);
    try {
      const res = await kaeApi.importFromSEP(selectedProviderId, fileItem.file_id);
      setFeedbackMsg({
        type: 'success',
        text: `Документ "${fileItem.name}" успешно отправлен в KAE! Job ID: ${res.job_id}`,
      });
      if (onImportSuccess) {
        onImportSuccess(res.job_id, res.source_uri);
      }
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err: any) {
      setFeedbackMsg({
        type: 'error',
        text: err.message || 'Ошибка импорта файла из хранилища SEP',
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
      const creds: Record<string, string> = {};
      const opts: Record<string, any> = {};

      if (newProviderType === 's3_minio') {
        opts['bucket'] = newS3Bucket;
        opts['endpoint'] = newS3Endpoint;
      } else if (newProviderType === 'webdav') {
        opts['url'] = newWebDavUrl;
      }

      const created = await kaeApi.createSEPProvider({
        name: newProviderName,
        sep_type: newProviderType,
        credentials: creds,
        options: opts,
      });

      setProviders((prev) => [...prev, created]);
      setSelectedProviderId(created.provider_id);
      setActiveTab('browse');
      setNewProviderName('');
      setFeedbackMsg({ type: 'success', text: `Хранилище "${created.name}" успешно подключено.` });
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Не удалось зарегистрировать провайдер' });
    } finally {
      setIsAddingProvider(false);
    }
  };

  const getProviderIcon = (type: string) => {
    switch (type) {
      case 'local_nvme':
        return <HardDrive className="w-4 h-4 text-emerald-400" />;
      case 's3_minio':
        return <Database className="w-4 h-4 text-amber-400" />;
      case 'webdav':
        return <Globe className="w-4 h-4 text-sky-400" />;
      case 'gdrive':
        return <Cloud className="w-4 h-4 text-purple-400" />;
      default:
        return <Cloud className="w-4 h-4 text-slate-400" />;
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden text-slate-100">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-xl">
              <HardDriveUpload className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Интеграция SEP Хранилищ</h2>
              <p className="text-xs text-slate-400">
                Подключение и прямое сканирование Local NVMe, S3/MinIO, WebDAV и Google Drive
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

        {/* Feedback Alert */}
        {feedbackMsg && (
          <div
            className={`px-6 py-2.5 text-xs flex items-center justify-between ${
              feedbackMsg.type === 'success'
                ? 'bg-emerald-500/10 text-emerald-300 border-b border-emerald-500/20'
                : 'bg-rose-500/10 text-rose-300 border-b border-rose-500/20'
            }`}
          >
            <div className="flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4" />
              <span>{feedbackMsg.text}</span>
            </div>
            <button onClick={() => setFeedbackMsg(null)} className="hover:opacity-80">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Tabs & Toolbar */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-slate-800 bg-slate-950/40 text-xs">
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setActiveTab('browse')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                activeTab === 'browse'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              Обзор файлов
            </button>
            <button
              onClick={() => setActiveTab('add')}
              className={`px-3 py-1.5 rounded-lg font-medium flex items-center space-x-1.5 transition-colors ${
                activeTab === 'add'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Подключить SEP провайдер</span>
            </button>
          </div>

          {activeTab === 'browse' && (
            <button
              onClick={() => selectedProviderId && loadFiles(selectedProviderId, currentFolderPath)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-1 transition-colors"
              title="Обновить список"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoadingFiles ? 'animate-spin' : ''}`} />
              <span>Обновить</span>
            </button>
          )}
        </div>

        {/* Main Content Area */}
        <div className="flex-1 overflow-hidden flex flex-col md:flex-row">
          {activeTab === 'browse' ? (
            <>
              {/* Sidebar Provider List */}
              <div className="w-full md:w-64 border-r border-slate-800 p-4 bg-slate-950/20 overflow-y-auto space-y-2">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-2 mb-2">
                  Источники SEP
                </div>
                {isLoadingProviders ? (
                  <div className="p-4 text-center text-xs text-slate-500">Загрузка провайдеров...</div>
                ) : providers.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500">Нет подключенных провайдеров</div>
                ) : (
                  providers.map((p) => {
                    const isSelected = p.provider_id === selectedProviderId;
                    return (
                      <button
                        key={p.provider_id}
                        onClick={() => {
                          setSelectedProviderId(p.provider_id);
                          setCurrentFolderPath('/');
                        }}
                        className={`w-full flex items-center justify-between p-2.5 rounded-xl border text-left transition-all ${
                          isSelected
                            ? 'bg-indigo-500/10 border-indigo-500/30 text-white font-medium shadow-sm'
                            : 'bg-slate-900/40 border-slate-800/80 text-slate-300 hover:bg-slate-800/60 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center space-x-2.5 min-w-0">
                          {getProviderIcon(p.sep_type)}
                          <span className="text-xs truncate">{p.name}</span>
                        </div>
                        <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" />
                      </button>
                    );
                  })
                )}
              </div>

              {/* Main File Explorer */}
              <div className="flex-1 flex flex-col overflow-hidden bg-slate-900/20">
                {/* Breadcrumbs */}
                <div className="px-5 py-2.5 border-b border-slate-800/80 bg-slate-950/30 flex items-center space-x-2 text-xs text-slate-400">
                  <span className="text-slate-400 font-medium">Путь:</span>
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
                            onClick={() => {
                              const newPath = '/' + arr.slice(0, idx + 1).join('/');
                              setCurrentFolderPath(newPath);
                            }}
                            className="hover:text-indigo-400 font-mono transition-colors"
                          >
                            {part}
                          </button>
                        </React.Fragment>
                      ))}
                </div>

                {/* File List */}
                <div className="flex-1 overflow-y-auto p-4">
                  {isLoadingFiles ? (
                    <div className="py-12 text-center text-xs text-slate-500 flex flex-col items-center space-y-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-indigo-400" />
                      <span>Чтение директории хранилища...</span>
                    </div>
                  ) : files.length === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-500 flex flex-col items-center space-y-2">
                      <Folder className="w-8 h-8 text-slate-700" />
                      <span>Папка пуста или недоступна</span>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {files.map((file) => {
                        const isSelected = selectedFile?.file_id === file.file_id;
                        return (
                          <div
                            key={file.file_id}
                            onClick={() => {
                              if (file.is_directory) {
                                setCurrentFolderPath(file.path);
                              } else {
                                setSelectedFile(file);
                              }
                            }}
                            className={`flex items-center justify-between p-2.5 rounded-xl border text-xs cursor-pointer transition-all ${
                              isSelected
                                ? 'bg-indigo-500/15 border-indigo-500/40 text-white'
                                : 'bg-slate-900/50 border-slate-800/60 text-slate-300 hover:bg-slate-800/60 hover:text-white'
                            }`}
                          >
                            <div className="flex items-center space-x-3 min-w-0">
                              {file.is_directory ? (
                                <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                              ) : (
                                <FileText className="w-4 h-4 text-indigo-400 shrink-0" />
                              )}
                              <span className="font-mono text-slate-200 truncate">{file.name}</span>
                            </div>

                            <div className="flex items-center space-x-4 shrink-0 text-slate-400 text-[11px]">
                              <span>{file.is_directory ? 'Папка' : formatBytes(file.size_bytes)}</span>
                              {!file.is_directory && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleImportFile(file);
                                  }}
                                  disabled={isImporting}
                                  className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg flex items-center space-x-1 transition-all disabled:opacity-50"
                                >
                                  <span>Импорт</span>
                                  <ArrowRight className="w-3 h-3" />
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            /* Add SEP Provider Form */
            <form onSubmit={handleCreateProvider} className="flex-1 p-6 overflow-y-auto space-y-5">
              <div>
                <h3 className="text-sm font-semibold text-white">Регистрация нового SEP Провайдера</h3>
                <p className="text-xs text-slate-400">
                  Подключите внешний или локальный источник данных для автоматической сборки KAE
                </p>
              </div>

              <div className="space-y-4 text-xs">
                <div>
                  <label className="block text-slate-300 font-medium mb-1.5">Название подключения</label>
                  <input
                    type="text"
                    value={newProviderName}
                    onChange={(e) => setNewProviderName(e.target.value)}
                    placeholder="например: Production MinIO Cluster"
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-medium mb-1.5">Тип провайдера хранилища</label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: 's3_minio', label: 'S3 / MinIO Storage', icon: Database },
                      { id: 'local_nvme', label: 'Local NVMe Storage', icon: HardDrive },
                      { id: 'webdav', label: 'WebDAV Protocol', icon: Globe },
                      { id: 'gdrive', label: 'Google Drive API', icon: Cloud },
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
                      <label className="block text-slate-300 font-medium mb-1">Имя S3 Баккета</label>
                      <input
                        type="text"
                        value={newS3Bucket}
                        onChange={(e) => setNewS3Bucket(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">S3 Endpoint URL</label>
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
                    <label className="block text-slate-300 font-medium mb-1">WebDAV Server URL</label>
                    <input
                      type="text"
                      value={newWebDavUrl}
                      onChange={(e) => setNewWebDavUrl(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono"
                    />
                  </div>
                )}
              </div>

              <div className="pt-4 flex items-center justify-end space-x-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setActiveTab('browse')}
                  className="px-4 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={isAddingProvider || !newProviderName.trim()}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-xl flex items-center space-x-2 transition-all disabled:opacity-50"
                >
                  {isAddingProvider ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Подключение...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      <span>Добавить провайдер</span>
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
