"""
Database module for Ghost Email Agent.
Handles SQLite schema and state management.
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from enum import Enum
import os


class EmailStatus(str, Enum):
    """Email processing status enum."""
    PENDING = "pending"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_EDIT = "waiting_for_edit"
    APPROVED = "approved"
    REPLY_SENT = "reply_sent"
    REJECTED = "rejected"


class Database:
    """Handle all database operations for Ghost Email Agent."""
    
    def __init__(self, db_path: str = "ghost_email.db"):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database schema."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Emails table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                gmail_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                sender_email TEXT NOT NULL,
                sender_name TEXT,
                subject TEXT,
                message_snippet TEXT,
                full_body TEXT,
                received_date TIMESTAMP,
                category TEXT,
                confidence_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # AI Replies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_id TEXT UNIQUE NOT NULL,
                thread_id TEXT NOT NULL,
                ai_generated_reply TEXT,
                confidence_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (gmail_id) REFERENCES emails(gmail_id)
            )
        """)
        
        # Approval tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_id TEXT UNIQUE NOT NULL,
                telegram_message_id INTEGER UNIQUE,
                status TEXT DEFAULT 'pending',
                approved_reply TEXT,
                sent_at TIMESTAMP,
                approval_timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (gmail_id) REFERENCES emails(gmail_id)
            )
        """)
        
        # State mapping for concurrent Telegram interactions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id INTEGER UNIQUE NOT NULL,
                gmail_message_id TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                current_state TEXT DEFAULT 'awaiting_action',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (gmail_message_id) REFERENCES emails(gmail_id)
            )
        """)
        
        # Email history for RAG (Retrieval-Augmented Generation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_email TEXT NOT NULL,
                email_id TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                category TEXT,
                timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(gmail_id)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender_email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_sender ON email_history(sender_email)
        """)
        
        conn.commit()
        conn.close()
    
    # ===================== EMAIL OPERATIONS =====================
    
    def store_email(
        self,
        gmail_id: str,
        thread_id: str,
        sender_email: str,
        sender_name: Optional[str],
        subject: str,
        message_snippet: str,
        full_body: str,
        received_date: datetime
    ) -> bool:
        """Store email in database."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO emails 
                (gmail_id, thread_id, sender_email, sender_name, subject, 
                 message_snippet, full_body, received_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gmail_id, thread_id, sender_email, sender_name,
                subject, message_snippet, full_body, received_date
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing email: {e}")
            return False
    
    def get_email(self, gmail_id: str) -> Optional[Dict[str, Any]]:
        """Get email by Gmail ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM emails WHERE gmail_id = ?", (gmail_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None

    def get_all_gmail_ids(self) -> Set[str]:
        """Get all stored Gmail IDs."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT gmail_id FROM emails")
        ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        return ids
    
    def get_all_emails_with_status(self) -> List[Dict[str, Any]]:
        """Get all emails with their approval status."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                e.*,
                a.status as approval_status,
                a.telegram_message_id,
                air.ai_generated_reply
            FROM emails e
            LEFT JOIN approvals a ON e.gmail_id = a.gmail_id
            LEFT JOIN ai_replies air ON e.gmail_id = air.gmail_id
            ORDER BY e.created_at DESC
            LIMIT 100
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_email_category(self, gmail_id: str, category: str, confidence_score: float) -> bool:
        """Update email category and confidence score."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE emails 
                SET category = ?, confidence_score = ?, updated_at = CURRENT_TIMESTAMP
                WHERE gmail_id = ?
            """, (category, confidence_score, gmail_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating email category: {e}")
            return False
    
    # ===================== AI REPLY OPERATIONS =====================
    
    def store_ai_reply(
        self,
        gmail_id: str,
        thread_id: str,
        ai_reply: str,
        confidence_score: float
    ) -> bool:
        """Store AI-generated reply."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO ai_replies 
                (gmail_id, thread_id, ai_generated_reply, confidence_score)
                VALUES (?, ?, ?, ?)
            """, (gmail_id, thread_id, ai_reply, confidence_score))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing AI reply: {e}")
            return False
    
    def get_ai_reply(self, gmail_id: str) -> Optional[str]:
        """Get AI reply for email."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT ai_generated_reply FROM ai_replies WHERE gmail_id = ?", 
                      (gmail_id,))
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else None
    
    # ===================== APPROVAL OPERATIONS =====================
    
    def create_approval_request(self, gmail_id: str, telegram_message_id: int) -> bool:
        """Create approval request for email."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO approvals (gmail_id, telegram_message_id, status)
                VALUES (?, ?, ?)
            """, (gmail_id, telegram_message_id, EmailStatus.WAITING_FOR_APPROVAL.value))
            
            conn.commit()
            conn.close()
            # Also update the emails table updated_at
            self._update_email_timestamp(gmail_id)
            return True
        except Exception as e:
            print(f"Error creating approval request: {e}")
            return False

    def _update_email_timestamp(self, gmail_id: str):
        """Update updated_at timestamp for email."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE emails SET updated_at = CURRENT_TIMESTAMP WHERE gmail_id = ?", (gmail_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def update_approval_status(
        self,
        gmail_id: str,
        status: EmailStatus,
        approved_reply: Optional[str] = None
    ) -> bool:
        """Update approval status for email."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE approvals 
                SET status = ?, approved_reply = ?, updated_at = CURRENT_TIMESTAMP
                WHERE gmail_id = ?
            """, (status.value, approved_reply, gmail_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating approval status: {e}")
            return False
    
    def get_approval(self, gmail_id: str) -> Optional[Dict[str, Any]]:
        """Get approval record for email."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM approvals WHERE gmail_id = ?", (gmail_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_approval_by_telegram_message_id(self, telegram_message_id: int) -> Optional[Dict[str, Any]]:
        """Get approval record by Telegram message ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM approvals WHERE telegram_message_id = ?
        """, (telegram_message_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    # ===================== TELEGRAM STATE OPERATIONS =====================
    
    def create_telegram_state(
        self,
        telegram_message_id: int,
        gmail_message_id: str,
        user_id: int
    ) -> bool:
        """Create Telegram state mapping for concurrent interactions."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO telegram_states 
                (telegram_message_id, gmail_message_id, telegram_user_id, current_state)
                VALUES (?, ?, ?, ?)
            """, (telegram_message_id, gmail_message_id, user_id, 'awaiting_action'))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error creating Telegram state: {e}")
            return False
    
    def update_telegram_state(
        self,
        telegram_message_id: int,
        new_state: str
    ) -> bool:
        """Update Telegram state."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE telegram_states 
                SET current_state = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_message_id = ?
            """, (new_state, telegram_message_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating Telegram state: {e}")
            return False
    
    def get_telegram_state(self, telegram_message_id: int) -> Optional[Dict[str, Any]]:
        """Get Telegram state for message."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM telegram_states WHERE telegram_message_id = ?
        """, (telegram_message_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    # ===================== EMAIL HISTORY OPERATIONS (FOR RAG) =====================
    
    def store_email_history(
        self,
        sender_email: str,
        email_id: str,
        subject: str,
        body: str,
        category: str,
        timestamp: datetime
    ) -> bool:
        """Store email in history for RAG context."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO email_history 
                (sender_email, email_id, subject, body, category, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sender_email, email_id, subject, body, category, timestamp))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing email history: {e}")
            return False
    
    def get_sender_history(self, sender_email: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get email history with specific sender for RAG."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM email_history 
            WHERE sender_email = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (sender_email, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    # ===================== UTILITY OPERATIONS =====================
    
    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get all pending approvals."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT e.*, a.telegram_message_id
            FROM emails e
            JOIN approvals a ON e.gmail_id = a.gmail_id
            WHERE a.status = ?
            ORDER BY e.created_at DESC
        """, (EmailStatus.WAITING_FOR_APPROVAL.value,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_waiting_for_edit(self) -> List[Dict[str, Any]]:
        """Get emails waiting for user edit."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT e.*, a.telegram_message_id
            FROM emails e
            JOIN approvals a ON e.gmail_id = a.gmail_id
            WHERE a.status = ?
            ORDER BY e.created_at DESC
        """, (EmailStatus.WAITING_FOR_EDIT.value,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def cleanup_old_records(self, days: int = 30) -> bool:
        """Clean up old records from database."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Delete old email history
            cursor.execute("""
                DELETE FROM email_history 
                WHERE created_at < datetime('now', ? || ' days')
            """, (f"-{days}",))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error cleaning up old records: {e}")
            return False
