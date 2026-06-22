"""
Compact Screen Recorder Pro
Description: A high-performance, lightweight Windows screen recording app with a 
             floating, invisible-to-video dashboard control layout, multi-mode capture presets,
             and navigation safety boundaries (Go-Back mechanisms).
Author: Bhoomika M, Goutham N
License: Open Source / MIT
"""

import cv2
import numpy as np
from mss import MSS  
from datetime import datetime
from pathlib import Path
import threading
import pyaudiowpatch as pyaudio
import wave
import time
import ffmpeg
import os
import sys
import tkinter as tk
from tkinter import ttk
# FROM PLYER IMPORT NOTIFICATION IS COMMENTED FOR LATER USE:
# from plyer import notification 
import ctypes  
import ctypes.wintypes

# Force 1:1 pixel accuracy for crisp coordinates on high-res laptop displays
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)) 
except Exception:
    pass

# ==========================================
# GLOBAL ENGINE CONTROL STATE
# ==========================================
recording = False
paused = False
audio_thread = None
video_thread = None

total_recorded_time = 0
session_start_time = 0

FPS_OPTIONS = ["30 FPS (Smooth Video)", "20 FPS (Balanced)", "15 FPS (Text/Static Screen)"]
CAPTURE_MODES = ["🎯 Custom Region Select", "🖥️ Full Screen Capture", "🔲 Target Application Window"]
CHUNK = 1024

# Target directory setup
videos_folder = Path.home() / "Videos"
videos_folder.mkdir(exist_ok=True)

temp_video = ""
temp_audio = ""
final_output = ""

# ==========================================
# ADVANCED ACTIVE WINDOW ENUMERATOR POPUP
# ==========================================
class WindowTargetPicker:
    """Enumerates open system windows via the Windows user32 library and 
    displays an interactive GUI menu for target application selection."""
    def __init__(self, parent, on_selection_callback):
        self.parent = parent
        self.on_selection_callback = on_selection_callback
        
        self.picker_win = tk.Toplevel(parent)
        self.picker_win.title("Select Application Window to Record")
        self.picker_win.geometry("520x420")
        self.picker_win.resizable(False, False)
        self.picker_win.configure(bg="#1e1e1e")
        self.picker_win.attributes("-topmost", True)
        
        label = tk.Label(self.picker_win, text="Select an active window from the list:", font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#1e1e1e")
        label.pack(pady=12)

        # Build list containment scroll frame
        list_frame = tk.Frame(self.picker_win, bg="#1e1e1e")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        self.scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=self.scrollbar.set, bg="#2d2d2d", fg="#ffffff", selectbackground="#d32f2f", font=("Segoe UI", 10), border=0, highlightthickness=0)
        self.scrollbar.config(command=self.listbox.yview)
        
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = tk.Frame(self.picker_win, bg="#1e1e1e")
        btn_frame.pack(fill=tk.X, pady=15)

        # Confirm target action
        self.select_btn = tk.Button(btn_frame, text="✔️ Confirm Target", font=("Segoe UI", 10, "bold"), fg="#ffffff", bg="#d32f2f", border=0, width=18, height=2, cursor="hand2", command=self.submit_target)
        self.select_btn.pack(side=tk.LEFT, padx=15)

        # Go-back button to return back to main configuration panel safely
        self.back_btn = tk.Button(btn_frame, text="⬅️ Back to Menu", font=("Segoe UI", 10, "bold"), fg="#ffffff", bg="#555555", border=0, width=16, height=2, cursor="hand2", command=self.close_picker)
        self.back_btn.pack(side=tk.RIGHT, padx=15)

        self.window_map = {} 
        self.populate_window_list()

        self.picker_win.protocol("WM_DELETE_WINDOW", self.close_picker)

    def populate_window_list(self):
        def enum_windows_callback(hwnd, extra):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value
                    
                    if title not in ["Settings", "Program Manager", "Compact Screen Recorder Pro"] and not title.strip() == "":
                        display_string = f"▪️ {title}"
                        self.listbox.insert(tk.END, display_string)
                        self.window_map[display_string] = hwnd
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    def submit_target(self):
        selected_index = self.listbox.curselection()
        if not selected_index:
            return 
        
        selected_text = self.listbox.get(selected_index[0])
        hwnd = self.window_map.get(selected_text)

        coords = None
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9) 
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.2) 

            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            
            if w % 2 != 0: w -= 1
            if h % 2 != 0: h -= 1
            
            if w > 40 and h > 40:
                coords = {"top": rect.top, "left": rect.left, "width": w, "height": h}

        self.picker_win.destroy()
        self.on_selection_callback(coords)

    def close_picker(self):
        self.picker_win.destroy()
        self.on_selection_callback(None)


# ==========================================
# ADVANCED REGION SELECTOR (HOLLOW FRAME)
# ==========================================
class FloatingRegionSelector:
    def __init__(self, parent, on_confirm_callback):
        self.parent = parent
        self.on_confirm_callback = on_confirm_callback
        
        self.win = tk.Toplevel(parent)
        self.win.title("Drag & Position This Box To Record")
        self.win.geometry("800x600+400+200")
        self.win.configure(bg="#1e1e1e")
        self.win.attributes("-topmost", True)
        self.win.wm_attributes("-transparentcolor", "#1e1e1e")
        
        self.border_frame = tk.Frame(self.win, highlightbackground="red", highlightcolor="red", highlightthickness=4, bg="#1e1e1e")
        self.border_frame.pack(fill="both", expand=True)

        # Bottom control confirmation banner inside the hollow zone
        self.control_bar = tk.Frame(self.border_frame, bg="red", height=40)
        self.control_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.control_bar.pack_propagate(False)

        # Confirm target area metrics
        self.btn = tk.Button(self.control_bar, text="✔️ Lock Area & Start Recording", font=("Segoe UI", 9, "bold"), fg="red", bg="white", activebackground="#eeeeee", command=self.confirm_and_close, border=0, padx=10)
        self.btn.pack(side=tk.LEFT, padx=20, pady=5)

        # Cancel and return button right on the red crop banner layer
        self.cancel_btn = tk.Button(self.control_bar, text="❌ Cancel & Go Back", font=("Segoe UI", 9, "bold"), fg="white", bg="#333333", activebackground="#444444", command=self.on_cancel, border=0, padx=10)
        self.cancel_btn.pack(side=tk.RIGHT, padx=20, pady=5)

        self.win.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def confirm_and_close(self):
        self.win.update_idletasks()
        
        x = self.win.winfo_x() + 4   
        y = self.win.winfo_y() + 4
        w = self.win.winfo_width() - 8
        h = self.win.winfo_height() - 48 # Trim out the bottom banner layout size

        if w % 2 != 0: w -= 1
        if h % 2 != 0: h -= 1

        coords = None
        if w > 40 and h > 40:
            coords = {"top": y, "left": x, "width": w, "height": h}
            
        self.win.destroy()
        self.on_confirm_callback(coords)

    def on_cancel(self):
        self.win.destroy()
        self.on_confirm_callback(None)

# ==========================================
# WINDOWS OS CAPTURE PROTECTION HOOKS
# ==========================================
def apply_invisibility():
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2) 
        if hwnd:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
    except Exception as e:
        print(f"Invisibility error: {e}")

def remove_invisibility():
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
        if hwnd:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000000)
    except Exception as e:
        print(f"Visibility restore error: {e}")

# ==========================================
# SYSTEM AUDIO ENGINE (WASAPI LOOPBACK)
# ==========================================
def record_system_audio(t_audio):
    global recording, paused
    p = pyaudio.PyAudio()
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except os.error:
        update_status("Audio Error: WASAPI driver missing.")
        return

    default_speakers = p.get_default_output_device_info()
    loopback_device = None
    for loopback in p.get_loopback_device_info_generator():
        if default_speakers["name"] in loopback["name"]:
            loopback_device = loopback
            break
    if not loopback_device:
        p.terminate()
        return

    samplerate = int(loopback_device["defaultSampleRate"])
    channels = loopback_device["maxInputChannels"]
    try:
        stream = p.open(format=pyaudio.paInt16, channels=channels, rate=samplerate, input=True, input_device_index=loopback_device["index"], frames_per_buffer=CHUNK)
    except Exception:
        p.terminate()
        return

    audio_frames = []
    bytes_per_chunk = 2 * channels * CHUNK
    time_per_chunk = CHUNK / samplerate
    audio_start_time = time.time()
    chunks_recorded = 0
    total_paused_duration = 0

    while recording:
        if paused:
            p_start = time.time()
            while paused and recording: time.sleep(0.01)
            total_paused_duration += (time.time() - p_start)
            continue
        try:
            current_active_time = time.time() - audio_start_time - total_paused_duration
            expected_chunks = int(current_active_time / time_per_chunk)
            available_frames = stream.get_read_available()
            if available_frames >= CHUNK:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_frames.append(data)
                chunks_recorded += 1
            else:
                if chunks_recorded < expected_chunks:
                    silence = b'\x00' * bytes_per_chunk
                    audio_frames.append(silence)
                    chunks_recorded += 1
                time.sleep(0.001)
        except IOError:
            pass
            
    stream.stop_stream()
    stream.close()
    wf = wave.open(str(t_audio), 'wb'); wf.setnchannels(channels); wf.setsampwidth(p.get_sample_size(pyaudio.paInt16)); wf.setframerate(samplerate); wf.writeframes(b''.join(audio_frames)); wf.close()
    p.terminate()

# ==========================================
# SCREEN RECORDING ENGINE (TARGET CROP)
# ==========================================
def record_video(t_video, target_w, target_h, current_fps, capture_box):
    global recording, paused
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(str(t_video), fourcc, current_fps, (target_w, target_h))

    time_per_frame = 1.0 / current_fps
    v_start_time = time.time()
    frame_count = 0
    total_paused_duration = 0

    with MSS() as sct:
        while recording:
            if paused:
                p_start = time.time()
                while paused and recording: time.sleep(0.01)
                total_paused_duration += (time.time() - p_start)
                continue

            screenshot = sct.grab(capture_box)
            current_frame = np.array(screenshot)
            current_frame = cv2.cvtColor(current_frame, cv2.COLOR_BGRA2BGR)
            last_frame = cv2.resize(current_frame, (target_w, target_h))

            elapsed_time = time.time() - v_start_time - total_paused_duration
            target_frame_count = int(elapsed_time / time_per_frame)

            while frame_count < target_frame_count:
                video_writer.write(last_frame)
                frame_count += 1
            time.sleep(0.002)
            
        video_writer.release()

# ==========================================
# BACKGROUND MULTITHREADED COMPRESSION PIPELINE
# ==========================================
def post_process_and_merge(t_video, t_audio, f_out, chosen_crf):
    update_status(f"Squeezing data into MP4 (Using CRF {chosen_crf})...")
    
    # COMMENTED FOR LATER USE:
    # notification.notify(title="Screen Recorder", message="Processing and compressing video...", timeout=2)
    
    if t_audio.exists() and os.path.getsize(t_audio) > 10000:
        try:
            video_input = ffmpeg.input(str(t_video))
            audio_input = ffmpeg.input(str(t_audio))
            ffmpeg.output(video_input, audio_input, str(f_out), vcodec='libx264', acodec='aac', pix_fmt='yuv420p', crf=chosen_crf, preset='ultrafast').run(quiet=True, overwrite_output=True)
            os.remove(t_video); os.remove(t_audio)
            update_status("✨ Done! Saved to Videos folder.")
            
            # COMMENTED FOR LATER USE:
            # notification.notify(title="Screen Recorder", message="Video optimized successfully!", timeout=3)
            
        except Exception as e:
            update_status(f"❌ Compression failed: {e}")
    else:
        if t_video.exists(): os.remove(t_video)
        if t_audio.exists(): os.remove(t_audio)
        update_status("⚠️ Recording aborted.")
    reset_ui_to_normal()

# ==========================================
# UI STATE AND LIFECYCLE MANAGEMENT
# ==========================================
def update_status(text):
    status_label.config(text=text)

def reset_ui_to_normal():
    remove_invisibility()
    root.attributes("-topmost", False) 
    
    record_btn.config(text="🔴 Start Recording", state="normal", bg="#d32f2f")
    pause_btn.config(text="⏸️ Pause", state="disabled", bg="#555555")
    fps_dropdown.config(state="readonly")
    mode_dropdown.config(state="readonly")
    crf_slider.config(state="normal")
    timer_label.config(text="00:00")
    update_status("Ready to record")

def update_timer():
    global total_recorded_time, session_start_time
    if recording:
        if not paused:
            display_time = int(total_recorded_time + (time.time() - session_start_time))
        else:
            display_time = int(total_recorded_time)
        minutes = display_time // 60; seconds = display_time % 60
        timer_label.config(text=f"{minutes:02d}:{seconds:02d}")
        root.after(500, update_timer)

def on_slider_move(val):
    v = int(float(val))
    if v <= 21: crf_hint.config(text=f"CRF: {v} (Ultra Sharp Text)")
    elif v <= 25: crf_hint.config(text=f"CRF: {v} (Best Balanced Profile)")
    else: crf_hint.config(text=f"CRF: {v} (Extreme Space Saver)")

def toggle_pause():
    global paused, session_start_time, total_recorded_time
    if not recording: return
    if not paused:
        paused = True
        total_recorded_time += (time.time() - session_start_time)
        pause_btn.config(text="▶️ Resume", bg="#388e3c")
        update_status("Paused. Dashboard remains floating & invisible.")
    else:
        paused = False
        session_start_time = time.time()
        pause_btn.config(text="⏸️ Pause", bg="#f57c00")
        update_status("Recording active area...")

def execute_capture_initialization(chosen_box):
    global recording, paused, audio_thread, video_thread, session_start_time, total_recorded_time
    global temp_video, temp_audio, final_output

    if not chosen_box:
        # Handled safety back routing
        root.deiconify()
        update_status("🔄 Returned. Adjusted configuration settings.")
        return

    width = chosen_box["width"]
    height = chosen_box["height"]

    recording = True
    paused = False
    total_recorded_time = 0
    session_start_time = time.time()
    chosen_fps = int(fps_var.get().split()[0])
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_video = videos_folder / f"temp_video_{timestamp}.mp4"
    temp_audio = videos_folder / f"temp_audio_{timestamp}.wav"
    final_output = videos_folder / f"compressed_recording_{timestamp}.mp4"

    root.deiconify()
    root.attributes("-topmost", True)  
    apply_invisibility()               

    record_btn.config(text="⏹️ Stop Recording", bg="#333333")
    pause_btn.config(state="normal", text="⏸️ Pause", bg="#f57c00")
    fps_dropdown.config(state="disabled"); mode_dropdown.config(state="disabled"); crf_slider.config(state="disabled")
    
    update_status("Recording! UI is pinned floating & invisible.")
    
    # COMMENTED FOR LATER USE:
    # notification.notify(title="Screen Recorder", message="Recording Started!", timeout=2)

    audio_thread = threading.Thread(target=record_system_audio, args=(temp_audio,), daemon=True)
    video_thread = threading.Thread(target=record_video, args=(temp_video, width, height, chosen_fps, chosen_box), daemon=True)
    audio_thread.start()
    video_thread.start()

    update_timer()

def toggle_recording():
    global recording, paused, video_thread, audio_thread

    if not recording:
        chosen_mode = mode_var.get()
        
        if chosen_mode == "🖥️ Full Screen Capture":
            with MSS() as sct:
                monitor = sct.monitors[1]
                box = {"top": monitor["top"], "left": monitor["left"], "width": monitor["width"], "height": monitor["height"]}
            execute_capture_initialization(box)
            
        elif chosen_mode == "🔲 Target Application Window":
            root.withdraw()
            time.sleep(0.1)
            WindowTargetPicker(root, execute_capture_initialization)
            
        else: # "🎯 Custom Region Select"
            root.withdraw()
            time.sleep(0.1)
            FloatingRegionSelector(root, execute_capture_initialization)
    else:
        recording = False
        paused = False
        record_btn.config(text="Processing...", state="disabled", bg="#777777")
        pause_btn.config(state="disabled", text="⏸️ Pause", bg="#555555")
        
        if video_thread: video_thread.join()
        if audio_thread: audio_thread.join()

        current_crf_val = int(crf_slider.get())
        processing_thread = threading.Thread(target=post_process_and_merge, args=(temp_video, temp_audio, final_output, current_crf_val), daemon=True)
        processing_thread.start()

# ==========================================
# GRAPHICAL WINDOW SETUP (TKINTER)
# ==========================================
root = tk.Tk()
root.title("Compact Screen Recorder Pro")
root.geometry("460x360")
root.resizable(False, False)
root.configure(bg="#1e1e1e")

style = ttk.Style()
style.theme_use('clam')

title_label = tk.Label(root, text="🎥 Compact Screen Recorder Pro", font=("Segoe UI", 13, "bold"), fg="#ffffff", bg="#1e1e1e")
title_label.pack(pady=10)

frame_mode = tk.Frame(root, bg="#1e1e1e")
frame_mode.pack(pady=4)
mode_label = tk.Label(frame_mode, text="Capture Area:", font=("Segoe UI", 10), fg="#bbbbbb", bg="#1e1e1e", width=12, anchor="w")
mode_label.pack(side=tk.LEFT, padx=5)
mode_var = tk.StringVar()
mode_dropdown = ttk.Combobox(frame_mode, textvariable=mode_var, values=CAPTURE_MODES, width=28, state="readonly")
mode_dropdown.pack(side=tk.LEFT, padx=5)
mode_dropdown.current(0) 

frame_fps = tk.Frame(root, bg="#1e1e1e")
frame_fps.pack(pady=4)
fps_label = tk.Label(frame_fps, text="Frame Rate:", font=("Segoe UI", 10), fg="#bbbbbb", bg="#1e1e1e", width=12, anchor="w")
fps_label.pack(side=tk.LEFT, padx=5)
fps_var = tk.StringVar()
fps_dropdown = ttk.Combobox(frame_fps, textvariable=fps_var, values=FPS_OPTIONS, width=28, state="readonly")
fps_dropdown.pack(side=tk.LEFT, padx=5)
fps_dropdown.current(1) 

frame_crf = tk.Frame(root, bg="#1e1e1e")
frame_crf.pack(pady=4)
crf_label = tk.Label(frame_crf, text="Video Quality:", font=("Segoe UI", 10), fg="#bbbbbb", bg="#1e1e1e", width=12, anchor="w")
crf_label.pack(side=tk.LEFT, padx=5)
crf_slider = tk.Scale(frame_crf, from_=18, to=32, orient=tk.HORIZONTAL, showvalue=False, bg="#1e1e1e", fg="#ffffff", highlightthickness=0, troughcolor="#333333", activebackground="#d32f2f", length=200, command=on_slider_move)
crf_slider.set(22) 
crf_slider.pack(side=tk.LEFT, padx=5)

crf_hint = tk.Label(root, text="CRF: 22 (Best Balanced Profile)", font=("Segoe UI", 9, "bold"), fg="#ff9100", bg="#1e1e1e")
crf_hint.pack(pady=2)

timer_label = tk.Label(root, text="00:00", font=("Consolas", 24, "bold"), fg="#ff3d00", bg="#1e1e1e")
timer_label.pack(pady=4)

btn_frame = tk.Frame(root, bg="#1e1e1e")
btn_frame.pack(pady=5)
record_btn = tk.Button(btn_frame, text="🔴 Start Recording", font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#d32f2f", activeforeground="#ffffff", activebackground="#b71c1c", border=0, cursor="hand2", width=22, height=2, command=toggle_recording)
record_btn.pack(side=tk.LEFT, padx=5)
pause_btn = tk.Button(btn_frame, text="⏸️ Pause", font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#555555", activeforeground="#ffffff", activebackground="#777777", border=0, state="disabled", cursor="hand2", width=14, height=2, command=toggle_pause)
pause_btn.pack(side=tk.LEFT, padx=5)

status_label = tk.Label(root, text="Ready to record", font=("Segoe UI", 9, "italic"), fg="#888888", bg="#1e1e1e")
status_label.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

if __name__ == "__main__":
    root.mainloop()