import cv2
import numpy as np
import mss
import time
import os
import threading
import keyboard
import shutil
import json
import psutil
import subprocess
import webbrowser
import pyaudio
import wave
from datetime import datetime
from collections import deque
from pathlib import Path

# GUI Imports
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk

# Google Drive Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configuración de tema
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

ACCENT_COLOR = "#3d5afe" # Indigo accent
BG_COLOR = "#0f111a"
SIDEBAR_COLOR = "#080a0f"

# ================= GESTOR DE CONFIGURACIÓN =================
class ConfigManager:
    DEFAULT_CONFIG = {
        "buffer_minutes": 2,
        "fps": 60,
        "resolution_scale": 1.0,
        "video_quality": "High", # Ultra, High, Medium, Low
        "hotkey_clip": "f8",
        "hotkey_full": "alt+f7",
        "output_folder": "Clips",
        "temp_folder": "Temp_Buffer",
        "auto_upload": True,
        "keep_local": False,
        "audio_device_index": None,
        "use_nvenc": False,  # Disabled by default - libx264 is more reliable
        "overlay_enabled": True,
        "monitor_index": 1,
        "auto_detect_apps": ["valorant.exe", "csgo.exe", "fortnite.exe", "r5apex.exe", "overwatch.exe"]
    }
    
    FILE_PATH = "medal_config.json"

    @staticmethod
    def load():
        if os.path.exists(ConfigManager.FILE_PATH):
            with open(ConfigManager.FILE_PATH, 'r') as f:
                config = json.load(f)
                # Merge con defaults por si hay claves nuevas
                return {**ConfigManager.DEFAULT_CONFIG, **config}
        return ConfigManager.DEFAULT_CONFIG

    @staticmethod
    def save(config):
        with open(ConfigManager.FILE_PATH, 'w') as f:
            json.dump(config, f, indent=4)

# ================= OVERLAY (NOTIFICACIONES) =================
class OverlayManager:
    def __init__(self):
        self.root = None

    def show_notification(self, text, duration=3000, color="#4CAF50"):
        if self.root:
            try: self.root.destroy()
            except: pass
        
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.8)
        self.root.config(bg="black")
        
        # Posicionar arriba a la izquierda
        self.root.geometry(f"300x50+20+20")
        
        label = tk.Label(self.root, text=text, fg="white", bg=color, font=("Arial", 12, "bold"))
        label.pack(fill="both", expand=True, padx=2, pady=2)
        
        self.root.after(duration, self.close)
        
    def close(self):
        if self.root:
            self.root.destroy()
            self.root = None

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
            # Intentar primero con 2 canales (Stereo), si falla bajar a 1 (Mono)
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

# ================= MOTOR DE GRABACIÓN DE VIDEO =================
class RecorderEngine:
    CHUNK_DURATION = 5  # Segundos por mini-archivo

    def __init__(self, config):
        self.config = config
        self.running = False
        self.recording_thread = None
        self.chunks = deque()
        self.lock = threading.Lock()
        self.overlay = OverlayManager()
        self.flush_requested = False  # Para forzar guardado del chunk actual
        
        # Crear directorios
        Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)
        Path(self.config["temp_folder"]).mkdir(parents=True, exist_ok=True)
        self.clean_temp_folder()

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

    def start(self):
        if self.running: return
        self.running = True
        self.recording_thread = threading.Thread(target=self._buffer_loop, daemon=True)
        self.recording_thread.start()
        if self.config["overlay_enabled"]:
            self.overlay.show_notification("🔴 Medal Pro: Buffer Started", color="#2196F3")

    def stop(self):
        self.running = False
        if self.recording_thread:
            self.recording_thread.join()
        self.clean_temp_folder()
        if self.config["overlay_enabled"]:
            self.overlay.show_notification("Medal Pro: Buffer Stopped", color="#f44336")

    def _buffer_loop(self):
        w, h = self.get_resolution()
        
        with mss.mss() as sct:
            monitor = sct.monitors[self.config["monitor_index"]]
            
            while self.running:
                chunk_name = os.path.join(self.config["temp_folder"], f"chunk_{int(time.time())}.avi")
                # Usamos MJPG para velocidad en escritura de buffer
                fourcc = cv2.VideoWriter_fourcc(*'MJPG') 
                # Usar el FPS configurado por el usuario
                target_fps = self.config["fps"]
                out = cv2.VideoWriter(chunk_name, fourcc, target_fps, (w, h))
                
                start_time = time.time()
                frame_count = 0
                
                # Audio para este chunk
                audio_chunk_name = chunk_name.replace(".avi", ".wav")
                audio_rec = AudioRecorder(audio_chunk_name, self.config["audio_device_index"])
                audio_rec.start()

                while time.time() - start_time < self.CHUNK_DURATION and self.running:
                    # Verificar si hay solicitud de flush (para no perder frames al clipear)
                    if self.flush_requested:
                        break
                    
                    loop_start = time.time()
                    
                    # Captura rápida
                    img = np.array(sct.grab(monitor))
                    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    
                    if self.config["resolution_scale"] != 1.0:
                        frame = cv2.resize(frame, (w, h))
                    
                    out.write(frame)
                    frame_count += 1
                    
                    # Sincronizar al FPS objetivo (sin cap artificial)
                    elapsed = time.time() - loop_start
                    target_delay = 1.0 / target_fps
                    remaining = target_delay - elapsed
                    if remaining > 0:
                        time.sleep(remaining)


                out.release()
                audio_rec.stop()
                audio_rec.join()
                
                # Calcular FPS real de este chunk
                chunk_duration = time.time() - start_time
                actual_fps = frame_count / chunk_duration if chunk_duration > 0 else target_fps
                
                # Guardar metadata del chunk
                meta_file = chunk_name.replace(".avi", ".meta")
                with open(meta_file, "w") as mf:
                    mf.write(f"{actual_fps:.2f}")
                
                # Gestión del buffer circular
                with self.lock:
                    self.chunks.append((chunk_name, audio_chunk_name, meta_file))
                    # Calcular cuántos chunks necesitamos para cubrir X minutos
                    needed_chunks = (self.config["buffer_minutes"] * 60) // self.CHUNK_DURATION
                    
                    while len(self.chunks) > needed_chunks + 2:
                        old_v, old_a, old_m = self.chunks.popleft()
                        for f in [old_v, old_a, old_m]:
                            try: os.remove(f)
                            except: pass
                
                # Resetear flag de flush
                self.flush_requested = False


    def save_clip(self, duration_seconds=None):
        """Une los chunks, procesa con FFmpeg y guarda."""
        if not self.running:
            print("Buffer is not active. Start the buffer first.")
            return None

        if self.config["overlay_enabled"]:
            self.overlay.show_notification("💾 Saving Clip...", color="#FF9800")
        
        # Forzar flush del chunk actual para incluir los frames más recientes
        self.flush_requested = True
        time.sleep(0.3)  # Dar tiempo para que el chunk se cierre
            
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        final_video = os.path.join(self.config["output_folder"], f"Clip_{timestamp}.mp4")
        
        with self.lock:
            if duration_seconds:
                chunks_needed = int(duration_seconds // self.CHUNK_DURATION) + 1
                current_chunks = list(self.chunks)[-chunks_needed:]
            else:
                current_chunks = list(self.chunks)

        if not current_chunks: 
            print("No chunks in buffer yet. Wait a few seconds.")
            if self.config["overlay_enabled"]:
                self.overlay.show_notification("❌ Error: No data", color="red")
            return None

        # 1. Crear archivos de lista para ffmpeg concat y calcular FPS promedio
        v_list = os.path.join(self.config["temp_folder"], "v_list.txt")
        a_list = os.path.join(self.config["temp_folder"], "a_list.txt")
        
        valid_chunks = []
        fps_values = []
        
        with open(v_list, "w") as fv, open(a_list, "w") as fa:
            for chunk_data in current_chunks:
                # Soportar tanto (vid, aud) como (vid, aud, meta)
                if len(chunk_data) == 3:
                    vid, aud, meta = chunk_data
                else:
                    vid, aud = chunk_data
                    meta = None
                
                if os.path.exists(vid) and os.path.exists(aud):
                    fv.write(f"file '{os.path.abspath(vid)}'\n")
                    fa.write(f"file '{os.path.abspath(aud)}'\n")
                    valid_chunks.append((vid, aud))
                    
                    # Leer FPS real del metadata
                    if meta and os.path.exists(meta):
                        try:
                            with open(meta, "r") as mf:
                                fps_values.append(float(mf.read().strip()))
                        except: pass

        if not valid_chunks:
            print("Temporary chunk files do not exist.")
            return None

        # Calculate average real FPS (or use 30 as fallback)
        avg_fps = sum(fps_values) / len(fps_values) if fps_values else 30
        print(f"Average real FPS: {avg_fps:.1f}")


        try:
            temp_v = os.path.join(self.config["temp_folder"], "temp_v.mp4")
            temp_a = os.path.join(self.config["temp_folder"], "temp_a.wav")
            
            # Unir Video (Stream Copy para velocidad)
            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', v_list, '-c', 'copy', temp_v], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Unir Audio
            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', a_list, temp_a], 
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Calidad de Video (CRF)
            # Map: Ultra=17, High=21, Medium=26, Low=32
            quality_map = {"Ultra": "17", "High": "21", "Medium": "26", "Low": "32"}
            crf_val = quality_map.get(self.config.get("video_quality", "High"), "21")

            # Combinar (Mux) con framerate REAL calculado - Siempre usar libx264 (más confiable)
            fps = str(int(round(avg_fps)))
            cmd_mux = [
                'ffmpeg', '-y', 
                '-r', fps,
                '-i', temp_v, 
                '-i', temp_a,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', crf_val,
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest', final_video
            ]
            
            subprocess.run(cmd_mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            
            # Limpiar temporales del clip
            for t in [temp_v, temp_a, v_list, a_list]:
                if os.path.exists(t):
                    try: os.remove(t)
                    except: pass

            if self.config["overlay_enabled"]:
                self.overlay.show_notification(f"✅ Clip Guardado: {duration_seconds or 'Full'}s", color="#4CAF50")
            
            return final_video
            
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg encoding error (code {e.returncode}).")
            if self.config["overlay_enabled"]:
                self.overlay.show_notification("❌ FFmpeg Error", color="red")
            return None

        except FileNotFoundError:
            msg = "FFMPEG not found. Download from https://ffmpeg.org/ and add to PATH."
            print(f"\n[ERROR] {msg}")
            self.overlay.show_notification("❌ Error: Missing FFmpeg", color="red")
            return None
        except Exception as e:
            print(f"Unexpected error saving clip: {e}")
            return None

# ================= CLIENTE DRIVE (INTEGRADO) =================
class DriveClient:
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.readonly']

    def __init__(self):
        self.service = None
        self.creds = None
        self.folder_id = None
        threading.Thread(target=self.authenticate, daemon=True).start()

    def authenticate(self):
        try:
            if os.path.exists('token.json'):
                self.creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
            
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    try:
                        self.creds.refresh(Request())
                    except Exception as e:
                        print(f"Error refreshing token: {e}")
                        self.creds = None # Forzar re-login
                
                if not self.creds or not self.creds.valid:
                    if os.path.exists('credentials.json'):
                        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.SCOPES)
                        self.creds = flow.run_local_server(port=0)
                    else:
                        print("Missing credentials.json for initial authentication.")
                        return

                with open('token.json', 'w') as token:
                    token.write(self.creds.to_json())
            
            self.service = build('drive', 'v3', credentials=self.creds)
            self.folder_id = self.get_or_create_folder("CustomClipper")
            print("Google Drive authentication successful.")
        except Exception as e:
            print(f"Drive Auth Critical Error: {e}")

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
        if not self.service: return []
        try:
            q = "mimeType contains 'video/' and trashed=false"
            if self.folder_id:
                q = f"'{self.folder_id}' in parents and " + q
                
            results = self.service.files().list(
                q=q,
                pageSize=20, fields="nextPageToken, files(id, name, thumbnailLink, webViewLink)").execute()
            return results.get('files', [])
        except Exception as e:
            print(f"Error listing videos: {e}")
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

    def download(self, file_id, dest_path):
        if not self.service: return False
        try:
            request = self.service.files().get_media(fileId=file_id)
            with open(dest_path, "wb") as f:
                f.write(request.execute())
            return True
        except Exception as e:
            print(f"Error downloading file: {e}")
            return False

    def delete(self, file_id):
        """Delete a file from Google Drive."""
        if not self.service: return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            print(f"File {file_id} deleted from Drive.")
            return True
        except Exception as e:
            print(f"Error deleting from Drive: {e}")
            return False

# ================= INTERFAZ GRÁFICA MODERNA =================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config = ConfigManager.load()
        self.recorder = RecorderEngine(self.config)
        self.drive = DriveClient()
        self.title("OPEN MEDAL PRO 🚀")
        self.geometry("1000x650")
        self.configure(fg_color=BG_COLOR)
        
        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDEBAR_COLOR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo = ctk.CTkLabel(self.sidebar, text="🎮 OPEN MEDAL", font=ctk.CTkFont(size=22, weight="bold", family="Segoe UI"))
        self.logo.pack(pady=30)
        
        button_style = {"height": 45, "corner_radius": 8, "font": ("Segoe UI", 13, "bold"), "anchor": "w"}
        
        self.btn_capture = ctk.CTkButton(self.sidebar, text="  📸 Capture", command=lambda: self.show_frame("capture"), fg_color="transparent", hover_color=ACCENT_COLOR, **button_style)
        self.btn_capture.pack(pady=5, padx=15, fill="x")
        
        self.btn_library = ctk.CTkButton(self.sidebar, text="  📁 Library", command=lambda: self.show_frame("library"), fg_color="transparent", hover_color=ACCENT_COLOR, **button_style)
        self.btn_library.pack(pady=5, padx=15, fill="x")
        
        self.btn_settings = ctk.CTkButton(self.sidebar, text="  ⚙️ Settings", command=lambda: self.show_frame("settings"), fg_color="transparent", hover_color=ACCENT_COLOR, **button_style)
        self.btn_settings.pack(pady=5, padx=15, fill="x")

        # Footer sidebar
        ctk.CTkLabel(self.sidebar, text="Build v2.0 Premium", font=("Arial", 10), text_color="gray").pack(side="bottom", pady=20)

        # Main Area
        self.main_area = ctk.CTkFrame(self, corner_radius=15, fg_color=BG_COLOR)
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        # Frames
        self.frames = {}
        self.init_capture_frame()
        self.init_library_frame()
        self.init_settings_frame()
        
        self.show_frame("capture")
        
        # Hotkeys
        keyboard.add_hotkey(self.config["hotkey_clip"], self.trigger_clip)
        
        # Auto-detect loop
        self.after(5000, self.auto_detect_apps)

    def show_frame(self, name):
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill="both", expand=True, padx=20, pady=20)
        if name == "library":
            self.refresh_library()

    # --- FRAME: CAPTURA ---
    def init_capture_frame(self):
        frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.frames["capture"] = frame
        
        # Header
        ctk.CTkLabel(frame, text="🚀 CAPTURE CENTER", font=("Segoe UI", 24, "bold")).pack(pady=20)

        preview_container = ctk.CTkFrame(frame, fg_color=SIDEBAR_COLOR, corner_radius=15)
        preview_container.pack(pady=10, padx=20, fill="both", expand=True)

        self.lbl_preview = ctk.CTkLabel(preview_container, text="LIVE PREVIEW", font=("Segoe UI", 12, "bold"), text_color="gray")
        self.lbl_preview.pack(pady=5)
        
        self.preview_image = ctk.CTkLabel(preview_container, text="", corner_radius=10)
        self.preview_image.pack(pady=10, padx=20, fill="both", expand=True)
        
        # Controles
        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.pack(pady=30, fill="x")
        
        self.btn_start = ctk.CTkButton(controls, text="▶ START RECORDING", height=50, command=self.toggle_recording, fg_color="#27ae60", hover_color="#2ecc71", font=("Segoe UI", 14, "bold"))
        self.btn_start.pack(side="left", padx=10, expand=True)
        
        self.btn_clip_15 = ctk.CTkButton(controls, text="⏱ Clip 15s", height=50, command=lambda: self.trigger_clip(15), fg_color=ACCENT_COLOR, font=("Segoe UI", 14, "bold"))
        self.btn_clip_15.pack(side="left", padx=5, expand=True)
        
        self.btn_clip_full = ctk.CTkButton(controls, text="📀 Full Clip", height=50, command=lambda: self.trigger_clip(None), fg_color="#8e44ad", font=("Segoe UI", 14, "bold"))
        self.btn_clip_full.pack(side="left", padx=5, expand=True)

        self.btn_open_folder = ctk.CTkButton(frame, text="📂 OPEN CLIPS FOLDER", height=35, command=self.open_output_folder, fg_color="transparent", border_width=1, font=("Segoe UI", 11))
        self.btn_open_folder.pack(pady=5)

        self.lbl_status = ctk.CTkLabel(frame, text="• STATUS: IDLE", font=("Segoe UI", 11, "bold"), text_color="gray")
        self.lbl_status.pack(pady=10)
        
        self.update_preview()

    def update_preview(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[self.config["monitor_index"]]
                img = sct.grab(monitor)
                img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                img.thumbnail((400, 225)) # 16:9 thumbnail
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(400, 225))
                self.preview_image.configure(image=ctk_img)
        except: pass
        
        if self.recorder.running:
            self.lbl_status.configure(text=f"• STATUS: 🔴 RECORDING BUFFER ({self.config['buffer_minutes']} min)", text_color="#e74c3c")
        else:
            self.lbl_status.configure(text="• STATUS: IDLE", text_color="gray")
            
        self.after(2000, self.update_preview)

    def toggle_recording(self):
        if self.recorder.running:
            self.recorder.stop()
            self.btn_start.configure(text="▶ START RECORDING", fg_color="#27ae60", hover_color="#2ecc71")
        else:
            self.recorder.start()
            self.btn_start.configure(text="⏹ STOP RECORDING", fg_color="#c0392b", hover_color="#e74c3c")

    def trigger_clip(self, duration=None):
        if not self.recorder.running:
            messagebox.showwarning("Error", "Buffer is not active")
            return
        
        def save_task():
            try:
                path = self.recorder.save_clip(duration)
                if path and os.path.exists(path):
                    print(f"Clip saved locally at: {path}")
                    
                    if self.config["auto_upload"]:
                        upload_result = self.drive.upload(path)
                        
                        # SOLO borrar si la subida fue EXITOSA (upload_result tiene 'id')
                        if upload_result and upload_result.get('id') and not self.config.get("keep_local", False):
                            try:
                                os.remove(path)
                                print(f"Local file deleted after successful upload: {path}")
                                if self.config["overlay_enabled"]:
                                    self.recorder.overlay.show_notification("☁️ Uploaded & Local Deleted", color="#9C27B0")
                            except: pass
                        elif upload_result:
                            print("Upload successful. Local file kept.")
                        else:
                            print("⚠ Upload failed. Local file kept for safety.")
                            if self.config["overlay_enabled"]:
                                self.recorder.overlay.show_notification("⚠ Upload Failed - Local OK", color="#FF9800")
                        
                        self.after(0, self.refresh_library)
            except Exception as e:
                print(f"Error in save thread: {e}")
                
        threading.Thread(target=save_task, daemon=True).start()

    def download_cloud_clip(self, file_id, filename):
        dest_path = os.path.join(self.config["output_folder"], filename)
        
        def download_task():
            if self.drive.download(file_id, dest_path):
                self.after(0, lambda: messagebox.showinfo("Download", f"Clip downloaded: {filename}"))
                self.after(0, self.refresh_library)
            else:
                self.after(0, lambda: messagebox.showerror("Error", "Could not download clip."))
                
        threading.Thread(target=download_task, daemon=True).start()

    # --- FRAME: BIBLIOTECA ---
    def init_library_frame(self):
        frame = ctk.CTkScrollableFrame(self.main_area, fg_color="transparent")
        self.frames["library"] = frame

    def refresh_library(self):
        for widget in self.frames["library"].winfo_children():
            widget.destroy()
            
        # Indicador de carga
        loading_lbl = ctk.CTkLabel(self.frames["library"], text="⌛ Loading library...")
        loading_lbl.pack(pady=20)

        def load_task():
            try:
                # 1. Obtener clips de Drive
                drive_files = self.drive.list_videos()
                
                # 2. Clips Locales con thumbnails
                local_files = []
                if os.path.exists(self.config["output_folder"]):
                    local_files = sorted(Path(self.config["output_folder"]).glob("*.mp4"), key=os.path.getmtime, reverse=True)
                
                # Generar thumbnails para clips locales
                thumbnails = {}
                thumb_dir = os.path.join(self.config["output_folder"], ".thumbnails")
                Path(thumb_dir).mkdir(exist_ok=True)
                
                for f in local_files:
                    thumb_path = os.path.join(thumb_dir, f"{f.stem}.jpg")
                    if not os.path.exists(thumb_path):
                        try:
                            subprocess.run([
                                'ffmpeg', '-y', '-i', str(f), '-ss', '00:00:01',
                                '-vframes', '1', '-q:v', '3', '-vf', 'scale=240:-1', thumb_path
                            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                        except: pass
                    if os.path.exists(thumb_path):
                        thumbnails[str(f)] = thumb_path
                
                def update_ui():
                    if not self.winfo_exists(): return
                    loading_lbl.destroy()
                    
                    # Sección Drive (mantener lista simple ya que no tenemos thumbnails locales)
                    if drive_files:
                        header_drive = ctk.CTkFrame(self.frames["library"], fg_color="transparent")
                        header_drive.pack(fill="x", pady=(10, 5))
                        ctk.CTkLabel(header_drive, text="☁ CLOUD CLIPS", font=("Segoe UI", 14, "bold"), text_color=ACCENT_COLOR).pack(side="left", padx=20)
                        
                        for f in drive_files:
                            row = ctk.CTkFrame(self.frames["library"], fg_color=SIDEBAR_COLOR, corner_radius=10)
                            row.pack(fill="x", pady=4, padx=15)
                            
                            ctk.CTkLabel(row, text=f"📹 {f['name']}", anchor="w", font=("Segoe UI", 11)).pack(side="left", padx=10, pady=8)
                            
                            actions = ctk.CTkFrame(row, fg_color="transparent")
                            actions.pack(side="right", padx=5)
                            
                            ctk.CTkButton(actions, text="🌐", width=35, height=28, fg_color=ACCENT_COLOR, command=lambda l=f['webViewLink']: webbrowser.open(l)).pack(side="left", padx=2)
                            ctk.CTkButton(actions, text="⬇", width=35, height=28, fg_color="#16a085", hover_color="#1abc9c", command=lambda fid=f['id'], fn=f['name']: self.download_cloud_clip(fid, fn)).pack(side="left", padx=2)
                            ctk.CTkButton(actions, text="🗑", width=35, height=28, fg_color="#c0392b", hover_color="##e74c3c", command=lambda fid=f['id'], fn=f['name']: self.delete_cloud_clip(fid, fn)).pack(side="left", padx=2)
                    
                    # Sección Local con Grid de Thumbnails
                    if local_files:
                        header_local = ctk.CTkFrame(self.frames["library"], fg_color="transparent")
                        header_local.pack(fill="x", pady=(20, 10))
                        ctk.CTkLabel(header_local, text="💾 LOCAL CLIPS", font=("Segoe UI", 14, "bold"), text_color="#27ae60").pack(side="left", padx=20)
                        ctk.CTkButton(header_local, text="📂 Open Folder", width=110, height=28, command=self.open_output_folder, fg_color="transparent", border_width=1).pack(side="right", padx=20)
                        
                        # Grid container
                        grid = ctk.CTkFrame(self.frames["library"], fg_color="transparent")
                        grid.pack(fill="x", padx=15)
                        
                        cols = 3
                        for idx, f in enumerate(local_files):
                            col = idx % cols
                            
                            card = ctk.CTkFrame(grid, fg_color="#1a1a2e", corner_radius=10, width=200)
                            card.grid(row=idx//cols, column=col, padx=5, pady=5, sticky="nsew")
                            
                            # Thumbnail - hacer más grande
                            thumb_path = thumbnails.get(str(f))
                            if thumb_path:
                                try:
                                    img = Image.open(thumb_path)
                                    # Thumbnail grande que llena la tarjeta
                                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 124))
                                    thumb_lbl = ctk.CTkLabel(card, image=ctk_img, text="", cursor="hand2")
                                    thumb_lbl.pack(pady=(5,3), padx=5, fill="x")
                                    thumb_lbl.bind("<Button-1>", lambda e, p=f: os.startfile(p))
                                except: pass
                            
                            # Nombre del clip (truncado)
                            name = f.stem[:18] + "..." if len(f.stem) > 18 else f.stem
                            ctk.CTkLabel(card, text=name, font=("Segoe UI", 9), text_color="gray").pack(pady=1)
                            
                            # Botones compactos
                            btns = ctk.CTkFrame(card, fg_color="transparent")
                            btns.pack(pady=(2,5))
                            ctk.CTkButton(btns, text="▶", width=28, height=22, fg_color="#2980b9", command=lambda p=f: os.startfile(p)).pack(side="left", padx=1)
                            ctk.CTkButton(btns, text="☁↑", width=28, height=22, fg_color="#8e44ad", command=lambda p=f: self.upload_local_clip(p)).pack(side="left", padx=1)
                            ctk.CTkButton(btns, text="🗑", width=28, height=22, fg_color="#c0392b", command=lambda p=f: self.delete_file(p)).pack(side="left", padx=1)
                        
                        # Configurar columnas del grid
                        for i in range(cols):
                            grid.columnconfigure(i, weight=1)

                    if not drive_files and not local_files:
                        ctk.CTkLabel(self.frames["library"], text="No clips available.", font=("Segoe UI", 12)).pack(pady=30)

                self.after(0, update_ui)

            except Exception as e:
                print(f"Error loading library: {e}")
                self.after(0, lambda: loading_lbl.configure(text="❌ Connection Error"))


        threading.Thread(target=load_task, daemon=True).start()


    def delete_file(self, path):
        if messagebox.askyesno("Confirm", f"Delete '{path.name}' from local disk?"):
            try:
                os.remove(path)
                self.refresh_library()
            except Exception as e:
                print(e)

    def delete_cloud_clip(self, file_id, filename):
        if messagebox.askyesno("Confirm", f"Delete '{filename}' from Google Drive?"):
            def delete_task():
                if self.drive.delete(file_id):
                    self.after(0, lambda: messagebox.showinfo("Deleted", f"'{filename}' deleted from cloud."))
                    self.after(0, self.refresh_library)
                else:
                    self.after(0, lambda: messagebox.showerror("Error", "Could not delete from cloud."))
            threading.Thread(target=delete_task, daemon=True).start()

    def upload_local_clip(self, path):
        def upload_task():
            result = self.drive.upload(str(path))
            if result and result.get('id'):
                self.after(0, lambda: messagebox.showinfo("Uploaded", f"'{path.name}' uploaded to cloud."))
                self.after(0, self.refresh_library)
            else:
                self.after(0, lambda: messagebox.showerror("Error", "Could not upload to cloud."))
        threading.Thread(target=upload_task, daemon=True).start()

    def load_drive_clips(self):
        # Método legacy, ya no se usa
        pass


    # --- FRAME: SETTINGS ---
    def init_settings_frame(self):
        frame = ctk.CTkScrollableFrame(self.main_area, fg_color="transparent")
        self.frames["settings"] = frame
        
        ctk.CTkLabel(frame, text="⚙️ ADVANCED SETTINGS", font=("Segoe UI", 20, "bold"), text_color=ACCENT_COLOR).pack(pady=20)
        
        self.add_setting_section(frame, "🎥 VIDEO")
        
        ctk.CTkLabel(frame, text="Export Quality", font=("Arial", 12)).pack(pady=(10, 0))
        self.combo_quality = ctk.CTkComboBox(frame, values=["Ultra", "High", "Medium", "Low"], width=200, command=self.update_config_ui)
        self.combo_quality.set(self.config.get("video_quality", "High"))
        self.combo_quality.pack(pady=5)

        ctk.CTkLabel(frame, text="Target FPS", font=("Arial", 12)).pack(pady=(10, 0))
        self.combo_fps = ctk.CTkComboBox(frame, values=["30", "60", "120", "144", "240"], width=200, command=self.update_config_ui)
        self.combo_fps.set(str(self.config["fps"]))
        self.combo_fps.pack(pady=5)

        ctk.CTkLabel(frame, text="Monitor Index", font=("Arial", 12)).pack(pady=(10, 0))
        self.monitor_spinbox = ctk.CTkComboBox(frame, values=["1", "2", "3"], width=100)
        self.monitor_spinbox.set(str(self.config["monitor_index"]))
        self.monitor_spinbox.pack(pady=5)

        self.add_setting_section(frame, "🌐 CLOUD")
        
        self.switch_upload = ctk.CTkSwitch(frame, text="Auto-upload to Google Drive", progress_color=ACCENT_COLOR)
        if self.config["auto_upload"]: self.switch_upload.select()
        self.switch_upload.pack(pady=5)

        self.switch_keep_local = ctk.CTkSwitch(frame, text="Keep local copy permanently", progress_color="#27ae60")
        if self.config.get("keep_local", False): self.switch_keep_local.select()
        self.switch_keep_local.pack(pady=10)

        self.add_setting_section(frame, "📁 STORAGE")
        
        folder_frame = ctk.CTkFrame(frame, fg_color="transparent")
        folder_frame.pack(pady=10, fill="x", padx=40)
        
        self.lbl_folder_path = ctk.CTkLabel(folder_frame, text=f"Path: {self.config['output_folder']}", font=("Arial", 10), wraplength=400)
        self.lbl_folder_path.pack(side="left", padx=10)
        
        ctk.CTkButton(folder_frame, text="Change", width=80, height=28, command=self.browse_folder).pack(side="right", padx=10)

        self.add_setting_section(frame, "⚡ HARDWARE")
        
        self.switch_nvenc = ctk.CTkSwitch(frame, text="NVIDIA Acceleration (NVENC)", progress_color=ACCENT_COLOR)
        if self.config["use_nvenc"]: self.switch_nvenc.select()
        self.switch_nvenc.pack(pady=10)

        self.add_setting_section(frame, "⏳ BUFFER")
        
        ctk.CTkLabel(frame, text="Rewind Minutes").pack()
        self.slider_buffer = ctk.CTkSlider(frame, from_=1, to=20, number_of_steps=19, command=self.update_config_ui, button_color=ACCENT_COLOR)
        self.slider_buffer.set(self.config["buffer_minutes"])
        self.slider_buffer.pack(pady=5, padx=50, fill="x")
        self.lbl_buffer_val = ctk.CTkLabel(frame, text=f"{self.config['buffer_minutes']} min", font=("Arial", 13, "bold"))
        self.lbl_buffer_val.pack()

        # Botón Guardar VIP
        self.btn_save = ctk.CTkButton(frame, text="💾 SAVE SETTINGS", height=50, fg_color=ACCENT_COLOR, font=("Segoe UI", 14, "bold"), command=self.save_settings)
        self.btn_save.pack(pady=40, padx=100, fill="x")

    def add_setting_section(self, parent, title):
        ctk.CTkLabel(parent, text=f"--- {title} ---", font=("Segoe UI", 12, "bold"), text_color="gray").pack(pady=(25, 10))

    def update_config_ui(self, value=None):
        self.lbl_buffer_val.configure(text=f"{int(self.slider_buffer.get())} min")

    def browse_folder(self):
        new_path = filedialog.askdirectory()
        if new_path:
            self.config["output_folder"] = new_path
            self.lbl_folder_path.configure(text=f"Path: {new_path}")
            # Crear si no existe
            Path(new_path).mkdir(parents=True, exist_ok=True)

    def open_output_folder(self):
        path = os.path.abspath(self.config["output_folder"])
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("Error", "Folder does not exist.")

    def save_settings(self):
        self.config["buffer_minutes"] = int(self.slider_buffer.get())
        self.config["fps"] = int(self.combo_fps.get())
        self.config["video_quality"] = self.combo_quality.get()
        self.config["use_nvenc"] = bool(self.switch_nvenc.get())
        self.config["auto_upload"] = bool(self.switch_upload.get())
        self.config["keep_local"] = bool(self.switch_keep_local.get())
        self.config["monitor_index"] = int(self.monitor_spinbox.get())
        
        ConfigManager.save(self.config)
        self.recorder.config = self.config 
        messagebox.showinfo("Saved", "Settings saved successfully.")

    # --- AUTO DETECT ---
    def auto_detect_apps(self):
        if not self.recorder.running:
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'].lower() in self.config["auto_detect_apps"]:
                        print(f"Game detected: {proc.info['name']}")
                        self.recorder.start()
                        self.overlay.show_notification(f"🎮 Game Detected: {proc.info['name']}")
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        self.after(10000, self.auto_detect_apps)

    def on_closing(self):
        self.recorder.stop()
        self.destroy()
        os._exit(0)

if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()