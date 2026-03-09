import sys
import os
import threading
import requests
import json
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QPushButton, QLineEdit, QLabel, QFrame, QDialog, QSlider, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QTimer
from PyQt5.QtGui import QFont, QCursor
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


class VideoCallbacks(QObject):
    """Thread-safe signal emitter for UI updates"""
    video_loaded = pyqtSignal(str, str, str, str, list, dict, bool)  # video_id, title, stream_url, original_url, qualities, captions, is_live
    

class StreamTile(QFrame):
    """Individual stream tile showing YouTube video"""
    def __init__(self, video_id="", parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.youtube_url = None
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setLineWidth(2)
        self.setStyleSheet("border: 2px solid #444; background: #000;")
        self.setMinimumSize(300, 220)  # Reduced minimum size for better responsiveness
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # VLC video widget
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(290, 160)  # Reduced for better responsiveness
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
        
        # Set the video widget as the output
        if self.vlc_player and os.name == 'nt':  # Windows
            try:
                self.vlc_player.set_hwnd(self.video_frame.winId())
                self.vlc_player.audio_set_volume(0)  # Start muted
                print("VLC output set to Windows window")
            except Exception as e:
                print(f"Failed to set VLC output: {e}")
        elif self.vlc_player:  # Linux/Unix
            try:
                self.vlc_player.set_xwindow(self.video_frame.winId())
                self.vlc_player.audio_set_volume(0)  # Start muted
                print("VLC output set to X11 window")
            except Exception as e:
                print(f"Failed to set VLC output: {e}")
        
        # Title label
        self.title_label = QLabel("Stream Title")
        self.title_label.setStyleSheet("background-color: #222; color: #fff; padding: 5px; font-weight: bold;")
        self.title_label.setMaximumHeight(30)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        
        # Status label
        self.status_label = QLabel("●  LIVE")
        self.status_label.setStyleSheet("background-color: #222; color: #4CAF50; padding: 3px 5px; font-size: 10px;")
        self.status_label.setMaximumHeight(20)
        layout.addWidget(self.status_label)
        
        # Playback controls
        control_layout = QHBoxLayout()
        control_layout.setSpacing(5)
        control_layout.setContentsMargins(5, 3, 5, 3)
        
        # Play/Pause button
        self.play_btn = QPushButton("▶")
        self.play_btn.setMaximumWidth(60)
        self.play_btn.setMinimumWidth(60)
        self.play_btn.setMaximumHeight(32)
        self.play_btn.setStyleSheet("background-color: #2196F3; color: #fff; padding: 3px; font-size: 14px; font-weight: bold;")
        self.play_btn.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_btn)
        
        # Seek slider
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setStyleSheet("QSlider::groove:horizontal { background: #333; height: 5px; } QSlider::handle:horizontal { background: #2196F3; width: 10px; margin: -3px 0; }")
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(100)
        self.seek_slider.sliderMoved.connect(self.on_seek)
        self.seek_slider.setMouseTracking(True)
        control_layout.addWidget(self.seek_slider)
        
        # Time label
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("color: #fff; font-size: 10px;")
        self.time_label.setMaximumWidth(60)
        control_layout.addWidget(self.time_label)
        
        # Volume slider
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setStyleSheet("QSlider::groove:horizontal { background: #333; height: 5px; } QSlider::handle:horizontal { background: #4CAF50; width: 10px; margin: -3px 0; }")
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(0)  # Start muted
        self.volume_slider.setMaximumWidth(50)
        self.volume_slider.sliderMoved.connect(self.on_volume_change)
        control_layout.addWidget(self.volume_slider)
        
        # Mute button
        self.mute_btn = QPushButton("�")  # Start with muted icon
        self.mute_btn.setMaximumWidth(40)
        self.mute_btn.setMinimumWidth(40)
        self.mute_btn.setMaximumHeight(32)
        self.mute_btn.setStyleSheet("background-color: #4CAF50; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
        self.mute_btn.clicked.connect(self.toggle_mute)
        control_layout.addWidget(self.mute_btn)
        
        # Quality selector
        self.quality_combo = QComboBox()
        self.quality_combo.setStyleSheet("background-color: #333; color: #fff; padding: 2px; font-size: 10px;")
        self.quality_combo.setMaximumWidth(80)
        self.quality_combo.currentTextChanged.connect(self.on_quality_change)
        control_layout.addWidget(self.quality_combo)
        
        # Caption selector
        self.caption_combo = QComboBox()
        self.caption_combo.setStyleSheet("background-color: #333; color: #fff; padding: 2px; font-size: 10px;")
        self.caption_combo.setMaximumWidth(80)
        self.caption_combo.currentTextChanged.connect(self.on_caption_change)
        control_layout.addWidget(self.caption_combo)
        
        # Control bar background
        control_bar = QWidget()
        control_bar.setStyleSheet("background-color: #111;")
        control_bar.setLayout(control_layout)
        control_bar.setMaximumHeight(40)
        layout.addWidget(control_bar)
        
        self.setLayout(layout)
        
        # Browser button (always visible)
        self.error_btn = QPushButton("Open in browser")
        self.error_btn.setStyleSheet("background-color: #2196F3; color: #fff; padding:5px; font-weight: bold;")
        self.error_btn.setEnabled(True)
        self.error_btn.setVisible(True)
        self.error_btn.clicked.connect(self.open_in_browser)
        layout.addWidget(self.error_btn)
        
        # Update timer for progress
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_progress)
        
        self.is_playing = False
        self.seeking = False
        self.is_muted = True  # Start muted
        self.previous_volume = 50  # Default unmuted volume
        self.available_qualities = []
        self.available_captions = {}
    
    def toggle_play(self):
        """Play or pause the video"""
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
        """Handle seek slider movement"""
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
        """Handle volume slider movement"""
        if not self.vlc_player:
            return
        
        try:
            self.vlc_player.audio_set_volume(value)
            if value == 0:
                self.is_muted = True
                self.mute_btn.setText("🔇")
                self.mute_btn.setStyleSheet("background-color: #f44336; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
            else:
                self.is_muted = False
                self.previous_volume = value
                self.mute_btn.setText("🔊")
                self.mute_btn.setStyleSheet("background-color: #4CAF50; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
        except Exception as e:
            print(f"Volume change error: {e}")
    
    def toggle_mute(self):
        """Toggle mute/unmute"""
        if not self.vlc_player:
            return
        
        try:
            if self.is_muted:
                # Unmute - restore previous volume
                self.vlc_player.audio_set_volume(self.previous_volume)
                self.volume_slider.setValue(self.previous_volume)
                self.is_muted = False
                self.mute_btn.setText("🔊")
                self.mute_btn.setStyleSheet("background-color: #4CAF50; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
            else:
                # Mute - set volume to 0
                self.previous_volume = self.volume_slider.value()
                self.vlc_player.audio_set_volume(0)
                self.volume_slider.setValue(0)
                self.is_muted = True
                self.mute_btn.setText("🔇")
                self.mute_btn.setStyleSheet("background-color: #f44336; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
        except Exception as e:
            print(f"Mute toggle error: {e}")
    
    def on_quality_change(self, quality_text):
        """Handle quality selection change"""
        if not quality_text or quality_text == "Select Quality":
            return
        
        # Find the format ID for this quality
        for fmt in self.available_qualities:
            if fmt.get('format_note', '') == quality_text or f"{fmt.get('height', '')}p" in quality_text:
                try:
                    # Reload with new quality
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
        """Handle caption selection change"""
        if not self.vlc_player or caption_text == "No Subs":
            return
        
        try:
            # Find caption URL
            if caption_text in self.available_captions:
                caption_url = self.available_captions[caption_text]
                # VLC can load subtitles from URL
                self.vlc_player.add_slave(1, caption_url, True)  # 1 = subtitle slave
        except Exception as e:
            print(f"Caption change error: {e}")
    
    def update_progress(self):
        """Update seek slider and time label"""
        if not self.vlc_player or self.seeking:
            return
        
        try:
            duration = self.vlc_player.get_length()
            current = self.vlc_player.get_time()
            
            if duration > 0:
                # Update seek slider
                progress = int((current / duration) * 100)
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(progress)
                self.seek_slider.blockSignals(False)
                
                # Update time label
                current_sec = current // 1000
                duration_sec = duration // 1000
                current_min, current_sec = divmod(current_sec, 60)
                duration_min, duration_sec = divmod(duration_sec, 60)
                self.time_label.setText(f"{current_min}:{current_sec:02d} / {duration_min}:{duration_sec:02d}")
        except Exception as e:
            print(f"Update progress error: {e}")
    
    def load_stream(self, stream_url, title, youtube_url="", is_live=False):
        """Load YouTube video using VLC or fallback"""
        self.youtube_url = youtube_url
        self.title_label.setText(title[:40] + "..." if len(title) > 40 else title)
        
        # Update status based on live/pre-recorded
        status_text = "●  LIVE" if is_live else "●  PRE-RECORDED"
        self.status_label.setText(f"{status_text} - {title[:30] + '...' if len(title) > 30 else title}")
        
        print(f"Loading stream: {stream_url} (live: {is_live})")
        
        # Try VLC first
        if self.vlc_player and stream_url:
            try:
                print("Trying VLC playback...")
                media = self.vlc_instance.media_new(stream_url)
                self.vlc_player.set_media(media)
                result = self.vlc_player.play()
                
                if result == 0:
                    print("VLC playback started")
                    self.title_label.setText("▶ Playing (VLC)")
                    self.title_label.setStyleSheet("background-color: #4CAF50; color: #fff; padding: 5px; font-weight: bold;")
                    self.is_playing = True
                    self.play_btn.setText("⏸")
                    
                    # Start muted
                    self.vlc_player.audio_set_volume(0)
                    self.volume_slider.setValue(0)
                    self.is_muted = True
                    self.mute_btn.setText("🔇")
                    self.mute_btn.setStyleSheet("background-color: #f44336; color: #fff; padding: 3px; font-size: 12px; font-weight: bold;")
                    
                    self.update_timer.start(500)
                    return
                else:
                    print(f"VLC failed with code: {result}")
            except Exception as e:
                print(f"VLC error: {e}")
        
        # Fallback: open in default media player
        print("Falling back to external player...")
        try:
            import subprocess
            import os
            
            if os.name == 'nt':  # Windows
                # Use start command to open with default player
                subprocess.run(['cmd', '/c', 'start', '', stream_url], shell=True)
                print("Opened with Windows default player")
            else:
                # Linux/Mac
                subprocess.run(['xdg-open', stream_url])
                print("Opened with xdg-open")
                
            self.title_label.setText("▶ Opened externally")
            self.title_label.setStyleSheet("background-color: #FF9800; color: #fff; padding: 5px; font-weight: bold;")
            
        except Exception as e:
            print(f"External player failed: {e}")
            self.title_label.setText("Playback failed")
            self.title_label.setStyleSheet("background-color: #d32f2f; color: #fff; padding: 5px; font-weight: bold;")

    def open_in_browser(self):
        print("Button clicked! Opening browser...")
        import subprocess
        import os
        print(f"Opening in browser: {self.youtube_url}")
        if self.youtube_url:
            try:
                # Try multiple methods to open browser
                if os.name == 'nt':  # Windows
                    os.startfile(self.youtube_url)
                    print("Used os.startfile()")
                else:
                    # Try webbrowser first
                    import webbrowser
                    result = webbrowser.open(self.youtube_url)
                    if not result:
                        # Fallback to system command
                        subprocess.run(['xdg-open', self.youtube_url], check=False)
                        print("Used xdg-open fallback")
                    else:
                        print("Used webbrowser.open()")
                print("Browser opened successfully")
            except Exception as e:
                print(f"Error opening browser: {e}")
                # Last resort - show the URL in a message
                print(f"Please manually open: {self.youtube_url}")
        else:
            print("No YouTube URL available")


class YouTubeVideoMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("YouTube Video Monitor")
        self.setGeometry(100, 100, 1600, 1000)
        self.setStyleSheet("background-color: #0a0a0a;")
        
        # Data storage
        self.videos = {}  # {video_id: {metadata}}
        self.tiles = []   # List of tile widgets
        self.tiles_map = {}  # {tile:widget: video_id}
        
        # Signal handler for thread-safe UI updates
        self.callbacks = VideoCallbacks()
        self.callbacks.video_loaded.connect(self.on_video_loaded, Qt.QueuedConnection)
        
        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Top bar with title and add button
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        title = QLabel("Live Streams")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #fff;")
        top_layout.addWidget(title)
        
        top_layout.addStretch()
        
        save_streams_btn = QPushButton("💾 Save Streams")
        save_streams_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px 15px; border: none; border-radius: 3px; font-weight: bold;")
        save_streams_btn.clicked.connect(self.save_streams)
        top_layout.addWidget(save_streams_btn)
        
        load_streams_btn = QPushButton("📁 Load Streams")
        load_streams_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px 15px; border: none; border-radius: 3px; font-weight: bold;")
        load_streams_btn.clicked.connect(self.load_streams)
        top_layout.addWidget(load_streams_btn)
        
        add_stream_btn = QPushButton("+ Add Stream")
        add_stream_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 15px; border: none; border-radius: 3px; font-weight: bold;")
        add_stream_btn.clicked.connect(self.show_add_stream_dialog)
        top_layout.addWidget(add_stream_btn)
        
        main_layout.addLayout(top_layout)
        
        # Grid layout for streams (3 columns)
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        
        main_layout.addLayout(self.grid_layout)
        main_widget.setLayout(main_layout)
    
    def show_add_stream_dialog(self):
        """Show dialog to add a new stream"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add YouTube Stream")
        dialog.setGeometry(400, 300, 450, 150)
        dialog.setStyleSheet("background-color: #222; color: #fff;")
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # Label
        label = QLabel("Enter YouTube URL:")
        label.setStyleSheet("color: #fff;")
        layout.addWidget(label)
        
        # URL input
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        url_input.setStyleSheet("background-color: #333; color: #fff; padding: 5px; border: 1px solid #555;")
        layout.addWidget(url_input)
        
        # Buttons
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
            
            if video_id in self.videos:
                dialog.reject()
                return
            
            # Fetch title and stream URL in background
            thread = threading.Thread(target=self.fetch_video_info, args=(video_id, url))
            thread.daemon = True
            thread.start()
            dialog.accept()
        
        add_btn.clicked.connect(add_video)
        dialog.exec_()
    
    def save_streams(self):
        """Save current streams to a JSON file"""
        print("Save streams button clicked")
        if not self.videos:
            print("No videos to save")
            return
        
        # Create data structure
        streams_data = {
            "streams": []
        }
        
        for video_id, video_info in self.videos.items():
            streams_data["streams"].append({
                "url": video_info["url"],
                "title": video_info["title"]
            })
        
        # Save to file
        try:
            with open("streams.json", "w", encoding="utf-8") as f:
                json.dump(streams_data, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(streams_data['streams'])} streams to streams.json")
        except Exception as e:
            print(f"Error saving streams: {e}")
    
    def load_streams(self):
        """Load streams from a JSON file"""
        print("Load streams button clicked")
        try:
            if not os.path.exists("streams.json"):
                print("No streams.json file found")
                return
            
            with open("streams.json", "r", encoding="utf-8") as f:
                streams_data = json.load(f)
            
            streams = streams_data.get("streams", [])
            print(f"Loading {len(streams)} streams from file")
            
            for stream in streams:
                url = stream.get("url")
                if url:
                    video_id = extract_youtube_video_id(url)
                    if video_id and video_id not in self.videos:
                        print(f"Adding stream: {url}")
                        # Add the stream
                        thread = threading.Thread(target=self.fetch_video_info, args=(video_id, url))
                        thread.daemon = True
                        thread.start()
                    else:
                        print(f"Skipping duplicate or invalid stream: {url}")
                        
        except Exception as e:
            print(f"Error loading streams: {e}")
    
    def fetch_video_info(self, video_id, url):
        """Fetch video title and stream URL from YouTube (runs in background thread)"""
        try:
            # Get title
            print(f"Fetching title for {video_id}...")
            response = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find('title').text.replace(' - YouTube', '') if soup.find('title') else video_id
            print(f"Got title: {title}")
            
            # Get stream URL using yt-dlp
            print(f"Extracting stream URL from {url}...")
            ydl_opts = {
                'format': 'best[ext=mp4][height<=480]',  # Prefer MP4, reasonable quality
                'quiet': False,
                'no_warnings': False,
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get('url')
                is_live = info.get('is_live', False)
                
                # Extract available qualities
                qualities = []
                for fmt in info.get('formats', []):
                    if fmt.get('height') and fmt.get('ext') == 'mp4' and fmt.get('url'):
                        qualities.append({
                            'height': fmt.get('height'),
                            'url': fmt.get('url'),
                            'format_note': fmt.get('format_note', '')
                        })
                
                # Extract available captions
                captions = {}
                if 'subtitles' in info:
                    for lang, subs in info['subtitles'].items():
                        if subs:
                            captions[lang.upper()] = subs[0]['url']
                
                print(f"Found {len(qualities)} qualities and {len(captions)} caption languages")
                print(f"Is live: {is_live}")
                
                if stream_url:
                    print(f"Got stream URL: {stream_url[:80]}...")
                else:
                    print("No stream URL found")
                
                print(f"Final stream URL: {stream_url}")
        except Exception as e:
            print(f"Error fetching video info: {type(e).__name__}: {e}")
            title = video_id
            stream_url = None
            qualities = []
            captions = {}
            is_live = False
        
        self.callbacks.video_loaded.emit(video_id, title, stream_url, url, qualities, captions, is_live)
    
    def on_video_loaded(self, video_id, title, stream_url, original_url, qualities, captions, is_live):
        """Handle video loaded signal (runs in main thread via signal connection)"""
        # Create new stream tile
        tile = StreamTile(video_id)
        tile.load_stream(stream_url, title, original_url, is_live)
        
        # Set available qualities and captions
        tile.available_qualities = qualities
        tile.available_captions = captions
        
        # Populate quality combo box
        tile.quality_combo.clear()
        tile.quality_combo.addItem("Select Quality")
        for fmt in qualities:
            height = fmt.get('height', 'Unknown')
            note = fmt.get('format_note', '')
            display_text = f"{height}p" if not note else f"{height}p ({note})"
            tile.quality_combo.addItem(display_text)
        
        # Populate caption combo box
        tile.caption_combo.clear()
        tile.caption_combo.addItem("No Subs")
        for lang in captions.keys():
            tile.caption_combo.addItem(lang)
        
        # Store video info
        self.videos[video_id] = {
            'title': title,
            'url': original_url,
            'tile': tile
        }
        
        # Add stream tile to grid with dynamic layout
        self.tiles.append(tile)
        self.rearrange_tiles()
    
    def rearrange_tiles(self):
        """Rearrange tiles in column-major layout with 2 videos per column"""
        if not self.tiles:
            return
        
        # Clear existing layout
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                self.grid_layout.removeWidget(widget)
        
        # Rearrange tiles in row-major order (fill rows left to right, max 3 columns)
        # This ensures each row has the same number of videos before starting new row
        cols = min(3, len(self.tiles))  # Max 3 columns
        rows = (len(self.tiles) + cols - 1) // cols  # Calculate rows needed
        
        for i, tile in enumerate(self.tiles):
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(tile, row, col)
        
        print(f"Rearranged {len(self.tiles)} tiles in {rows} rows x {cols} columns layout")
    
    def resizeEvent(self, event):
        """Handle window resize to rearrange tiles"""
        super().resizeEvent(event)
        self.rearrange_tiles()
    
    def extract_video_id(self, url):
        """Extract video ID from YouTube URL"""
        try:
            if 'youtube.com/watch?v=' in url:
                return url.split('youtube.com/watch?v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                return url.split('youtu.be/')[1].split('?')[0]
        except:
            pass
        return None


if __name__ == "__main__":
    import sys
    print("Starting application...")
    app = QApplication(sys.argv)
    print("Creating window...")
    window = YouTubeVideoMonitor()
    print("Showing window...")
    window.show()
    print("Running event loop...")
    sys.exit(app.exec_())