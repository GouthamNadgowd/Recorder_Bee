# 🐝 Recorder_Bee Pro

A high-performance, lightweight Windows screen recording application engineered to capture crisp desktop video and loopback system audio seamlessly. Built with a multi-threaded architecture to prevent UI freezing and optimize background processing pipelines.

## ✨ Key Features
* **Multi-Mode Tracking:** Toggle instantly between 🎯 Custom Region Select, 🖥️ Full Screen Capture, and 🔲 Target Application Window tracking profiles.
* **Invisible Control Layer:** The dashboard utility controls automatically hide from the final video layout using native Windows display affinity hooks (`WDA_EXCLUDEFROMCAPTURE`).
* **WASAPI System Audio Loopback:** Captures high-fidelity PCM digital blocks straight from your soundcard with automatic silence frame injection to guarantee perfect A/V sync.
* **Smart Navigation UI:** Built-in "Go-Back" safety options to seamlessly return to parameter configurations without losing workflow states.
* **Zero-Lag H.264 Compression:** Leverages multithreaded FFmpeg processing loops using optimized Constant Rate Factor (CRF) profiles.

---

## 🚀 Installation & Setup

### Prerequisites
1. **Python 3.10+** installed on your machine.
2. **FFmpeg installed on Windows system paths** (Required for video compression and audio muxing).
   ```cmd
   winget install Gyan.FFmpeg
