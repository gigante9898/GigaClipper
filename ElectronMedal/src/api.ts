const API_URL = 'http://127.0.0.1:5000';

export interface Clip {
    name: string;
    path?: string;
    size?: number;
    created?: number; // timestamp
    thumbnail?: string;
    duration?: number; // duration in seconds
    id?: string; // Drive ID
    webViewLink?: string; // Drive Link
}

export interface AppConfig {
    buffer_minutes: number;
    fps: number;
    resolution_scale: number;
    video_quality: string;
    hotkey_clip: string;
    hotkey_full: string;
    output_folder: string;
    auto_upload: boolean;
    keep_local: boolean;
    use_nvenc: boolean;
    overlay_enabled: boolean;
    clip_duration: number; // Duration in seconds for "Save Clip"
    capture_mode?: "monitor" | "window";
    capture_window_title?: string;
    capture_window_hwnd?: number; // Window handle for capture
    theme?: string; // Theme name
    auto_start_recording?: boolean; // Start buffer on app launch
    auto_detect_apps?: string[];
}

export const api = {
    async getWindows(): Promise<{ id: number, title: string }[]> {
        try {
            const res = await fetch(`${API_URL}/windows`);
            return await res.json();
        } catch { return []; }
    },

    async getStatus() {
        try {
            const res = await fetch(`${API_URL}/status`);
            return await res.json();
        } catch (e) {
            console.error("API error", e);
            return { running: false };
        }
    },

    async startRecording() {
        return await fetch(`${API_URL}/start`, { method: 'POST' });
    },

    async stopRecording() {
        return await fetch(`${API_URL}/stop`, { method: 'POST' });
    },

    async saveClip(duration: number | null) {
        return await fetch(`${API_URL}/clip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration })
        });
    },

    async getLocalFiles(): Promise<Clip[]> {
        try {
            const res = await fetch(`${API_URL}/files/local`);
            return await res.json();
        } catch { return []; }
    },

    async getCloudFiles(): Promise<Clip[]> {
        try {
            const res = await fetch(`${API_URL}/files/cloud`);
            return await res.json();
        } catch { return []; }
    },

    async openFolder() {
        return await fetch(`${API_URL}/open_folder`, { method: 'POST' });
    },

    async openLocalFile(path: string) {
        return await fetch(`${API_URL}/open_file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
    },

    async deleteLocalFile(path: string) {
        return await fetch(`${API_URL}/files/local/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
    },

    async deleteCloudFile(file_id: string) {
        return await fetch(`${API_URL}/files/cloud/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id })
        });
    },

    async uploadFile(path: string) {
        return await fetch(`${API_URL}/files/upload`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
    },

    async downloadFile(file_id: string, name: string) {
        return await fetch(`${API_URL}/files/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id, name })
        });
    },

    async getSettings(): Promise<AppConfig> {
        const res = await fetch(`${API_URL}/settings`);
        return await res.json();
    },

    async updateSettings(settings: Partial<AppConfig>) {
        return await fetch(`${API_URL}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
    },

    async trimClip(path: string, start: number, end: number) {
        return await fetch(`${API_URL}/clip/trim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, start, end })
        });
    },

    async trimCloudClip(id: string, name: string, start: number, end: number) {
        return await fetch(`${API_URL}/clip/trim/cloud`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, name, start, end })
        });
    },

    async copyToClipboard(path: string) {
        return await fetch(`${API_URL}/copy-to-clipboard`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
    },

    async addGame(name: string) {
        return await fetch(`${API_URL}/settings/games/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
    },

    async removeGame(name: string) {
        return await fetch(`${API_URL}/settings/games/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
    },

    async getProcesses(): Promise<string[]> {
        return await fetch(`${API_URL}/processes`).then(res => res.json());
    },

    async connectDrive() {
        return await fetch(`${API_URL}/auth/connect`, { method: 'POST' });
    },

    async getAuthStatus() {
        try {
            const res = await fetch(`${API_URL}/auth/status`);
            return await res.json();
        } catch (e) {
            console.error(e);
            return { connected: false };
        }
    },

    async pickFolder() {
        try {
            const res = await fetch(`${API_URL}/system/pick-folder`, { method: 'POST' });
            return await res.json();
        } catch (e) {
            console.error("Pick folder failed", e);
            return { path: null };
        }
    },

    async checkUpdates(currentVersion: string) {
        try {
            const res = await fetch(`${API_URL}/updates/check?version=${currentVersion}`);
            return await res.json();
        } catch (e) {
            console.error("Update check failed", e);
            return { available: false };
        }
    },

    async installUpdate(fileId: string, filename: string) {
        try {
            const res = await fetch(`${API_URL}/updates/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: fileId, filename })
            });
            return await res.json();
        } catch (e) {
            console.error("Install failed", e);
            return { error: 'Failed to trigger install' };
        }
    },

    getVideoUrl(path: string): string {
        return `${API_URL}/files/stream?path=${encodeURIComponent(path)}`;
    }
};
