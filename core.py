import os
import sys
import json
import threading
import subprocess
import time
import shutil
import pyaudio
import wave
import mss
import cv2
import numpy as np
from collections import deque
from pathlib import Path
from datetime import datetime
import traceback
import requests

# Google Drive Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
# ================= FFMPEG PATH RESOLUTION =================
def get_ffmpeg_path(tool="ffmpeg"):
    if getattr(sys, 'frozen', False):
        # If run from PyInstaller bundle
        base_path = sys._MEIPASS
    else:
        # If run from source
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    ext = ".exe" if os.name == 'nt' else ""
    
    # 1. Check in specific ffmpeg/ folder (for dev)
    local_path = os.path.join(base_path, "ffmpeg", f"{tool}{ext}")
    if os.path.exists(local_path):
        return local_path
        
    # 2. Check in root (for flat bundle)
    root_path = os.path.join(base_path, f"{tool}{ext}")
    if os.path.exists(root_path):
        return root_path
        
    # 3. Fallback to system PATH
    return tool# ================= DATA DIRECTORY RESOLUTION =================
def get_data_dir():
    """Returns a writable directory for config/logs/data"""
    app_name = "GigaClipper"
    if getattr(sys, 'frozen', False):
        # Production: Use %APPDATA%/GigaClipper
        # Fallback to local if APPDATA missing (unlikely on Windows)
        base = os.getenv('APPDATA') or os.path.expanduser("~")
        path = os.path.join(base, app_name)
    else:
        # Development: Use current directory
        path = os.path.dirname(os.path.abspath(__file__))
    
    if not os.path.exists(path):
        try: os.makedirs(path)
        except: pass
    return path

# ================= LOGGING SETUP =================
def safe_log(message):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_file = os.path.join(get_data_dir(), "debug_log.txt")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass

# ================= GESTOR DE CONFIGURACIÓN =================
# ================= GESTOR DE CONFIGURACIÓN =================
class ConfigManager:
    DEFAULT_CONFIG = {
        "buffer_minutes": 2,
        "fps": 60,
        "resolution_scale": 1.0,
        "video_quality": "High", # Ultra, High, Medium, Low
        "hotkey_clip": "f8",
        "hotkey_full": "alt+f7",
        "output_folder": os.path.join(os.path.expanduser("~"), "Videos", "GigaClipper"),
        "temp_folder": "Temp_Buffer", # Relative to data dir
        "auto_upload": True,
        "keep_local": False,
        "audio_device_index": None,
        "use_nvenc": False,
        "overlay_enabled": True,
        "monitor_index": 1,
        "auto_detect_apps": [
            "valorant.exe", "csgo.exe", "fortnite.exe", "r5apex.exe", "overwatch.exe",
            "wutheringwaves.exe", "client-win64-shipping.exe",  # Wuthering Waves
            "geometrydash.exe",  # Geometry Dash
            "league of legends.exe", "leagueclient.exe",  # League of Legends
            "robloxplayerbeta.exe", "robloxstudiobeta.exe",  # Roblox
            "thefinals.exe", "discovery.exe"  # The Finals
        ],
        "clip_duration": 15,
        "capture_mode": "monitor", # "monitor" or "window"
        "capture_window_title": None,
        "capture_window_hwnd": None,
        "theme": "default",
        "auto_start_recording": False
    }
    
    # Theme colors for overlay (matches CSS variables)
    THEME_COLORS = {
        "default":  {"primary": "#7a3b69", "accent": "#9a879d"},
        "coffee":   {"primary": "#9bbec7", "accent": "#e2c391"},
        "sage":     {"primary": "#7f9183", "accent": "#586f6b"},
        "forest":   {"primary": "#7b904b", "accent": "#58641d"},
        "grape":    {"primary": "#7261a3", "accent": "#a67db8"},
        "lavender": {"primary": "#9a879d", "accent": "#7a3b69"},
        "sunset":   {"primary": "#ff8a80", "accent": "#ff6b6b"},
        "ocean":    {"primary": "#26c6da", "accent": "#0097a7"},
        "midnight": {"primary": "#818cf8", "accent": "#6366f1"},
        "cherry":   {"primary": "#ff8fa3", "accent": "#ffb3ba"},
        "cyber":    {"primary": "#00d9ff", "accent": "#bd00ff"},
    }
    
    FILE_NAME = "giga_config.json"
    
    @staticmethod
    def get_config_path():
        return os.path.join(get_data_dir(), ConfigManager.FILE_NAME)
    
    @staticmethod
    def get_theme_color(config, color_type="primary"):
        theme = config.get("theme", "default")
        colors = ConfigManager.THEME_COLORS.get(theme, ConfigManager.THEME_COLORS["default"])
        return colors.get(color_type, colors["primary"])

    @staticmethod
    def load():
        path = ConfigManager.get_config_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    config = json.load(f)
                    return {**ConfigManager.DEFAULT_CONFIG, **config}
            except: pass
        return ConfigManager.DEFAULT_CONFIG

    @staticmethod
    def save(config):
        try:
            with open(ConfigManager.get_config_path(), 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            safe_log(f"Config Save Error: {e}")


# ================= CLIENTE DRIVE =================
class DriveClient:
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.readonly']

    def __init__(self, on_auth_success=None):
        self.service = None
        self.creds = None
        self.folder_id = None
        self.on_auth_success = on_auth_success
        self.auth_lock = threading.Lock() # Prevent race conditions during auth/refresh
        threading.Thread(target=self.login_silent, daemon=True).start()

    def login_silent(self):
        """Attempts to login silently using existing token. Returns True if successful. Non-blocking."""
        # Try to acquire lock with timeout to prevent freezing if interactive login is active
        acquired = self.auth_lock.acquire(timeout=2)
        if not acquired:
            safe_log("Silent login skipped: Auth lock held (likely interactive login in progress).")
            return False
            
        try:
            token_path = os.path.join(get_data_dir(), 'token.json')
            if os.path.exists(token_path):
                try:
                    self.creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)
                except Exception as e:
                    safe_log(f"Token file corrupt or invalid: {e}")
                    self.creds = None

            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    safe_log(f"Error refreshing token: {e}")
                    self.creds = None
            
            if self.creds and self.creds.valid:
                    self.service = build('drive', 'v3', credentials=self.creds)
                    # Lazy load folder checking to avoid API call on startup if unnecessary
                    # self.folder_id = self.get_or_create_folder("CustomClipper") 
                    safe_log("Silent Drive login successful.")
                    return True
            
            safe_log("Silent login failed: No valid token found.")
            return False
        except Exception as e:
            safe_log(f"Silent Auth Critical Error: {e}")
            return False
        finally:
            self.auth_lock.release()

    def login_interactive(self):
        """Triggers browser popup for detailed login. Returns True if successful."""
        with self.auth_lock:
            try:
                # If already valid, do nothing
                if self.creds and self.creds.valid:
                    return True
                    
                creds_path = 'credentials.json'
                # Check bundled credentials if frozen
                if getattr(sys, 'frozen', False):
                    bundled = os.path.join(sys._MEIPASS, 'credentials.json')
                    if os.path.exists(bundled): creds_path = bundled
                elif os.path.exists(os.path.join(os.path.dirname(__file__), 'credentials.json')):
                     creds_path = os.path.join(os.path.dirname(__file__), 'credentials.json')

                if os.path.exists(creds_path):
                    flow = InstalledAppFlow.from_client_secrets_file(creds_path, self.SCOPES)
                    self.creds = flow.run_local_server(port=0)
                else:
                    safe_log(f"Missing credentials.json at {creds_path} for interactive authentication.")
                    return False

                token_path = os.path.join(get_data_dir(), 'token.json')
                with open(token_path, 'w') as token:
                    token.write(self.creds.to_json())
            
                self.service = build('drive', 'v3', credentials=self.creds)
                # Ensure folder exists upon login
                self.folder_id = self.get_or_create_folder("CustomClipper")
                safe_log("Interactive Drive login successful.")
                if self.on_auth_success:
                    self.on_auth_success()
                return True
            except Exception as e:
                safe_log(f"Interactive Auth Error: {e}")
                return False

    def authenticate(self):
        """Legacy method for backward compatibility - calls silent then interactive"""
        if not self.login_silent():
            self.login_interactive()

    def get_or_create_folder(self, folder_name):
        if not self.service: return None
        
        # Buscar la carpeta
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = self.service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        if files:
            return files[0]['id']
        else:
            # Crear la carpeta si no existe
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            file = self.service.files().create(body=file_metadata, fields='id').execute()
            print(f"Folder '{folder_name}' created in Drive.")
            return file.get('id')

    def list_videos(self):
        if not self.creds or not self.creds.valid:
             if not self.login_silent():
                 safe_log("Drive not connected. Skipping list_videos.")
                 return [] # Do NOT trigger interactive login here
             
        if not self.service: return []
        
        # Ensure folder ID is loaded (since we lazy loaded in silent login)
        if not self.folder_id:
             self.folder_id = self.get_or_create_folder("CustomClipper")
        
        # Cache Trims folder ID if not already cached (lazy load)
        if not hasattr(self, 'trims_folder_id') or not self.trims_folder_id:
             self.trims_folder_id = self._get_or_create_subfolder("Trims")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                base_q = "mimeType contains 'video/' and trashed=false"
                if self.folder_id:
                    # Search in BOTH root folder and Trims subfolder
                    parents_q = f"'{self.folder_id}' in parents"
                    if self.trims_folder_id:
                        parents_q = f"('{self.folder_id}' in parents or '{self.trims_folder_id}' in parents)"
                    
                    q = f"{parents_q} and {base_q}"
                else:
                    q = base_q
                    
                results = self.service.files().list(
                    q=q,
                    pageSize=50, # Increased page size
                    fields="nextPageToken, files(id, name, thumbnailLink, webViewLink, videoMediaMetadata, createdTime)"
                ).execute()
                return results.get('files', [])
            except Exception as e:
                safe_log(f"Error listing videos (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    safe_log(f"Final failure listing videos: {traceback.format_exc()}")
                time.sleep(1 * (attempt + 1))
        return []

    def upload(self, file_path):
        if not self.service: return None
        try:
            file_metadata = {'name': os.path.basename(file_path)}
            if self.folder_id:
                file_metadata['parents'] = [self.folder_id]
                
            media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
            file = self.service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            return file
        except Exception as e:
            print(f"Error uploading file: {e}")
            return None

    def upload_to_trims(self, file_path):
        """Upload file to Trims subfolder inside CustomClipper"""
        if not self.service: return None
        try:
            # Get or create Trims folder inside CustomClipper
            trims_folder_id = self._get_or_create_subfolder("Trims")
            if not trims_folder_id:
                return None
                
            file_metadata = {'name': os.path.basename(file_path), 'parents': [trims_folder_id]}
            media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
            file = self.service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            return file
        except Exception as e:
            print(f"Error uploading to trims: {e}")
            return None

    def _get_or_create_subfolder(self, folder_name):
        """Get or create a subfolder inside the main CustomClipper folder"""
        if not self.service or not self.folder_id: return None
        try:
            # Search for existing folder
            q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{self.folder_id}' in parents and trashed = false"
            results = self.service.files().list(q=q, fields="files(id)").execute()
            files = results.get('files', [])
            if files:
                return files[0]['id']
            
            # Create folder
            metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [self.folder_id]
            }
            folder = self.service.files().create(body=metadata, fields='id').execute()
            return folder.get('id')
        except Exception as e:
            print(f"Error creating subfolder: {e}")
            return None

    def check_for_updates(self, current_version):
        """Checks for updates in the 'GigaClipperUpdates' folder on Drive.
           Returns { available: bool, version: str, notes: str, file_id: str }
        """
        if not self.login_silent():
            return {"available": False, "error": "Not connected"}
            
        try:
            # 1. Find 'GigaClipperUpdates' folder
            query = "mimeType='application/vnd.google-apps.folder' and name='GigaClipperUpdates' and trashed=false"
            results = self.service.files().list(q=query, fields="files(id, name)").execute()
            items = results.get('files', [])
            
            if not items:
                return {"available": False, "error": "Update folder not found"}
                
            update_folder_id = items[0]['id']
            
            # 2. Find 'version.json' inside
            query = f"'{update_folder_id}' in parents and name='version.json' and trashed=false"
            results = self.service.files().list(q=query, fields="files(id, name)").execute()
            items = results.get('files', [])
            
            if not items:
                return {"available": False, "error": "Version info not found"}
                
            version_file_id = items[0]['id']
            
            # 3. Read version.json content
            request = self.service.files().get_media(fileId=version_file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                
            fh.seek(0)
            version_data = json.load(fh)
            
            remote_version = version_data.get('version', '0.0.0')
            release_notes = version_data.get('notes', 'No notes provided.')
            installer_name = version_data.get('installer_name', 'GigaClipperSetup.exe')
            
            # 4. Compare versions (Simple string comparison for now, assuming semantic versioning)
            # A robust comparison would parse x.y.z
            if remote_version > current_version:
                # Find the installer file
                query = f"'{update_folder_id}' in parents and name='{installer_name}' and trashed=false"
                results = self.service.files().list(q=query, fields="files(id, name)").execute()
                files = results.get('files', [])
                
                if files:
                    return {
                        "available": True, 
                        "version": remote_version, 
                        "notes": release_notes,
                        "file_id": files[0]['id'],
                        "filename": files[0]['name']
                    }
            
            return {"available": False, "version": remote_version}

        except Exception as e:
            safe_log(f"Update Check Error: {e}")
            return {"available": False, "error": str(e)}

    def download_update(self, file_id, filename):
        """Downloads the update installer to the temp folder."""
        try:
            if not self.creds: return None
            
            temp_dir = os.path.join(os.environ.get('TEMP'), 'GigaClipperUpdates')
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                
            destination = os.path.join(temp_dir, filename)
            
            request = self.service.files().get_media(fileId=file_id)
            fh = io.FileIO(destination, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                
            return destination
        except Exception as e:
            safe_log(f"Update Download Error: {e}")
            return None            
    def download(self, file_id, dest_path):
        """Download a file efficiently using streaming"""
        try:
            # Use our unified stream method to download
            response = self.open_stream(file_id)
            if not response: return False
            
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024*1024): # 1MB chunks
                    if chunk: f.write(chunk)
            return True
        except Exception as e:
            safe_log(f"Error downloading file {file_id}: {e}")

    def open_stream(self, file_id, start=0, end=None):
        """
        Opens a robust HTTP stream to Google Drive file.
        Returns the requests.Response object (stream=True).
        Handles Authentication and Range headers automatically.
        """
        # 1. Ensure Auth
        if not self.creds or not self.creds.valid:
            self.authenticate()
            
        try:
            # 2. Prepare Request
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            headers = {"Authorization": f"Bearer {self.creds.token}"}
            
            # 3. Handle Range (if requested)
            if start > 0 or end is not None:
                range_str = f"bytes={start}-"
                if end: range_str += f"{end}"
                headers["Range"] = range_str
                
            # 4. Execute Request
            # stream=True is critical for memory efficiency and speed
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            
            # 5. Check immediate errors
            if response.status_code >= 400:
                # If 401/403, might be expired token, try once refresh
                if response.status_code in [401, 403]:
                    safe_log("Drive stream 401/403, refreshing auth...")
                    self.authenticate()
                    headers["Authorization"] = f"Bearer {self.creds.token}"
                    response = requests.get(url, headers=headers, stream=True, timeout=15)
                
                if response.status_code >= 400:
                    safe_log(f"Drive stream failed: {response.status_code} - {response.text}")
                    return None
                    
            return response
            
        except Exception as e:
            safe_log(f"Error opening drive stream: {e}")
            return None
            
    # Legacy aliases mapped to new system for compatibility
    def stream_video_range(self, file_id, start, end):
        return self.open_stream(file_id, start, end)

    def stream_video_chunks(self, file_id, chunk_size=1024*1024):
        resp = self.open_stream(file_id)
        if resp:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk: yield chunk

    def get_video_size(self, file_id):
        """Get file size for Content-Length header with auth check"""
        if not self.creds or not self.creds.valid:
             self.authenticate()
             
        if not self.service: return None
        
        try:
            file = self.service.files().get(fileId=file_id, fields='size').execute()
            return int(file.get('size', 0))
        except Exception as e:
            safe_log(f"Error getting video size for {file_id}: {e}")
            # Try once more with re-auth if it might be an auth issue
            try:
                self.authenticate()
                file = self.service.files().get(fileId=file_id, fields='size').execute()
                return int(file.get('size', 0))
            except:
                return None

    def delete(self, file_id):
        if not self.service: return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            print(f"Error deleting from Drive: {e}")
            return False

# ================= MOTOR DE AUDIO =================
class AudioRecorder(threading.Thread):
    def __init__(self, filename, device_index=None):
        super().__init__(daemon=True)
        self.filename = filename
        self.device_index = device_index
        self.running = True
        self.p = pyaudio.PyAudio()
        self.frames = []
        self.channels = 2  # Default

    def run(self):
        try:
            try:
                stream = self.p.open(format=pyaudio.paInt16,
                                     channels=2,
                                     rate=44100,
                                     input=True,
                                     input_device_index=self.device_index,
                                     frames_per_buffer=1024)
                self.channels = 2
            except Exception:
                stream = self.p.open(format=pyaudio.paInt16,
                                     channels=1,
                                     rate=44100,
                                     input=True,
                                     input_device_index=self.device_index,
                                     frames_per_buffer=1024)
                self.channels = 1

            while self.running:
                data = stream.read(1024, exception_on_overflow=False)
                self.frames.append(data)
            
            stream.stop_stream()
            stream.close()
            self.save()
        except Exception as e:
            print(f"[AUDIO] Error: {e}")
        finally:
            self.p.terminate()

    def stop(self):
        self.running = False

    def save(self):
        if not self.frames: return
        wf = wave.open(self.filename, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(self.frames))
        wf.close()

# ================= MOTOR DE VIDEO =================
class RecorderEngine:
    CHUNK_DURATION = 5

    def __init__(self, config, on_notification=None):
        self.config = config
        self.on_notification = on_notification # Callback(text, color, duration)
        self.running = False
        self.recording_thread = None
        self.chunks = deque()
        self.lock = threading.Lock()
        self.flush_requested = False
        
        Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)
        
        # Resolve temp folder
        if not os.path.isabs(self.config["temp_folder"]):
            self.config["temp_folder"] = os.path.join(get_data_dir(), self.config["temp_folder"])
            
        Path(self.config["temp_folder"]).mkdir(parents=True, exist_ok=True)
        self.clean_temp_folder()

    def notify(self, text, color="#4CAF50", duration=3000):
        try:
            safe_log(f"[NOTIFY] {text}")
        except:
            safe_log("[NOTIFY] (Message could not be printed due to encoding)")

        if self.on_notification and self.config["overlay_enabled"]:
            self.on_notification(text, color, duration)

    def clean_temp_folder(self):
        folder = self.config["temp_folder"]
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path): os.unlink(file_path)
            except Exception as e:
                print(f"Error limpiando temp: {e}")

    def get_resolution(self):
        with mss.mss() as sct:
            monitor = sct.monitors[self.config["monitor_index"]]
            return int(monitor["width"] * self.config["resolution_scale"]), \
                   int(monitor["height"] * self.config["resolution_scale"])

    def _get_capture_region(self, sct):
        # Determine capture area: Monitor or Window
        mode = self.config.get("capture_mode", "monitor")
        
        if mode == "window":
            hwnd = self.config.get("capture_window_hwnd")
            if hwnd:
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    rect = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        width = rect.right - rect.left
                        height = rect.bottom - rect.top
                        if width > 0 and height > 0:
                            return {"top": rect.top, "left": rect.left, "width": width, "height": height}
                except Exception as e:
                    print(f"Window capture error: {e}")
        
        # Fallback to monitor
        return sct.monitors[self.config["monitor_index"]]

    def start(self):
        if self.running: return
        self.running = True
        self.recording_thread = threading.Thread(target=self._buffer_loop, daemon=True)
        self.recording_thread.start()
        self.notify("🔴 GigaClipper: Buffer Started", ConfigManager.get_theme_color(self.config, "primary"))

    def stop(self):
        self.running = False
        if self.recording_thread:
            self.recording_thread.join()
        self.clean_temp_folder()
        self.notify("GigaClipper: Buffer Stopped", ConfigManager.get_theme_color(self.config, "accent"))

    def _buffer_loop(self):
        # We need dynamic resolution handling for window mode effectively, 
        # but for simplicity let's stick to initial resolution or try to adapt?
        # If window resizes, video might break if resolution changes mid-stream (AVI/CV2 limitation).
        # We will lock resolution at start of recording for now.
        
        with mss.mss() as sct:
            rect = self._get_capture_region(sct)
            w, h = int(rect["width"] * self.config["resolution_scale"]), int(rect["height"] * self.config["resolution_scale"])
             # Ensure even dimensions for ffmpeg compatibility
            w = w - (w % 2)
            h = h - (h % 2)

            while self.running:
                chunk_name = os.path.join(self.config["temp_folder"], f"chunk_{int(time.time())}.avi")
                fourcc = cv2.VideoWriter_fourcc(*'MJPG') 
                target_fps = self.config["fps"]
                out = cv2.VideoWriter(chunk_name, fourcc, target_fps, (w, h))
                
                start_time = time.time()
                frame_count = 0
                
                audio_chunk_name = chunk_name.replace(".avi", ".wav")
                audio_rec = AudioRecorder(audio_chunk_name, self.config["audio_device_index"])
                audio_rec.start()

                while time.time() - start_time < self.CHUNK_DURATION and self.running:
                    if self.flush_requested: break
                    loop_start = time.time()
                    
                    # Capture specific region (rect)
                    img = np.array(sct.grab(rect))
                    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    if self.config["resolution_scale"] != 1.0:
                        frame = cv2.resize(frame, (w, h))
                    
                    out.write(frame)
                    frame_count += 1
                    
                    elapsed = time.time() - loop_start
                    target_delay = 1.0 / target_fps
                    remaining = target_delay - elapsed
                    if remaining > 0: time.sleep(remaining)

                out.release()
                audio_rec.stop()
                audio_rec.join()
                
                # Metadata FPS
                chunk_duration = time.time() - start_time
                actual_fps = frame_count / chunk_duration if chunk_duration > 0 else target_fps
                meta_file = chunk_name.replace(".avi", ".meta")
                with open(meta_file, "w") as mf: mf.write(f"{actual_fps:.2f}")
                
                with self.lock:
                    self.chunks.append((chunk_name, audio_chunk_name, meta_file))
                    needed_chunks = (self.config["buffer_minutes"] * 60) // self.CHUNK_DURATION
                    while len(self.chunks) > needed_chunks + 2:
                        old_files = self.chunks.popleft()
                        for f in old_files:
                            try: os.remove(f)
                            except: pass
                
                self.flush_requested = False

    def save_clip(self, duration_seconds=None):
        if not self.running:
            print("Buffer is not active.")
            return None

        theme_color = ConfigManager.get_theme_color(self.config, "primary")
        self.notify("💾 Saving Clip...", theme_color)
        
        self.flush_requested = True
        time.sleep(0.3)
            
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        final_video = os.path.join(self.config["output_folder"], f"Clip_{timestamp}.mp4")
        
        with self.lock:
            if duration_seconds:
                chunks_needed = int(duration_seconds // self.CHUNK_DURATION) + 1
                current_chunks = list(self.chunks)[-chunks_needed:]
            else:
                current_chunks = list(self.chunks)

        if not current_chunks:
            self.notify("❌ Error: No data", "red")
            return None

        v_list = os.path.join(self.config["temp_folder"], "v_list.txt")
        a_list = os.path.join(self.config["temp_folder"], "a_list.txt")
        
        valid_chunks = []
        fps_values = []
        
        with open(v_list, "w") as fv, open(a_list, "w") as fa:
            for chunk_data in current_chunks:
                if len(chunk_data) == 3: vid, aud, meta = chunk_data
                else: vid, aud = chunk_data; meta = None
                
                if os.path.exists(vid) and os.path.exists(aud):
                    fv.write(f"file '{os.path.abspath(vid)}'\n")
                    fa.write(f"file '{os.path.abspath(aud)}'\n")
                    valid_chunks.append((vid, aud))
                    if meta and os.path.exists(meta):
                        try:
                            with open(meta, "r") as mf: fps_values.append(float(mf.read().strip()))
                        except: pass

        if not valid_chunks: return None

        avg_fps = sum(fps_values) / len(fps_values) if fps_values else 30
        print(f"Average real FPS: {avg_fps:.1f}")

        try:
            temp_v = os.path.join(self.config["temp_folder"], "temp_v.mp4")
            temp_a = os.path.join(self.config["temp_folder"], "temp_a.wav")
            
            # CREATE_NO_WINDOW flag to hide CMD on Windows
            no_window = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            
            ffmpeg_exe = get_ffmpeg_path("ffmpeg")
            
            subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', v_list, '-c', 'copy', temp_v], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=no_window)
            subprocess.run([ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', a_list, temp_a], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=no_window)
            
            quality_map = {"Ultra": "17", "High": "21", "Medium": "26", "Low": "32"}
            crf_val = quality_map.get(self.config.get("video_quality", "High"), "21")
            
            cmd_mux = [
                ffmpeg_exe, '-y', 
                '-r', str(int(round(avg_fps))),
                '-i', temp_v, '-i', temp_a,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', crf_val,
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest', final_video
            ]
            
            subprocess.run(cmd_mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=no_window)
            
            for t in [temp_v, temp_a, v_list, a_list]:
                if os.path.exists(t):
                    try: os.remove(t)
                    except: pass

            self.notify(f"✅ Clip Saved: {duration_seconds or 'Full'}s", ConfigManager.get_theme_color(self.config, "primary"))
            return final_video
            
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg encoding error (code {e.returncode}).")
            self.notify("❌ FFmpeg Error", "red")
            return None
        except Exception as e:
            print(f"Unexpected error saving clip: {e}")
            return None
