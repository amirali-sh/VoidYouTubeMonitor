# YouTube Video Monitor

A Python desktop application to monitor multiple YouTube videos. Displays videos as tiles with the ability to add/remove videos, showing title and live status.

## Features

- Monitor multiple YouTube videos in a grid layout
- Display videos as tiles with embedded VLC playback
- Add and remove videos dynamically
- Show live status with video titles
- Full playback controls (play/pause, seek, volume, mute)
- Quality selection for different video resolutions
- Caption/subtitle support
- Save and load stream collections
- Open videos in browser as fallback

## Controls

- **Play/Pause**: Toggle video playback
- **Seek Slider**: Scrub through video timeline
- **Volume Slider**: Adjust audio volume
- **Mute Button**: Toggle audio mute/unmute
- **Quality Selector**: Choose video resolution
- **Caption Selector**: Select subtitle language
- **Save Streams**: Save current stream list to file
- **Load Streams**: Load streams from saved file

## Setup

1. Install Python (if not already installed)
2. Install dependencies: `pip install -r requirements.txt`
3. Run the application: `python main.py`

## Requirements

- Python 3.8+
- VLC media player (for embedded playback)
- Dependencies listed in requirements.txt

## Saving/Loading Streams

- Click "💾 Save Streams" to save your current collection of videos to `streams.json`
- Click "📁 Load Streams" to load all videos from `streams.json`
- This makes it easy to restore your favorite streams or share collections