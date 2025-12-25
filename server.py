from flask import Flask, request, jsonify, send_from_directory, send_file, Response
from flask_cors import CORS
import threading
import os
import sys
import psutil
import time
import keyboard
import tkinter as tk
from pathlib import Path
import subprocess
import ctypes
from datetime import datetime

from core import ConfigManager, RecorderEngine, DriveClient, safe_log, get_ffmpeg_path

# Ctypes Setup for Window Listing
try:
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    GetWindowText = user32.GetWindowTextW
    GetWindowTextLength = user32.GetWindowTextLengthW
    IsWindowVisible = user32.IsWindowVisible
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
except:
    user32 = None

app = Flask(__name__)
# Allow CORS for development & production
CORS(app, resources={r"/*": {"origins": "*"}})

# Global State
import argparse

# Parse arguments for root dir
parser = argparse.ArgumentParser()
parser.add_argument('--root-dir', default=os.getcwd(), help='Directory containing backend assets')
args, _ = parser.parse_known_args()
backend_dir = args.root_dir

print(f"Server starting. CWD: {os.getcwd()}, Backend Root: {backend_dir}")

config = ConfigManager.load()
drive_client = DriveClient()
current_game = None  # Track currently detected game

# Overlay Manager (Tkinter in a separate thread)
class OverlayManager:
    def __init__(self):
        self.root = None
        self.queue = []
        self.lock = threading.Lock()
        
    def start_loop(self):
        # Tkinter must run in the main thread usually, but here we run it in a daemon thread 
        # distinct from Flask's thread. We need a dedicated loop.
        self.root = tk.Tk()
        self.root.withdraw() # Hide the main window
        self.process_queue()
        self.root.mainloop()

    def process_queue(self):
        with self.lock:
            if self.queue:
                text, color, duration = self.queue.pop(0)
                self.show_notification_gui(text, color, duration)
        
        if self.root:
            self.root.after(500, self.process_queue)

    def show_notification(self, text, color="#4CAF50", duration=3000):
        with self.lock:
            self.queue.append((text, color, duration))

    def show_notification_gui(self, text, color, duration):
        try:
            notification = tk.Toplevel(self.root)
            notification.overrideredirect(True)
            notification.attributes("-topmost", True)
            notification.attributes("-alpha", 0.95)
            notification.config(bg="#1a1b1e")
            
            # Calculate dynamic width roughly based on characters (avg 8px per char + padding)
            width = min(max(len(text) * 9 + 40, 250), 400)
            height = 50
            notification.geometry(f"{width}x{height}+20+20")
            
            # Main container frame
            container = tk.Frame(notification, bg="#1a1b1e")
            container.pack(fill="both", expand=True)
            
            # Accent strip on the left
            accent_width = 4
            accent = tk.Frame(container, bg=color, width=accent_width)
            accent.pack(side="left", fill="y")
            
            # Text label
            label = tk.Label(
                container, 
                text=text, 
                fg="#ffffff", 
                bg="#1a1b1e", 
                font=("Segoe UI", 10, "bold"),
                anchor="w",
                justify="left"
            )
            label.pack(side="left", fill="both", expand=True, padx=(10, 10))
            
            # Auto close
            notification.after(duration, notification.destroy)
            
            # Fade in effect (optional/simple)
            def fade_in(alpha=0):
                if alpha < 0.95:
                    alpha += 0.1
                    notification.attributes("-alpha", alpha)
                    notification.after(20, lambda: fade_in(alpha))
            
            notification.attributes("-alpha", 0) # Start invisible
            fade_in()
            
        except Exception as e:
            print(f"Overlay error: {e}")

overlay = OverlayManager()
threading.Thread(target=overlay.start_loop, daemon=True).start()

# Pass overlay notification method to recorder
recorder = RecorderEngine(config, on_notification=overlay.show_notification)

# Auto-start buffer if configured
if config.get("auto_start_recording", False):
    print("[AUTO] Auto-start recording enabled. Starting buffer...")
    recorder.start()

# Game Detection Logic
def auto_detect_game_loop():
    global current_game
    while True:
        try:
            found = False
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name'].lower()
                    if name in config["auto_detect_apps"]:
                        current_game = name
                        found = True
                        if not recorder.running:
                            print(f"[AUTO] Game detected: {name}. Starting buffer...")
                            recorder.start()
                            overlay.show_notification(f"🎮 Game Detected: {name}", "#2196F3")
                        break # Only need to find one
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            if not found:
                 current_game = None
            
            # If buffer is running but no game found? (Optional: auto-stop logic)
            # For now, we only auto-start.
            
        except Exception as e:
            safe_log(f"Error in game detection: {e}")
        
        time.sleep(5)

threading.Thread(target=auto_detect_game_loop, daemon=True).start()

# Hotkeys Logic
def setup_hotkeys():
    try:
        # Clip Hotkey - suppress=False to allow key to pass through
        duration = config.get("clip_duration", 15)
        keyboard.add_hotkey(config["hotkey_clip"], lambda: save_clip_internal(duration), suppress=False, trigger_on_release=False)
        # Full Clip Hotkey
        keyboard.add_hotkey(config["hotkey_full"], lambda: save_clip_internal(None), suppress=False, trigger_on_release=False)
        print(f"Hotkeys registered. Clip duration: {duration}s")
    except Exception as e:
        safe_log(f"Error registering hotkeys: {e}")

threading.Thread(target=setup_hotkeys, daemon=True).start()

def save_clip_internal(duration):
    if not recorder.running:
        print("Cannot clip: Buffer inactive")
        return

    def background_clip():
        path = recorder.save_clip(duration)
        if path:
            # Play audio confirmation
            try:
                import winsound
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except: pass
            
            if config.get("auto_upload"):
                # Auto-upload background task
                res = drive_client.upload(path)
                if res and res.get('id') and not config.get("keep_local", False):
                    try: os.remove(path)
                    except: pass

    threading.Thread(target=background_clip, daemon=True).start()

# Routes
@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        "running": recorder.running,
        "buffer_minutes": config["buffer_minutes"],
        "temp_folder_size": len(recorder.chunks) if recorder.chunks else 0,
        "current_game": current_game
    })

@app.route('/start', methods=['POST'])
def start_buffer():
    if not recorder.running:
        recorder.start()
        return jsonify({"status": "started", "message": "Buffer started"})
    return jsonify({"status": "already_running", "message": "Buffer is already running"})

@app.route('/stop', methods=['POST'])
def stop_buffer():
    if recorder.running:
        recorder.stop()
        return jsonify({"status": "stopped", "message": "Buffer stopped"})
    return jsonify({"status": "not_running", "message": "Buffer is not running"})

@app.route('/clip', methods=['POST'])
def save_clip_route():
    data = request.json or {}
    duration = data.get('duration') # Can be None for full buffer
    
    if not recorder.running:
        return jsonify({"error": "Buffer not running"}), 400

    save_clip_internal(duration)
    return jsonify({"status": "processing", "message": "Clip save initiated"})

@app.route('/clip/trim', methods=['POST'])
def trim_clip():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    path = data.get('path')
    start = data.get('start', 0)
    end = data.get('end')
    
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    
    if end is None:
        return jsonify({"error": "End time required"}), 400
    
    # Generate output filename
    base, ext = os.path.splitext(path)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = f"{base}_trimmed_{timestamp}{ext}"
    
    try:
        # FFmpeg trim command
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-to', str(end),
            '-i', path,
            '-c', 'copy',  # Fast copy without re-encoding
            output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        return jsonify({"status": "success", "output": output_path})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"FFmpeg error: {e.returncode}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/clip/trim/cloud', methods=['POST'])
def trim_cloud_clip():
    """Trim a cloud video: download, trim, upload to Trims folder"""
    data = request.json
    file_id = data.get('id')
    start = data.get('start', 0)
    end = data.get('end')
    name = data.get('name', 'clip.mp4')
    
    if not file_id or end is None:
        return jsonify({"error": "Missing file_id or end time"}), 400
    
    try:
        # Ensure temp folder exists
        Path(config["temp_folder"]).mkdir(parents=True, exist_ok=True)
        
        # Download the video from Drive
        temp_input = os.path.join(config["temp_folder"], f"cloud_input_{file_id}.mp4")
        if not drive_client.download(file_id, temp_input):
            return jsonify({"error": "Failed to download from Drive"}), 500
        
        # Generate output path
        base_name = os.path.splitext(name)[0]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_output = os.path.join(config["temp_folder"], f"{base_name}_trimmed_{timestamp}.mp4")
        
        print(f"Cloud trim: {temp_input} -> {temp_output}, start={start}, end={end}")
        
        # Run FFmpeg to trim
        no_window = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        cmd = ['ffmpeg', '-y', '-ss', str(start), '-to', str(end), '-i', temp_input, '-c', 'copy', temp_output]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=no_window)
        
        print(f"FFmpeg completed. Uploading to Trims...")
        
        # Upload to Drive Trims folder
        result = drive_client.upload_to_trims(temp_output)
        
        # Cleanup temp files
        for f in [temp_input, temp_output]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
        
        if result:
            theme_color = ConfigManager.get_theme_color(config, "primary")
            recorder.notify(f"✅ Trimmed clip uploaded to Drive/Trims!", theme_color)
            return jsonify({"status": "success", "webViewLink": result.get("webViewLink")})
        
        recorder.notify("❌ Upload to Trims failed", "#f44336")
        return jsonify({"error": "Failed to upload to Drive"}), 500
        
    except Exception as e:
        safe_log(f"Cloud trim error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/windows', methods=['GET'])
def list_windows():
    if not user32:
        return jsonify([])
    
    windows = []
    
    # Blacklist for window titles
    blacklist = {
        "Default IME", "MSCTFIME UI", "GDI+ Window", "Program Manager", 
        "Settings", "Configuracion", "Microsoft Text Input Application", 
        "Windows Input Experience", "NVIDIA GeForce Overlay", "Medal Overlay",
        "Administrador de tareas", "Task Manager", "Cortana", "Search",
        "Start", "Notification Center", "ShellExperienceHost", "Screen Snipping"
    }
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buff, length + 1)
                title = buff.value
                
                # Robust filtering
                if title and title.strip():
                     # Skip blacklisted exact matches
                     if title in blacklist: return True
                     # Skip if title is just "." or common junk
                     if title == ".": return True
                     
                     windows.append({"id": hwnd, "title": title})
        return True
        
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    
    # Sort by title
    windows.sort(key=lambda x: x["title"].lower())
    return jsonify(windows)

@app.route('/files/local', methods=['GET'])
def list_local_files():
    folder = config["output_folder"]
    if not os.path.exists(folder):
        return jsonify([])
    
    files = sorted(Path(folder).glob("*.mp4"), key=os.path.getmtime, reverse=True)
    results = []
    
    # Generate thumbnails on the fly if missing
    thumb_dir = os.path.join(folder, ".thumbnails")
    Path(thumb_dir).mkdir(exist_ok=True)
    
    for f in files:
        thumb_path = os.path.join(thumb_dir, f"{f.stem}.jpg")
        if not os.path.exists(thumb_path):
            try:
                ffmpeg_exe = get_ffmpeg_path("ffmpeg")
                subprocess.run([
                    ffmpeg_exe, '-y', '-i', str(f), '-ss', '00:00:01',
                    '-vframes', '1', '-q:v', '3', '-vf', 'scale=320:-1', thumb_path
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                   creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            except: pass
            
        # Get video duration using ffprobe
        duration = None
        try:
            ffprobe_exe = get_ffmpeg_path("ffprobe")
            result = subprocess.run([
                ffprobe_exe, '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(f)
            ], capture_output=True, text=True, timeout=5,
               creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            if result.stdout.strip():
                duration = float(result.stdout.strip())
        except: pass
            
        results.append({
            "name": f.name,
            "path": str(f.absolute()),
            "size": f.stat().st_size,
            "created": f.stat().st_mtime,
            "thumbnail": f"http://127.0.0.1:5000/thumbnail/{f.stem}.jpg" if os.path.exists(thumb_path) else None,
            "duration": duration
        })
        
    return jsonify(results)

@app.route('/thumbnail/<path:filename>')
def serve_thumbnail(filename):
    # Use send_file with absolute path to avoid directory quirks
    thumb_path = os.path.join(config["output_folder"], ".thumbnails", filename)
    if os.path.exists(thumb_path):
        return send_file(thumb_path)
    return jsonify({"error": "Thumbnail not found"}), 404

@app.route('/open_file', methods=['POST'])
def open_file_route():
    data = request.json
    path = data.get("path")
    if path and os.path.exists(path):
        os.startfile(path)
        return jsonify({"status": "opened"})
    return jsonify({"error": "File not found"}), 404

@app.route('/system/pick-folder', methods=['POST'])
def pick_folder_route():
    try:
        # PowerShell command to open folder picker
        # Requires -sta for OLE calls (OpenFileDialog)
        ps_cmd = """
        Add-Type -AssemblyName System.Windows.Forms
        $f = New-Object System.Windows.Forms.FolderBrowserDialog
        $f.ShowNewFolderButton = $true
        $f.Description = "Select Medal Output Folder"
        if ($f.ShowDialog() -eq 'OK') {
            Write-Output $f.SelectedPath
        }
        """
        # Run powershell with proper encoding
        result = subprocess.run(
            ['powershell', '-Command', ps_cmd], 
            capture_output=True, 
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        
        path = result.stdout.strip()
        if path and os.path.isdir(path):
            # Update config
            global config
            config["output_folder"] = path
            ConfigManager.save(config)
            return jsonify({"path": path})
            
        return jsonify({"path": None})
    except Exception as e:
        safe_log(f"Pick folder error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/video')
@app.route('/files/stream')
def serve_video():
    """Serve local video files to avoid file:// security restrictions"""
    video_path = request.args.get('path')
    if not video_path:
        return jsonify({"error": "No path provided"}), 400
        
    # URL decode just in case, though Flask handles request.args
    # Verify existence
    if not os.path.exists(video_path):
        return jsonify({"error": "File not found"}), 404
    
    # Use send_file for range support (Flask handles ranges automatically with send_file since 2.0?)
    # send_from_directory is safer, let's stick to it but ensure directory is correct
    directory = os.path.dirname(video_path)
    filename = os.path.basename(video_path)
    
    # Manually constructing headers for ranges if needed, OR try simple send_file
    # Simple send_file is usually best for video
    try:
        from flask import send_file
        return send_file(video_path, mimetype='video/mp4')
    except Exception as e:
        safe_log(f"Stream error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/updates/check', methods=['GET'])
def check_updates_route():
    try:
        # Get current version from query param or default
        current_version = request.args.get('version', '0.0.0')
        result = drive_client.check_for_updates(current_version)
        return jsonify(result)
    except Exception as e:
        safe_log(f"Update Check Fail: {e}")
        return jsonify({"available": False, "error": str(e)})

@app.route('/updates/install', methods=['POST'])
def install_update_route():
    data = request.json
    file_id = data.get("file_id")
    filename = data.get("filename", "GigaClipperSetup.exe")
    
    if not file_id:
        return jsonify({"error": "Missing file_id"}), 400
        
    try:
        installer_path = drive_client.download_update(file_id, filename)
        if installer_path and os.path.exists(installer_path):
            # Launch installer and exit
            subprocess.Popen([installer_path], close_fds=True)
            
            # Kill current app after a brief delay
            def exit_app():
                time.sleep(2)
                os._exit(0)
            threading.Thread(target=exit_app, daemon=True).start()
            
            return jsonify({"status": "installing", "path": installer_path})
        return jsonify({"error": "Download failed"}), 500
    except Exception as e:
        safe_log(f"Install Fail: {e}")
        return jsonify({"error": str(e)}), 500

# Global Cache and Session
THUMBNAIL_LINK_CACHE = {}
# Session for connection reuse (Crucial for SSL performance)
import requests
http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

# Limit concurrent Drive downloads to prevent SSL socket exhaustion
thumbnail_semaphore = threading.Semaphore(6)

@app.route('/files/cloud', methods=['GET'])
def list_cloud_files():
    # Only try silent login. If it fails, return 401 so frontend knows to show "Connect" button.
    # Note: list_videos() in core.py now uses login_silent() internally and return [] if fails.
    # But we want to distinguish between "empty folder" and "not connected".
    
    if not drive_client.login_silent():
        return jsonify({"error": "Not connected to Drive", "auth_required": True}), 401

    files = drive_client.list_videos()
    # Map Drive fields to match frontend Clip interface
    result = []
    for f in files:
        file_id = f.get("id")
        # Cache thumbnail link if available
        if file_id and f.get("thumbnailLink"):
            THUMBNAIL_LINK_CACHE[file_id] = f.get("thumbnailLink")

        # Get duration from videoMediaMetadata (in milliseconds)
        duration_ms = None
        video_meta = f.get("videoMediaMetadata", {})
        if video_meta and video_meta.get("durationMillis"):
            duration_ms = int(video_meta["durationMillis"]) / 1000  # Convert to seconds
        
        # Parse createdTime to Unix timestamp
        created_time = None
        if f.get("createdTime"):
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00"))
                created_time = dt.timestamp()
            except: pass
        # Use proxy URL for thumbnail to avoid CORS
        
        thumb_url = f"http://127.0.0.1:5000/drive/thumbnail/{file_id}" if file_id else None
        
        result.append({
            "id": file_id,
            "name": f.get("name"),
            "thumbnail": thumb_url,
            "webViewLink": f.get("webViewLink"),
            "duration": duration_ms,
            "created": created_time
        })
    return jsonify(result)

@app.route('/auth/connect', methods=['POST'])
def auth_connect():
    """Trigger interactive login (browser popup)"""
    success = drive_client.login_interactive()
    if success:
        return jsonify({"status": "connected"})
    return jsonify({"error": "Login failed"}), 500

@app.route('/auth/status', methods=['GET'])
def auth_status():
    """Check if currently connected"""
    connected = drive_client.login_silent()
    return jsonify({"connected": connected})

# ... (downloads endpoints unchanged)

@app.route('/drive/stream/<file_id>')
def stream_drive_video(file_id):
    """Stream video from Google Drive with proper Range support for fast seeking"""
    from flask import Response, request as flask_request
    
    range_header = flask_request.headers.get('Range', None)
    file_size = drive_client.get_video_size(file_id)
    
    if not file_size:
        # Fallback if size unknown (should allow at least partial play)
        return Response("File size unknown", status=500)

    start, end = 0, None
    length = file_size

    if range_header:
        # Example Range: bytes=0-1023 or bytes=1024-
        try:
            byte_range = range_header.replace('bytes=', '').split('-')
            start = int(byte_range[0])
            if len(byte_range) > 1 and byte_range[1]:
                end = int(byte_range[1])
            
            # Request specific range from Drive
            drive_response = drive_client.stream_video_range(file_id, start, end)
            
            if not drive_response or not drive_response.ok:
                return Response("Drive stream failed", status=502)
                
            # Use the actual content length returned by Drive or calculate
            chunk_size = int(drive_response.headers.get('Content-Length', file_size - start))
            
            # Create generator from requests stream
            def generate():
                for chunk in drive_response.iter_content(chunk_size=1024*64): # 64KB chunks
                    if chunk: yield chunk
            
            resp = Response(generate(), status=206, mimetype='video/mp4')
            resp.headers['Content-Range'] = f'bytes {start}-{end if end else file_size-1}/{file_size}'
            resp.headers['Accept-Ranges'] = 'bytes'
            resp.headers['Content-Length'] = str(chunk_size)
            return resp

        except Exception as e:
            safe_log(f"Range parse error: {e}")
            # Fallback to full download if range fails
            pass
            
    # No range or fallback: Stream full file
    # Note: This prevents seeking in some browsers if they strictly require 206 for it
    def generate_full():
        for chunk in drive_client.stream_video_chunks(file_id):
            yield chunk
            
    headers = {
        'Content-Type': 'video/mp4',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(file_size)
    }
    return Response(generate_full(), headers=headers, mimetype='video/mp4')

@app.route('/drive/thumbnail/<file_id>')
def get_drive_thumbnail(file_id):
    """Proxy thumbnail from Drive with local caching"""
    import time
    
    # 1. Check local disk cache first (fastest)
    cache_dir = os.path.join(os.getcwd(), ".cache", "thumbnails")
    os.makedirs(cache_dir, exist_ok=True)
    
    cached_path = os.path.join(cache_dir, f"{file_id}.jpg")
    
    if os.path.exists(cached_path):
        return send_from_directory(cache_dir, f"{file_id}.jpg")

    # 2. Fetch from Drive if not cached
    acquired = thumbnail_semaphore.acquire(blocking=False)
    if not acquired:
        # If too many requests, fail fast or wait briefly? 
        # Better to wait briefly to avoid broken images, but for now let's try non-blocking for speed
        # Actually, let's block with timeout to queue them properly
        if not thumbnail_semaphore.acquire(timeout=2):
             return jsonify({"error": "Busy"}), 429
             
    try:
        for attempt in range(2): # Reduced retries for speed
            try:
                # Try getting link from memory cache first
                thumb_url = THUMBNAIL_LINK_CACHE.get(file_id)
                
                # If not in memory cache, fetch from API (slow fallback)
                if not thumb_url:
                    if drive_client.service:
                        print(f"Propagating Thumbnail fallback for {file_id}...")
                        file = drive_client.service.files().get(fileId=file_id, fields='thumbnailLink').execute()
                        thumb_url = file.get('thumbnailLink')
                
                if thumb_url:
                    # Reuse global session for SSL efficiency
                    resp = http_session.get(thumb_url, timeout=5)
                    if resp.status_code == 200:
                        # Save to cache
                        with open(cached_path, "wb") as f:
                            f.write(resp.content)
                            
                        # Serve
                        from flask import Response
                        return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'image/jpeg'))
            except Exception as e:
                safe_log(f"Thumbnail error (attempt {attempt}): {e}")
                if attempt == 0:
                        # Try re-authing once
                        try: drive_client.authenticate()
                        except: pass
                time.sleep(0.5)
    finally:
        thumbnail_semaphore.release()

    return jsonify({"error": "Thumbnail failed"}), 404

    return jsonify({"error": "Thumbnail failed"}), 404
    
    # Return empty response or placeholder
    return '', 204

@app.route('/settings', methods=['GET'])
def get_settings():
    return jsonify(ConfigManager.load())

@app.route('/settings', methods=['POST'])
def update_settings():
    new_settings = request.json
    global config
    config = {**config, **new_settings}
    ConfigManager.save(config)
    # Update recorder config live
    recorder.config = config
    # Re-register hotkeys dynamically
    try:
        keyboard.unhook_all_hotkeys()
        setup_hotkeys()
    except Exception as e:
        safe_log(f"Error reloading hotkeys: {e}")
        
    return jsonify({"status": "updated", "config": config})

@app.route('/settings/games/add', methods=['POST'])
def add_game_detection():
    data = request.json
    game_exe = data.get("name")
    if not game_exe: return jsonify({"error": "No name provided"}), 400
    
    game_exe = game_exe.lower()
    if not game_exe.endswith(".exe"): game_exe += ".exe"
    
    if game_exe not in config["auto_detect_apps"]:
        config["auto_detect_apps"].append(game_exe)
        ConfigManager.save(config)
        return jsonify({"status": "added", "game": game_exe, "list": config["auto_detect_apps"]})
    return jsonify({"status": "exists", "message": "Game already in list"})

@app.route('/settings/games/remove', methods=['POST'])
def remove_game_detection():
    data = request.json
    game_exe = data.get("name")
    if not game_exe: return jsonify({"error": "No name provided"}), 400
    
    if game_exe in config["auto_detect_apps"]:
        config["auto_detect_apps"].remove(game_exe)
        ConfigManager.save(config)
        return jsonify({"status": "removed", "game": game_exe, "list": config["auto_detect_apps"]})
    return jsonify({"status": "not_found", "message": "Game not in list"})

@app.route('/processes', methods=['GET'])
def get_running_processes():
    """Get list of distinct running .exe processes that have visible windows (Alt-Tab style)"""
    if not user32:
        return jsonify([])

    visible_pids = set()

    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            if length > 0:
                 pid = ctypes.c_ulong()
                 user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                 visible_pids.add(pid.value)
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    
    # Blacklist of useless system apps that have windows but aren't games/apps user wants
    blacklist = {
        "applicationframehost.exe", "systemsettings.exe", "textinputhost.exe",
        "searchhost.exe", "startmenuexperiencehost.exe", "lockapp.exe",
        "shellexperiencehost.exe", "gamebar.exe", "taskmgr.exe"
    }

    procs = set()
    for p in psutil.process_iter(['name', 'pid']):
        try:
            if p.pid in visible_pids:
                val = p.info['name']
                if val and val.lower().endswith(".exe"):
                    name_lower = val.lower()
                    if name_lower not in blacklist:
                        procs.add(name_lower)
        except: pass
        
    # Additional filter: ensure known game launchers or common apps are included if they have windows
    # (The logic above covers them if they have a visible window title)
        
    return jsonify(sorted(list(procs)))

@app.route('/open_folder', methods=['POST'])
def open_folder():
    path = config["output_folder"]
    os.startfile(path)
    return jsonify({"status": "opened"})


@app.route('/copy-to-clipboard', methods=['POST'])
def copy_to_clipboard():
    """Copy file to Windows clipboard using PowerShell"""
    data = request.json
    path = data.get('path')
    
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    
    try:
        # Use PowerShell to copy file to clipboard
        ps_cmd = f'''
        Add-Type -AssemblyName System.Windows.Forms
        $file = [System.Collections.Specialized.StringCollection]::new()
        $file.Add("{path.replace(chr(92), chr(92)+chr(92))}")
        [System.Windows.Forms.Clipboard]::SetFileDropList($file)
        '''
        subprocess.run(['powershell', '-Command', ps_cmd], check=True, capture_output=True,
                      creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        return jsonify({"status": "copied"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/files/local/delete', methods=['POST'])
def delete_local_file():
    data = request.json
    path = data.get("path")
    if Path(path).exists():
        try:
            os.remove(path)
            # Try removing thumbnail too
            thumb_path = os.path.join(os.path.dirname(path), ".thumbnails", Path(path).stem + ".jpg")
            if os.path.exists(thumb_path): os.remove(thumb_path)
            return jsonify({"status": "deleted"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route('/files/cloud/delete', methods=['POST'])
def delete_cloud_file():
    data = request.json
    file_id = data.get("file_id")
    if drive_client.delete(file_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Failed to delete"}), 500

@app.route('/files/upload', methods=['POST'])
def upload_file():
    data = request.json
    path = data.get("path")
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
        
    def bg_upload():
        res = drive_client.upload(path)
        theme_color = ConfigManager.get_theme_color(config, "primary")
        if res and res.get('id'):
            recorder.notify(f"☁ Uploaded: {Path(path).name}", theme_color)
        else:
            recorder.notify("⚠ Upload Failed", "#f44336")
            
    threading.Thread(target=bg_upload, daemon=True).start()
    return jsonify({"status": "processing", "message": "Upload started"})

@app.route('/files/download', methods=['POST'])
def download_file():
    data = request.json
    file_id = data.get("file_id")
    name = data.get("name")
    dest_path = os.path.join(config["output_folder"], name)
    
    if os.path.exists(dest_path):
        return jsonify({"status": "exists", "message": "File already exists locally"})
        
    def bg_download():
        theme_color = ConfigManager.get_theme_color(config, "primary")
        recorder.notify(f"⬇ Downloading: {name}...", theme_color)
        if drive_client.download(file_id, dest_path):
            recorder.notify(f"✅ Downloaded: {name}", theme_color)
        else:
            recorder.notify("❌ Download Failed", "#f44336")
            
    threading.Thread(target=bg_download, daemon=True).start()
    return jsonify({"status": "processing", "message": "Download started"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    safe_log(f"Starting Python Server on port {port}...")
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
