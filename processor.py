"""
Processor module for Ghost Email Agent.
Handles Groq LLM classification and ChromaDB RAG operations.
"""

import os
from typing import Optional, List, Dict, Any, Tuple
from groq import Groq
import json
from datetime import datetime

import warnings
warnings.filterwarnings("ignore")

class EmailProcessor:
    """Process emails with Groq LLM and store in ChromaDB."""
    
    def __init__(self, groq_api_key: str, chroma_path: str = "./chroma_db"):
        """
        Initialize EmailProcessor.
        
        Args:
            groq_api_key: Groq API key
            chroma_path: Path to ChromaDB storage
        """
        self.groq_client = Groq(api_key=groq_api_key)
        self.model = "llama-3.3-70b-versatile"  # Updated from decommissioned mixtral model
        
        # Initialize ChromaDB (lazy import)
        try:
            import chromadb
            import sys
            # For Python 3.14+ compatibility and ChromaDB 1.5.x
            self.chroma_client = chromadb.PersistentClient(path=chroma_path)
            print(f"[OK] ChromaDB initialized successfully (Version: {chromadb.__version__})")
        except Exception as e:
            import sys
            print(f"\n[WARNING] CHROMADB COMPATIBILITY ALERT (Python {sys.version.split()[0]})")
            print(f"Error: {e}")
            if "chroma_server_nofile" in str(e):
                print("REASON: Python 3.14 is currently incompatible with the internal settings model of ChromaDB.")
                print("SUGGESTION: Please use Python 3.12 or 3.13 for full RAG features.")
            print("RAG features will be disabled, but email processing and classification will continue using LLM only.\n")
            self.chroma_client = None
        
        # Create or get collections
        try:
            if self.chroma_client:
                self.emails_collection = self.chroma_client.get_or_create_collection(
                    name="emails",
                    metadata={"hnsw:space": "cosine"}
                )
                self.history_collection = self.chroma_client.get_or_create_collection(
                    name="email_history",
                    metadata={"hnsw:space": "cosine"}
                )
            else:
                self.emails_collection = None
                self.history_collection = None
        except Exception as e:
            print(f"Warning: ChromaDB collection creation failed: {e}")
            self.emails_collection = None
            self.history_collection = None
    
    # ===================== CLASSIFICATION OPERATIONS =====================
    
    def classify_email(self, subject: str, body: str) -> Tuple[str, float]:
        """
        Classify email using Groq Llama 3.
        
        Args:
            subject: Email subject
            body: Email body/message
        
        Returns:
            Tuple of (category, confidence_score)
        """
        prompt = f"""Classify the following email into one of these categories:
- Finance: Invoices, payments, billing, financial reports
- Meeting: Meeting requests, calendar updates, rescheduling
- Support: Technical issues, bug reports, help requests
- Promotion: Marketing, sales, promotional offers, newsletters
- Administrative: HR, company policies, announcements
- Follow-up: Responses to previous emails, feedback
- Urgent: Time-sensitive matters requiring immediate attention
- Other: Doesn't fit above categories

Email Subject: {subject[:200]}
Email Body: {body[:3000]}

Respond with a JSON object containing:
{{"category": "CategoryName", "confidence": 0.95}}
Only respond with the JSON, no additional text."""

        try:
            message = self.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=100,
            )
            
            response_text = message.choices[0].message.content.strip()
            
            # Extract JSON from potential markdown blocks
            if "```" in response_text:
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)
            
            result = json.loads(response_text)
            
            return result.get("category", "Other"), float(result.get("confidence", 0.5))
        except Exception as e:
            print(f"Error classifying email: {e}")
            # Regex fallback for "Meeting"
            meeting_keywords = ["meeting", "fix a meeting", "schedule", "calendar", "appointment", "catch up", "sync"]
            if any(keyword in subject.lower() or keyword in body.lower() for keyword in meeting_keywords):
                return "Meeting", 0.5
            return "Other", 0.0
    
    # ===================== MEETING EXTRACTION =====================
    
    def extract_meeting_details(self, subject: str, body: str) -> Optional[Dict[str, Any]]:
        """
        Extract meeting date and time from email content.
        
        Returns:
            Dict with 'date' (YYYY-MM-DD), 'start_time' (HH:MM), 'end_time' (HH:MM)
        """
        prompt = f"""Extract meeting details from this email.
        
Email Subject: {subject[:200]}
Email Body: {body[:3000]}
Today's Date: {datetime.now().strftime('%Y-%m-%d')}

Respond with a JSON object containing:
{{
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "end_time": "HH:MM",
  "reasoning": "Quick explanation"
}}
If no specific time is mentioned, assume a 30-minute meeting starting at 10:00 AM.
If no date is mentioned but "tomorrow" is, calculate based on Today's Date.
Only respond with the JSON, no additional text."""

        try:
            message = self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.1,
                max_tokens=200,
            )
            
            response_text = message.choices[0].message.content.strip()
            
            # Extract JSON
            if "```" in response_text:
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)
            
            result = json.loads(response_text)
            
            # Basic validation
            if all(k in result for k in ["date", "start_time", "end_time"]):
                return result
            return None
        except Exception as e:
            print(f"Error extracting meeting details: {e}")
            # Regex fallback for date/time extraction
            import re
            # Match 6/3/26 or 06-03-2026 or 6.3.26
            date_match = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', body)
            if date_match:
                d, m, y = date_match.groups()
                if len(y) == 2: y = "20" + y
                return {"date": f"{y}-{m.zfill(2)}-{d.zfill(2)}", "start_time": "10:00", "end_time": "10:30", "reasoning": "Fallback regex match (numeric)"}
            
            # Match "6 march"
            date_match = re.search(r'(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)', body.lower())
            if date_match:
                day = date_match.group(1).zfill(2)
                month_str = date_match.group(2)
                months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
                          "january": "01", "february": "02", "march": "03", "april": "04", "june": "06", "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12"}
                month = months.get(month_str[:3], "01")
                return {"date": f"{datetime.now().year}-{month}-{day}", "start_time": "10:00", "end_time": "10:30", "reasoning": "Fallback regex match (word)"}
                
            return None

    # ===================== REPLY GENERATION OPERATIONS =====================
    
    def generate_reply(
        self,
        sender_email: str,
        sender_name: str,
        subject: str,
        email_body: str,
        category: str,
        calendar_context: Optional[str] = None
    ) -> Tuple[str, float]:
        """
        Generate contextual reply using previous sender interactions.
        
        Args:
            sender_email: Sender's email address
            sender_name: Sender's name
            subject: Email subject
            email_body: Email body
            category: Email category
            calendar_context: Optional info about calendar availability
        
        Returns:
            Tuple of (generated_reply, confidence_score)
        """
        # Get context from ChromaDB
        context = self._get_sender_context(sender_email)
        
        # Get calendar context from ChromaDB (RAG)
        calendar_rag_context = ""
        if "Meeting" in category or "Meeting" in subject:
            # Extract date if possible to narrow search
            meeting_date = ""
            import re
            # Try extracting from calendar_context
            if calendar_context:
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', str(calendar_context))
                if date_match:
                    meeting_date = date_match.group(1)
            
            # Fallback: Try extracting from body/subject if context didn't have it
            if not meeting_date:
                # Reuse regex for numeric date
                date_match = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', email_body + " " + subject)
                if date_match:
                    d, m, y = date_match.groups()
                    if len(y) == 2: y = "20" + y
                    meeting_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                else:
                    # Reuse regex for word month
                    date_match = re.search(r'(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)', (email_body + " " + subject).lower())
                    if date_match:
                        day = date_match.group(1).zfill(2)
                        month_str = date_match.group(2)
                        months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
                        month = months.get(month_str[:3], "01")
                        meeting_date = f"{datetime.now().year}-{month}-{day}"
            
            query = f"calendar event schedule {meeting_date}".strip()
            similar_events = self.search_similar_emails(query, limit=5)
            if similar_events:
                events_found = []
                for event in similar_events:
                    if event['metadata'].get('category') == 'Calendar':
                        # Double check date match in text or metadata to avoid false positives
                        evt_doc = event['document']
                        if not meeting_date or meeting_date in evt_doc or meeting_date in str(event['metadata']):
                            events_found.append(f"- {evt_doc}")
                
                if events_found:
                    calendar_rag_context = "\n\nRelevant schedule information from your calendar:\n" + "\n".join(events_found)
        
        context_text = ""
        if context:
            context_text = "\n\nPrevious interactions with this sender (for context):\n"
            for item in context:
                context_text += f"- {item['metadata'].get('subject', '')}: {item['document'][:200]}...\n"
        
        prompt = f"""You are a professional email assistant. Generate a brief, professional reply to this email.

Sender: {sender_name} ({sender_email})
Subject: {subject[:200]}
Category: {category}
Email Body:
{email_body[:3000]}
{context_text}
{calendar_rag_context}
{f"\nCalendar Availability Check Result:\n{calendar_context}" if calendar_context else ""}

Important guidelines:
1. Keep the reply concise (2-3 sentences max)
2. Match the tone of the original email
3. Be professional and helpful
4. If "Calendar Availability Check Result" or "Relevant schedule information" shows a conflict, politely decline or suggest a different time. If available, confirm the time.

Respond with a JSON object containing:
{{"reply": "The actual email body here", "confidence": 0.9}}
Only respond with the JSON, no additional text."""

        try:
            message = self.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=0.7,
                max_tokens=500,
            )
            
            response_text = message.choices[0].message.content.strip()
            
            # Extract JSON from potential markdown blocks
            if "```" in response_text:
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)
            
            result = json.loads(response_text)
            reply = result.get("reply", "")
            confidence = float(result.get("confidence", 0.8))
            
            if not reply:
                # Fallback if AI didn't follow JSON format perfectly
                reply = response_text
            
            return reply, confidence
        except Exception as e:
            print(f"Error generating reply: {e}")
            
            # Robust fallback logic based on context
            fallback_msg = "Thank you for your email. I'll review this and get back to you shortly."
            
            if calendar_context:
                if "Conflict" in str(calendar_context):
                    # Try to extract the specific conflict mentioned
                    import re
                    conflict_match = re.search(r'Conflict: I have (.+?) during', str(calendar_context))
                    if conflict_match:
                        busy_reason = conflict_match.group(1)
                        fallback_msg = f"Thank you for reaching out. I've checked my calendar and I see a conflict ({busy_reason}) during the requested time. Would another time work for you?"
                    else:
                        fallback_msg = "Thank you for the meeting request. I noticed a conflict on my calendar for that time. Could we look at a different slot?"
                elif "Available" in str(calendar_context):
                    fallback_msg = "Thank you for the meeting request! I've checked my calendar and I'm free during that time. I'll get back to you soon to confirm the details."
            
            return fallback_msg, 0.5
    
    # ===================== CHROMADB OPERATIONS =====================
    
    def store_email_in_chroma(
        self,
        email_id: str,
        sender_email: str,
        sender_name: str,
        subject: str,
        body: str,
        category: str,
        received_date: str
    ) -> bool:
        """
        Store email in ChromaDB for RAG.
        
        Args:
            email_id: Unique email ID from Gmail
            sender_email: Sender's email address
            sender_name: Sender's name
            subject: Email subject
            body: Email body
            category: Email category
            received_date: When email was received
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.emails_collection or not self.history_collection:
                print("Warning: ChromaDB collections not available, skipping storage")
                return True  # Don't fail, just skip
            
            # Create document text
            document = f"From: {sender_name} ({sender_email})\nSubject: {subject}\n\n{body}"
            
            # Store in emails collection
            self.emails_collection.add(
                ids=[email_id],
                documents=[document],
                metadatas=[{
                    "sender_email": sender_email,
                    "sender_name": sender_name,
                    "subject": subject,
                    "category": category,
                    "received_date": received_date
                }]
            )
            
            # Also store in history collection for easier filtering
            self.history_collection.add(
                ids=[f"hist_{email_id}"],
                documents=[document],
                metadatas=[{
                    "sender_email": sender_email,
                    "subject": subject,
                    "category": category,
                    "received_date": received_date,
                    "email_id": email_id
                }]
            )
            
            return True
        except Exception as e:
            print(f"Error storing email in ChromaDB: {e}")
            return False
            
    def store_calendar_event_in_chroma(
        self,
        event_id: str,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = ""
    ) -> bool:
        """Store calendar event in ChromaDB for RAG."""
        try:
            if not self.emails_collection:
                return True
                
            document = f"Calendar Event: {summary}\nTime: {start_time} to {end_time}\nDescription: {description}"
            
            self.emails_collection.add(
                ids=[f"cal_{event_id}"],
                documents=[document],
                metadatas=[{
                    "category": "Calendar",
                    "summary": summary,
                    "start_time": start_time,
                    "end_time": end_time
                }]
            )
            return True
        except Exception as e:
            print(f"Error storing calendar event in ChromaDB: {e}")
            return False
    
    def _get_sender_context(self, sender_email: str, limit: int = 5) -> List[Dict]:
        """
        Get previous interactions with sender from ChromaDB.
        
        Args:
            sender_email: Sender's email address
            limit: Number of previous interactions to retrieve
        
        Returns:
            List of relevant email documents
        """
        try:
            if not self.history_collection:
                return []
            
            results = self.history_collection.query(
                query_texts=[sender_email],
                n_results=limit,
                where={"sender_email": sender_email}
            )
            
            if results and results['documents']:
                return [
                    {
                        'document': doc,
                        'metadata': meta
                    }
                    for doc, meta in zip(results['documents'][0], results['metadatas'][0])
                ]
            
            return []
        except Exception as e:
            print(f"Error retrieving sender context: {e}")
            return []
    
    def search_similar_emails(
        self,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar emails in ChromaDB.
        
        Args:
            query: Search query
            limit: Number of results to return
        
        Returns:
            List of similar emails
        """
        try:
            if not self.emails_collection:
                return []
            
            results = self.emails_collection.query(
                query_texts=[query],
                n_results=limit
            )
            
            if results and results['documents']:
                return [
                    {
                        'id': id_,
                        'document': doc,
                        'metadata': meta,
                        'distance': dist
                    }
                    for id_, doc, meta, dist in zip(
                        results['ids'][0],
                        results['documents'][0],
                        results['metadatas'][0],
                        results['distances'][0]
                    )
                ]
            
            return []
        except Exception as e:
            print(f"Error searching emails: {e}")
            return []
    
    def get_emails_by_sender(self, sender_email: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get all emails from specific sender.
        
        Args:
            sender_email: Sender's email address
            limit: Number of results to return
        
        Returns:
            List of emails from sender
        """
        try:
            if not self.history_collection:
                return []
            
            results = self.history_collection.get(
                where={"sender_email": sender_email},
                limit=limit
            )
            
            if results and results['documents']:
                return [
                    {
                        'id': id_,
                        'document': doc,
                        'metadata': meta
                    }
                    for id_, doc, meta in zip(
                        results['ids'],
                        results['documents'],
                        results['metadatas']
                    )
                ]
            
            return []
        except Exception as e:
            print(f"Error getting emails by sender: {e}")
            return []
    
    # ===================== UTILITY OPERATIONS =====================
    
    def delete_email_from_chroma(self, email_id: str) -> bool:
        """Delete email from ChromaDB."""
        try:
            if not self.emails_collection or not self.history_collection:
                return True  # Skip if collections unavailable
            
            self.emails_collection.delete(ids=[email_id])
            self.history_collection.delete(ids=[f"hist_{email_id}"])
            return True
        except Exception as e:
            print(f"Error deleting email from ChromaDB: {e}")
            return False
    
    def get_collection_stats(self) -> Dict[str, int]:
        """Get statistics about stored emails."""
        try:
            if not self.emails_collection or not self.history_collection:
                return {"emails": 0, "history": 0}
            
            emails_count = self.emails_collection.count()
            history_count = self.history_collection.count()
            
            return {
                "emails": emails_count,
                "history": history_count
            }
        except Exception as e:
            print(f"Error getting collection stats: {e}")
            return {"emails": 0, "history": 0}
