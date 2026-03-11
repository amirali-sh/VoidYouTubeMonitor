# YouTube Video Monitor

A Windows desktop application to monitor multiple YouTube live streams simultaneously. Displays streams as tiles with embedded playback, live status indicators, and full media controls.

## Download

👉 Download the latest release from the [Releases](../../releases) page — no installation required.

## Features

- Watch multiple YouTube streams side by side in a grid layout
- Embedded video playback (no browser needed)
- Add and remove streams dynamically
- Shows live status and video titles
- Full playback controls (play/pause, seek, volume, mute)
- Quality selection for different video resolutions
- Caption/subtitle support
- Save and load stream collections

## Controls

- **Play/Pause**: Toggle video playback
- **Seek Slider**: Scrub through video timeline
- **Volume Slider**: Adjust audio volume
- **Mute Button**: Toggle audio mute/unmute
- **Quality Selector**: Choose video resolution
- **Caption Selector**: Select subtitle language
- **Save Streams** 💾: Save current stream list to `streams.json`
- **Load Streams** 📁: Restore streams from `streams.json`

## Running from Source

1. Install Python 3.8+
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run:
   ```
   python main.py
   ```

## Building the Executable

To build a standalone `.exe` (requires VLC installed on your machine):

```
build.bat
```

Output will be in `dist\VoidYouTubeMonitor\`. The build bundles VLC — your friends do **not** need VLC installed to run the exe.