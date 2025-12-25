# GigaClipper

**GigaClipper** is a powerful desktop application designed to be your personal game clipping companion, inspired by Medal.tv. It automatically detects when you're playing, records your gameplay in the background, and lets you save those epic moments with a single keystroke.

## 🚀 Key Features

*   **🎮 Auto-Game Detection**: Automatically detects running games (executables) and starts the recording buffer. No manual start needed!
*   **⏪ Instant Replay Buffer**: Continuously records the last X seconds (configurable, e.g., 15s, 60s) in a circular buffer. Never miss a moment.
*   **💾 One-Click Save**: Hit your hotkey (default `F8`) to instantly save the buffered clip to your library.
*   **☁️ Cloud Sync**: Seamlessly syncs your clips to **Google Drive**, so you can access them anywhere or share them easily.
*   **🎨 Custom Themes**: Personalize your experience with a variety of beautiful, high-quality themes (Cyber Neon, Royal Plum, Coffee & Jasmine, and more).
*   **✂️ Built-in Editor**: Trim and refine your clips directly within the app before sharing.
*   **🔄 Auto-Updates**: The app checks for updates from the cloud, keeping you on the latest version automatically.

## 🛠️ Tech Stack

GigaClipper is built with a modern, high-performance stack:

*   **Frontend**: [React](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) + [Vite](https://vitejs.dev/)
    *   *Why?* Lightning-fast UI, component-based architecture, and type safety.
*   **Desktop Wrapper**: [Electron](https://www.electronjs.org/)
    *   *Why?* Native desktop integration, system tray support, and ability to spawn backend processes.
*   **Backend**: [Python](https://www.python.org/) + [Flask](https://flask.palletsprojects.com/)
    *   *Why?* Robust logic for file handling, Google Drive API integration, and process management.
*   **Video Processing**: [FFmpeg](https://ffmpeg.org/)
    *   *Why?* Industry-standard tool for high-efficiency video recording and processing.

## 🏗️ Architecture

The application runs as a hybrid process:

1.  **Electron (Main Process)**: Handles the application window, system events, and spawns the Python backend.
2.  **React (Renderer)**: Provides the user interface. It communicates with the Python backend via HTTP requests.
3.  **Python Engine**:
    *   Runs a local Flask server.
    *   Monitors system processes to detect games.
    *   Manages the FFmpeg recording subprocess.
    *   Handles local file management and Google Drive uploads.

## 📦 Installation & Release

Download the latest version from the [Releases](https://github.com/gigante9898/GigaClipper/releases) page.

**To Install:**
1. Download `GigaClipper Setup x.x.x.exe`.
2. Run the installer.
3. Launch GigaClipper and start gaming!
