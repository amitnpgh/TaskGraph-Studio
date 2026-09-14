"""Desktop bootstrap with a GUI-independent error report and startup log."""
import os
from pathlib import Path
import sys
import tempfile
import traceback


def log_failure(details):
    destinations = [Path(__file__).resolve().parent / "startup-error.txt",
                    Path(tempfile.gettempdir()) / "taskgraph-startup-error.txt"]
    for path in destinations:
        try:
            path.write_text("Taskgraph Studio startup error\nPython: " + sys.executable
                            + "\n\n" + details, encoding="utf-8")
            return str(path)
        except OSError:
            continue
    return "The startup log could not be written."


def main():
    check = "--check-ui" in sys.argv
    smoke = "--smoke-test" in sys.argv
    try:
        if sys.version_info < (3, 11):
            raise RuntimeError("Python 3.11 or newer is required.")
        if check:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.update_idletasks()
            root.destroy()
        else:
            from desktop import Studio
            app = Studio()
            if smoke:
                app.withdraw()
                app.update_idletasks()
                app.destroy()
            else:
                app.mainloop()
        return 0
    except Exception:
        details = traceback.format_exc()
        location = log_failure(details)
        if not check and not smoke:
            message = ("Taskgraph Studio could not start.\n\n"
                       "Error details were saved here:\n" + location + "\n\n"
                       "If the error mentions Tkinter or init.tcl, repair or install "
                       "Python 3.11 or newer with the Tcl/Tk and IDLE option. "
                       "Also ensure the complete ZIP has been extracted.")
            if os.name == "nt":
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, "Taskgraph Studio", 16)
            elif sys.stderr:
                print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
