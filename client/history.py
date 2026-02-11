import json
import os
import tempfile
import re
from pathlib import Path


class ChatHistory:
    
    def __init__(self, max_messages=500, username=None):
        self.max_messages = max_messages
        self.username = username

        safe_username = (username or "default").replace("/", "_").replace("\\", "_")
        self.history_file = Path(tempfile.gettempdir()) / f"cursorlant_chat_history_{safe_username}.json"
    
    def _normalize_sender(self, sender: str | None) -> str | None:
        if not sender:
            return None

        for suffix in (" joined", " left"):
            if sender.endswith(suffix):
                return sender[: -len(suffix)]
        return sender

    def _extract_sender(self, text):
        match = re.match(r'^\[([^\]]+)\](?:\s*:|[\s]|$)', text)
        if match:
            return self._normalize_sender(match.group(1))
        return None
    
    def save(self, messages):
        try:
            messages_to_save = messages[-self.max_messages:] if len(messages) > self.max_messages else messages
            
            packed = []
            for text, _ in messages_to_save:
                sender = self._extract_sender(text)
                packed.append({"text": text, "sender": sender})

            history_data = {"messages": packed, "count": len(packed)}
            
            temp_file = str(self.history_file) + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(history_data, f)
            
            os.replace(temp_file, self.history_file)
            
        except Exception as e:
            pass
    
    def load(self, current_username):

        try:
            if not self.history_file.exists():
                return []
            
            with open(self.history_file, 'r') as f:
                history_data = json.load(f)
            
            messages = []
            for msg_data in history_data.get("messages", []):
                text = msg_data.get("text", "")
                sender = self._normalize_sender(msg_data.get("sender"))
                
                is_self = False
                
                if sender:
                    is_self = (sender == current_username)

                elif text.startswith(f"[{current_username}]:") or text.startswith(f"[{current_username}] system"):
                    is_self = True

                elif "is_self" in msg_data:

                    extracted_sender = self._extract_sender(text)

                    if extracted_sender:
                        is_self = (extracted_sender == current_username)

                    else:
                        is_self = msg_data["is_self"]
                
                messages.append((text, is_self))
            
            return messages[-self.max_messages:] if len(messages) > self.max_messages else messages
            
        except Exception as e:
            return []
    
    def clear(self):
        try:
            if self.history_file.exists():
                self.history_file.unlink()
        except Exception:
            pass
 
