import os
import base64
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError
from email.mime.text import MIMEText

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]

class GoogleAuth:
    """Manages Google API authentication."""
    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = None

    def authenticate(self, interactive: bool = True):
        """Authenticates and returns credentials. If interactive False, won't launch browser."""
        if os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except RefreshError:
                    print(f"Token refresh failed. Removing {self.token_path} and re-authenticating.")
                    if os.path.exists(self.token_path):
                        os.remove(self.token_path)
                    self.creds = None
            
            if not self.creds:
                if not interactive:
                    print("Authentication required but running in non-interactive mode. Returning None.")
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            if self.creds:
                with open(self.token_path, 'w') as token:
                    token.write(self.creds.to_json())
        
        return self.creds

class GmailService:
    """Handles Gmail operations."""
    def __init__(self, creds):
        self.service = build('gmail', 'v1', credentials=creds)

    def fetch_emails(self, limit: int = 100, query: str = '') -> List[Dict[str, Any]]:
        """Fetch last N emails from Gmail."""
        import httplib2
        try:
            results = self.service.users().messages().list(
                userId='me', maxResults=limit, q=query, includeSpamTrash=False
            ).execute()
            messages = results.get('messages', [])
            emails = []
            for msg in messages:
                try:
                    email_data = self.get_email_details(msg['id'])
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    print(f"Error fetching email {msg['id']}: {e}")
                    continue
            return emails
        except httplib2.error.ServerNotFoundError as e:
             print(f"Network error listing emails: {e}")
             return []
        except Exception as e:
             if "IncompleteRead" in str(e.__class__.__name__) or "SSL" in str(e):
                  print(f"Connection dropped while listing emails: {e}")
             else:
                  print(f"Error fetching emails: {e}")
             return []

    def list_unread_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Alias for fetch_emails to support MCP tool naming."""
        return self.fetch_emails(limit=max_results)

    def get_email_details(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific email."""
        import httplib2
        try:
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender_email_raw = next((h['value'] for h in headers if h['name'] == 'From'), '')
            to_email = next((h['value'] for h in headers if h['name'] == 'To'), '')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            import email.utils
            sender_name, sender_email = email.utils.parseaddr(sender_email_raw)
            if not sender_name: sender_name = sender_email.split('@')[0]
            
            body = self._get_message_body(message['payload'])
            snippet = message.get('snippet', '')[:200]
            
            return {
                'gmail_id': message_id,
                'thread_id': message['threadId'],
                'sender_email': sender_email,
                'sender_name': sender_name,
                'to_email': to_email,
                'subject': subject,
                'message_snippet': snippet,
                'full_body': body,
                'received_date': date,
                'labels': message.get('labelIds', []),
                'is_read': 'UNREAD' not in message.get('labelIds', [])
            }
        except httplib2.error.ServerNotFoundError as e:
             print(f"Network error getting email details: {e}")
             return None
        except Exception as e:
            # Catch IncompleteRead, SSL WantReadError, etc without needing exact imports
            if "IncompleteRead" in str(e.__class__.__name__) or "SSL" in str(e):
                 print(f"Connection dropped while getting email details: {e}")
            else:
                 print(f"Error getting email details: {e}")
            return None

    def _get_message_body(self, payload: Dict[str, Any]) -> str:
        """Extract message body from Gmail payload."""
        def get_text_from_payload(p: Dict[str, Any], mime: str) -> str:
            if 'parts' in p:
                for part in p['parts']:
                    if part.get('mimeType') == mime:
                        if 'data' in part['body']:
                            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    if 'parts' in part:
                        res = get_text_from_payload(part, mime)
                        if res: return res
            elif p.get('mimeType') == mime and 'body' in p and 'data' in p['body']:
                return base64.urlsafe_b64decode(p['body']['data']).decode('utf-8')
            return ''

        try:
            text = get_text_from_payload(payload, 'text/plain')
            if text:
                return text.strip()
            
            html_content = get_text_from_payload(payload, 'text/html')
            if not html_content and 'body' in payload and 'data' in payload['body']:
                html_content = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
                
            if html_content:
                import re
                from html import unescape
                text = re.sub(r'<style.*?>.*?</style>', '', html_content, flags=re.IGNORECASE|re.DOTALL)
                text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE|re.DOTALL)
                text = re.sub(r'<head.*?>.*?</head>', '', text, flags=re.IGNORECASE|re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = unescape(text)
                return re.sub(r'\s+', ' ', text).strip()
                
            return ''
        except Exception as e:
            print(f"Error decoding message body: {e}")
            return ''

    def send_email(self, to_email: str, subject: str, body: str, thread_id: Optional[str] = None) -> Optional[str]:
        """Sends an email or a reply. Returns message_id if successful."""
        try:
            message = MIMEText(body)
            message['to'] = to_email
            message['subject'] = subject
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            send_message = {'raw': raw}
            if thread_id:
                send_message['threadId'] = thread_id

            result = self.service.users().messages().send(userId='me', body=send_message).execute()
            return result.get('id')
        except Exception as e:
            print(f"Error sending email: {e}")
            return None

class CalendarService:
    """Handles Google Calendar operations."""
    def __init__(self, creds):
        self.service = build('calendar', 'v3', credentials=creds)

    def check_calendar(self, date: str, start_time: str, end_time: str) -> Dict[str, Any]:
        """
        Checks for conflicts on a given date and time range.
        Format for start_time/end_time: 'HH:MM' (24h)
        Format for date: 'YYYY-MM-DD'
        """
        try:
            # Construct ISO strings
            time_start_iso = f"{date}T{start_time}:00Z" # Assuming UTC for simplicity
            time_end_iso = f"{date}T{end_time}:00Z"
            
            # Fetch events for that day
            day_start = f"{date}T00:00:00Z"
            day_end = f"{date}T23:59:59Z"
            
            events_result = self.service.events().list(
                calendarId='primary', timeMin=day_start, timeMax=day_end,
                singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            req_start = datetime.fromisoformat(time_start_iso.replace('Z', '+00:00'))
            req_end = datetime.fromisoformat(time_end_iso.replace('Z', '+00:00'))
            
            conflicts = []
            for event in events:
                ext_start_str = event['start'].get('dateTime', event['start'].get('date'))
                ext_end_str = event['end'].get('dateTime', event['end'].get('date'))
                
                # Normalize extension times (handle date-only events or mixed)
                if 'T' not in ext_start_str: ext_start_str += "T00:00:00Z"
                if 'T' not in ext_end_str: ext_end_str += "T23:59:59Z"
                
                ext_start = datetime.fromisoformat(ext_start_str.replace('Z', '+00:00'))
                ext_end = datetime.fromisoformat(ext_end_str.replace('Z', '+00:00'))
                
                # Conflict Logic: (Start_req < End_ext) AND (End_req > Start_ext)
                if req_start < ext_end and req_end > ext_start:
                    conflicts.append({
                        'summary': event.get('summary', 'No Title'),
                        'start': ext_start_str,
                        'end': ext_end_str
                    })
            
            return {
                'available': len(conflicts) == 0,
                'conflicts': conflicts
            }
        except Exception as e:
            print(f"Error checking calendar: {e}")
            return {'error': str(e)}

    def schedule_meeting(self, summary: str, date: str, start_time: str, end_time: str) -> Optional[str]:
        """Schedules a meeting on the primary calendar."""
        try:
            event = {
                'summary': summary,
                'start': {'dateTime': f"{date}T{start_time}:00Z", 'timeZone': 'UTC'},
                'end': {'dateTime': f"{date}T{end_time}:00Z", 'timeZone': 'UTC'},
            }
            created_event = self.service.events().insert(calendarId='primary', body=event).execute()
            return created_event.get('htmlLink')
        except Exception as e:
            print(f"Error scheduling meeting: {e}")
            return None

    def fetch_upcoming_events(self, days: int = 30) -> List[Dict[str, Any]]:
        """Fetch all calendar events for the next N days."""
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            end = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary', timeMin=now, timeMax=end,
                singleEvents=True, orderBy='startTime'
            ).execute()
            return events_result.get('items', [])
        except Exception as e:
            print(f"Error fetching upcoming events: {e}")
            return []
