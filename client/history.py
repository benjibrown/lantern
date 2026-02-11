import json
import os
import tempfile
import re
from pathlib import Path


class ChatHistory:
    """Manages temporary chat history storage in /tmp directory"""
    
    def __init__(self, max_messages=500, username=None):
        """
        Initialize chat history manager
        
        Args:
            max_messages: Maximum number of messages to store
            username: Username for per-user history file
        """
        self.max_messages = max_messages
        self.username = username
        # Use a per-username file for chat history
        safe_username = (username or "default").replace("/", "_").replace("\\", "_")
        self.history_file = Path(tempfile.gettempdir()) / f"cursorlant_chat_history_{safe_username}.json"
    
    def _normalize_sender(self, sender: str | None) -> str | None:
        if not sender:
            return None
        # Server emits join/leave as: "[username joined]" / "[username left]"
        # Older history may have incorrectly captured "username joined" as sender.
        for suffix in (" joined", " left"):
            if sender.endswith(suffix):
                return sender[: -len(suffix)]
        return sender

    def _extract_sender(self, text):
        """
        Extract sender username from message text
        
        Returns:
            Username string if found, None otherwise
        """
        # Pattern: "[username]: msg", "[username] system", "[username joined]", "[username left]"
        # NOTE: join/left embeds the action inside the brackets.
        match = re.match(r'^\[([^\]]+)\](?:\s*:|[\s]|$)', text)
        if match:
            return self._normalize_sender(match.group(1))
        return None
    
    def save(self, messages):
        """
        Save messages to temporary file
        
        Args:
            messages: List of (text, is_self) tuples
        """
        try:
            # Only save the last max_messages
            messages_to_save = messages[-self.max_messages:] if len(messages) > self.max_messages else messages
            
            # Convert to serializable format - save sender username instead of is_self
            packed = []
            for text, _ in messages_to_save:
                sender = self._extract_sender(text)
                packed.append({"text": text, "sender": sender})

            history_data = {"messages": packed, "count": len(packed)}
            
            # Write to temp file atomically
            temp_file = str(self.history_file) + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(history_data, f)
            
            # Atomic rename
            os.replace(temp_file, self.history_file)
            
        except Exception as e:
            # Silently fail - this is temporary storage, not critical
            pass
    
    def load(self, current_username):
        """
        Load messages from temporary file and recalculate is_self based on current username
        
        Args:
            current_username: Current username to determine is_self
        
        Returns:
            List of (text, is_self) tuples, or empty list if file doesn't exist
        """
        try:
            if not self.history_file.exists():
                return []
            
            with open(self.history_file, 'r') as f:
                history_data = json.load(f)
            
            # Convert back to tuple format, recalculating is_self based on current username
            messages = []
            for msg_data in history_data.get("messages", []):
                text = msg_data.get("text", "")
                sender = self._normalize_sender(msg_data.get("sender"))
                
                # Recalculate is_self based on current username
                is_self = False
                
                # First check if we have a saved sender (new format)
                if sender:
                    is_self = (sender == current_username)
                # Check if message format matches current username
                elif text.startswith(f"[{current_username}]:") or text.startswith(f"[{current_username}] system"):
                    is_self = True
                # Handle legacy format where is_self might be saved (backward compatibility)
                elif "is_self" in msg_data:
                    # Try to extract sender from text to recalculate
                    extracted_sender = self._extract_sender(text)
                    if extracted_sender:
                        # We can recalculate based on extracted sender
                        is_self = (extracted_sender == current_username)
                    else:
                        # No sender in text, use legacy is_self value
                        is_self = msg_data["is_self"]
                
                messages.append((text, is_self))
            
            # Limit to max_messages
            return messages[-self.max_messages:] if len(messages) > self.max_messages else messages
            
        except Exception as e:
            # If file is corrupted or doesn't exist, return empty list
            return []
    
    def clear(self):
        """Clear the chat history file"""
        try:
            if self.history_file.exists():
                self.history_file.unlink()
        except Exception:
            pass
 
