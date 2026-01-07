"""
Log window utility: popup a Tkinter window that live-streams logs and print output.

Features:
- Root logger configured with console + GUI handlers
- Redirects print (stdout/stderr) to logger so all output shows in both places
- Non-blocking GUI runs in a background thread
"""

from __future__ import annotations

import io
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional
import os
import multiprocessing

try:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
except Exception:  # pragma: no cover - tkinter might be missing in some envs
    tk = None
    ScrolledText = None  # type: ignore


class QueueHandler(logging.Handler):
    """Logging handler that sends records to a thread-safe queue."""

    def __init__(self, log_queue: queue.Queue[str]):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.log_queue.put_nowait(msg)
        except Exception:  # pragma: no cover
            self.handleError(record)


class _BufferedRedirect(io.TextIOBase):
    """
    Redirector that buffers writes until newline and forwards to a logger.
    This replaces sys.stdout/sys.stderr so print() also shows in the GUI.
    """

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self._buffer: list[str] = []

    def write(self, s) -> int:  # type: ignore[override]
        # Accept both str and bytes; decode bytes to str
        if s is None:
            return 0
        if isinstance(s, (bytes, bytearray)):
            try:
                s = s.decode('utf-8', errors='replace')
            except Exception:
                s = str(s)

        if not s:
            return 0

        self._buffer.append(s)
        if "\n" in s:
            text = "".join(self._buffer)
            self._buffer.clear()
            for line in text.splitlines():
                if line.strip():
                    self.logger.log(self.level, line)
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        if self._buffer:
            # Ensure buffer contains text
            text = "".join(self._buffer)
            self._buffer.clear()
            if isinstance(text, (bytes, bytearray)):
                try:
                    text = text.decode('utf-8', errors='replace')
                except Exception:
                    text = str(text)
            if text.strip():
                self.logger.log(self.level, text)


@dataclass
class GuiLoggerWindow:
    log_queue: queue.Queue[str]
    title: str = "FIEngine Logs"
    max_lines: int = 5000
    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = threading.Event()

    def start(self) -> None:
        if tk is None:
            return  # Tkinter not available; fail gracefully
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_gui, name="LogWindow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    # GUI thread
    def _run_gui(self) -> None:  # pragma: no cover - requires GUI
        root = tk.Tk()
        root.title(self.title)
        # Reasonable default size; users can resize
        root.geometry("900x500")

        # Try to ensure the window is visible / in front on Windows
        try:
            root.update_idletasks()
            root.deiconify()
            root.lift()
            # Temporarily make topmost so it appears above other windows, then clear the flag
            try:
                root.attributes("-topmost", True)
                root.after(700, lambda: root.attributes("-topmost", False))
            except Exception:
                # Some systems may not support attributes; ignore
                pass
        except Exception:
            # If any of these fail, continue; window may still appear normally
            pass

        text = ScrolledText(root, state="disabled", wrap="word")
        text.pack(fill="both", expand=True)

        # Style tags
        text.tag_config("INFO", foreground="#DDE6F7")
        text.tag_config("DEBUG", foreground="#A0AEC0")
        text.tag_config("WARNING", foreground="#ECC94B")
        text.tag_config("ERROR", foreground="#F56565")
        text.tag_config("CRITICAL", foreground="#FFFFFF", background="#E53E3E")

        # Dark background
        text.configure(background="#1A202C")

        def poll_queue() -> None:
            if self._stop_event.is_set():
                try:
                    root.destroy()
                except Exception:
                    pass
                return
            try:
                while True:
                    msg = self.log_queue.get_nowait()
                    self._append(text, msg)
            except queue.Empty:
                pass
            root.after(100, poll_queue)

        root.after(100, poll_queue)
        try:
            root.mainloop()
        except Exception:
            # Avoid crashing the app if GUI loop errors
            pass

    @staticmethod
    def _append(widget, msg: str) -> None:  # pragma: no cover - GUI
        # Try infer level from prefix like "INFO:" etc.
        level_tag = "INFO"
        upper = msg.upper()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            if upper.startswith(level):
                level_tag = level
                break

        widget.configure(state="normal")
        widget.insert("end", msg + "\n", level_tag)
        # Trim lines to keep memory in check
        lines = int(widget.index('end-1c').split('.')[0])
        if lines > 6000:
            try:
                widget.delete('1.0', f"{lines - 5000}.0")
            except Exception:
                pass
        widget.see("end")
        widget.configure(state="disabled")


# Global variables to ensure singleton behavior
_logging_initialized = False
_gui_window = None
_creator_pid = None  # PID of the process that created the GUI


def setup_logging(show_window: bool = True, level: int = logging.INFO):
    """
    Configure root logging with console + GUI, and redirect print to logger.
    Uses singleton pattern to ensure only one log window is created.

    Returns a tuple: (logger, gui_window)
    """
    global _logging_initialized, _gui_window, _creator_pid
    
    logger = logging.getLogger()
    
    # If already initialized, just return the existing setup
    if _logging_initialized:
        # If already initialized in this process, optionally bring the window to front
        if show_window and _gui_window and tk is not None:
            try:
                # Send a small message so the poll loop triggers and window comes to front
                _gui_window.log_queue.put_nowait("INFO: Logging already initialized")
            except Exception:
                pass
        return logger, _gui_window
    
    logger.setLevel(level)

    # Clear any existing handlers to prevent conflicts
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Add console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Mute noisy HTTP access logs (Werkzeug / Flask dev server)
    for noisy_name in (
        "werkzeug",
        "werkzeug.serving",
        "werkzeug._internal",
        "urllib3.connectionpool",
    ):
        try:
            nl = logging.getLogger(noisy_name)
            nl.setLevel(logging.WARNING)
            # Prevent double propagation to root at INFO level
            nl.propagate = True
        except Exception:
            pass

    # Only the creator (main) process should create a GUI window.
    # On Windows, child processes get 'spawn' start method and would re-run imports.
    current_pid = os.getpid()
    is_main_process = (multiprocessing.current_process().name == 'MainProcess')

    if show_window and tk is not None and is_main_process:
        log_q: queue.Queue[str] = queue.Queue(maxsize=10000)
        gui_handler = QueueHandler(log_q)
        gui_handler.setLevel(level)
        gui_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(gui_handler)

        _gui_window = GuiLoggerWindow(log_q)
        _gui_window.start()
        _creator_pid = current_pid

        # Redirect stdout/stderr so print() also goes through logger
        import sys as _sys
        _sys.stdout = _BufferedRedirect(logger, logging.INFO)  # type: ignore
        _sys.stderr = _BufferedRedirect(logger, logging.ERROR)  # type: ignore

        # Small banner so the window isn't empty
        logger.info("Log window started at %s", time.strftime('%H:%M:%S'))
    else:
        # If Tk isn't available, or not main process, still ensure console logging works
        if tk is None:
            logger.debug("Tkinter not available, GUI log window disabled.")
        elif not is_main_process:
            logger.debug("Child process detected; GUI log window not created.")

    _logging_initialized = True
    return logger, _gui_window


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance that will use the centralized logging setup.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance configured to use the central logging system
    """
    if not _logging_initialized:
        # If setup_logging hasn't been called yet in this process, call it without GUI
        setup_logging(show_window=False)
    
    return logging.getLogger(name)
