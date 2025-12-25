import electron from 'electron';
const { app, BrowserWindow, ipcMain } = electron;
import pkg from "electron-updater";
const { autoUpdater } = pkg;
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

import { spawn, spawnSync, execSync } from 'child_process';

let pythonProcess = null;

function startPythonServer() {
    let scriptPath;
    let command;
    let args;

    if (app.isPackaged) {
        // Production: Run the compiled executable
        // In electron-builder, extraResources puts files in contents/resources
        scriptPath = path.join(process.resourcesPath, 'backend', 'LocalMedalEngine.exe');
        console.log('Production: Starting backend from', scriptPath);
        command = scriptPath;
        args = [];
    } else {
        // Development: Run python script
        scriptPath = path.join(__dirname, '../../server.py');
        console.log('Development: Starting Python server at:', scriptPath);
        // Force 'python' instead of 'pythonw' for better compatibility/debugging
        command = 'python';
        args = [scriptPath];
    }

    pythonProcess = spawn(command, args, {
        cwd: app.isPackaged ? path.dirname(scriptPath) : path.dirname(scriptPath),
        // Use 'pipe' to capture output without opening a window with 'inherit'
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: false, // Revert to false to fix startup crash
        detached: false
    });

    // Pipe outputs to console for debugging without a separate window
    if (pythonProcess.stdout) {
        pythonProcess.stdout.on('data', (data) => console.log(`[Python]: ${data}`));
    }
    if (pythonProcess.stderr) {
        pythonProcess.stderr.on('data', (data) => console.error(`[Python Error]: ${data}`));
    }

    pythonProcess.on('close', (code) => {
        console.log(`Backend server exited with code ${code}`);
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to start backend:', err);
    });
}

function createWindow() {
    const win = new BrowserWindow({
        width: 1200,
        height: 800,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            webviewTag: true, // Enable <webview> for Drive preview
            webSecurity: false // Allow loading local resources (file://)
        },
        backgroundColor: '#0f0f0f',
        // Ocultar barra de menú por defecto (estilo más pro)
        autoHideMenuBar: true,
    });

    // En desarrollo, cargar desde Vite
    if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
        win.loadURL('http://localhost:5173');
        // win.webContents.openDevTools();
    } else {
        // En producción, cargar el build
        win.loadFile(path.join(__dirname, '../dist/index.html'));
    }
}

// Kill any process running on port 5000
function killStartUpZombies() {
    try {
        console.log('Checking for zombie processes on port 5000...');
        if (process.platform === 'win32') {
            // Find PID occupying port 5000
            const cmd = `FOR /F "tokens=5" %a IN ('netstat -aon ^| find ":5000" ^| find "LISTENING"') DO taskkill /f /pid %a`;
            // Execute in shell
            execSync(cmd, { stdio: 'ignore', shell: true });
        }
    } catch (e) {
        // Ignore errors (no process found usually throws)
    }
}

app.whenReady().then(() => {
    killStartUpZombies();
    startPythonServer();
    createWindow();

    // Note: Updates are now handled via Gist fetch in the renderer process
    // No electron-updater needed for private repo

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('will-quit', () => {
    console.log('Cleaning up processes...');
    try {
        if (process.platform === 'win32') {
            // Kill by PID first
            if (pythonProcess && pythonProcess.pid) {
                spawnSync('taskkill', ['/pid', String(pythonProcess.pid), '/f', '/t'], { stdio: 'ignore' });
            }
            // Also kill by name to catch any orphans
            spawnSync('taskkill', ['/im', 'LocalMedalEngine.exe', '/f', '/t'], { stdio: 'ignore' });
        } else if (pythonProcess) {
            pythonProcess.kill('SIGKILL');
        }
    } catch (e) {
        console.error("Cleanup error:", e);
    }
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
