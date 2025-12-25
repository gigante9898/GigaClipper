import React, { useState, useEffect, useRef } from 'react'
import './App.css'
import { api, type Clip, type AppConfig } from './api'
import {
  Home,
  Library,
  Settings,
  Search,
  User,
  Gamepad2,
  Share2,
  Trash2,
  Play,
  Save,
  RotateCw,
  Folder,
  CloudUpload,
  CloudDownload,
  X,
  Maximize2,
  ChevronLeft,
  ChevronRight,
  Pause,
  Volume2,
  Scissors,
  Palette,
  Laptop,
  Cloud,
  CloudLightning,
  Ghost,
  LogIn,
  Check
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean, error: any }> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: any) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 20, color: 'white' }}>
          <h1>Something went wrong.</h1>
          <pre>{this.state.error?.toString()}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

// Helper component for processes
function RunningProcessesList({ onAdd }: { onAdd: (name: string) => void }) {
  const [procs, setProcs] = useState<string[]>([]);

  useEffect(() => {
    api.getProcesses().then(setProcs);
    const interval = setInterval(() => api.getProcesses().then(setProcs), 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', maxHeight: '150px', overflowY: 'auto' }}>
      {procs.filter(p => !['svchost.exe', 'conhost.exe', 'explorer.exe', 'chrome.exe', 'brave.exe', 'firefox.exe', 'msedge.exe', 'discord.exe'].includes(p)).map(p => (
        <button
          key={p}
          onClick={() => onAdd(p)}
          className="filter-chip"
          style={{ fontSize: '12px', padding: '4px 8px', opacity: 0.7 }}
        >
          {p.replace('.exe', '')}
        </button>
      ))}
    </div>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState('home')
  const [isRecording, setIsRecording] = useState(false)
  const [libraryTab, setLibraryTab] = useState<'local' | 'cloud' | 'edited' | 'cloud_edited'>('local')
  const [clips, setClips] = useState<Clip[]>([])
  const [loading, setLoading] = useState(false)
  const [previewClip, setPreviewClip] = useState<Clip | null>(null)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [windows, setWindows] = useState<{ id: number, title: string }[]>([])
  const [cloudConnected, setCloudConnected] = useState(false)
  const [settingsSection, setSettingsSection] = useState<'general' | 'recording' | 'cloud' | 'shortcuts'>('general')
  const [recentClips, setRecentClips] = useState<Clip[]>([]);
  const [totalSize, setTotalSize] = useState(0);
  const [currentGame, setCurrentGame] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ message: string, onConfirm: () => void } | null>(null);
  const libraryRequestId = useRef(0);
  const [updateAvailable, setUpdateAvailable] = useState<any>(null);
  const APP_VERSION = "1.0.0";

  // Show toast notification
  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => {
    // Poll for status and active game
    const interval = setInterval(async () => {
      const status = await api.getStatus();
      setIsRecording(status.running);
      if (status.current_game !== currentGame) setCurrentGame(status.current_game || null);
    }, 2000);
    return () => clearInterval(interval);
  }, []); // Remove dependency on currentGame to avoid loop, simple poll

  // Initial Home Load
  useEffect(() => {
    const fetchHomeData = async () => {
      const local = await api.getLocalFiles();
      setRecentClips(local.slice(0, 3));
      const size = local.reduce((acc, clip) => acc + (clip.size || 0), 0);
      setTotalSize(size);
    };

    const loadConfig = async () => {
      try {
        const settings = await api.getSettings();
        if (settings) setConfig(settings);
      } catch (e) {
        // Retry if failed (backend might be starting)
        setTimeout(loadConfig, 1000);
      }
    };

    if (activeTab === 'home') fetchHomeData();
    // Always load config on start
    loadConfig();
    checkAuthStatus(); // Check connectivity on start too

  }, [activeTab]);

  // Load Library with race condition protection

  const loadLibrary = async () => {
    const requestId = ++libraryRequestId.current;
    setLoading(true);
    let data: Clip[] = [];

    try {
      // Timeout promise
      const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), 10000));

      let fetchPromise;
      if (libraryTab === 'local' || libraryTab === 'edited') {
        fetchPromise = api.getLocalFiles();
      } else {
        fetchPromise = api.getCloudFiles();
      }

      // Race against timeout
      const result: any = await Promise.race([fetchPromise, timeoutPromise]);

      if (libraryTab === 'cloud' || libraryTab === 'cloud_edited') {
        if (result && result.auth_required) {
          setCloudConnected(false);
          data = [];
        } else if (Array.isArray(result)) {
          data = result;
          setCloudConnected(true);
        } else {
          console.error("Unexpected response:", result);
          data = [];
        }
      } else {
        data = result;
      }

    } catch (e: any) {
      console.error("Library load error:", e);
      if (e.message === "Timeout") {
        showToast("⚠️ Library load timed out.");
      }
      // If timed out or failed, we might want to keep previous data or empty
      // data = []; // Keep default empty
    }

    // Only update if this is the latest request
    if (requestId === libraryRequestId.current) {
      setClips(data);
      setLoading(false);
    }
  };

  // Check for updates via electron-updater (requires public GitHub repo)
  const checkForUpdates = (manual = false) => {
    if (window.electronAPI) {
      if (manual) showToast("🔍 Checking for updates...");
      window.electronAPI.sendMessage('check-for-updates');
    }
  };

  const handleUpdate = () => {
    if (updateAvailable) {
      window.electronAPI.sendMessage('quit-and-install');
    }
  };

  // Listen for update events from main process
  useEffect(() => {
    if (!window.electronAPI) return;

    window.electronAPI.onMessage('update-available', (info: any) => {
      setUpdateAvailable(info);
      showToast(`🎉 Update available: v${info.version}`);
    });

    window.electronAPI.onMessage('update-not-available', () => {
      console.log("No update available");
    });

    window.electronAPI.onMessage('update-downloaded', (info: any) => {
      setUpdateAvailable({ ...info, downloaded: true });
      showToast("✅ Update ready! Click to restart.");
    });

    window.electronAPI.onMessage('download-progress', (progress: any) => {
      console.log(`Download: ${Math.round(progress.percent)}%`);
    });

    window.electronAPI.onMessage('update-error', (err: string) => {
      console.log("Update error:", err);
    });

    // Check on startup
    checkForUpdates();
  }, []);

  // Check Cloud Auth Status
  const checkAuthStatus = async () => {
    const status = await api.getAuthStatus();
    setCloudConnected(!!status.connected);
  };

  // Connect to Drive
  const handleConnectDrive = async () => {
    showToast("🔐 Opening browser for Google login...");
    try {
      const res = await api.connectDrive();
      if (res.ok) {
        setCloudConnected(true);
        showToast("✅ Connected to Google Drive!");
      } else {
        showToast("❌ Login failed.");
      }
    } catch (e) {
      showToast("❌ Login error.");
    }
  };

  // Auto-reload library when tab changes
  useEffect(() => {
    if (activeTab === 'library') {
      loadLibrary();
      checkAuthStatus(); // Check connectivity
    }
  }, [activeTab, libraryTab]);

  // Load config and windows on initial mount
  useEffect(() => {
    api.getSettings().then(setConfig);
    api.getWindows().then(setWindows);
    checkAuthStatus();
  }, []);

  // Reload windows when going to settings tab
  useEffect(() => {
    if (activeTab === 'settings') {
      api.getWindows().then(setWindows);
    }
  }, [activeTab]);

  // Apply theme when config loads or changes
  useEffect(() => {
    if (config?.theme) {
      document.documentElement.setAttribute('data-theme', config.theme);
    }
  }, [config?.theme]);

  // Actions
  const handleClipClick = async (clip: Clip) => {
    // Open Preview Modal for BOTH local and cloud clips
    setPreviewClip(clip);
  };

  const handleToggleRecord = async () => {
    if (isRecording) {
      await api.stopRecording();
      setIsRecording(false);
    } else {
      await api.startRecording();
      setIsRecording(true);
    }
  };

  const handleSaveClip = async (duration: number | null) => {
    await api.saveClip(duration);
    showToast(`✅ Clip saved! (${duration ? duration + 's' : 'Full buffer'})`);
    if (activeTab === 'library' || activeTab === 'home') {
      setTimeout(loadLibrary, 4000);
    }
  };

  const handleUpload = async (e: React.MouseEvent, clip: Clip) => {
    e.stopPropagation();
    if (!clip.path) return;
    await api.uploadFile(clip.path);
    // Don't refresh immediately
  };

  const handleDownload = async (e: React.MouseEvent, clip: Clip) => {
    e.stopPropagation();
    if (!clip.id) return;
    await api.downloadFile(clip.id, clip.name);
  };

  const handleDelete = async (e: React.MouseEvent, clip: Clip) => {
    e.stopPropagation();

    setConfirmModal({
      message: `Delete "${clip.name}"?`,
      onConfirm: async () => {
        // Optimistic UI Update: Remove from list immediately
        setClips(prev => prev.filter(c => {
          // Filter by ID if cloud/local mixed, or path if only local
          if (c.id && clip.id) return c.id !== clip.id;
          if (c.path && clip.path) return c.path !== clip.path;
          return c !== clip;
        }));

        // Perform actual delete in background
        try {
          if ((libraryTab === 'local' || libraryTab === 'edited') && clip.path) {
            await api.deleteLocalFile(clip.path);
          } else if ((libraryTab === 'cloud' || libraryTab === 'cloud_edited') && clip.id) {
            await api.deleteCloudFile(clip.id);
          }
        } catch (e) {
          // Silently fail or show toast, but honestly if it fails user can refresh.
          // Keeping it simple as requested for "smoothness"
          console.error("Delete failed", e);
        }

        setConfirmModal(null);
      }
    });
  };

  const updateConfig = async (key: keyof AppConfig, value: any) => {
    if (!config) return;
    const newConfig = { ...config, [key]: value };
    setConfig(newConfig);
    await api.updateSettings({ [key]: value });
  };

  return (
    <div className="layout">
      {/* Toast Notification */}
      <AnimatePresence>
        {toast && (
          <motion.div
            className="toast-notification"
            initial={{ opacity: 0, y: -50 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -50 }}
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Custom Confirm Modal */}
      <AnimatePresence>
        {confirmModal && (
          <motion.div
            className="confirm-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setConfirmModal(null)}
          >
            <motion.div
              className="confirm-modal"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="confirm-icon">🗑️</div>
              <p className="confirm-message">{confirmModal.message}</p>
              <div className="confirm-buttons">
                <button className="btn-cancel" onClick={() => setConfirmModal(null)}>Cancel</button>
                <button className="btn-confirm" onClick={confirmModal.onConfirm}>Delete</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      {/* Sidebar */}
      <nav className="sidebar">
        <div className="logo">
          <Gamepad2 size={32} color="var(--accent-primary)" />
          <span className="logo-text">GIGA<span>CLIPPER</span></span>
        </div>

        <div className="nav-items">
          <NavItem
            icon={<Home size={20} />}
            label="Home"
            active={activeTab === 'home'}
            onClick={() => setActiveTab('home')}
          />
          <NavItem
            icon={<Library size={20} />}
            label="Library"
            active={activeTab === 'library'}
            onClick={() => setActiveTab('library')}
          />
          <NavItem
            icon={<Palette size={20} />}
            label="Themes"
            active={activeTab === 'themes'}
            onClick={() => setActiveTab('themes')}
          />
          <NavItem
            icon={<Settings size={20} />}
            label="Settings"
            active={activeTab === 'settings'}
            onClick={() => setActiveTab('settings')}
          />
        </div>

        <div className="sidebar-footer">
          <div className="user-profile">
            <div className="avatar">
              <User size={20} />
            </div>
            <div className="user-info">
              <span className="username">gigante9898</span>
              <span className="status">Online</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="content">
        <header className="topbar glass">
          <div className="search-bar">
            <Search size={18} className="search-icon" />
            <input type="text" placeholder="Search clips, games..." />
          </div>

          <div className="topbar-actions">
            <div className="recording-actions">
              <button className="btn-secondary" onClick={() => handleSaveClip(config?.clip_duration || 15)} disabled={!isRecording} style={{ opacity: isRecording ? 1 : 0.5, cursor: isRecording ? 'pointer' : 'not-allowed' }}>
                <Save size={16} /> Clip {config?.clip_duration || 15}s [{config?.hotkey_clip || 'F8'}]
              </button>
            </div>

            <button
              className="btn-primary"
              onClick={handleToggleRecord}
              style={{ backgroundColor: isRecording ? '#c0392b' : '' }}
            >
              <div className={isRecording ? "recording-dot" : ""} />
              {isRecording ? 'Stop Recording' : 'Start Recording'}
            </button>
          </div>
        </header>

        <section className="scroll-area">
          <AnimatePresence mode="wait">
            {activeTab === 'home' && (
              <motion.div
                key="home"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="view"
              >
                <h1>Welcome back!</h1>
                <p className="subtitle">Ready to capture some magic?</p>

                <div className="stats-grid">
                  <StatCard label="BUFFER STATUS" value={isRecording ? "ACTIVE" : "IDLE"} color={isRecording ? "#10b981" : "#64748b"} />
                  <StatCard label="GAME DETECTED" value={currentGame ? currentGame.replace(/\.exe$/i, '').replace(/\.bin$/i, '') : "None"} color={currentGame ? "#f59e0b" : "#475569"} />
                  <StatCard label="STORAGE USED" value={(totalSize / (1024 * 1024 * 1024)).toFixed(2) + " GB"} color="#3b82f6" />
                </div>

                <h2 className="section-title">Recent Clips</h2>
                <div className="recent-clips-row">
                  {recentClips.map((clip, i) => (
                    <ClipCard
                      key={i}
                      clip={clip}
                      isLocal={true}
                      onClick={() => setPreviewClip(clip)}
                      onUpload={(e) => handleUpload(e, clip)}
                      onDownload={(e) => handleDownload(e, clip)}
                      onDelete={(e) => handleDelete(e, clip)}
                    />
                  ))}
                  {recentClips.length === 0 && <p className="text-dim">No clips recorded yet.</p>}
                </div>

                <div className="quick-actions">
                  <button className="action-card" onClick={() => api.openFolder()}>
                    <Folder size={32} />
                    <span>Open Folder</span>
                  </button>
                </div>
              </motion.div>
            )}

            {activeTab === 'library' && (
              <motion.div
                key="library"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="view"
              >
                <div className="section-header">
                  <h1>Library</h1>
                  <button className="btn-icon" onClick={loadLibrary}><RotateCw size={18} /></button>
                </div>

                <div className="library-tabs-container" style={{
                  display: 'inline-flex',
                  background: 'rgba(0,0,0,0.3)',
                  padding: '4px',
                  borderRadius: '12px',
                  marginBottom: '20px',
                  gap: '4px'
                }}>
                  {[
                    { id: 'local', label: 'Local', icon: <Laptop size={16} /> },
                    { id: 'cloud', label: 'Cloud', icon: <Cloud size={16} /> },
                    { id: 'edited', label: 'Edits', icon: <Scissors size={16} /> },
                    { id: 'cloud_edited', label: 'Cloud Edits', icon: <CloudLightning size={16} /> }
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setLibraryTab(tab.id as any)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        padding: '8px 16px',
                        borderRadius: '8px',
                        border: 'none',
                        background: libraryTab === tab.id ? 'var(--accent)' : 'transparent',
                        color: libraryTab === tab.id ? 'white' : 'var(--text-dim)',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontWeight: 500,
                        transition: 'all 0.2s ease'
                      }}
                    >
                      {tab.icon}
                      {tab.label}
                    </button>
                  ))}
                </div>

                {loading ? (
                  <div className="loading-container">
                    <div className="spinner"></div>
                    <span>Loading clips...</span>
                  </div>
                ) : (() => {
                  // Connect Prompt when Disconnected
                  if ((libraryTab === 'cloud' || libraryTab === 'cloud_edited') && !cloudConnected) {
                    return (
                      <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '100%',
                        width: '100%',
                        minHeight: '400px',
                        color: 'var(--text-normal)'
                      }}>
                        <div style={{
                          background: 'rgba(255, 255, 255, 0.03)',
                          backdropFilter: 'blur(10px)',
                          border: '1px solid rgba(255, 255, 255, 0.05)',
                          padding: '60px 40px',
                          borderRadius: '24px',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          gap: '20px',
                          maxWidth: '400px',
                          textAlign: 'center',
                          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)'
                        }}>
                          <div style={{
                            background: 'linear-gradient(135deg, rgba(66, 133, 244, 0.2) 0%, rgba(66, 133, 244, 0.1) 100%)',
                            padding: '24px',
                            borderRadius: '50%',
                            marginBottom: '10px',
                            border: '1px solid rgba(66, 133, 244, 0.3)',
                            boxShadow: '0 0 20px rgba(66, 133, 244, 0.1)'
                          }}>
                            <Cloud size={48} color="#4285F4" strokeWidth={1.5} />
                          </div>

                          <div>
                            <h2 style={{ margin: '0 0 8px 0', fontSize: '1.5rem', fontWeight: 600 }}>Cloud Storage</h2>
                            <p style={{ margin: 0, color: 'var(--text-dim)', lineHeight: '1.5' }}>
                              Connect your Google Drive account to sync and access your clips from anywhere.
                            </p>
                          </div>

                          <button
                            className="btn-primary"
                            style={{
                              marginTop: '10px',
                              background: 'linear-gradient(135deg, #4285F4 0%, #3367D6 100%)',
                              border: 'none',
                              padding: '12px 24px',
                              fontSize: '1rem',
                              boxShadow: '0 4px 12px rgba(66, 133, 244, 0.3)'
                            }}
                            onClick={async () => {
                              // Navigate to settings > cloud
                              setActiveTab('settings');
                              setSettingsSection('cloud');
                            }}
                          >
                            Connect Drive
                          </button>
                        </div>
                      </div>
                    )
                  }

                  // Filter clips based on tab
                  let displayClips = clips;
                  if (libraryTab === 'edited') {
                    displayClips = clips.filter(c => c.name.includes('_trimmed_') || c.name.includes('_edit'));
                  } else if (libraryTab === 'local') {
                    displayClips = clips.filter(c => !c.name.includes('_trimmed_') && !c.name.includes('_edit'));
                  } else if (libraryTab === 'cloud_edited') {
                    displayClips = clips.filter(c => c.name.includes('_trimmed_') || c.name.includes('_edit'));
                  } else if (libraryTab === 'cloud') {
                    displayClips = clips.filter(c => !c.name.includes('_trimmed_') && !c.name.includes('_edit'));
                  }

                  return (
                    <div className="clips-grid" style={{ position: 'relative' }}>
                      <AnimatePresence mode="popLayout">
                        {displayClips.map((clip) => (
                          <ClipCard
                            key={clip.id || clip.path || clip.name}
                            clip={clip}
                            isLocal={libraryTab === 'local' || libraryTab === 'edited'}
                            onClick={() => handleClipClick(clip)}
                            onUpload={(e) => handleUpload(e, clip)}
                            onDownload={(e) => handleDownload(e, clip)}
                            onDelete={(e) => handleDelete(e, clip)}
                            // Pass motion props down
                            layout
                            initial={{ opacity: 0, scale: 0.8 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.5, transition: { duration: 0.2 } }}
                          />
                        ))}
                      </AnimatePresence>
                      {displayClips.length === 0 && !loading && (
                        <div style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          height: '400px',
                          width: '100%',
                          gridColumn: '1 / -1',
                          color: 'var(--text-dim)',
                          opacity: 0.7
                        }}>
                          <div style={{
                            background: 'rgba(255,255,255,0.05)',
                            padding: '40px',
                            borderRadius: '50%',
                            marginBottom: '20px',
                            border: '1px solid rgba(255,255,255,0.1)'
                          }}>
                            <Ghost size={64} strokeWidth={1.5} />
                          </div>
                          <h2 style={{ margin: '0 0 10px 0', color: 'var(--text-normal)', fontSize: '1.5rem' }}>It's quiet here...</h2>
                          <p style={{ margin: 0, fontSize: '1rem' }}>No clips found in {libraryTab.replace('cloud_', 'Cloud ').replace('_', ' ')} yet.</p>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </motion.div>
            )}

            {activeTab === 'themes' && config && (
              <motion.div
                key="themes"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="view"
              >
                <h1>🎨 Themes</h1>
                <p className="subtitle">Choose your vibe and make it yours</p>

                <div className="themes-section">
                  <h3 className="themes-category">✨ Signature</h3>
                  <div className="themes-grid">
                    <ThemeCard
                      name="Royal Plum"
                      emoji="🟣"
                      colors={['#d7dedc', '#9a879d', '#7a3b69', '#563440', '#1a1518']}
                      active={config.theme === 'default' || !config.theme}
                      onClick={() => updateConfig('theme', 'default')}
                    />
                  </div>
                </div>

                <div className="themes-section">
                  <h3 className="themes-category">🎨 User Palettes</h3>
                  <div className="themes-grid">
                    <ThemeCard
                      name="Coffee & Jasmine"
                      emoji="☕"
                      colors={['#f6e27f', '#e2c391', '#a8b7ab', '#9bbec7', '#251605']}
                      active={config.theme === 'coffee'}
                      onClick={() => updateConfig('theme', 'coffee')}
                    />
                    <ThemeCard
                      name="Sage & Olive"
                      emoji="🌿"
                      colors={['#ddd5d0', '#cfc0bd', '#b8b8aa', '#7f9183', '#586f6b']}
                      active={config.theme === 'sage'}
                      onClick={() => updateConfig('theme', 'sage')}
                    />
                    <ThemeCard
                      name="Forest Nature"
                      emoji="🌲"
                      colors={['#dbd2e0', '#7b904b', '#58641d', '#273b09', '#002400']}
                      active={config.theme === 'forest'}
                      onClick={() => updateConfig('theme', 'forest')}
                    />
                    <ThemeCard
                      name="Slate Grape"
                      emoji="🍇"
                      colors={['#a67db8', '#7261a3', '#4f5d75', '#395756', '#1b3022']}
                      active={config.theme === 'grape'}
                      onClick={() => updateConfig('theme', 'grape')}
                    />
                    <ThemeCard
                      name="Lavender Mist"
                      emoji="💜"
                      colors={['#d7dedc', '#cfcfcd', '#9a879d', '#7a3b69', '#563440']}
                      active={config.theme === 'lavender'}
                      onClick={() => updateConfig('theme', 'lavender')}
                    />
                  </div>
                </div>

                <div className="themes-section">
                  <h3 className="themes-category">🌟 Themed Vibes</h3>
                  <div className="themes-grid">
                    <ThemeCard
                      name="Sunset Chill"
                      emoji="🌅"
                      colors={['#ffecd2', '#fcb69f', '#ff8a80', '#ff6b6b', '#4a1c40']}
                      active={config.theme === 'sunset'}
                      onClick={() => updateConfig('theme', 'sunset')}
                    />
                    <ThemeCard
                      name="Ocean Cozy"
                      emoji="🌊"
                      colors={['#e0f7fa', '#80deea', '#26c6da', '#0097a7', '#00363a']}
                      active={config.theme === 'ocean'}
                      onClick={() => updateConfig('theme', 'ocean')}
                    />
                    <ThemeCard
                      name="Midnight Gaming"
                      emoji="🌙"
                      colors={['#e8eaff', '#a5b4fc', '#818cf8', '#6366f1', '#1e1b4b']}
                      active={config.theme === 'midnight'}
                      onClick={() => updateConfig('theme', 'midnight')}
                    />
                    <ThemeCard
                      name="Cherry Blossom"
                      emoji="🌸"
                      colors={['#fff5f5', '#ffc1cc', '#ffb3ba', '#ff8fa3', '#4a1c2e']}
                      active={config.theme === 'cherry'}
                      onClick={() => updateConfig('theme', 'cherry')}
                    />
                    <ThemeCard
                      name="Cyber Neon"
                      emoji="⚡"
                      colors={['#f0fff0', '#00ff9f', '#00d9ff', '#bd00ff', '#0d0221']}
                      active={config.theme === 'cyber'}
                      onClick={() => updateConfig('theme', 'cyber')}
                    />
                    <ThemeCard
                      name="Slate Monochrome"
                      emoji="🌑"
                      colors={['#F4F7F5', '#A7A2A9', '#575A5E', '#222823', '#08090A']}
                      active={config.theme === 'slate'}
                      onClick={() => updateConfig('theme', 'slate')}
                    />
                    <ThemeCard
                      name="Alice Teal"
                      emoji="🌊"
                      colors={['#E8F1F2', '#B3EFB2', '#7A9E7E', '#31493C', '#001A23']}
                      active={config.theme === 'alice'}
                      onClick={() => updateConfig('theme', 'alice')}
                    />
                    <ThemeCard
                      name="Rust Gold"
                      emoji="🔥"
                      colors={['#FBFFFE', '#E6AF2E', '#A3320B', '#6B0504', '#001514']}
                      active={config.theme === 'rust'}
                      onClick={() => updateConfig('theme', 'rust')}
                    />
                    <ThemeCard
                      id="olive"
                      name="Olive Beige"
                      emoji="🫒"
                      colors={['#E3E7D3', '#BDC2BF', '#989C94', '#25291C', '#1a1c14']}
                      active={config.theme === 'olive'}
                      onClick={() => updateConfig('theme', 'olive')}
                    />
                    <ThemeCard
                      id="coral"
                      name="Coral Bordeaux"
                      emoji="🌺"
                      colors={['#FF9B54', '#FF7F51', '#CE4257', '#720026', '#4F000B']}
                      active={config.theme === 'coral'}
                      onClick={() => updateConfig('theme', 'coral')}
                    />
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === 'settings' && config && (
              <motion.div
                key="settings"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="view settings-view"
                style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '20px' }}
              >
                <h1>Settings</h1>

                <div className="settings-layout" style={{ display: 'flex', gap: '30px', flex: 1, overflow: 'hidden' }}>

                  {/* Settings Sidebar */}
                  <div className="settings-sidebar" style={{ width: '200px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                    {['General', 'Recording', 'Cloud', 'Shortcuts'].map(section => {
                      const id = section.toLowerCase();
                      const isActive = settingsSection === id;
                      return (
                        <button
                          key={id}
                          onClick={() => setSettingsSection(id as any)}
                          style={{
                            textAlign: 'left',
                            padding: '10px 15px',
                            borderRadius: '8px',
                            background: isActive ? 'var(--accent)' : 'transparent',
                            color: isActive ? 'white' : 'var(--text-dim)',
                            border: 'none',
                            cursor: 'pointer',
                            fontWeight: 500
                          }}
                        >
                          {section}
                        </button>
                      )
                    })}
                  </div>

                  {/* Settings Content Area */}
                  <div className="settings-content" style={{ flex: 1, overflowY: 'auto', paddingRight: '10px' }}>

                    {/* GENERAL SECTION */}
                    {settingsSection === 'general' && (
                      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}>
                        <h3 className="section-title">General</h3>
                        <div className="settings-card">
                          <div className="setting-item">
                            <div className="setting-info">
                              <span>App Version</span>
                              <p>v{APP_VERSION}</p>
                            </div>
                            <button className="btn-secondary" onClick={() => checkForUpdates(true)}>
                              Check for Updates
                            </button>
                          </div>
                        </div>

                        <h3 className="section-title">Game Detection</h3>
                        <div className="settings-card">
                          <div className="setting-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                            <div className="setting-info" style={{ marginBottom: '10px' }}>
                              <span>Auto-Detect Games</span>
                              <p>Add game executables (.exe) to auto-record when launched.</p>
                            </div>

                            <div style={{ display: 'flex', gap: '10px', width: '100%', marginBottom: '10px' }}>
                              <input
                                type="text"
                                id="game-input"
                                placeholder="e.g. valorant.exe"
                                className="search-bar"
                                style={{ flex: 1, color: 'white' }}
                              />
                              <button
                                className="btn-primary"
                                style={{ padding: '8px 16px' }}
                                onClick={async () => {
                                  const input = document.getElementById('game-input') as HTMLInputElement;
                                  if (input && input.value) {
                                    await api.addGame(input.value);
                                    input.value = '';
                                    const conf = await api.getSettings();
                                    setConfig(conf);
                                  }
                                }}
                              >
                                Add
                              </button>
                            </div>

                            <div className="chips-container" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                              {config.auto_detect_apps?.map(app => (
                                <div key={app} className="filter-chip active" style={{ display: 'flex', alignItems: 'center', gap: '5px', paddingRight: '8px' }}>
                                  {app.replace('.exe', '')}
                                  <X
                                    size={14}
                                    style={{ cursor: 'pointer' }}
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      await api.removeGame(app);
                                      const conf = await api.getSettings();
                                      setConfig(conf);
                                    }}
                                  />
                                </div>
                              ))}
                            </div>

                            <div style={{ marginTop: '20px', width: '100%', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '15px' }}>
                              <div className="setting-info" style={{ marginBottom: '10px' }}>
                                <span>Detected Running Games</span>
                                <p>Click to add to auto-record list</p>
                              </div>
                              <RunningProcessesList onAdd={async (name) => {
                                await api.addGame(name);
                                const conf = await api.getSettings();
                                setConfig(conf);
                              }} />
                            </div>
                          </div>
                        </div>
                      </motion.div>
                    )}

                    {/* RECORDING SECTION */}
                    {settingsSection === 'recording' && (
                      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}>
                        <h3 className="section-title">Capture Settings</h3>
                        <div className="settings-card">
                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Output Folder</span>
                              <p style={{ fontSize: '0.8rem', opacity: 0.6, maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {config.output_folder}
                              </p>
                            </div>
                            <button
                              className="btn-secondary"
                              style={{ padding: '8px 12px', gap: '6px' }}
                              onClick={async () => {
                                const res = await api.pickFolder();
                                if (res && res.path) {
                                  updateConfig('output_folder', res.path);
                                }
                              }}
                            >
                              <Folder size={14} /> Browse
                            </button>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Target FPS</span>
                              <p>Recording Framerate</p>
                            </div>
                            <select
                              value={config.fps}
                              onChange={(e) => updateConfig('fps', parseInt(e.target.value))}
                              className="setting-select"
                            >
                              <option value={30}>30 FPS</option>
                              <option value={60}>60 FPS</option>
                              <option value={120}>120 FPS</option>
                            </select>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Video Quality</span>
                              <p>Current: {config.video_quality}</p>
                            </div>
                            <select
                              value={config.video_quality}
                              onChange={(e) => updateConfig('video_quality', e.target.value)}
                              className="setting-select"
                            >
                              <option value="Ultra">Ultra</option>
                              <option value="High">High</option>
                              <option value="Medium">Medium</option>
                              <option value="Low">Low</option>
                            </select>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Short Clip Duration</span>
                              <p>Buffer length (15s - 120s)</p>
                            </div>
                            <select
                              value={config.clip_duration || 15}
                              onChange={(e) => updateConfig('clip_duration', parseInt(e.target.value))}
                              className="setting-select"
                            >
                              <option value={15}>15 Seconds</option>
                              <option value={30}>30 Seconds</option>
                              <option value={45}>45 Seconds</option>
                              <option value={60}>60 Seconds</option>
                              <option value={90}>90 Seconds</option>
                              <option value={120}>2 Minutes</option>
                            </select>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Recording Source</span>
                              <p>Choose what to capture</p>
                            </div>
                            <div style={{ display: 'flex', gap: '10px' }}>
                              <select
                                value={config.capture_mode === 'window' ? 'window' : 'monitor'}
                                onChange={(e) => {
                                  if (e.target.value === 'monitor') {
                                    updateConfig('capture_mode', 'monitor');
                                  } else {
                                    updateConfig('capture_mode', 'window');
                                    api.getWindows().then(setWindows);
                                  }
                                }}
                                className="setting-select"
                              >
                                <option value="monitor">Full Screen</option>
                                <option value="window">Specific Window</option>
                              </select>

                              {config.capture_mode === 'window' && (
                                <select
                                  value={config.capture_window_title || ""}
                                  onChange={(e) => {
                                    const sel = windows.find(w => w.title === e.target.value);
                                    if (sel) {
                                      updateConfig('capture_window_title', sel.title);
                                      updateConfig('capture_window_hwnd', sel.id);
                                    }
                                  }}
                                  className="setting-select"
                                  style={{ maxWidth: '150px' }}
                                >
                                  <option value="" disabled>Select Window...</option>
                                  {windows.map(w => (
                                    <option key={w.id} value={w.title}>{w.title.substring(0, 20)}...</option>
                                  ))}
                                </select>
                              )}
                            </div>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Auto-Start Buffer</span>
                              <p>Start recording buffer automatically</p>
                            </div>
                            <Toggle
                              checked={config.auto_start_recording || false}
                              onChange={(v) => updateConfig('auto_start_recording', v)}
                            />
                          </div>
                        </div>
                      </motion.div>
                    )}

                    {/* CLOUD SECTION */}
                    {settingsSection === 'cloud' && (
                      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}>
                        <h3 className="section-title">Cloud Storage</h3>
                        <div className="settings-card">
                          <div className="setting-item" style={{
                            background: 'linear-gradient(145deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)',
                            border: '1px solid rgba(255,255,255,0.05)',
                            borderRadius: '16px',
                            padding: '24px',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            position: 'relative',
                            overflow: 'hidden'
                          }}>
                            {/* Subtle background glow */}
                            <div style={{
                              position: 'absolute',
                              top: '-50%',
                              right: '-10%',
                              width: '200px',
                              height: '200px',
                              background: cloudConnected ? 'rgba(16, 185, 129, 0.1)' : 'rgba(66, 133, 244, 0.1)',
                              filter: 'blur(60px)',
                              borderRadius: '50%',
                              pointerEvents: 'none'
                            }} />

                            <div className="setting-info" style={{ zIndex: 1 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '4px' }}>
                                <div style={{
                                  background: cloudConnected ? 'rgba(16, 185, 129, 0.2)' : 'rgba(66, 133, 244, 0.2)',
                                  padding: '8px',
                                  borderRadius: '8px',
                                  display: 'flex'
                                }}>
                                  <Cloud size={20} color={cloudConnected ? '#10b981' : '#4285F4'} />
                                </div>
                                <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>Google Drive</span>
                              </div>
                              <p style={{ opacity: 0.7, margin: 0 }}>
                                {cloudConnected
                                  ? "Your account is linked. Clips will sync automatically."
                                  : "Link your account to enable cloud storage."}
                              </p>
                            </div>

                            <button
                              className="btn-primary"
                              onClick={handleConnectDrive}
                              style={{
                                backgroundColor: cloudConnected ? 'transparent' : '#4285F4',
                                border: cloudConnected ? '1px solid rgba(255,255,255,0.1)' : 'none',
                                gap: '8px',
                                padding: '10px 20px',
                                zIndex: 1,
                                minWidth: '140px',
                                justifyContent: 'center'
                              }}
                            >
                              {cloudConnected ? (
                                <><Check size={16} /> Connected</>
                              ) : (
                                <><LogIn size={16} /> Connect</>
                              )}
                            </button>
                          </div>

                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Auto Upload</span>
                              <p>Automatically upload new clips</p>
                            </div>
                            <Toggle
                              checked={config.auto_upload}
                              onChange={(v) => updateConfig('auto_upload', v)}
                            />
                          </div>
                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Keep Local Copy</span>
                              <p>Don't delete file after upload</p>
                            </div>
                            <Toggle
                              checked={config.keep_local}
                              onChange={(v) => updateConfig('keep_local', v)}
                            />
                          </div>
                        </div>
                      </motion.div>
                    )}

                    {/* SHORTCUTS SECTION */}
                    {settingsSection === 'shortcuts' && (
                      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}>
                        <h3 className="section-title">Keyboard Shortcuts</h3>
                        <div className="settings-card">
                          <div className="setting-item">
                            <div className="setting-info">
                              <span>Save Clip</span>
                              <p>Capture the last {config.clip_duration} seconds</p>
                            </div>
                            <KeybindRecorder
                              value={config.hotkey_clip}
                              onChange={(k) => updateConfig('hotkey_clip', k)}
                            />
                          </div>
                        </div>
                      </motion.div>
                    )}

                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        {previewClip && (
          <PreviewModal
            clip={previewClip}
            clips={clips}
            onClose={() => setPreviewClip(null)}
            onNavigate={(clip) => setPreviewClip(clip)}
            showToast={showToast}
          />
        )}

        {/* UPDATE MODAL */}
        <AnimatePresence>
          {updateAvailable && (
            <div style={{
              position: 'fixed',
              bottom: '20px',
              right: '20px',
              zIndex: 1000,
              background: 'rgba(20, 20, 20, 0.95)',
              backdropFilter: 'blur(10px)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: '16px',
              padding: '20px',
              boxShadow: '0 10px 40px rgba(0,0,0,0.5)',
              maxWidth: '350px',
              animation: 'slideIn 0.3s ease-out'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '10px' }}>
                <h4 style={{ margin: 0, color: '#10b981', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <CloudDownload size={18} /> Update Available
                </h4>
                <button
                  onClick={() => setUpdateAvailable(null)}
                  style={{ background: 'none', border: 'none', color: '#666', cursor: 'pointer', padding: 0 }}
                >
                  <X size={16} />
                </button>
              </div>

              <p style={{ margin: '0 0 15px 0', fontSize: '0.9rem' }}>
                New version <strong>{updateAvailable.version}</strong> is ready.
                <br />
                <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>{updateAvailable.notes}</span>
              </p>

              <button
                className="btn-primary"
                style={{ width: '100%', background: '#10b981', display: 'flex', justifyContent: 'center', gap: '8px' }}
                onClick={handleUpdate}
              >
                Update & Restart
              </button>
            </div>
          )}
        </AnimatePresence>
      </main>
    </div>
  )
}

function NavItem({ icon, label, active, onClick }: { icon: any, label: string, active: boolean, onClick: () => void }) {
  return (
    <div className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="nav-icon">{icon}</div>
      <span className="nav-label">{label}</span>
      {active && <motion.div layoutId="nav-active" className="nav-active-indicator" />}
    </div>
  )
}

function StatCard({ label, value, color }: { label: string, value: string, color: string }) {
  return (
    <div className="stat-card">
      <div className="stat-indicator" style={{ backgroundColor: color }}></div>
      <div className="stat-content">
        <span className="stat-label">{label}</span>
        <span className="stat-value">{value}</span>
      </div>
    </div>
  )
}

function ClipCard({ clip, isLocal, onClick, onUpload, onDownload, onDelete, ...props }:
  { clip: Clip, isLocal: boolean, onClick: () => void, onUpload: (e: any) => void, onDownload: (e: any) => void, onDelete: (e: any) => void } & React.ComponentProps<typeof motion.div>) {

  const [isHovered, setIsHovered] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const image = clip.thumbnail;
  const timestamp = clip.created
    ? new Date(clip.created * 1000).toLocaleString('es-ES', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    })
    : "";

  // Format duration from seconds to MM:SS
  const formatDuration = (secs: number | null | undefined) => {
    if (!secs) return "--:--";
    const mins = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${mins}:${s.toString().padStart(2, '0')}`;
  };

  const videoSrc = isLocal && clip.path
    ? api.getVideoUrl(clip.path)
    : (clip.id ? `http://127.0.0.1:5000/drive/stream/${clip.id}` : "");

  return (
    <motion.div
      className="clip-card"
      whileHover={{ y: -4 }}
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      {...props}
    >
      <div className="clip-thumbnail" style={{ backgroundImage: image && !isHovered ? `url('${image}')` : undefined, backgroundSize: 'cover' }}>
        {!image && !isHovered && <div className="no-thumb"><Gamepad2 size={24} /></div>}

        {isHovered && videoSrc && (
          <video
            ref={videoRef}
            src={videoSrc}
            autoPlay
            muted
            loop
            className="hover-preview-video"
            style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '8px' }}
          />
        )}

        {!isHovered && (
          <div className="play-overlay">
            <Play size={32} fill="white" />
          </div>
        )}
        <span className="duration-tag">{formatDuration(clip.duration)}</span>
      </div>
      <div className="clip-info">
        <span className="clip-title">{clip.name}</span>
        <div className="clip-meta">
          <span>{timestamp}</span>
          <div className="clip-actions">

            {isLocal ? (
              <button className="btn-icon-small" title="Upload to Cloud" onClick={onUpload}>
                <CloudUpload size={14} />
              </button>
            ) : (
              <>
                <button className="btn-icon-small" title="Open in Browser" onClick={(e) => { e.stopPropagation(); if (clip.webViewLink) window.open(clip.webViewLink); }}>
                  <Share2 size={14} />
                </button>
                <button className="btn-icon-small" title="Download" onClick={onDownload}>
                  <CloudDownload size={14} />
                </button>
              </>
            )}

            <button className="btn-icon-small delete" title="Delete" onClick={onDelete}>
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean, onChange: (v: boolean) => void }) {
  return (
    <div
      className={`toggle ${checked ? 'checked' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <div className="toggle-thumb" />
    </div>
  )
}

// Theme Card Component with beautiful previews
// Theme Card Component with beautiful previews
function ThemeCard({ name, emoji, colors, active, onClick }: {
  id?: string,
  name: string,
  emoji: string,
  colors: string[],
  active: boolean,
  onClick: () => void
}) {
  // Create a gradient from the theme colors
  const gradient = `linear-gradient(135deg, ${colors[2]} 0%, ${colors[3]} 50%, ${colors[4]} 100%)`;

  return (
    <motion.div
      className={`theme-card ${active ? 'active' : ''}`}
      onClick={onClick}
      whileHover={{ scale: 1.02, y: -4 }}
      whileTap={{ scale: 0.98 }}
    >
      {/* Gradient Preview */}
      <div className="theme-preview" style={{ background: gradient }}>
        <div className="theme-preview-overlay">
          {/* Mini UI mockup */}
          <div className="theme-mockup">
            <div className="mockup-sidebar" style={{ backgroundColor: colors[4] }}>
              <div className="mockup-nav-item" style={{ backgroundColor: colors[3] }}></div>
              <div className="mockup-nav-item" style={{ backgroundColor: colors[3] }}></div>
            </div>
            <div className="mockup-content">
              <div className="mockup-card" style={{ backgroundColor: colors[3], opacity: 0.5 }}></div>
              <div className="mockup-card" style={{ backgroundColor: colors[3], opacity: 0.5 }}></div>
            </div>
          </div>
        </div>
        {active && (
          <div className="theme-active-badge">
            <span>✓</span>
          </div>
        )}
      </div>

      {/* Color Swatches */}
      <div className="theme-swatches">
        {colors.map((color, i) => (
          <div
            key={i}
            className="theme-swatch"
            style={{ backgroundColor: color }}
            title={color}
          />
        ))}
      </div>

      {/* Theme Info */}
      <div className="theme-info">
        <span className="theme-emoji">{emoji}</span>
        <span className="theme-name">{name}</span>
      </div>
    </motion.div>
  )
}

// Enhanced Preview Modal with Custom Video Player
function PreviewModal({
  clip,
  clips,
  onClose,
  onNavigate,
  showToast
}: {
  clip: Clip,
  clips: Clip[],
  onClose: () => void,
  onNavigate: (clip: Clip) => void,
  showToast: (msg: string) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [isTrimming, setIsTrimming] = useState(false);
  const [isSavingTrim, setIsSavingTrim] = useState(false);
  const [isVideoLoading, setIsVideoLoading] = useState(true);

  if (!clip) return null;

  const currentIndex = clips.findIndex(c => c.name === clip.name);
  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex < clips.length - 1;

  // Build preview URL

  // Build preview URL
  let previewUrl = "";

  if (clip.path) {
    // Local: Use Flask video endpoint to avoid file:// security issues
    previewUrl = api.getVideoUrl(clip.path);
  } else if (clip.id) {
    // Cloud: Use Flask streaming endpoint (bypasses Drive processing delay)
    previewUrl = `http://127.0.0.1:5000/drive/stream/${clip.id}`;
  }

  // Find related trimmed clips (clips that were cut from this video)
  const baseName = clip.name.replace('.mp4', '').replace('.webm', '');
  const relatedClips = clips.filter(c =>
    c.name.includes(baseName + '_trimmed_') && c.name !== clip.name
  );

  // Video event handlers
  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
      setTrimEnd(videoRef.current.duration);
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setCurrentTime(time);
    }
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = parseFloat(e.target.value);
    setVolume(vol);
    if (videoRef.current) {
      videoRef.current.volume = vol;
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleTrimSave = async () => {
    setIsSavingTrim(true);
    try {
      if (clip.id && !clip.path) {
        // Cloud clip - use trimCloudClip
        await api.trimCloudClip(clip.id, clip.name, trimStart, trimEnd);
        showToast('✅ Cloud clip trimmed and saved to Trims folder!');
      } else if (clip.path) {
        // Local clip
        await api.trimClip(clip.path, trimStart, trimEnd);
        showToast('✅ Clip trimmed successfully!');
      }
    } catch (e) {
      showToast('❌ Error trimming clip');
    }
    setIsSavingTrim(false);
  };

  const handleCopyToClipboard = async () => {
    if (clip.path) {
      try {
        await api.copyToClipboard(clip.path);
        showToast('✅ Video copied to clipboard!');
      } catch (e) {
        showToast('❌ Error copying to clipboard');
      }
    }
  };

  const handleFullscreen = () => {
    if (videoRef.current) {
      videoRef.current.requestFullscreen();
    }
  };

  const handlePrev = () => hasPrev && onNavigate(clips[currentIndex - 1]);
  const handleNext = () => hasNext && onNavigate(clips[currentIndex + 1]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') handlePrev();
      if (e.key === 'ArrowRight') handleNext();
      if (e.key === ' ') { e.preventDefault(); togglePlay(); }
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentIndex, isPlaying]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content video-player-modal" onClick={e => e.stopPropagation()}>
        {/* Navigation Arrows */}
        {hasPrev && (
          <button className="nav-arrow nav-arrow-left" onClick={handlePrev}>
            <ChevronLeft size={32} />
          </button>
        )}
        {hasNext && (
          <button className="nav-arrow nav-arrow-right" onClick={handleNext}>
            <ChevronRight size={32} />
          </button>
        )}

        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-area">
            <h3>{clip.name}</h3>
            {clip.created && (
              <span className="clip-timestamp">
                {new Date(clip.created * 1000).toLocaleString()}
              </span>
            )}
          </div>
          <div className="modal-actions">
            <button className="btn-icon" onClick={handleCopyToClipboard} title="Copy Path">
              <Share2 size={18} />
            </button>
            <button className="btn-icon" onClick={() => {
              if (clip.path) api.openLocalFile(clip.path);
              else if (clip.webViewLink) window.open(clip.webViewLink, '_blank');
            }} title="Open External">
              <Maximize2 size={18} />
            </button>
            <button className="btn-icon" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Video Body */}
        <div className="modal-body video-container">
          <video
            ref={videoRef}
            src={previewUrl}
            onLoadedMetadata={handleLoadedMetadata}
            onTimeUpdate={handleTimeUpdate}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
            onCanPlay={() => setIsVideoLoading(false)}
            onWaiting={() => setIsVideoLoading(true)}
            onClick={togglePlay}
            className="custom-video"
          />
          {/* Loading Overlay */}
          {isVideoLoading && (
            <div className="video-loading-overlay">
              <div className="loading-spinner"></div>
              <span>Loading video...</span>
            </div>
          )}
          {/* Play/Pause Overlay */}
          {!isPlaying && !isVideoLoading && (
            <div className="video-play-overlay" onClick={togglePlay}>
              <Play size={64} fill="white" />
            </div>
          )}
        </div>

        {/* Custom Controls */}
        {previewUrl && (
          <div className="video-controls">
            {/* Main Controls Row */}
            <div className="controls-row">
              <button className="control-btn" onClick={togglePlay}>
                {isPlaying ? <Pause size={20} /> : <Play size={20} />}
              </button>

              <span className="time-display">{formatTime(currentTime)}</span>

              <input
                type="range"
                className="seek-bar"
                min={0}
                max={duration || 100}
                step={0.1}
                value={currentTime}
                onChange={handleSeek}
                style={{ '--seek-before-width': `${(currentTime / (duration || 1)) * 100}%` } as React.CSSProperties}
              />

              <span className="time-display">{formatTime(duration)}</span>

              <div className="volume-control">
                <Volume2 size={18} />
                <input
                  type="range"
                  className="volume-bar"
                  min={0}
                  max={1}
                  step={0.05}
                  value={volume}
                  onChange={handleVolumeChange}
                />
              </div>

              <button className="control-btn" onClick={handleFullscreen}>
                <Maximize2 size={18} />
              </button>
            </div>

            {/* Trim Controls */}
            <div className="trim-section">
              <button
                className={`trim-toggle ${isTrimming ? 'active' : ''}`}
                onClick={() => setIsTrimming(!isTrimming)}
              >
                <Scissors size={16} /> {isTrimming ? 'Cancel Trim' : 'Trim Clip'}
              </button>

              {isTrimming && (
                <div className="trim-controls">
                  <div className="trim-marker">
                    <div className="trim-label">
                      <span>Start: {formatTime(trimStart)}</span>
                      <button
                        className="set-time-btn"
                        onClick={() => setTrimStart(currentTime)}
                        title="Set to current time"
                      >
                        📍 Set
                      </button>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={duration}
                      step={0.1}
                      value={trimStart}
                      onChange={(e) => setTrimStart(Math.min(parseFloat(e.target.value), trimEnd - 0.5))}
                      className="trim-slider trim-start"
                    />
                  </div>
                  <div className="trim-marker">
                    <div className="trim-label">
                      <span>End: {formatTime(trimEnd)}</span>
                      <button
                        className="set-time-btn"
                        onClick={() => setTrimEnd(currentTime)}
                        title="Set to current time"
                      >
                        📍 Set
                      </button>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={duration}
                      step={0.1}
                      value={trimEnd}
                      onChange={(e) => setTrimEnd(Math.max(parseFloat(e.target.value), trimStart + 0.5))}
                      className="trim-slider trim-end"
                    />
                  </div>
                  <button
                    className="btn-primary save-trim-btn"
                    onClick={handleTrimSave}
                    disabled={isSavingTrim}
                  >
                    {isSavingTrim ? 'Saving...' : 'Save Trimmed Clip'}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Related Trimmed Clips */}
        {relatedClips.length > 0 && (
          <div className="related-clips-section">
            <h4>✂️ Trimmed Versions ({relatedClips.length})</h4>
            <div className="related-clips-list">
              {relatedClips.map((rc, i) => (
                <button
                  key={i}
                  className="related-clip-btn"
                  onClick={() => onNavigate(rc)}
                >
                  {rc.name.split('_trimmed_')[1]?.replace('.mp4', '') || rc.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function KeybindRecorder({ value, onChange }: { value: string, onChange: (v: string) => void }) {
  const [listening, setListening] = useState(false);

  useEffect(() => {
    if (!listening) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      e.preventDefault();

      const modifiers = [];
      if (e.ctrlKey) modifiers.push('ctrl');
      if (e.shiftKey) modifiers.push('shift');
      if (e.altKey) modifiers.push('alt');

      let key = e.key.toLowerCase();

      // Ignore modifier-only presses
      if (['control', 'shift', 'alt', 'meta'].includes(key)) return;

      if (key === ' ') key = 'space';

      const combo = [...modifiers, key].join('+');
      onChange(combo);
      setListening(false);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [listening, onChange]);

  return (
    <button
      className={`keybind-recorder ${listening ? 'listening' : ''}`}
      onClick={() => setListening(true)}
      onBlur={() => setListening(false)}
    >
      {listening ? 'Listening...' : (value || 'Click to set')}
    </button>
  )
}

// Loading screen wrapper - handles backend readiness without affecting App's hooks
function LoadingScreen() {
  return (
    <div style={{
      width: '100vw',
      height: '100vh',
      background: 'linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 50%, #0f0f0f 100%)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '24px',
      fontFamily: 'system-ui, -apple-system, sans-serif'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', animation: 'pulse 2s ease-in-out infinite' }}>
        <Gamepad2 size={48} color="#8b5cf6" />
        <span style={{
          fontSize: '2.5rem',
          fontWeight: 800,
          background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent'
        }}>
          GIGA<span style={{ fontWeight: 400 }}>CLIPPER</span>
        </span>
      </div>
      <div style={{
        width: '40px',
        height: '40px',
        border: '3px solid rgba(139, 92, 246, 0.2)',
        borderTop: '3px solid #8b5cf6',
        borderRadius: '50%',
        animation: 'spin 1s linear infinite'
      }} />
      <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.9rem', margin: 0 }}>Starting backend...</p>
      <style>{`
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
      `}</style>
    </div>
  );
}

export default function AppWrapper() {
  const [backendReady, setBackendReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    const checkBackend = async () => {
      try {
        const res = await fetch('http://127.0.0.1:5000/status', { signal: AbortSignal.timeout(1000) });
        if (res.ok && mounted) setBackendReady(true);
      } catch {
        if (mounted) setTimeout(checkBackend, 500);
      }
    };
    checkBackend();
    return () => { mounted = false; };
  }, []);

  if (!backendReady) return <LoadingScreen />;

  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}
