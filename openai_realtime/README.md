# OpenAI Realtime API Overlay

A transparent floating overlay that displays AI-assisted responses from OpenAI's Realtime API.

## Features

-   **Transparent Overlay**: Floats above other applications with adjustable transparency.
-   **Screen Share Compatible**: Option to hide the overlay during screen recordings.
-   **Keyboard Shortcuts**: Easy control with keyboard shortcuts.
-   **Status Bar Control**: Convenient menu in the macOS status bar.

## Requirements

-   macOS (tested on macOS Ventura and later)
-   Python 3.9+
-   OpenAI API key with access to the realtime API models

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.sample` to `.env` and add your OpenAI API key:

```bash
cp .env.sample .env
```

4. Edit `.env` and replace `your_openai_api_key_here` with your actual OpenAI API key.

## Usage

Run the overlay:

```bash
python openai_overlay.py
```

### Controls

-   **Start/Stop**: Use the buttons in the overlay window.
-   **Keyboard Shortcuts**:
    -   `Cmd+Shift+H`: Toggle overlay visibility
    -   `Cmd+Shift++`: Increase overlay size
    -   `Cmd+Shift+-`: Decrease overlay size
    -   `Cmd+Shift+T`: Decrease opacity
    -   `Cmd+Shift+Y`: Increase opacity
    -   `Cmd+Shift+Q`: Quit application
    -   `Cmd+Shift+P`: Toggle presentation mode (hide during screen sharing)

### Status Bar Menu

Click the microphone icon in the macOS status bar for additional options:

-   Show/Hide Overlay
-   Toggle presentation mode
-   Adjust transparency
-   Quit the application

## Custom Instructions

You can customize the AI's instructions by creating a `prompt.txt` file in the same directory as the script. The
contents of this file will be used as instructions for the OpenAI model.

## Troubleshooting

-   **No sound detected**: Check your microphone settings and permissions.
-   **API errors**: Verify your API key and internet connection.
-   **Performance issues**: Try adjusting the audio quality settings if CPU usage is high.

## License

MIT
