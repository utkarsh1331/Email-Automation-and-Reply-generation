"""
Main entry point script for Ghost Email Agent.
Runs the Telegram bot for interactive email approvals.
"""

import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

from database import Database
from google_utils import GoogleAuth, GmailService, CalendarService
from processor import EmailProcessor
from telegram_bot import TelegramBotHandler


# Load environment variables
import warnings
warnings.filterwarnings("ignore")
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GhostEmailAgent:
    """Main Ghost Email Agent application."""
    
    def __init__(self):
        """Initialize the agent with all components."""
        logger.info("Initializing Ghost Email Agent...")
        
        # Initialize components
        self.db = Database(os.getenv("DATABASE_PATH", "ghost_email.db"))
        logger.info("[OK] Database initialized")
        
        try:
            self.auth = GoogleAuth(
                os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
            )
            creds = self.auth.authenticate()
            self.gmail = GmailService(creds)
            self.calendar = CalendarService(creds)
            logger.info("[OK] Gmail and Calendar APIs authenticated")
        except Exception as e:
            logger.error(f"[FAIL] Gmail authentication failed: {e}")
            raise
        
        try:
            self.processor = EmailProcessor(
                groq_api_key=os.getenv("GROQ_API_KEY"),
                chroma_path=os.getenv("CHROMADB_PATH", "./chroma_db")
            )
            logger.info("[OK] Processor initialized (Groq + ChromaDB)")
        except Exception as e:
            logger.error(f"[FAIL] Processor initialization failed: {e}")
            raise
        
        try:
            self.telegram = TelegramBotHandler(
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
                user_chat_id=int(os.getenv("TELEGRAM_USER_ID")),
                db=self.db,
                gmail=self.gmail
            )
            logger.info("✓ Telegram bot handler initialized")
        except Exception as e:
            logger.error(f"✗ Telegram handler initialization failed: {e}")
            raise
        
        # Initialize Telegram bot app
        self.telegram.initialize_app()
        logger.info("✓ Telegram bot application created")
        
        # Add background scheduler for email syncing
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(
            self._sync_emails_async,
            'interval',
            minutes=5,
            id='email_sync'
        )
        self.scheduler.start()
        logger.info("✓ Email sync scheduler started (every 5 minutes)")
        
        # Register cleanup on exit
        atexit.register(self.shutdown)
        
        logger.info("✓ Ghost Email Agent fully initialized!")
    
    def _sync_emails_async(self):
        """Wrapper to sync emails asynchronously."""
        asyncio.run(self.sync_emails())
    
    async def sync_emails(self):
        """Fetch and process emails from Gmail."""
        try:
            logger.info("🔄 Syncing unread emails and calendar from Gmail...")
            
            # Sync Calendar events to ChromaDB
            try:
                upcoming_events = self.calendar.fetch_upcoming_events(days=30)
                for event in upcoming_events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    self.processor.store_calendar_event_in_chroma(
                        event_id=event['id'],
                        summary=event.get('summary', 'No Title'),
                        start_time=start,
                        end_time=end,
                        description=event.get('description', '')
                    )
                logger.info(f"✓ Synced {len(upcoming_events)} calendar events to ChromaDB")
            except Exception as e:
                logger.error(f"✗ Calendar sync failed: {e}")

            # Get all stored IDs to avoid redundant fetching
            stored_ids = self.db.get_all_gmail_ids()
            
            # Fetch unread emails
            emails = self.gmail.fetch_emails(limit=50, query='is:unread')
            processed = 0
            
            for email in emails:
                # Skip if already stored (extra safety) or self-sent
                if email['gmail_id'] in stored_ids:
                    continue
                    
                if email['sender_email'] == os.getenv("USER_EMAIL"):
                    continue
                
                # Store email
                self.db.store_email(
                    gmail_id=email['gmail_id'],
                    thread_id=email['thread_id'],
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    message_snippet=email['message_snippet'],
                    full_body=email['full_body'],
                    received_date=email['received_date']
                )
                
                # Classify email
                category, confidence = self.processor.classify_email(
                    email['subject'],
                    email['full_body']
                )
                
                self.db.update_email_category(
                    email['gmail_id'],
                    category,
                    confidence
                )
                
                # Calendar context if it's a meeting
                calendar_context = None
                if category == "Meeting":
                    logger.info(f"📅 Extracting meeting details for: {email['subject']}")
                    meeting_details = self.processor.extract_meeting_details(
                        email['subject'],
                        email['full_body']
                    )
                    if meeting_details:
                        logger.info(f"📅 Checking calendar for {meeting_details['date']} at {meeting_details['start_time']}")
                        avail = self.calendar.check_calendar(
                            meeting_details['date'],
                            meeting_details['start_time'],
                            meeting_details['end_time']
                        )
                        if avail.get('available'):
                            calendar_context = f"Available: I am free for this meeting on {meeting_details['date']} from {meeting_details['start_time']} to {meeting_details['end_time']}."
                        elif 'error' in avail:
                            logger.error(f"📅 Calendar API error: {avail['error']}")
                            calendar_context = f"Error: Could not check calendar availability due to an API error ({avail['error']}). Please verify manually."
                        else:
                            conflicts = [c['summary'] for c in avail.get('conflicts', [])]
                            calendar_context = f"Conflict: I have other commitments ({', '.join(conflicts)}) during the requested time."
                    else:
                        calendar_context = "Request: Need more specific time/date details to check calendar."

                # Generate reply
                reply, reply_confidence = self.processor.generate_reply(
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    email_body=email['full_body'],
                    category=category,
                    calendar_context=calendar_context
                )
                
                self.db.store_ai_reply(
                    email['gmail_id'],
                    email['thread_id'],
                    reply,
                    reply_confidence
                )
                
                # Store in ChromaDB
                self.processor.store_email_in_chroma(
                    email_id=email['gmail_id'],
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    body=email['full_body'],
                    category=category,
                    received_date=str(email['received_date'])
                )
                
                # Store in email history for RAG
                from datetime import datetime
                self.db.store_email_history(
                    sender_email=email['sender_email'],
                    email_id=email['gmail_id'],
                    subject=email['subject'],
                    body=email['full_body'],
                    category=category,
                    timestamp=datetime.now()
                )
                
                # Send Telegram approval request
                await self.telegram.send_approval_request(
                    gmail_id=email['gmail_id'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    email_snippet=email['message_snippet'],
                    ai_reply=reply
                )
                
                processed += 1
                logger.info(f"  ✓ Processed: {email['subject']}")
            
            logger.info(f"✓ Email sync complete ({processed} new emails)")
        
        except Exception as e:
            logger.error(f"✗ Error during email sync: {e}")
    
    def shutdown(self):
        """Cleanup on shutdown."""
        logger.info("Shutting down Ghost Email Agent...")
        
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("✓ Scheduler stopped")
    
    async def run(self):
        """Run the Telegram bot with email sync."""
        try:
            logger.info("🚀 Starting Ghost Email Agent")
            logger.info("📊 Streamlit dashboard: http://localhost:8501")
            logger.info("🤖 Telegram Bot is now running...")
            
            # Start the Telegram bot
            await self.telegram.start()
            
            # Keep the bot running indefinitely
            logger.info("Bot is active and listening for commands...")
            stop_event = asyncio.Event()
            await stop_event.wait()
            
        except Exception as e:
            logger.error(f"Error during runtime: {e}")
            raise


async def main():
    """Main entry point."""
    try:
        # Validate environment variables
        required_vars = [
            "GROQ_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_USER_ID"
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please fill in .env file with your credentials")
            return
        
        # Initialize agent
        agent = GhostEmailAgent()
        
        # Run the agent
        await agent.run()
    
    except KeyboardInterrupt:
        logger.info("\n⏸️  Application interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
