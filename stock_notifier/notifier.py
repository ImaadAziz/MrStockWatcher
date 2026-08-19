from __future__ import annotations

import subprocess


class IMessageNotifier:
    """Send messages through the macOS Messages app."""

    def send(self, recipient: str, message: str) -> None:
        script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{_escape(recipient)}" of targetService
            send "{_escape(message)}" to targetBuddy
        end tell
        '''
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
