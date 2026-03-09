import sys
import os
import threading
import requests
import json
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QPushButton, QLineEdit, QLabel, QFrame, QDialog, QSlider, QComboBox, QFileDialog, QMessageBox, QAction)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QRect, QPoint
from PyQt5.QtGui import QFont, QCursor, QIcon, QPainter, QColor, QPen, QBrush, QFontMetrics
import re
import vlc


def extract_youtube_video_id(url):
    """Extract YouTube video ID from various URL formats"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/v\/([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None



class ModernSlider(QWidget):
    """Custom slider with inner horizontal padding and modern flat style."""
    valueChanged = pyqtSignal(int)
    sliderMoved  = pyqtSignal(int)

    def __init__(self, color="#2196F3", parent=None):
        super().__init__(parent)
        self._value   = 0
        self._minimum = 0
        self._maximum = 100
        self._color   = QColor(color)
        self._dragging = False
        self._pad = 10          # left/right inner padding in px
        self._groove_h = 4      # groove height
        self._handle_r = 6      # handle radius
        self.setFixedHeight(30)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    # ── value API (mirrors QSlider) ──────────────────────────────────────
    def value(self):      return self._value
    def minimum(self):    return self._minimum
    def maximum(self):    return self._maximum

    def setValue(self, v):
        v = max(self._minimum, min(self._maximum, v))
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def setMinimum(self, v): self._minimum = v; self.update()
    def setMaximum(self, v): self._maximum = v; self.update()

    def blockSignals(self, b):
        super().blockSignals(b)

    # ── geometry helpers ─────────────────────────────────────────────────
    def _track_rect(self):
        cy = self.height() // 2
        return QRect(self._pad, cy - self._groove_h // 2,
                     self.width() - 2 * self._pad, self._groove_h)

    def _handle_x(self):
        tr = self._track_rect()
        span = self._maximum - self._minimum or 1
        ratio = (self._value - self._minimum) / span
        return tr.x() + int(ratio * tr.width())

    def _value_from_x(self, x):
        tr = self._track_rect()
        ratio = max(0.0, min(1.0, (x - tr.x()) / max(tr.width(), 1)))
        return self._minimum + int(ratio * (self._maximum - self._minimum))

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tr = self._track_rect()
        hx = self._handle_x()
        cy = self.height() // 2

        # Background groove
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#2a2a2a")))
        p.drawRoundedRect(tr, self._groove_h / 2, self._groove_h / 2)

        # Filled portion
        filled = QRect(tr.x(), tr.y(), hx - tr.x(), tr.height())
        if filled.width() > 0:
            p.setBrush(QBrush(self._color))
            p.drawRoundedRect(filled, self._groove_h / 2, self._groove_h / 2)

        # Handle
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(hx, cy), self._handle_r, self._handle_r)
        p.end()

    # ── mouse events ─────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_event(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._update_from_event(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = False

    def _update_from_event(self, e):
        v = self._value_from_x(e.x())
        old = self._value
        self.setValue(v)
        if v != old:
            self.sliderMoved.emit(v)



class ModernTimeDisplay(QWidget):
    """Custom-painted time display matching ModernSlider aesthetic."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = "0:00 / 0:00"
        self._pad_x = 10
        self._pad_y = 4
        self._bg    = QColor("#2a2a2a")
        self._fg    = QColor("#ffffff")
        self._font  = QFont("Segoe UI", 8)
        self._font.setWeight(QFont.Medium)
        self.setFixedHeight(30)
        self._update_width()

    def setText(self, text):
        if text != self._text:
            self._text = text
            self._update_width()
            self.update()

    def _update_width(self):
        fm = QFontMetrics(self._font)
        w = fm.horizontalAdvance(self._text) + self._pad_x * 2
        self.setFixedWidth(max(w, 74))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        # Dark rounded pill background
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._bg))
        p.drawRoundedRect(r, 6, 6)
        # Text
        p.setPen(QPen(self._fg))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignCenter, self._text)
        p.end()


class VideoCallbacks(QObject):
    """Thread-safe signal emitter for UI updates"""
    video_loaded = pyqtSignal(str, str, str, str, list, dict, bool)  # video_id, title, stream_url, original_url, qualities, captions, is_live
    remove_stream = pyqtSignal(str)  # video_id


class StreamTile(QFrame):
    """Individual stream tile showing YouTube video"""
    def __init__(self, video_id="", parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.youtube_url = None
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setLineWidth(2)
        self.setStyleSheet("border: 2px solid #444; background: #000;")
        self.setMinimumSize(300, 220)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # VLC video widget
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(290, 160)
        self.video_frame.setStyleSheet("background-color: #000;")
        layout.addWidget(self.video_frame)
        
        # Create VLC instance and player
        try:
            self.vlc_instance = vlc.Instance()
            self.vlc_player = self.vlc_instance.media_player_new()
            print(f"VLC player created for tile {video_id}")
        except Exception as e:
            print(f"Failed to create VLC player: {e}")
            self.vlc_instance = None
            self.vlc_player = None
        
        if self.vlc_player and os.name == 'nt':
            try:
                self.vlc_player.set_hwnd(self.video_frame.winId())
                self.vlc_player.audio_set_volume(0)
            except Exception as e:
                print(f"Failed to set VLC output: {e}")
        elif self.vlc_player:
            try:
                self.vlc_player.set_xwindow(self.video_frame.winId())
                self.vlc_player.audio_set_volume(0)
            except Exception as e:
                print(f"Failed to set VLC output: {e}")
        
        # Title bar: title label + remove button
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #222;")
        title_bar.setFixedHeight(42)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(8, 5, 8, 5)
        title_bar_layout.setSpacing(8)

        self.title_label = QLabel("Stream Title")
        self.title_label.setStyleSheet("color: #fff; font-weight: bold; background: transparent;")
        self.title_label.setWordWrap(False)
        title_bar_layout.addWidget(self.title_label, stretch=1)

        self.remove_btn = QPushButton("✕  Remove Stream")
        self.remove_btn.setFixedHeight(28)
        self.remove_btn.setStyleSheet(
            "background-color: #c0392b; color: white; padding: 4px 12px; border: none; border-radius: 4px; font-weight: bold; font-size: 12px;"
        )
        self.remove_btn.setCursor(QCursor(Qt.PointingHandCursor))
        title_bar_layout.addWidget(self.remove_btn, alignment=Qt.AlignVCenter)

        layout.addWidget(title_bar)
        

        # Playback controls
        control_layout = QHBoxLayout()
        control_layout.setSpacing(6)
        control_layout.setContentsMargins(8, 5, 8, 5)

        self.go_live_btn = QPushButton("⏭ Live")
        self.go_live_btn.setFixedSize(56, 30)
        self.go_live_btn.setStyleSheet(
            "background-color: #2a2a2a; color: #555; padding: 4px 6px; border: none; border-radius: 4px; font-size: 10px; font-weight: bold;"
        )
        self.go_live_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.setToolTip("Jump to live")
        self.go_live_btn.clicked.connect(self.jump_to_live)
        control_layout.addWidget(self.go_live_btn)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(34, 30)
        self.play_btn.setStyleSheet("background-color: #2196F3; color: #fff; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px; font-weight: bold;")
        self.play_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.play_btn.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_btn)

        self.seek_slider = ModernSlider(color="#2196F3")
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(100)
        self.seek_slider.sliderMoved.connect(self.on_seek)
        control_layout.addWidget(self.seek_slider)

        self.time_label = ModernTimeDisplay()
        control_layout.addWidget(self.time_label)

        self.mute_btn = QPushButton("🔇")
        self.mute_btn.setFixedSize(34, 30)
        self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #aaa; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
        self.mute_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.mute_btn.clicked.connect(self.toggle_mute)
        control_layout.addWidget(self.mute_btn)

        self.volume_slider = ModernSlider(color="#4CAF50")
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(0)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.sliderMoved.connect(self.on_volume_change)
        control_layout.addWidget(self.volume_slider)
        
        self.quality_combo = QComboBox()
        self.quality_combo.setStyleSheet("background-color: #333; color: #fff; padding: 2px; font-size: 10px;")
        self.quality_combo.setMaximumWidth(80)
        self.quality_combo.currentTextChanged.connect(self.on_quality_change)
        control_layout.addWidget(self.quality_combo)
        
        
        control_bar = QWidget()
        control_bar.setStyleSheet("background-color: #181818; border-top: 1px solid #2a2a2a;")
        control_bar.setLayout(control_layout)
        control_bar.setFixedHeight(44)
        layout.addWidget(control_bar)
        
        self.setLayout(layout)
        
        self.error_btn = QPushButton("Open in browser")
        self.error_btn.setStyleSheet("background-color: #2196F3; color: #fff; padding:5px; font-weight: bold;")
        self.error_btn.clicked.connect(self.open_in_browser)
        layout.addWidget(self.error_btn)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_progress)
        
        self.is_playing = False
        self.seeking = False
        self.is_muted = True
        self.is_live = False
        self.previous_volume = 50
        self.available_qualities = []
        self.available_captions = {}

        # Wire remove button — signal connected by main window after creation
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        self._on_remove = None  # callback set by main window

    def _on_remove_clicked(self):
        if callable(self._on_remove):
            self._on_remove(self.video_id)

    def cleanup(self):
        """Stop playback and release VLC resources."""
        try:
            self.update_timer.stop()
            if self.vlc_player:
                self.vlc_player.stop()
                self.vlc_player.release()
                self.vlc_player = None
            if self.vlc_instance:
                self.vlc_instance.release()
                self.vlc_instance = None
        except Exception as e:
            print(f"Cleanup error for {self.video_id}: {e}")
    
    def toggle_play(self):
        if not self.vlc_player:
            return
        try:
            if self.is_playing:
                self.vlc_player.pause()
                self.play_btn.setText("▶")
                self.is_playing = False
                self.update_timer.stop()
            else:
                self.vlc_player.play()
                self.play_btn.setText("⏸")
                self.is_playing = True
                self.update_timer.start(500)
        except Exception as e:
            print(f"Toggle play error: {e}")
    
    def on_seek(self, value):
        if not self.vlc_player or self.vlc_player.get_length() <= 0:
            return
        try:
            self.seeking = True
            duration = self.vlc_player.get_length()
            position = int((value / 100.0) * duration)
            self.vlc_player.set_time(position)
            self.seeking = False
        except Exception as e:
            print(f"Seek error: {e}")
            self.seeking = False
    
    def on_volume_change(self, value):
        if not self.vlc_player:
            return
        try:
            self.vlc_player.audio_set_volume(value)
            if value == 0:
                self.is_muted = True
                self.mute_btn.setText("🔇")
                self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #aaa; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
            else:
                self.is_muted = False
                self.previous_volume = value
                self.mute_btn.setText("🔊")
                self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #fff; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
        except Exception as e:
            print(f"Volume change error: {e}")
    
    def toggle_mute(self):
        if not self.vlc_player:
            return
        try:
            if self.is_muted:
                self.vlc_player.audio_set_volume(self.previous_volume)
                self.volume_slider.setValue(self.previous_volume)
                self.is_muted = False
                self.mute_btn.setText("🔊")
                self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #fff; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
            else:
                self.previous_volume = self.volume_slider.value()
                self.vlc_player.audio_set_volume(0)
                self.volume_slider.setValue(0)
                self.is_muted = True
                self.mute_btn.setText("🔇")
                self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #aaa; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
        except Exception as e:
            print(f"Mute toggle error: {e}")
    
    def on_quality_change(self, quality_text):
        if not quality_text or quality_text == "Select Quality":
            return
        for fmt in self.available_qualities:
            if fmt.get('format_note', '') == quality_text or f"{fmt.get('height', '')}p" in quality_text:
                try:
                    stream_url = fmt.get('url')
                    if stream_url and self.vlc_player:
                        media = self.vlc_instance.media_new(stream_url)
                        self.vlc_player.set_media(media)
                        if self.is_playing:
                            self.vlc_player.play()
                except Exception as e:
                    print(f"Quality change error: {e}")
                break
    
    def on_caption_change(self, caption_text):
        if not self.vlc_player or caption_text == "No Subs":
            return
        try:
            if caption_text in self.available_captions:
                caption_url = self.available_captions[caption_text]
                self.vlc_player.add_slave(1, caption_url, True)
        except Exception as e:
            print(f"Caption change error: {e}")
    
    def update_progress(self):
        if not self.vlc_player or self.seeking:
            return
        try:
            duration = self.vlc_player.get_length()
            current = self.vlc_player.get_time()
            if duration > 0:
                progress = int((current / duration) * 100)
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(progress)
                self.seek_slider.blockSignals(False)
                current_sec = current // 1000
                duration_sec = duration // 1000
                current_min, current_sec = divmod(current_sec, 60)
                duration_min, duration_sec = divmod(duration_sec, 60)
                self.time_label.setText(f"{current_min}:{current_sec:02d} / {duration_min}:{duration_sec:02d}")

                # Show/enable Go Live button when behind live edge (>3s from end)
                if self.is_live:
                    behind = (duration - current) > 3000  # ms
                    self.go_live_btn.setEnabled(behind)
                    if behind:
                        self.go_live_btn.setStyleSheet(
                            "background-color: #e53935; color: #fff; padding: 4px 6px; border: none; border-radius: 4px; font-size: 10px; font-weight: bold;"
                        )
                    else:
                        self.go_live_btn.setStyleSheet(
                            "background-color: #2a2a2a; color: #555; padding: 4px 6px; border: none; border-radius: 4px; font-size: 10px; font-weight: bold;"
                        )
        except Exception as e:
            print(f"Update progress error: {e}")

    def jump_to_live(self):
        """Seek to the live edge (end of stream buffer)."""
        if not self.vlc_player:
            return
        try:
            duration = self.vlc_player.get_length()
            if duration > 0:
                self.vlc_player.set_time(duration - 500)  # 0.5s before edge
                print("Jumped to live edge")
        except Exception as e:
            print(f"Jump to live error: {e}")
    
    def load_stream(self, stream_url, title, youtube_url="", is_live=False):
        self.youtube_url = youtube_url
        self.is_live = is_live
        badge = "● LIVE" if is_live else "● VOD"
        display_title = title[:45] + "..." if len(title) > 45 else title
        self.title_label.setText(f"{badge}  {display_title}")
        print(f"Loading stream: {stream_url} (live: {is_live})")

        if self.vlc_player and stream_url:
            try:
                media = self.vlc_instance.media_new(stream_url)
                self.vlc_player.set_media(media)
                result = self.vlc_player.play()
                if result == 0:
                    self.is_playing = True
                    self.play_btn.setText("⏸")
                    self.vlc_player.audio_set_volume(0)
                    self.volume_slider.setValue(0)
                    self.is_muted = True
                    self.mute_btn.setText("🔇")
                    self.mute_btn.setStyleSheet("background-color: #2a2a2a; color: #aaa; padding: 4px 8px; border: none; border-radius: 4px; font-size: 13px;")
                    self.update_timer.start(500)
                    return
                else:
                    print(f"VLC failed with code: {result}")
            except Exception as e:
                print(f"VLC error: {e}")

        try:
            import subprocess
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'start', '', stream_url], shell=True)
            else:
                subprocess.run(['xdg-open', stream_url])
        except Exception as e:
            print(f"External player failed: {e}")
            self.title_label.setText("⚠ Playback failed")

    def open_in_browser(self):
        import subprocess
        if self.youtube_url:
            try:
                if os.name == 'nt':
                    os.startfile(self.youtube_url)
                else:
                    import webbrowser
                    if not webbrowser.open(self.youtube_url):
                        subprocess.run(['xdg-open', self.youtube_url], check=False)
            except Exception as e:
                print(f"Error opening browser: {e}")


class YouTubeVideoMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Void YouTube Monitor")
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")))
        self.setGeometry(100, 100, 900, 600)
        self.setMinimumSize(600, 400)
        self.setStyleSheet("background-color: #0a0a0a;")
        
        self.videos = {}        # {video_id: {metadata}} — populated only after on_video_loaded
        self.pending_ids = set() # video IDs currently being fetched (prevents race-condition dupes)
        self.tiles = []
        
        self.callbacks = VideoCallbacks()
        self.callbacks.video_loaded.connect(self.on_video_loaded, Qt.QueuedConnection)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Menu bar ─────────────────────────────────────────────────────
        menubar = self.menuBar()
        menubar.setStyleSheet("background-color: #1a1a1a; color: #fff; border: none;")
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(56)
        toolbar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 8, 16, 8)
        toolbar_layout.setSpacing(10)

        title = QLabel("📺  Void YouTube Monitor")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #fff; background: transparent;")
        toolbar_layout.addWidget(title)

        toolbar_layout.addStretch()

        btn_style_blue   = "background-color: #2196F3; color: white; padding: 7px 14px; border: none; border-radius: 4px; font-weight: bold; font-size: 12px;"
        btn_style_orange = "background-color: #FF9800; color: white; padding: 7px 14px; border: none; border-radius: 4px; font-weight: bold; font-size: 12px;"
        btn_style_green  = "background-color: #4CAF50; color: white; padding: 7px 14px; border: none; border-radius: 4px; font-weight: bold; font-size: 12px;"

        load_streams_btn = QPushButton("📁  Load Streams")
        load_streams_btn.setStyleSheet(btn_style_orange)
        load_streams_btn.setCursor(QCursor(Qt.PointingHandCursor))
        load_streams_btn.clicked.connect(self.load_streams)
        toolbar_layout.addWidget(load_streams_btn)

        save_streams_btn = QPushButton("💾  Save Streams")
        save_streams_btn.setStyleSheet(btn_style_blue)
        save_streams_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_streams_btn.clicked.connect(self.save_streams)
        toolbar_layout.addWidget(save_streams_btn)

        add_stream_btn = QPushButton("＋  Add Stream")
        add_stream_btn.setStyleSheet(btn_style_green)
        add_stream_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_stream_btn.clicked.connect(self.show_add_stream_dialog)
        toolbar_layout.addWidget(add_stream_btn)

        main_layout.addWidget(toolbar)

        # ── Content area ─────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background-color: #0a0a0a;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        # Empty-state label (hidden once streams load)
        self.empty_label = QLabel("No streams yet.\nClick  ＋ Add Stream  or  📁 Load Streams  to get started.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #555; font-size: 15px;")
        content_layout.addWidget(self.empty_label, alignment=Qt.AlignCenter)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addLayout(self.grid_layout)

        main_layout.addWidget(content)
        main_widget.setLayout(main_layout)
    
    def show_add_stream_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add YouTube Stream")
        dialog.setGeometry(400, 300, 450, 150)
        dialog.setStyleSheet("background-color: #222; color: #fff;")
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        label = QLabel("Enter YouTube URL:")
        label.setStyleSheet("color: #fff;")
        layout.addWidget(label)
        
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        url_input.setStyleSheet("background-color: #333; color: #fff; padding: 5px; border: 1px solid #555;")
        layout.addWidget(url_input)
        
        button_layout = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; border: none; border-radius: 3px;")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #555; color: white; padding: 8px; border: none; border-radius: 3px;")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        def add_video():
            url = url_input.text().strip()
            if not url:
                return
            video_id = extract_youtube_video_id(url)
            if not video_id:
                url_input.setText("Invalid URL!")
                return
            self._add_stream_by_id(video_id, url)
            dialog.accept()
        
        add_btn.clicked.connect(add_video)
        dialog.exec_()
    
    def _add_stream_by_id(self, video_id, url):
        """Start fetching a stream if not already loaded or pending."""
        if video_id in self.videos or video_id in self.pending_ids:
            print(f"Skipping duplicate stream: {video_id}")
            return
        self.pending_ids.add(video_id)
        thread = threading.Thread(target=self.fetch_video_info, args=(video_id, url))
        thread.daemon = True
        thread.start()

    # ------------------------------------------------------------------ #
    #  SAVE — uses a file dialog so the user always knows where it saved  #
    # ------------------------------------------------------------------ #
    def save_streams(self):
        if not self.videos:
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Streams", "streams.json", "JSON Files (*.json)"
        )
        if not path:
            return  # User cancelled
        
        streams_data = {
            "streams": [
                {"url": info["url"], "title": info["title"]}
                for info in self.videos.values()
            ]
        }
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(streams_data, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(streams_data['streams'])} streams to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")
            print(f"Error saving streams: {e}")

    # ------------------------------------------------------------------ #
    #  LOAD — uses a file dialog; skips dupes; handles missing keys       #
    # ------------------------------------------------------------------ #
    def load_streams(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Streams", "", "JSON Files (*.json)"
        )
        if not path:
            return  # User cancelled
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                streams_data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not read file:\n{e}")
            print(f"Error loading streams: {e}")
            return
        
        streams = streams_data.get("streams", [])
        if not streams:
            return
        
        added = 0
        for stream in streams:
            url = stream.get("url", "").strip()
            if not url:
                continue
            video_id = extract_youtube_video_id(url)
            if not video_id:
                print(f"Could not extract video ID from: {url}")
                continue
            if video_id in self.videos or video_id in self.pending_ids:
                print(f"Skipping duplicate: {video_id}")
                continue
            self._add_stream_by_id(video_id, url)
            added += 1
        
        if added:
            print(f"Loading {added} stream(s)...")

    def fetch_video_info(self, video_id, url):
        """Fetch video title and stream URL from YouTube (background thread)"""
        try:
            print(f"Fetching title for {video_id}...")
            response = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find('title').text.replace(' - YouTube', '') if soup.find('title') else video_id
            print(f"Got title: {title}")
            
            ydl_opts = {
                'format': 'best[ext=mp4][height<=480]',
                'quiet': False,
                'no_warnings': False,
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get('url')
                is_live = info.get('is_live', False)
                
                qualities = []
                for fmt in info.get('formats', []):
                    if fmt.get('height') and fmt.get('ext') == 'mp4' and fmt.get('url'):
                        qualities.append({
                            'height': fmt.get('height'),
                            'url': fmt.get('url'),
                            'format_note': fmt.get('format_note', '')
                        })
                
                captions = {}
                for lang, subs in info.get('subtitles', {}).items():
                    if subs:
                        captions[lang.upper()] = subs[0]['url']
                
                print(f"Found {len(qualities)} qualities, {len(captions)} caption langs, live={is_live}")
        except Exception as e:
            print(f"Error fetching video info: {type(e).__name__}: {e}")
            title = video_id
            stream_url = None
            qualities = []
            captions = {}
            is_live = False
        
        self.callbacks.video_loaded.emit(video_id, title, stream_url or "", url, qualities, captions, is_live)
    
    def on_video_loaded(self, video_id, title, stream_url, original_url, qualities, captions, is_live):
        """Handle video loaded signal (main thread)"""
        # Remove from pending set
        self.pending_ids.discard(video_id)
        
        # Guard against duplicates arriving from simultaneous threads
        if video_id in self.videos:
            print(f"Duplicate signal for {video_id}, ignoring.")
            return
        
        tile = StreamTile(video_id)
        tile.load_stream(stream_url, title, original_url, is_live)
        tile.available_qualities = qualities
        tile.available_captions = captions
        
        tile.quality_combo.clear()
        tile.quality_combo.addItem("Select Quality")
        for fmt in qualities:
            height = fmt.get('height', 'Unknown')
            note = fmt.get('format_note', '')
            display_text = f"{height}p" if not note else f"{height}p ({note})"
            tile.quality_combo.addItem(display_text)
        
        # Store AFTER tile is ready
        self.videos[video_id] = {
            'title': title,
            'url': original_url,
            'tile': tile
        }

        # Wire the remove button
        tile._on_remove = self.remove_stream
        
        self.tiles.append(tile)
        self.rearrange_tiles()

    def remove_stream(self, video_id):
        """Stop and remove a stream tile."""
        if video_id not in self.videos:
            return

        info = self.videos.pop(video_id)
        tile = info['tile']

        # Stop playback and free VLC
        tile.cleanup()

        # Remove from tile list and grid
        if tile in self.tiles:
            self.tiles.remove(tile)
        self.grid_layout.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()

        self.rearrange_tiles()
        print(f"Removed stream: {video_id}")
    
    def rearrange_tiles(self):
        has_tiles = bool(self.tiles)
        self.empty_label.setVisible(not has_tiles)

        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                self.grid_layout.removeWidget(widget)

        if not has_tiles:
            return

        cols = min(3, len(self.tiles))
        for i, tile in enumerate(self.tiles):
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(tile, row, col)
    
    def show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About")
        dialog.setFixedSize(300, 120)
        dialog.setStyleSheet("background-color: #1a1a1a; color: #fff;")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        label = QLabel("📺  Void YouTube Monitor")
        label.setStyleSheet("color: #fff; font-size: 14px; font-weight: bold; background: transparent;")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        copy_label = QLabel("Copyright 2026 VoidStar")
        copy_label.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")
        copy_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(copy_label)
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 6px 20px; border: none; border-radius: 4px; font-weight: bold;")
        ok_btn.setCursor(QCursor(Qt.PointingHandCursor))
        ok_btn.clicked.connect(dialog.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignCenter)
        dialog.exec_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.rearrange_tiles()


if __name__ == "__main__":
    print("Starting application...")
    app = QApplication(sys.argv)
    window = YouTubeVideoMonitor()
    window.show()
    sys.exit(app.exec_())