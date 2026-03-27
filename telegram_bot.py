"""
Telegram Bot Handler for Ghost Email Agent.
Manages interactive buttons and state management using Telegram Bot API.
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatAction

from database import Database, EmailStatus
from google_utils import GmailService

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Handle Telegram interactions for email approvals."""
    
    def __init__(
        self,
        bot_token: str,
        user_chat_id: int,
        db: Database,
        gmail: GmailService
    ):
        """
        Initialize Telegram bot handler.
        
        Args:
            bot_token: Telegram bot token from BotFather
            user_chat_id: Chat ID of the user to receive notifications
            db: Database instance
            gmail: Gmail service instance
        """
        self.bot_token = bot_token
        self.user_chat_id = user_chat_id
        self.db = db
        self.gmail = gmail
        self.app = None
        
    def initialize_app(self) -> Application:
        """Initialize the Telegram bot application."""
        if self.app is not None:
            return self.app
            
        self.app = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("status", self._status_command))
        self.app.add_handler(CommandHandler("help", self._help_command))
        
        # Callback query handler for buttons
        self.app.add_handler(
            CallbackQueryHandler(self._handle_button_click)
        )
        
        # Message handler for text (used for edit mode)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message)
        )
        
        logger.info("Telegram bot application initialized")
        return self.app
    
    # ===================== COMMAND HANDLERS =====================
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            "👋 Welcome to Ghost Email Agent!\n\n"
            "I'll send you incoming emails for approval.\n"
            "Use /help for available commands."
        )
        logger.info(f"User {update.effective_user.id} started the bot")
    
    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command - show pending approvals."""
        pending = self.db.get_pending_approvals()
        
        if not pending:
            await update.message.reply_text("✅ No pending approvals!")
            return
        
        status_text = f"📋 Pending Approvals ({len(pending)}):\n\n"
        for i, email in enumerate(pending[:5], 1):
            status_text += f"{i}. From: {email['sender_name']}\n"
            status_text += f"   Subject: {email['subject'][:50]}\n\n"
        
        if len(pending) > 5:
            status_text += f"... and {len(pending) - 5} more"
        
        await update.message.reply_text(status_text)
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = """
🤖 Ghost Email Agent - Available Commands:

/start - Start the bot
/status - Show pending approvals
/help - Show this help message

📲 How to use:
1. I'll send you emails for approval with action buttons
2. Click "Approve" to send the AI-generated reply
3. Click "Edit" to customize the reply first
4. Click "Reject" if no reply is needed
"""
        await update.message.reply_text(help_text)
    
    # ===================== SEND APPROVAL REQUEST =====================
    
    async def send_approval_request(
        self,
        gmail_id: str,
        sender_name: str,
        subject: str,
        email_snippet: str,
        ai_reply: str
    ) -> Optional[int]:
        """
        Send Telegram message with interactive buttons for approval.
        
        Args:
            gmail_id: Gmail message ID
            sender_name: Sender's name
            subject: Email subject
            email_snippet: Email preview
            ai_reply: AI-generated reply
        
        Returns:
            Telegram message ID if successful
        """
        try:
            if self.app is None:
                logger.error("Telegram app not initialized")
                return None
            
            # Build message text
            message_text = self._build_message_text(
                sender_name, subject, email_snippet, ai_reply
            )
            
            # Build inline keyboard
            keyboard = self._build_inline_keyboard(gmail_id)
            
            # Send message
            message = await self.app.bot.send_message(
                chat_id=self.user_chat_id,
                text=message_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            # Store Telegram state mapping
            self.db.create_telegram_state(
                telegram_message_id=message.message_id,
                gmail_message_id=gmail_id,
                user_id=self.user_chat_id
            )
            
            self.db.create_approval_request(gmail_id, message.message_id)
            
            logger.info(
                f"Sent approval request for {gmail_id}, "
                f"Telegram message ID: {message.message_id}"
            )
            return message.message_id
        
        except Exception as e:
            logger.error(f"Error sending approval request: {e}")
            return None
    
    def _build_message_text(
        self,
        sender_name: str,
        subject: str,
        email_snippet: str,
        ai_reply: str
    ) -> str:
        """Build the message text for approval request."""
        message = (
            f"📧 <b>New Email from {sender_name}</b>\n\n"
            f"<b>Subject:</b> {subject}\n\n"
            f"<b>Preview:</b>\n{email_snippet[:150]}...\n\n"
            f"<b>🤖 AI Generated Reply:</b>\n<code>{ai_reply}</code>\n\n"
            f"<b>What would you like to do?</b>"
        )
        return message
    
    def _build_inline_keyboard(self, gmail_id: str) -> InlineKeyboardMarkup:
        """Build inline keyboard with action buttons."""
        buttons = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{gmail_id}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{gmail_id}"),
            ],
            [
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{gmail_id}"),
            ]
        ]
        return InlineKeyboardMarkup(buttons)
    
    # ===================== CALLBACK QUERY HANDLERS =====================
    
    async def _handle_button_click(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline button clicks."""
        query = update.callback_query
        
        try:
            # Acknowledge the button press
            await query.answer()
            
            # Parse callback data
            callback_data = query.data
            parts = callback_data.split("_", 1)
            
            if len(parts) != 2:
                await query.edit_message_text("❌ Invalid button data")
                return
            
            action, gmail_id = parts
            message_id = query.message.message_id
            
            logger.info(f"🟢 Telegram Callback received - Action: {action}, Gmail ID: {gmail_id}")
            
            # Handle actions
            if action == "approve":
                logger.info(f"Processing APPROVE for {gmail_id}...")
                await self._handle_approve(query, gmail_id, message_id)
            elif action == "edit":
                logger.info(f"Processing EDIT for {gmail_id}...")
                await self._handle_edit(query, gmail_id, message_id)
            elif action == "reject":
                logger.info(f"Processing REJECT for {gmail_id}...")
                await self._handle_reject(query, gmail_id, message_id)
            else:
                logger.warning(f"Unknown action received: {action}")
                await query.edit_message_text(f"❌ Unknown action: {action}")
        
        except Exception as e:
            logger.error(f"🔴 Error handling button click: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def _handle_approve(
        self,
        query: Any,
        gmail_id: str,
        message_id: int
    ) -> None:
        """Handle approval action."""
        try:
            # Show typing indicator
            await query.message.chat.send_action(ChatAction.TYPING)
            
            # Get email and AI reply
            email = self.db.get_email(gmail_id)
            ai_reply = self.db.get_ai_reply(gmail_id)
            
            if not email or not ai_reply:
                await query.edit_message_text("❌ Email or reply not found")
                return
            
            # Send email reply
            message_id_sent = self.gmail.send_email(
                to_email=email['sender_email'],
                subject=email['subject'],
                body=ai_reply,
                thread_id=email['thread_id']
            )
            
            if not message_id_sent:
                await query.edit_message_text(
                    "❌ Failed to send email. Please try again."
                )
                return
            
            # Update status
            self.db.update_approval_status(
                gmail_id,
                EmailStatus.REPLY_SENT,
                ai_reply
            )
            
            # Update message
            confirmation_text = (
                f"✅ <b>Email Reply Sent!</b>\n\n"
                f"<b>To:</b> {email['sender_email']}\n"
                f"<b>Subject:</b> {email['subject']}"
            )
            await query.edit_message_text(confirmation_text, parse_mode='HTML')
            
            logger.info(f"Approved and sent email for {gmail_id}")
        
        except Exception as e:
            logger.error(f"Error in approve action: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def _handle_edit(
        self,
        query: Any,
        gmail_id: str,
        message_id: int
    ) -> None:
        """Handle edit action - transition to WAITING_FOR_EDIT state."""
        try:
            # Update state
            self.db.update_telegram_state(message_id, "waiting_for_edit")
            self.db.update_approval_status(
                gmail_id,
                EmailStatus.WAITING_FOR_EDIT
            )
            
            # Get email details
            email = self.db.get_email(gmail_id)
            
            # Update original message
            edit_prompt_text = (
                f"✏️ <b>Edit Mode Activated</b>\n\n"
                f"Please send your revised reply below.\n"
                f"<b>Recipient:</b> {email['sender_email']}\n"
                f"<b>Subject:</b> {email['subject']}"
            )
            await query.edit_message_text(edit_prompt_text, parse_mode='HTML')
            
            # Send follow-up message
            await query.message.chat.send_message(
                text=(
                    "📝 <b>Please type your revised email reply:</b>\n\n"
                    "(Your next message will be sent as the email body)"
                ),
                parse_mode='HTML'
            )
            
            logger.info(f"Transitioned to edit mode for {gmail_id}")
        
        except Exception as e:
            logger.error(f"Error in edit action: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def _handle_reject(
        self,
        query: Any,
        gmail_id: str,
        message_id: int
    ) -> None:
        """Handle rejection action."""
        try:
            # Update status
            self.db.update_approval_status(gmail_id, EmailStatus.REJECTED)
            
            # Update message
            confirmation_text = (
                "❌ <b>Email Marked as Rejected</b>\n\n"
                "No reply will be sent."
            )
            await query.edit_message_text(confirmation_text, parse_mode='HTML')
            
            logger.info(f"Rejected email {gmail_id}")
        
        except Exception as e:
            logger.error(f"Error in reject action: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    # ===================== TEXT MESSAGE HANDLER =====================
    
    async def _handle_text_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text message for edit mode."""
        try:
            message_text = update.message.text
            user_id = update.effective_user.id
            
            # Get pending edit
            pending_edits = self.db.get_waiting_for_edit()
            
            if not pending_edits:
                await update.message.reply_text(
                    "ℹ️ No pending edits. Awaiting email approvals..."
                )
                return
            
            # Use most recent pending edit
            pending_edit = pending_edits[0]
            gmail_id = pending_edit['gmail_id']
            email = self.db.get_email(gmail_id)
            
            # Show typing indicator
            await update.message.chat.send_action(ChatAction.TYPING)
            
            # Send the edited reply
            message_id_sent = self.gmail.send_email(
                to_email=email['sender_email'],
                subject=email['subject'],
                body=message_text,
                thread_id=email['thread_id']
            )
            
            if not message_id_sent:
                await update.message.reply_text(
                    "❌ Failed to send edited reply. Please try again."
                )
                return
            
            # Update status
            self.db.update_approval_status(
                gmail_id,
                EmailStatus.REPLY_SENT,
                message_text
            )
            
            # Send confirmation
            confirmation_text = (
                f"✅ <b>Edited Reply Sent!</b>\n\n"
                f"<b>To:</b> {email['sender_email']}\n"
                f"<b>Subject:</b> {email['subject']}\n\n"
                f"<b>Message:</b>\n<code>{message_text}</code>"
            )
            await update.message.reply_text(confirmation_text, parse_mode='HTML')
            
            logger.info(f"Sent edited reply for {gmail_id}")
        
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    # ===================== UTILITY METHODS =====================
    
    async def send_message(self, text: str, parse_mode: str = None) -> Optional[int]:
        """Send a message to the configured chat."""
        try:
            if self.app is None:
                logger.error("Telegram app not initialized")
                return None
            
            message = await self.app.bot.send_message(
                chat_id=self.user_chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return message.message_id
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    async def send_notification(self, title: str, body: str) -> Optional[int]:
        """Send a formatted notification."""
        text = f"<b>{title}</b>\n\n{body}"
        return await self.send_message(text, parse_mode='HTML')
    
    async def start(self) -> None:
        """Start the bot polling."""
        try:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            logger.info("Telegram bot started successfully")
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the bot gracefully."""
        try:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
