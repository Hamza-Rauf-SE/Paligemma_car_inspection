#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OpenAI Realtime API Overlay for macOS

A transparent floating overlay that displays AI-assisted responses from OpenAI Realtime API.
"""

import os
import sys
import asyncio
import threading
import time
import queue
import base64
import io
import argparse
import json
import ssl
import logging
from dotenv import load_dotenv
import os.path

# Try to import websockets with proper error handling
try:
    import websockets
except ImportError:
    print("ERROR: The 'websockets' package is not installed.")
    print("Please install it using: pip install websockets>=11.0.0")
    sys.exit(1)

import pyaudio

# PyObjC imports for macOS UI
import AppKit
import Foundation
import PyObjCTools.AppHelper
from objc import super

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    # Try loading from parent directory as fallback
    parent_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(parent_dotenv_path):
        load_dotenv(parent_dotenv_path)
    else:
        load_dotenv()  # Try default locations

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
FORMAT = pyaudio.paInt16
CHANNELS = 1
SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

# OpenAI API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-realtime-preview-2024-10-01")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "wss://api.openai.com/v1/realtime")
OPENAI_VOICE = os.getenv("OPENAI_VOICE", "alloy")

# Check if we have an API key
if not OPENAI_API_KEY:
    print("WARNING: No OpenAI API key found in environment variables or .env file.")
    print("The application will start, but you won't be able to use the OpenAI Realtime API.")
    print("Please set the OPENAI_API_KEY environment variable or add it to a .env file.")

# Replace the DEFAULT_INSTRUCTIONS constant with a function that reads from a file
def load_prompt_from_file():
    """Load the prompt from prompt.txt or return the default if file not found"""
    prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt.txt')
    default_prompt = """You are a helpful assistant providing real-time responses to the user's questions.
IMPORTANT: Do not respond until the user has asked a complete question or given a command.
Listen carefully to the user's voice input and only reply when they have finished speaking.
Keep your answers concise and relevant."""
    
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r') as f:
                prompt = f.read().strip()
            if prompt:  # Only use if not empty
                return prompt
        except Exception as e:
            print(f"Error reading prompt file: {e}")
    
    # Create the file with default prompt if it doesn't exist
    try:
        os.makedirs(os.path.dirname(prompt_path), exist_ok=True)
        with open(prompt_path, 'w') as f:
            f.write(default_prompt)
    except Exception as e:
        print(f"Error creating prompt file: {e}")
    
    return default_prompt

# Initialize PyAudio
pya = pyaudio.PyAudio()

# For Python versions < 3.11
if sys.version_info < (3, 11, 0):
    import taskgroup, exceptiongroup
    asyncio.TaskGroup = taskgroup.TaskGroup
    asyncio.ExceptionGroup = exceptiongroup.ExceptionGroup


class TransparentWindow(AppKit.NSWindow):
    """A transparent window with standard controls that floats above all apps."""
    
    def initWithContentRect_styleMask_backing_defer_(self, rect, style, backing, defer):
        # Use standard window style with title bar and controls, but still borderless
        super(TransparentWindow, self).initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskTitled |           # Add title bar
            AppKit.NSWindowStyleMaskClosable |         # Add close button
            AppKit.NSWindowStyleMaskMiniaturizable |   # Add minimize button
            AppKit.NSWindowStyleMaskResizable,         # Add resize controls
            backing,
            defer
        )
        
        self.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.setAlphaValue_(1.0)  # Set to 100% opacity (fully opaque)
        self.setOpaque_(False)
        self.setHasShadow_(True)  # Add shadow for better visibility
        self.setLevel_(AppKit.NSFloatingWindowLevel)  # Float above other windows
        self.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                   AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        
        # Set a title for the window
        self.setTitle_("OpenAI Realtime Overlay")
        
        # Make the title bar blend with the window
        self.setTitlebarAppearsTransparent_(True)
        
        # Set the title bar color to match the window background
        self.setTitleVisibility_(AppKit.NSWindowTitleHidden)  # Hide the title text
        
        # Use dark appearance for the window
        if hasattr(AppKit, 'NSAppearanceNameDarkAqua'):
            darkAppearance = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
            self.setAppearance_(darkAppearance)
        
        return self


class OverlayView(AppKit.NSView):
    """The main view for the overlay window."""
    
    def initWithFrame_(self, frame):
        super(OverlayView, self).initWithFrame_(frame)
        
        # Create a tab view
        self.tabView = AppKit.NSTabView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, frame.size.width, frame.size.height)
        )
        self.tabView.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        self.addSubview_(self.tabView)
        
        # Create the main tab
        mainTab = AppKit.NSTabViewItem.alloc().init()
        mainTab.setLabel_("Realtime")
        self.tabView.addTabViewItem_(mainTab)
        
        # Create the prompt tab
        promptTab = AppKit.NSTabViewItem.alloc().init()
        promptTab.setLabel_("Prompt")
        self.tabView.addTabViewItem_(promptTab)
        
        # Set up main tab view (conversation view)
        mainView = AppKit.NSView.alloc().initWithFrame_(self.tabView.contentRect())
        mainTab.setView_(mainView)
        
        # Create a scroll view to contain the text view for the main tab
        scrollView = AppKit.NSScrollView.alloc().initWithFrame_(mainView.bounds())
        scrollView.setHasVerticalScroller_(True)
        scrollView.setAutohidesScrollers_(True)
        scrollView.setBorderType_(AppKit.NSNoBorder)
        scrollView.setDrawsBackground_(False)
        
        # Create the text view for the main tab
        self.textView = AppKit.NSTextView.alloc().initWithFrame_(scrollView.contentView().bounds())
        self.textView.setEditable_(False)
        self.textView.setSelectable_(True)
        self.textView.setDrawsBackground_(False)
        self.textView.setFont_(AppKit.NSFont.fontWithName_size_("Helvetica", 18.0))
        self.textView.setTextColor_(AppKit.NSColor.whiteColor())
        self.textView.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        
        # Configure text container
        self.textView.textContainer().setLineFragmentPadding_(10.0)
        self.textView.textContainer().setWidthTracksTextView_(True)
        
        # Add text view to scroll view
        scrollView.setDocumentView_(self.textView)
        
        # Add scroll view to the main view
        mainView.addSubview_(scrollView)
        scrollView.setFrame_(mainView.bounds())
        scrollView.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        
        # Add transparency control buttons to main view
        self.addTransparencyControls(self)
        
        # Set up prompt tab view
        promptView = AppKit.NSView.alloc().initWithFrame_(self.tabView.contentRect())
        promptTab.setView_(promptView)
        
        # Create a scroll view for the prompt editor
        promptScrollView = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(10, 50, promptView.bounds().size.width - 20, promptView.bounds().size.height - 60)
        )
        promptScrollView.setHasVerticalScroller_(True)
        promptScrollView.setAutohidesScrollers_(True)
        promptScrollView.setBorderType_(AppKit.NSBezelBorder)  # Add border for better visibility
        promptScrollView.setDrawsBackground_(False)
        promptScrollView.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        
        # Create the prompt editor text view
        self.promptTextView = AppKit.NSTextView.alloc().initWithFrame_(promptScrollView.contentView().bounds())
        self.promptTextView.setEditable_(True)
        self.promptTextView.setSelectable_(True)
        self.promptTextView.setDrawsBackground_(True)
        self.promptTextView.setBackgroundColor_(AppKit.NSColor.darkGrayColor())
        self.promptTextView.setFont_(AppKit.NSFont.fontWithName_size_("Menlo", 14.0))
        self.promptTextView.setTextColor_(AppKit.NSColor.whiteColor())
        self.promptTextView.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        
        # Configure prompt text container
        self.promptTextView.textContainer().setLineFragmentPadding_(10.0)
        self.promptTextView.textContainer().setWidthTracksTextView_(True)
        
        # Add prompt text view to scroll view
        promptScrollView.setDocumentView_(self.promptTextView)
        
        # Add scroll view to the prompt view
        promptView.addSubview_(promptScrollView)
        
        # Add a "Save Prompt" button
        saveButton = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(10, 10, 120, 30)
        )
        saveButton.setTitle_("Save Prompt")
        saveButton.setBezelStyle_(AppKit.NSBezelStyleRounded)
        saveButton.setTarget_(self)
        saveButton.setAction_("savePrompt:")
        promptView.addSubview_(saveButton)
        
        # Add a label above the prompt editor
        promptLabel = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(10, promptView.bounds().size.height - 30, promptView.bounds().size.width - 20, 20)
        )
        promptLabel.setStringValue_("Edit the prompt used for the OpenAI Realtime session:")
        promptLabel.setEditable_(False)
        promptLabel.setSelectable_(False)
        promptLabel.setDrawsBackground_(False)
        promptLabel.setBezeled_(False)
        promptLabel.setTextColor_(AppKit.NSColor.whiteColor())
        promptLabel.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        promptView.addSubview_(promptLabel)
        
        # Load the initial prompt text
        self.loadPromptText()
        
        return self
    
    def loadPromptText(self):
        """Load the prompt text from file into the prompt editor"""
        prompt = load_prompt_from_file()
        if hasattr(self, 'promptTextView'):
            self.promptTextView.setString_(prompt)
    
    def savePrompt_(self, sender):
        """Save the prompt text to file"""
        if hasattr(self, 'promptTextView'):
            prompt_text = self.promptTextView.string()
            prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt.txt')
            try:
                with open(prompt_path, 'w') as f:
                    f.write(prompt_text)
                # Flash the button to indicate success
                sender.setTitle_("Saved!")
                def restore_title():
                    sender.setTitle_("Save Prompt")
                # Schedule title restoration after 1 second
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0, self, "restoreButtonTitle:", sender, False
                )
            except Exception as e:
                # Show error in the UI
                AppKit.NSBeep()
                sender.setTitle_(f"Error: {str(e)}")
                # Schedule title restoration after 3 seconds
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    3.0, self, "restoreButtonTitle:", sender, False
                )
    
    def restoreButtonTitle_(self, timer):
        """Restore the button title after temporarily changing it"""
        button = timer.userInfo()
        if button:
            button.setTitle_("Save Prompt")

    def drawRect_(self, rect):
        # Draw a semi-transparent background
        bgColor = AppKit.NSColor.blackColor().colorWithAlphaComponent_(0.5)
        bgColor.set()
        
        # Use rounded corners for a nicer look
        cornerRadius = 10.0
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, cornerRadius, cornerRadius)
        path.fill()
    
    def appendText_(self, text):
        # Append text to the text view
        if not text:
            return
            
        # Fix: Create attributes dictionary correctly
        attributes = AppKit.NSDictionary.dictionaryWithObjects_forKeys_(
            [AppKit.NSColor.whiteColor(), AppKit.NSFont.fontWithName_size_("Helvetica", 18.0)],
            [AppKit.NSForegroundColorAttributeName, AppKit.NSFontAttributeName]
        )
        
        attrString = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            text,
            attributes
        )
        
        self.textView.textStorage().appendAttributedString_(attrString)
        self.textView.scrollRangeToVisible_(AppKit.NSMakeRange(self.textView.string().length(), 0))

    def addTransparencyControls(self, parentView=None):
        """Add transparency controls to the specified view or self if none provided."""
        # If no parent view provided, use self
        if parentView is None:
            parentView = self
        
        # Create a container for the buttons
        controlsHeight = 30
        controlsWidth = 200  # Wider to accommodate more buttons
        controlsFrame = Foundation.NSMakeRect(
            parentView.bounds().size.width - controlsWidth - 10,
            10,
            controlsWidth,
            controlsHeight
        )
        
        controlsView = AppKit.NSView.alloc().initWithFrame_(controlsFrame)
        controlsView.setAutoresizingMask_(AppKit.NSViewMinXMargin | AppKit.NSViewMaxYMargin)
        parentView.addSubview_(controlsView)
        
        # Add decrease opacity button
        decreaseButton = AppKit.NSButton.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, 30, controlsHeight)
        )
        decreaseButton.setTitle_("-")
        decreaseButton.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.decreaseButton = decreaseButton
        controlsView.addSubview_(decreaseButton)
        
        # Add increase opacity button
        increaseButton = AppKit.NSButton.alloc().initWithFrame_(
            Foundation.NSMakeRect(40, 0, 30, controlsHeight)
        )
        increaseButton.setTitle_("+")
        increaseButton.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.increaseButton = increaseButton
        controlsView.addSubview_(increaseButton)
        
        # Add start session button
        startButton = AppKit.NSButton.alloc().initWithFrame_(
            Foundation.NSMakeRect(80, 0, 50, controlsHeight)
        )
        startButton.setTitle_("Start")
        startButton.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.startButton = startButton
        controlsView.addSubview_(startButton)
        
        # Add stop session button
        stopButton = AppKit.NSButton.alloc().initWithFrame_(
            Foundation.NSMakeRect(140, 0, 50, controlsHeight)
        )
        stopButton.setTitle_("Stop")
        stopButton.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.stopButton = stopButton
        controlsView.addSubview_(stopButton)

    def setupButtonTargets_(self, delegate):
        """Set up the button targets after the delegate is available."""
        if hasattr(self, 'decreaseButton'):
            self.decreaseButton.setTarget_(delegate)
            self.decreaseButton.setAction_("decreaseOpacity:")
        
        if hasattr(self, 'increaseButton'):
            self.increaseButton.setTarget_(delegate)
            self.increaseButton.setAction_("increaseOpacity:")
        
        if hasattr(self, 'startButton'):
            self.startButton.setTarget_(delegate)
            self.startButton.setAction_("startOpenAISession:")
        
        if hasattr(self, 'stopButton'):
            self.stopButton.setTarget_(delegate)
            self.stopButton.setAction_("stopOpenAISession:")


class AppDelegate(AppKit.NSObject):
    """The application delegate that handles app lifecycle and keyboard shortcuts."""
    
    def init(self):
        self = super(AppDelegate, self).init()
        if self is None:
            return None
            
        # Create a window
        screenRect = AppKit.NSScreen.mainScreen().frame()
        windowWidth = 1000
        windowHeight = 900
        windowRect = Foundation.NSMakeRect(
            (screenRect.size.width - windowWidth) / 2,
            (screenRect.size.height - windowHeight) / 2,
            windowWidth,
            windowHeight
        )
        
        # Use the correct style mask that matches TransparentWindow class
        self.window = TransparentWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            windowRect,
            AppKit.NSWindowStyleMaskTitled |
            AppKit.NSWindowStyleMaskClosable |
            AppKit.NSWindowStyleMaskMiniaturizable |
            AppKit.NSWindowStyleMaskResizable,
            AppKit.NSBackingStoreBuffered,
            False
        )
        
        # Create the content view
        self.overlayView = OverlayView.alloc().initWithFrame_(self.window.contentView().bounds())
        self.window.setContentView_(self.overlayView)
        
        # Set up the message queue for communication between threads
        self.message_queue = queue.Queue()
        
        # Flag to track if OpenAI session is running
        self.openai_running = False
        self.openai_thread = None
        
        # Register for global keyboard events
        self.setupKeyboardShortcuts()
        
        # Start a timer to check for new messages
        self.timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1,  # Check every 100ms
            self,
            "checkMessages:",
            None,
            True
        )
        
        # Create status bar item
        self.setupStatusBar()
        
        # Set this object as the window delegate to handle window events
        self.window.setDelegate_(self)
        
        # Now that the delegate is set, configure the button targets
        self.overlayView.setupButtonTargets_(self)
        
        return self
    
    def applicationDidFinishLaunching_(self, notification):
        self.window.makeKeyAndOrderFront_(None)
        self.window.setLevel_(AppKit.NSFloatingWindowLevel)
        
        # Add a welcome message
        self.overlayView.appendText_("🎙️ OpenAI Realtime API Overlay\n")
        self.overlayView.appendText_("Click 'Start' to begin listening...\n\n")
        
        # Check if API key is available
        if not OPENAI_API_KEY:
            self.overlayView.appendText_("⚠️ No OpenAI API key found. Please set the OPENAI_API_KEY environment variable.\n")
        
        # Register for keyboard notifications
        notificationCenter = AppKit.NSNotificationCenter.defaultCenter()
        notificationCenter.addObserver_selector_name_object_(
            self,
            "handleKeyEvent:",
            AppKit.NSWindowDidBecomeKeyNotification,
            self.window
        )
        
        # Make the window the first responder to receive keyboard events
        self.window.makeFirstResponder_(self.overlayView)
    
    def setupKeyboardShortcuts(self):
        # Register for global keyboard events using the event tap
        # Use NSEventMaskKeyDown | NSEventMaskFlagsChanged to catch modifier key changes too
        self.eventTap = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown,
            self.handleKeyDown_
        )
        
        # Also add a local monitor for the window's own keyboard events
        # This is more reliable for keyboard shortcuts when the window is active
        self.localEventTap = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown,
            self.handleLocalKeyDown_
        )
    
    def handleKeyDown_(self, event):
        # Check for our keyboard shortcuts
        flags = event.modifierFlags()
        cmd_shift = (flags & AppKit.NSEventModifierFlagCommand) and (flags & AppKit.NSEventModifierFlagShift)
        
        if not cmd_shift:
            return
            
        key = event.charactersIgnoringModifiers()
        
        if key == "h":  # Cmd+Shift+H to toggle visibility
            if self.window.isVisible():
                self.window.orderOut_(None)
            else:
                self.window.makeKeyAndOrderFront_(None)
                
        elif key == "=":  # Cmd+Shift++ to increase size
            frame = self.window.frame()
            newFrame = Foundation.NSMakeRect(
                frame.origin.x - 25,
                frame.origin.y - 25,
                frame.size.width + 50,
                frame.size.height + 50
            )
            self.window.setFrame_display_animate_(newFrame, True, True)
            
        elif key == "-":  # Cmd+Shift+- to decrease size
            frame = self.window.frame()
            newFrame = Foundation.NSMakeRect(
                frame.origin.x + 25,
                frame.origin.y + 25,
                frame.size.width - 50,
                frame.size.height - 50
            )
            self.window.setFrame_display_animate_(newFrame, True, True)
            
        elif key == "q":  # Cmd+Shift+Q to quit
            AppKit.NSApplication.sharedApplication().terminate_(None)
            
        elif key == "p":  # Cmd+Shift+P to toggle presentation mode
            self.togglePresentationMode_(self)
    
    def handleLocalKeyDown_(self, event):
        # This handles keyboard events when our window is active
        flags = event.modifierFlags()
        cmd_shift = (flags & AppKit.NSEventModifierFlagCommand) and (flags & AppKit.NSEventModifierFlagShift)
        
        if cmd_shift:
            key = event.charactersIgnoringModifiers()
            
            if key == "t":  # Cmd+Shift+T to decrease opacity
                current_alpha = self.window.alphaValue()
                new_alpha = max(0.2, current_alpha - 0.1)
                self.window.setAlphaValue_(new_alpha)
                self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")
                return None  # Consume the event
            
            elif key == "y":  # Cmd+Shift+Y to increase opacity
                current_alpha = self.window.alphaValue()
                new_alpha = min(1.0, current_alpha + 0.1)
                self.window.setAlphaValue_(new_alpha)
                self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")
                return None  # Consume the event
        
        # For other keys, pass the event through
        return event
    
    def checkMessages_(self, timer):
        # Check for new messages from the OpenAI thread
        try:
            while True:
                message = self.message_queue.get_nowait()
                
                # Use performSelectorOnMainThread to safely update UI
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "updateUIWithMessage:",
                    message,
                    False
                )
                
        except queue.Empty:
            pass
    
    def updateUIWithMessage_(self, message):
        # Update the UI with a new message
        self.overlayView.appendText_(message)
    
    def run_openai_loop(self):
        # Run the asyncio event loop in this thread
        self.message_queue.put("🔄 Initializing OpenAI session...")
        try:
            # Check if API key is available
            if not OPENAI_API_KEY:
                self.message_queue.put("❌ ERROR: OpenAI API key is missing. Please set the OPENAI_API_KEY environment variable.")
                self.openai_running = False
                return
                
            # Verify API key format
            if not OPENAI_API_KEY.startswith("sk-") or len(OPENAI_API_KEY) < 20:
                self.message_queue.put("⚠️ Warning: Your API key doesn't look like a standard OpenAI key.")
                self.message_queue.put("It should start with 'sk-' and be at least 20 characters long.")
                self.message_queue.put("Continuing anyway, but may fail to connect...")
                
            self.message_queue.put("🔄 Starting asyncio event loop...")
            asyncio.run(self.openai_main())
        except Exception as e:
            import traceback
            error_text = traceback.format_exc()
            error_msg = f"⚠️ Critical error in OpenAI thread: {str(e)}\n{error_text}"
            self.message_queue.put(error_msg)
            
            # Add more details for specific errors
            if "ssl" in str(e).lower() or "certificate" in str(e).lower():
                self.message_queue.put("This may be an SSL certificate issue. Check your network connection.")
            elif "connection" in str(e).lower():
                self.message_queue.put("This appears to be a connection issue. Check your internet connection.")
            elif "unauthorized" in str(e).lower() or "authentication" in str(e).lower() or "api key" in str(e).lower():
                self.message_queue.put("This appears to be an authentication issue. Verify your OpenAI API key.")
            
            # Log to console as well for easier debugging
            print(error_msg)
        finally:
            self.openai_running = False
            self.message_queue.put("Session initialization has stopped. Please try again.")
            
    async def openai_main(self):
        """Main entry point for the OpenAI Realtime API."""
        self.message_queue.put("Creating OpenAI Realtime Loop...")
        audio_loop = OpenAIRealtimeLoop(self.message_queue)
        
        while self.openai_running:
            try:
                self.message_queue.put("🔄 Starting a new OpenAI Realtime API session...")
                await audio_loop.run(self)  # Pass self to check running state
            except asyncio.CancelledError:
                self.message_queue.put("Session was cancelled.")
                break
            except websockets.ConnectionClosed as e:
                error_msg = f"⚠️ WebSocket connection closed: {str(e)}"
                self.message_queue.put(error_msg)
                if self.openai_running:  # Only reconnect if still running
                    self.message_queue.put("🔁 Reconnecting in 3 seconds...")
                    await asyncio.sleep(3)
                else:
                    break
            except Exception as e:
                error_msg = f"⚠️ Error: {str(e)}"
                self.message_queue.put(error_msg)
                import traceback
                self.message_queue.put(f"Details: {traceback.format_exc()}")
                
                if self.openai_running:  # Only reconnect if still running
                    self.message_queue.put("🔁 Reconnecting in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    break
    
    def setupStatusBar(self):
        """Set up the status bar icon and menu."""
        self.statusItem = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        
        # Set the status bar icon
        self.statusItem.setTitle_("🎙️")
        
        # Create the menu
        menu = AppKit.NSMenu.alloc().init()
        
        # Add menu items
        showItem = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show/Hide OpenAI Overlay", "toggleWindow:", "")
        menu.addItem_(showItem)
        
        # Add presentation mode toggle
        self.presentationModeItem = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "✓ Hide During Screen Sharing", "togglePresentationMode:", "")
        self.presentationModeItem.setState_(AppKit.NSControlStateValueOn)  # Default to on
        menu.addItem_(self.presentationModeItem)
        
        # Add transparency submenu
        transparencyMenu = AppKit.NSMenu.alloc().init()
        
        for level in [20, 40, 60, 80, 100]:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"{level}% Opacity", "setTransparency:", "")
            item.setRepresentedObject_(level)
            transparencyMenu.addItem_(item)
        
        transparencyItem = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Transparency", "", "")
        transparencyItem.setSubmenu_(transparencyMenu)
        menu.addItem_(transparencyItem)
        
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        
        quitItem = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "")
        menu.addItem_(quitItem)
        
        # Set the menu
        self.statusItem.setMenu_(menu)
        
        # Enable presentation mode by default
        self.togglePresentationMode_(None)
    
    def toggleWindow_(self, sender):
        """Toggle the window visibility."""
        if self.window.isVisible():
            self.window.orderOut_(None)
        else:
            self.window.makeKeyAndOrderFront_(None)

    def togglePresentationMode_(self, sender):
        """Toggle whether the window is visible during screen sharing."""
        if sender is not None:  # Only toggle state if called from menu
            currentState = self.presentationModeItem.state()
            newState = AppKit.NSControlStateValueOff if currentState == AppKit.NSControlStateValueOn else AppKit.NSControlStateValueOn
            self.presentationModeItem.setState_(newState)
        
        # Get current state
        hideInScreenSharing = self.presentationModeItem.state() == AppKit.NSControlStateValueOn
        
        if hideInScreenSharing:
            # Make window invisible during screen sharing
            # Use a combination of settings that ensure the window won't appear in recordings
            
            # 1. Set the window level to a background level
            self.window.setLevel_(AppKit.NSNormalWindowLevel - 1)
            
            # 2. Set the window to be excluded from window lists
            self.window.setExcludedFromWindowsMenu_(True)
            
            # 3. Set the window to be non-activating
            self.window.setCanHide_(True)
            
            # 4. Set the window to be transparent during screen capture
            # This is the most important setting for screen sharing
            self.window.setSharingType_(AppKit.NSWindowSharingNone)
            
            # 5. Set appropriate collection behavior
            self.window.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | 
                AppKit.NSWindowCollectionBehaviorTransient |
                AppKit.NSWindowCollectionBehaviorIgnoresCycle
            )
            
            # Update menu text
            self.presentationModeItem.setTitle_("✓ Hide During Screen Sharing")
        else:
            # Make window visible during screen sharing
            self.window.setLevel_(AppKit.NSFloatingWindowLevel)
            self.window.setExcludedFromWindowsMenu_(False)
            self.window.setCanHide_(False)
            self.window.setSharingType_(AppKit.NSWindowSharingReadOnly)
            self.window.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | 
                AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            
            # Update menu text
            self.presentationModeItem.setTitle_("Hide During Screen Sharing")

    def applicationWillTerminate_(self, notification):
        """Clean up resources when the application is about to terminate."""
        # Stop the event taps for keyboard monitoring
        if hasattr(self, 'eventTap') and self.eventTap:
            AppKit.NSEvent.removeMonitor_(self.eventTap)
        
        if hasattr(self, 'localEventTap') and self.localEventTap:
            AppKit.NSEvent.removeMonitor_(self.localEventTap)
        
        # Clean up audio resources
        if hasattr(self, 'openai_thread') and self.openai_thread.is_alive():
            # Signal the thread to stop
            self.message_queue.put("QUIT_SIGNAL")
            
            # Give it a moment to clean up
            self.openai_thread.join(0.5)
        
        # Log termination
        print("Application terminated")

    def windowWillClose_(self, notification):
        """Handle window close event."""
        # When the window is closed with the close button, quit the application
        AppKit.NSApplication.sharedApplication().terminate_(None)
        return True

    def setTransparency_(self, sender):
        """Set the window transparency from menu selection."""
        level = sender.representedObject()
        if level is not None:
            opacity = level / 100.0
            self.window.setAlphaValue_(opacity)
            self.message_queue.put(f"Transparency set to {level}%")

    def handleKeyEvent_(self, notification):
        # This method is called when the window becomes key (active)
        # We'll use it to set up a monitor for key events
        AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown,
            self.processKeyEvent_
        )

    def processKeyEvent_(self, event):
        # Process keyboard events
        flags = event.modifierFlags()
        cmd_shift = (flags & AppKit.NSEventModifierFlagCommand) and (flags & AppKit.NSEventModifierFlagShift)
        
        if cmd_shift:
            key = event.charactersIgnoringModifiers()
            
            if key == "t":  # Cmd+Shift+T to decrease opacity
                current_alpha = self.window.alphaValue()
                new_alpha = max(0.2, current_alpha - 0.1)
                self.window.setAlphaValue_(new_alpha)
                self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")
                return None  # Consume the event
            
            elif key == "y":  # Cmd+Shift+Y to increase opacity
                current_alpha = self.window.alphaValue()
                new_alpha = min(1.0, current_alpha + 0.1)
                self.window.setAlphaValue_(new_alpha)
                self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")
                return None  # Consume the event
        
        # For other keys, pass the event through
        return event

    def decreaseOpacity_(self, sender):
        """Decrease the window opacity."""
        current_alpha = self.window.alphaValue()
        new_alpha = max(0.2, current_alpha - 0.1)
        self.window.setAlphaValue_(new_alpha)
        self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")

    def increaseOpacity_(self, sender):
        """Increase the window opacity."""
        current_alpha = self.window.alphaValue()
        new_alpha = min(1.0, current_alpha + 0.1)
        self.window.setAlphaValue_(new_alpha)
        self.message_queue.put(f"Transparency set to {int(new_alpha * 100)}%")

    def startOpenAISession_(self, sender):
        """Start the OpenAI session."""
        if self.openai_running:
            self.overlayView.appendText_("⚠️ Session already running\n")
            return
        
        # Check for API key
        if not OPENAI_API_KEY:
            self.overlayView.appendText_("⚠️ No OpenAI API key found. Please set the OPENAI_API_KEY environment variable.\n")
            return
        
        # Clean up any existing thread
        if self.openai_thread and self.openai_thread.is_alive():
            self.openai_running = False
            self.overlayView.appendText_("Cleaning up previous session...\n")
            try:
                self.openai_thread.join(2.0)  # Give more time to clean up
            except:
                pass
        
        # Clear the view for a clean start
        self.clearTextView_(None)
        
        self.overlayView.appendText_("🚀 Starting OpenAI session...\n")
        
        self.openai_running = True
        self.openai_thread = threading.Thread(target=self.run_openai_loop)
        self.openai_thread.daemon = True
        self.openai_thread.start()
        
    def clearTextView_(self, sender):
        """Clear the text view - safe to call from main thread."""
        if hasattr(self, 'overlayView') and hasattr(self.overlayView, 'textView'):
            self.overlayView.textView.setString_("")
            self.overlayView.appendText_("🎙️ OpenAI Realtime API Overlay\n")
            self.overlayView.appendText_("Session starting...\n\n")

    def stopOpenAISession_(self, sender):
        """Stop the OpenAI session."""
        if not self.openai_running:
            self.message_queue.put("⚠️ No active session to stop")
            return
        
        self.message_queue.put("🛑 Stopping OpenAI session...")
        self.openai_running = False
        
        # Put a stop signal in the queue that the audio loop will check for
        self.message_queue.put("STOP_SESSION")
        
        # Clean up audio resources
        if hasattr(self, 'openai_thread') and self.openai_thread:
            try:
                # Give the thread a moment to clean up
                self.openai_thread.join(1.0)  # Increased timeout to ensure cleanup
            except:
                pass
        
        self.message_queue.put("✅ Session stopped and audio resources cleaned up")


class OpenAIRealtimeLoop:
    def __init__(self, message_queue):
        self.message_queue = message_queue
        self.ws = None
        self.audio_stream = None
        self.running = True
        self.tasks = []
        
        # Create SSL context
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        self.response_started = False
        self.current_text_response = ''
        
        # VAD Configuration
        self.vad_config = {
            "type": "server_vad",
            "threshold": 0.6,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 600
        }
        
        # Load prompt from file (will be updated before connecting)
        self.prompt = load_prompt_from_file()
        
        # Session configuration
        self.session_config = {
            "modalities": ["text"],
            "instructions": self.prompt,  # Use the loaded prompt
            "voice": OPENAI_VOICE,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": self.vad_config,
            "temperature": 0.6
        }

    async def connect(self):
        """Connect to the WebSocket server."""
        self.message_queue.put("🔄 Connecting to OpenAI Realtime API...")
        
        # Reload the prompt from file in case it has been updated
        self.prompt = load_prompt_from_file()
        self.session_config["instructions"] = self.prompt
        
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        try:
            # Direct connection approach like your working example
            self.ws = await websockets.connect(
                f"{OPENAI_BASE_URL}?model={OPENAI_MODEL}",
                ssl=self.ssl_context,
                additional_headers=headers
            )
            self.message_queue.put("✅ Connected to OpenAI Realtime API")
            
            # Configure session
            await self.ws.send(json.dumps({
                "type": "session.update",
                "session": self.session_config
            }))
            
            # Initialize conversation
            await self.ws.send(json.dumps({"type": "response.create"}))
            return True
        except Exception as e:
            self.message_queue.put(f"❌ Error connecting to OpenAI: {str(e)}")
            import traceback
            self.message_queue.put(f"Details: {traceback.format_exc()}")
            return False
    
    async def receive_events(self):
        """Process events using async for loop like working example"""
        if not self.ws:
            self.message_queue.put("⚠️ WebSocket not connected")
            return
            
        try:
            # Using the direct approach from your working example
            async for message in self.ws:
                if not self.running:
                    break
                
                event = json.loads(message)
                event_type = event.get("type")
                
                # Handle events directly instead of passing to another method
                if event_type == "error":
                    error_msg = f"Error event: {event['error']['message']}"
                    self.message_queue.put(f"\n❌ {error_msg}\n")
                
                elif event_type == "response.text.delta":
                    text_delta = event["delta"]
                    
                    if not self.response_started:
                        self.message_queue.put("\n[OpenAI]: ")
                        self.response_started = True
                    
                    # Send text through the message queue
                    self.message_queue.put(text_delta)
                    self.current_text_response += text_delta
                
                elif event_type == "response.done":
                    self.message_queue.put("\n------------ End of response ------------\n")
                    self.current_text_response = ''
                    self.response_started = False
                
                elif event_type == "turn_detected.start":
                    self.message_queue.put("\n🎤 Speech detected...\n")
                
                elif event_type == "turn_detected.end":
                    self.message_queue.put("\n🔄 Processing your query...\n")
                    # Create a new response after turn ended
                    await self.ws.send(json.dumps({"type": "response.create"}))
                
        except websockets.ConnectionClosed as e:
            self.message_queue.put(f"\n⚠️ WebSocket connection closed: {e}\n")
        except Exception as e:
            self.message_queue.put(f"\n⚠️ Error in event processing: {str(e)}\n")
            import traceback
            self.message_queue.put(f"Details: {traceback.format_exc()}")
    
    async def listen_audio(self):
        """Capture audio from BlackHole 16ch to listen to meeting audio"""
        try:
            # Look for BlackHole device instead of default microphone
            blackhole_device_index = None
            blackhole_device_name = "BlackHole 16ch"
            
            # List all available audio devices to find BlackHole
            info = pya.get_host_api_info_by_index(0)
            num_devices = info.get('deviceCount')
            
            for i in range(0, num_devices):
                device_info = pya.get_device_info_by_host_api_device_index(0, i)
                device_name = device_info.get('name')
                self.message_queue.put(f"Found audio device: {device_name}")
                
                if blackhole_device_name.lower() in device_name.lower() and device_info.get('maxInputChannels') > 0:
                    blackhole_device_index = i
                    self.message_queue.put(f"✅ Found BlackHole input device: {device_name}")
                    break
            
            # If BlackHole not found, fall back to default device
            if blackhole_device_index is None:
                self.message_queue.put("⚠️ BlackHole 16ch not found, using default input device")
                blackhole_device_index = pya.get_default_input_device_info()["index"]
                device_info = pya.get_device_info_by_host_api_device_index(0, blackhole_device_index)
            else:
                self.message_queue.put(f"✅ Using BlackHole 16ch as input to capture meeting audio")
            
            # Open audio stream using BlackHole
            self.audio_stream = pya.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=blackhole_device_index,
                frames_per_buffer=CHUNK_SIZE
            )
            
            self.message_queue.put(f"🎤 Audio capture initialized successfully")
            self.message_queue.put("Listening to meeting audio from Chrome/Zoom...")
            
            # Read audio data in a loop
            while self.running:
                try:
                    # Read directly from BlackHole
                    data = self.audio_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    # Only send when WebSocket is connected
                    if self.ws:
                        # Send audio data to OpenAI
                        base64_chunk = base64.b64encode(data).decode('utf-8')
                        await self.ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64_chunk
                        }))
                    
                    # Short sleep to avoid overloading
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    self.message_queue.put(f"Error reading audio: {str(e)}")
                    await asyncio.sleep(0.5)  # Pause on error
        
        except Exception as e:
            self.message_queue.put(f"⚠️ Error in audio capture: {str(e)}")
            import traceback
            self.message_queue.put(f"Details: {traceback.format_exc()}")
        finally:
            self.cleanup_audio()
    
    async def start_session(self, delegate):
        try:
            self.running = True
            
            # List available audio devices
            self.message_queue.put("Checking available audio devices...")
            device_list = self.list_audio_devices()
            for device in device_list:
                self.message_queue.put(device)
            
            # Connect to WebSocket directly
            if not await self.connect():
                self.message_queue.put("Failed to connect to OpenAI API")
                return
            
            self.message_queue.put("🎙️ Listening for meeting audio...")
            
            # Start audio and event handling as separate tasks
            async with asyncio.TaskGroup() as tg:
                listen_task = tg.create_task(self.listen_audio())
                receive_task = tg.create_task(self.receive_events())
                stop_check_task = tg.create_task(self.check_stop_signal(delegate))
                
                # Wait for any task to complete
                try:
                    await asyncio.gather(listen_task, receive_task, stop_check_task)
                except asyncio.CancelledError:
                    self.message_queue.put("Tasks cancelled")
                    raise
        except Exception as e:
            self.message_queue.put(f"⚠️ Error in session: {str(e)}")
            import traceback
            self.message_queue.put(f"Details: {traceback.format_exc()}")
        finally:
            await self.cleanup_all()
    
    async def check_stop_signal(self, delegate):
        while self.running:
            if not delegate.openai_running:
                self.running = False
                return
            await asyncio.sleep(0.2)
    
    async def run(self, delegate):
        while delegate.openai_running:
            try:
                await self.start_session(delegate)
                if not delegate.openai_running:
                    break
                print("Session ended, reconnecting...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Error in session: {str(e)}")
                if not delegate.openai_running:
                    break
                print("Reconnecting...")
                await asyncio.sleep(3)

    def cleanup_audio(self):
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            except:
                pass

    async def cleanup_all(self):
        self.running = False
        
        # Close WebSocket
        if self.ws:
            try:
                await self.ws.close()
                self.ws = None
            except:
                pass
        
        # Clean up audio resources
        self.cleanup_audio()
        
    def list_audio_devices(self):
        """List all available audio input and output devices"""
        device_list = []
        info = pya.get_host_api_info_by_index(0)
        num_devices = info.get('deviceCount')
        
        for i in range(0, num_devices):
            try:
                device_info = pya.get_device_info_by_host_api_device_index(0, i)
                device_name = device_info.get('name')
                max_input = device_info.get('maxInputChannels')
                max_output = device_info.get('maxOutputChannels')
                
                status = []
                if max_input > 0:
                    status.append("input")
                if max_output > 0:
                    status.append("output")
                
                description = f"Device {i}: {device_name} ({', '.join(status)})"
                device_list.append(description)
                
            except Exception:
                pass
        
        return device_list


def main():
    # Verify API key is available
    if not OPENAI_API_KEY:
        print("Warning: OPENAI_API_KEY environment variable is not set.")
        print("The application will start, but you won't be able to use the OpenAI Realtime API.")
        print("Please set the OPENAI_API_KEY environment variable or use a .env file.")
    else:
        # Test the OpenAI connection in a background thread
        threading.Thread(target=test_openai_connection).start()
    
    # Create and run the application
    app = AppKit.NSApplication.sharedApplication()
    
    # Set the activation policy to accessory to hide from Dock
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    
    # Add a welcome message
    delegate.overlayView.appendText_("🎙️ OpenAI Realtime API Overlay\n")
    delegate.overlayView.appendText_("Click 'Start' to begin listening...\n\n")
    
    PyObjCTools.AppHelper.runEventLoop()

def test_openai_connection():
    """Test the connection to OpenAI to verify API key works."""
    try:
        import requests
        # Test basic API connectivity
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
        )
        if response.status_code == 200:
            print("✅ OpenAI API connection test successful. API key is valid.")
            return True
        else:
            print(f"❌ OpenAI API connection test failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error testing OpenAI API connection: {e}")
        return False


if __name__ == "__main__":
    main() 