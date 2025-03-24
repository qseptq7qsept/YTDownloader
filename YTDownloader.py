import sys
import os
import subprocess
import re
import yt_dlp
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QMessageBox, QHBoxLayout,
    QFileDialog, QTextEdit, QDialog
)
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import QThread, Signal

CONFIG_FILE = "config.json"

script_dir = os.path.dirname(os.path.abspath(__file__))
ffmpeg_folder = os.path.join(script_dir, "ffmpeg")
ffmpeg_exe = os.path.join(ffmpeg_folder, "ffmpeg.exe")

class DownloadThread(QThread):
    finished_signal = Signal(str)
    error_signal = Signal(str)
    debug_signal = Signal(str)

    def __init__(self, url, output_dir, out_format, naming_preset, is_playlist, resolution, start_time=None, end_time=None):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.out_format = out_format      # "mp3", "aac", "wav", "opus", or "mp4"
        self.naming_preset = naming_preset  # e.g. "Default", "Lowercase-Dash", "Indexed"
        self.is_playlist = is_playlist
        self.resolution = resolution      # For mp4: "Auto" or a numeric string like "720"
        self.start_time = start_time
        self.end_time = end_time

    def run(self):

        self.debug_signal.emit("Starting download thread...")
        presets = {
            "Default": "%(title)s.%(ext)s",
            "Lowercase-Dash": "%(title)s-%(id)s.%(ext)s",
            "Indexed": "%(playlist_index)02d - %(title)s.%(ext)s"
        }
        outtmpl = os.path.join(self.output_dir, presets.get(self.naming_preset, "%(title)s.%(ext)s"))
        self.debug_signal.emit(f"Output template set to: {outtmpl}")

        if self.out_format == "mp4":
            if self.resolution != "Auto":
                fmt = f"bestvideo[height<={self.resolution}]+bestaudio/best[height<={self.resolution}]"
            else:
                fmt = "bestvideo+bestaudio/best"
        else:
            fmt = "bestaudio/best"
        self.debug_signal.emit(f"Using format: {fmt}")

        ydl_opts = {
            'format': fmt,
            'outtmpl': outtmpl,
            'progress_hooks': [self.progress_hook],
            'merge_output_format': self.out_format if self.out_format == "mp4" else None,
            'ignoreerrors': True  # Skip errors during download
        }
        if self.is_playlist:
            ydl_opts['yes_playlist'] = True
        else:
            ydl_opts['no_playlist'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)

            def convert_file(downloaded_file):              

                downloaded_basename = os.path.splitext(downloaded_file)[0]
                if self.out_format in ["mp3", "aac", "wav", "opus"]:
                    ffmpeg_cmds = {
                        "mp3": [
                            ffmpeg_exe, "-y", "-i", downloaded_file, "-vn",
                            "-ar", "44100", "-ac", "2", "-b:a", "320k",
                            downloaded_basename + ".mp3"
                        ],
                        "aac": [
                            ffmpeg_exe, "-y", "-i", downloaded_file, "-vn",
                            "-c:a", "aac", "-b:a", "320k",
                            downloaded_basename + ".aac"
                        ],
                        "wav": [
                            ffmpeg_exe, "-y", "-i", downloaded_file, "-vn",
                            downloaded_basename + ".wav"
                        ],
                        "opus": [
                            ffmpeg_exe, "-y", "-i", downloaded_file, "-vn",
                            "-c:a", "libopus", "-b:a", "192k",
                            downloaded_basename + ".opus"
                        ]
                    }
                    if self.out_format in ffmpeg_cmds:
                        subprocess.run(ffmpeg_cmds[self.out_format], check=True)
                elif self.out_format == "mp4":
                    scale_filter = ""
                    if self.resolution != "Auto":
                        scale_filter = f"scale=-2:{self.resolution}"
                    vf_option = ["-vf", scale_filter] if scale_filter else []
                    ext = os.path.splitext(downloaded_file)[1].lower()
                    if ext == ".mp4":
                        mp4_output = downloaded_basename + "_converted.mp4"
                    else:
                        mp4_output = downloaded_basename + ".mp4"
                    ffmpeg_cmd = [ffmpeg_exe, "-y", "-i", downloaded_file] + vf_option + [
                        "-c:v", "libx264", "-crf", "23", "-preset", "slow",
                        "-c:a", "aac", "-b:a", "192k", mp4_output
                    ]
                    subprocess.run(ffmpeg_cmd, check=True)

                # Delete the source file once conversion is done.
                if os.path.exists(downloaded_file):
                    os.remove(downloaded_file)

            if self.is_playlist and info and 'entries' in info:
                for entry in info['entries']:
                    if entry is None:
                        continue
                    try:
                        downloaded_file = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(entry)
                        convert_file(downloaded_file)
                    except Exception as e:
                        error_str = str(e)
                        if "Video unavailable" in error_str and "blocked" in error_str:
                            self.debug_signal.emit(f"Skipping video due to geo-restriction: {error_str}")
                            continue
                        else:
                            self.error_signal.emit(error_str)
                            continue
            elif info:
                downloaded_file = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
                convert_file(downloaded_file)
            else:
                self.debug_signal.emit("No video info could be extracted.")
            self.finished_signal.emit("Download and conversion finished!")
        except Exception as e:
            self.error_signal.emit(str(e))
            self.debug_signal.emit(f"Error in download process: {str(e)}")

    def progress_hook(self, d):
        if d.get('status') == 'downloading':
            msg = d.get('_percent_str', '').strip()
            if not msg and 'message' in d:
                msg = d['message']
            ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
            clean_msg = ansi_escape.sub('', msg)
            self.debug_signal.emit(f"Download progress: {clean_msg}")
        elif d.get('status') == 'finished':
            self.debug_signal.emit("Download complete")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Downloader & GIF Creator")
        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.setup_ui()

    def setup_ui(self):
        # URL input
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter video URL")
        self.main_layout.addWidget(QLabel("Video URL:"))
        self.main_layout.addWidget(self.url_input)
        
        # Folder selection
        self.folder_line_edit = QLineEdit(os.getcwd())
        folder_button = QPushButton("Browse Folder")
        folder_button.clicked.connect(self.select_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_line_edit)
        folder_layout.addWidget(folder_button)
        self.main_layout.addWidget(QLabel("Output Folder:"))
        self.main_layout.addLayout(folder_layout)
        
        # Naming preset
        self.naming_combo = QComboBox()
        self.naming_combo.addItems(["Default", "Lowercase-Dash", "Indexed"])
        self.main_layout.addWidget(QLabel("Naming Preset:"))
        self.main_layout.addWidget(self.naming_combo)
        
        # Output format
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp3", "aac", "wav", "opus", "mp4", "gif"])
        self.main_layout.addWidget(QLabel("Output Format:"))
        self.main_layout.addWidget(self.format_combo)
        
        # Resolution for mp4
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["Auto", "720", "1080"])
        self.main_layout.addWidget(QLabel("Resolution (for mp4):"))
        self.main_layout.addWidget(self.resolution_combo)
        
        # Console log
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.main_layout.addWidget(QLabel("Console Log:"))
        self.main_layout.addWidget(self.log_text_edit)
        
        # Download button
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.handle_download)
        self.main_layout.addWidget(self.download_button)
        
        # Add GIF editor settings
        self.add_gif_editor_ui()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", self.folder_line_edit.text())
        if folder:
            self.folder_line_edit.setText(folder)

    def log_console(self, message):
        self.log_text_edit.append(message)

    def progress_hook(self, d):
        if d.get('status') == 'downloading':
            msg = d.get('_percent_str', '').strip()
            self.log_console(f"Downloading: {msg}")
        elif d.get('status') == 'finished':
            self.log_console("Download finished")

    def handle_download(self):
        if self.format_combo.currentText() == "gif":
            self.create_gif_if_needed()
        else:
            self.start_download()

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a valid URL.")
            return
        naming_preset = self.naming_combo.currentText()
        out_format = self.format_combo.currentText()
        is_playlist = "list=" in url
        resolution = self.resolution_combo.currentText() if out_format == "mp4" else "Auto"
        output_dir = self.folder_line_edit.text().strip()
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        self.download_button.setEnabled(False)
        self.log_console("Starting download...")
        self.thread = DownloadThread(url, output_dir, out_format, naming_preset, is_playlist, resolution)
        self.thread.finished_signal.connect(self.download_finished)
        self.thread.error_signal.connect(self.download_error)
        self.thread.debug_signal.connect(self.log_console)
        self.thread.start()

    def download_finished(self, msg):
        self.log_console(msg)
        self.download_button.setEnabled(True)
        QMessageBox.information(self, "Finished", msg)

    def download_error(self, err):
        self.log_console("Error: " + err)
        self.download_button.setEnabled(True)
        QMessageBox.critical(self, "Error", err)

    def add_gif_editor_ui(self):
        self.main_layout.addWidget(QLabel("GIF Editor Settings:"))
        # Time In
        time_in_layout = QHBoxLayout()
        time_in_label = QLabel("Time In (s):")
        self.time_in_input = QLineEdit("0")
        time_in_layout.addWidget(time_in_label)
        time_in_layout.addWidget(self.time_in_input)
        self.main_layout.addLayout(time_in_layout)
        # Time Out
        time_out_layout = QHBoxLayout()
        time_out_label = QLabel("Time Out (s):")
        self.time_out_input = QLineEdit("10")
        time_out_layout.addWidget(time_out_label)
        time_out_layout.addWidget(self.time_out_input)
        self.main_layout.addLayout(time_out_layout)

    def create_gif_if_needed(self):
        url = self.url_input.text().strip()
        output_dir = self.folder_line_edit.text().strip()
        naming_preset = self.naming_combo.currentText()
        try:
            time_in = float(self.time_in_input.text())
            time_out = float(self.time_out_input.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid time input.")
            return

        # Enforce maximum duration of 3 seconds for GIFs
        duration = time_out - time_in
        if duration > 5:
            QMessageBox.warning(self, "Input Error", "GIF duration cannot exceed 5 seconds.")
            return

        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a valid URL.")
            return
        if time_in >= time_out:
            QMessageBox.warning(self, "Input Error", "Time In must be less than Time Out.")
            return
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        self.download_button.setEnabled(False)
        self.log_console("Starting GIF creation...")

        # Download video to a temporary file
        temp_video_path = os.path.join(output_dir, "temp_video.mp4")
        ydl_opts = {
            'outtmpl': temp_video_path,
            'format': 'bestvideo+bestaudio/best',
            'progress_hooks': [self.progress_hook],
            'merge_output_format': 'mp4'
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.log_console(f"Downloaded video to {temp_video_path}")
        except Exception as e:
            QMessageBox.critical(self, "Download Error", str(e))
            self.log_console("Error downloading video: " + str(e))
            self.download_button.setEnabled(True)
            return

        # Create the GIF using ffmpeg
        output_gif = os.path.join(output_dir, "output.gif")
        ffmpeg_cmd = [
            ffmpeg_exe, "-y", "-i", temp_video_path,
            "-ss", str(time_in),
            "-t", str(duration),
            "-vf", "fps=10,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            output_gif
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True)
            self.log_console(f"GIF created at {output_gif}")
            QMessageBox.information(self, "Success", f"GIF saved to {output_gif}")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "GIF Creation Error", str(e))
            self.log_console("Error creating GIF: " + str(e))
        finally:
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                self.log_console(f"Deleted temporary video file: {temp_video_path}")
        self.download_button.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Set Fusion style and a custom dark palette
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Base, QColor(42, 42, 42))
    dark_palette.setColor(QPalette.AlternateBase, QColor(66, 66, 66))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    dark_palette.setColor(QPalette.Link, QColor(208, 42, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(208, 42, 218))
    dark_palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(dark_palette)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
