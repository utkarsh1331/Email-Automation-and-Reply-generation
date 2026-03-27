"""
Streamlit Dashboard for Ghost Email Agent.
Real-time email status and management UI.
"""

import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time

from database import Database, EmailStatus
from google_utils import GoogleAuth, GmailService, CalendarService
from processor import EmailProcessor
from streamlit_autorefresh import st_autorefresh


# Load environment variables
import warnings
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.ERROR) # Only show errors for Streamlit backend, to avoid clutter
load_dotenv()

# Configure Streamlit page
st.set_page_config(
    page_title="Ghost Email Agent",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
<style>
    /* Main background */
    .main {
        background-color: #f8f9fa;
    }
    
    /* Status styling */
    .status-waiting {
        background-color: #fff3cd;
        color: #856404;
        padding: 8px 12px;
        border-radius: 4px;
        font-weight: bold;
    }
    
    .status-sent {
        background-color: #d4edda;
        color: #155724;
        padding: 8px 12px;
        border-radius: 4px;
        font-weight: bold;
    }
    
    .status-rejected {
        background-color: #f8d7da;
        color: #721c24;
        padding: 8px 12px;
        border-radius: 4px;
        font-weight: bold;
    }
    
    .status-pending {
        background-color: #d1ecf1;
        color: #0c5460;
        padding: 8px 12px;
        border-radius: 4px;
        font-weight: bold;
    }
    
    /* Card styling */
    .email-card {
        background-color: white;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* Table styling */
    table {
        background-color: white;
        border-collapse: collapse;
    }
    
    th {
        background-color: #2c3e50;
        color: white;
        padding: 12px;
        text-align: left;
        font-weight: bold;
    }
    
    td {
        padding: 10px 12px;
        border-bottom: 1px solid #eee;
    }
    
    tr:hover {
        background-color: #f5f5f5;
    }
    
    /* Metric styling */
    .metric-box {
        background-color: white;
        border-left: 4px solid #007bff;
        padding: 16px;
        border-radius: 4px;
        margin: 8px 0;
    }
    
    .metric-label {
        font-size: 12px;
        color: #666;
        font-weight: bold;
        text-transform: uppercase;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: bold;
        color: #007bff;
        margin-top: 4px;
    }
</style>
""", unsafe_allow_html=True)


# ===================== SESSION STATE INITIALIZATION =====================

@st.cache_resource
def init_components():
    """Initialize database, Gmail, and processor components."""
    progress_text = st.empty()
    try:
        progress_text.text("📁 Connecting to database...")
        db = Database(os.getenv("DATABASE_PATH", "ghost_email.db"))
        
        progress_text.text("🔑 Authenticating with Gmail and Calendar...")
        auth = GoogleAuth(os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json"))
        creds = auth.authenticate(interactive=False)
        
        if not creds:
            progress_text.warning("⚠️ **Authentication Required**\n\nPlease check your terminal where `start.py` or `main.py` is running to complete the Google Sign-in process.\nStreamlit will automatically refresh once authenticated.")
            st.stop()
            
        gmail = GmailService(creds)
        calendar = CalendarService(creds)
        
        progress_text.text("🤖 Initializing AI Processor...")
        processor = EmailProcessor(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            chroma_path=os.getenv("CHROMADB_PATH", "./chroma_db")
        )
        
        progress_text.empty()
        return db, gmail, calendar, processor
    except Exception as e:
        progress_text.error(f"Error initializing components: {e}")
        st.stop()


db, gmail, calendar, processor = init_components()

# Setup auto-refresh (handled at the bottom of the file)
if "refresh_interval" not in st.session_state:
    st.session_state.refresh_interval = 30


# ===================== UTILITY FUNCTIONS =====================

def get_status_badge(status):
    """Get HTML badge for status."""
    status_map = {
        "waiting_for_approval": ("⏳ Waiting for Approval", "status-waiting"),
        "reply_sent": ("✅ Reply Sent", "status-sent"),
        "rejected": ("❌ Approval Rejected", "status-rejected"),
        "pending": ("⏳ Pending", "status-pending"),
        "approved": ("✅ Approved", "status-sent"),
        "waiting_for_edit": ("✏️ Waiting for Edit", "status-waiting"),
    }
    
    text, css_class = status_map.get(status, (status, "status-pending"))
    return f'<div class="{css_class}">{text}</div>'


def fetch_and_process_emails():
    """Fetch emails from Gmail and process them."""
    with st.spinner("🔄 Fetching unread emails and calendar..."):
        try:
            # Sync Calendar events to ChromaDB
            try:
                upcoming_events = calendar.fetch_upcoming_events(days=30)
                for event in upcoming_events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    processor.store_calendar_event_in_chroma(
                        event_id=event['id'],
                        summary=event.get('summary', 'No Title'),
                        start_time=start,
                        end_time=end,
                        description=event.get('description', '')
                    )
            except Exception as e:
                st.warning(f"⚠️ Calendar sync failed: {e}")

            # Get all stored IDs to avoid redundant fetching
            stored_ids = db.get_all_gmail_ids()
            
            # Fetch unread emails
            emails = gmail.fetch_emails(limit=50, query='is:unread')
            
            new_emails_count = 0
            for email in emails:
                # Skip if already stored or self-sent
                if email['gmail_id'] in stored_ids:
                    continue
                    
                if email['sender_email'] == os.getenv("USER_EMAIL"):
                    continue
                
                # Store email
                db.store_email(
                    gmail_id=email['gmail_id'],
                    thread_id=email['thread_id'],
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    message_snippet=email['message_snippet'],
                    full_body=email['full_body'],
                    received_date=datetime.now()
                )
                
                # Classify email
                category, confidence = processor.classify_email(
                    email['subject'],
                    email['full_body']
                )
                
                db.update_email_category(email['gmail_id'], category, confidence)
                
                # Calendar context if it's a meeting
                calendar_context = None
                if category == "Meeting":
                    meeting_details = processor.extract_meeting_details(
                        email['subject'],
                        email['full_body']
                    )
                    if meeting_details:
                        avail = calendar.check_calendar(
                            meeting_details['date'],
                            meeting_details['start_time'],
                            meeting_details['end_time']
                        )
                        if avail.get('available'):
                            calendar_context = f"Available: I am free for this meeting on {meeting_details['date']} from {meeting_details['start_time']} to {meeting_details['end_time']}."
                        elif 'error' in avail:
                            calendar_context = f"Error: Could not check calendar availability due to an API error ({avail['error']})."
                        else:
                            conflicts = [c['summary'] for c in avail.get('conflicts', [])]
                            calendar_context = f"Conflict: I have other commitments ({', '.join(conflicts)}) during the requested time."
                    else:
                        calendar_context = "Request: Need more specific time/date details to check calendar."

                # Generate reply
                reply, reply_confidence = processor.generate_reply(
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    email_body=email['full_body'],
                    category=category,
                    calendar_context=calendar_context
                )
                
                db.store_ai_reply(
                    email['gmail_id'],
                    email['thread_id'],
                    reply,
                    reply_confidence
                )
                
                # Store in ChromaDB
                processor.store_email_in_chroma(
                    email_id=email['gmail_id'],
                    sender_email=email['sender_email'],
                    sender_name=email['sender_name'],
                    subject=email['subject'],
                    body=email['full_body'],
                    category=category,
                    received_date=str(datetime.now())
                )
                new_emails_count += 1
                
                # Note: Telegram bot will send approval request via main.py
                # The dashboard just processes and stores the email
            
            st.success(f"✅ Processed {new_emails_count} new emails (Telegram bot will send approvals)")
            return new_emails_count
        
        except Exception as e:
            st.error(f"❌ Error fetching emails: {e}")
            return 0


def get_email_dataframe():
    """Get all emails with status as a dataframe."""
    try:
        emails = db.get_all_emails_with_status()
        
        if not emails:
            return pd.DataFrame()
        
        data = []
        for email in emails:
            # Safely handle None values from DB
            confidence = email.get('confidence_score')
            if confidence is None: confidence = 0.0
            
            ai_reply = email.get('ai_generated_reply') or 'N/A'
            
            data.append({
                "Sender": email.get('sender_name') or 'Unknown',
                "Email": email.get('sender_email') or '',
                "Date/Time": email.get('received_date') or '',
                "Subject": (email.get('subject') or '')[:50],
                "Snippet": (email.get('message_snippet') or '')[:50],
                "Category": email.get('category') or 'Unknown',
                "AI Reply": ai_reply[:50],
                "Status": email.get('approval_status') or 'pending',
                "Gmail ID": email.get('gmail_id') or '',
            })
        
        return pd.DataFrame(data)
    
    except Exception as e:
        st.error(f"Error loading emails: {e}")
        return pd.DataFrame()


# ===================== PAGE LAYOUT =====================

# Header
st.markdown("# 📧 Ghost Email Agent Dashboard")
st.markdown("**Intelligent AI-powered email management with Telegram bot approval workflow**")

# Sidebar
with st.sidebar:
    st.markdown("## ⚙️ Controls")
    
    if st.button("🔄 Sync Emails"):
        fetch_and_process_emails()
    
    if st.button("🗘 Refresh Dashboard"):
        st.rerun()
    
    st.markdown("---")
    
    with st.expander("📊 Statistics"):
        try:
            all_emails = db.get_all_emails_with_status()
            pending = len([e for e in all_emails if e.get('approval_status') == 'waiting_for_approval'])
            approved = len([e for e in all_emails if e.get('approval_status') == 'reply_sent'])
            rejected = len([e for e in all_emails if e.get('approval_status') == 'rejected'])
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Emails", len(all_emails))
                st.metric("Approved", approved)
            with col2:
                st.metric("Pending", pending)
                st.metric("Rejected", rejected)
        
        except Exception as e:
            st.warning(f"Could not load statistics: {e}")
    
    with st.expander("🗄️ Database Info"):
        try:
            stats = processor.get_collection_stats()
            st.write(f"**Emails in ChromaDB:** {stats['emails']}")
            st.write(f"**History Records:** {stats['history']}")
        except Exception as e:
            st.warning(f"Could not load ChromaDB stats: {e}")
    
    with st.expander("⚙️ Settings"):
        st.selectbox(
            "Refresh interval (seconds)",
            [5, 10, 30, 60],
            key="refresh_interval"
        )
        
        if st.button("🗑️ Clean old records"):
            db.cleanup_old_records(days=30)
            st.success("✅ Cleaned records older than 30 days")

# Main content area
tab1, tab2, tab3, tab4 = st.tabs([
    "📬 Inbox",
    "⏳ Pending Approval",
    "✏️ Waiting for Edit",
    "📊 Analytics"
])

# ===================== TAB 1: INBOX =====================

with tab1:
    st.markdown("### 📬 All Emails")

    all_emails = db.get_all_emails_with_status()

    if not all_emails:
        st.info("📭 No emails found. Click 'Sync Emails' to fetch from Gmail.")
    else:
        st.caption(f"Total: {len(all_emails)} emails — Click on any email to expand details")
        st.markdown("---")

        for row in all_emails:
            gmail_id = row.get('gmail_id', '')
            sender = row.get('sender_name') or row.get('sender_email') or 'Unknown'
            subject = row.get('subject') or '(No Subject)'
            category = row.get('category') or 'Unknown'
            approval_status = row.get('approval_status') or 'pending'

            status_icons = {
                'waiting_for_approval': '⏳',
                'reply_sent': '✅',
                'rejected': '❌',
                'pending': '🔵',
                'approved': '✅',
                'waiting_for_edit': '✏️',
            }
            icon = status_icons.get(approval_status, '🔵')

            label = f"{icon} **{sender}** — {subject[:60]}  `{category}`"

            with st.expander(label, expanded=False):
                email_data = db.get_email(gmail_id)
                ai_reply = db.get_ai_reply(gmail_id)
                approval = db.get_approval(gmail_id)

                if email_data:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**From:** {email_data.get('sender_name')} ({email_data.get('sender_email')})")
                        st.write(f"**Subject:** {email_data.get('subject')}")
                        st.write(f"**Date:** {email_data.get('received_date')}")
                        st.write(f"**Category:** {category}")
                    with col2:
                        if approval:
                            st.write(f"**Status:** {icon} {approval_status.replace('_', ' ').title()}")

                    st.markdown("**📄 Email Body:**")
                    st.text_area("Email Body", value=email_data.get('full_body', ''), height=180,
                                 disabled=True, key=f"body_{gmail_id}", label_visibility="collapsed")

                    st.markdown("**🤖 AI Generated Reply:**")
                    st.text_area("AI Reply", value=ai_reply or "No reply generated yet", height=150,
                                 disabled=True, key=f"reply_{gmail_id}", label_visibility="collapsed")



# ===================== TAB 2: PENDING APPROVAL =====================

with tab2:
    st.markdown("### Pending Approvals")
    
    try:
        pending = db.get_pending_approvals()
        
        if not pending:
            st.info("✅ No pending approvals!")
        else:
            for email in pending:
                with st.container():
                    st.markdown(f"""
                    <div class="email-card">
                        <h4>{email['subject']}</h4>
                        <p><strong>From:</strong> {email['sender_name']} ({email['sender_email']})</p>
                        <p><strong>Category:</strong> {email['category']} ({email['confidence_score']:.0%})</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    ai_reply = db.get_ai_reply(email['gmail_id'])
                    
                    st.markdown("**AI Generated Reply:**")
                    st.info(ai_reply or "No reply generated")
                    
                    # Manual actions
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        if st.button(f"✅ Approve #{email['gmail_id'][:8]}"):
                            message_id = gmail.send_email(
                                to_email=email['sender_email'],
                                subject=email['subject'],
                                body=ai_reply,
                                thread_id=email['thread_id']
                            )
                            
                            if message_id:
                                db.update_approval_status(
                                    email['gmail_id'],
                                    EmailStatus.REPLY_SENT,
                                    ai_reply
                                )
                                st.success("✅ Email sent!")
                                st.rerun()
                            else:
                                st.error("❌ Failed to send email")
                    
                    with col2:
                        if st.button(f"✏️ Edit #{email['gmail_id'][:8]}"):
                            db.update_approval_status(
                                email['gmail_id'],
                                EmailStatus.WAITING_FOR_EDIT
                            )
                            st.warning("✏️ Waiting for your edited reply...")
                            st.rerun()
                    
                    with col3:
                        if st.button(f"❌ Reject #{email['gmail_id'][:8]}"):
                            db.update_approval_status(
                                email['gmail_id'],
                                EmailStatus.REJECTED
                            )
                            st.success("❌ Email rejected")
                            st.rerun()
                    
                    st.markdown("---")
    
    except Exception as e:
        st.error(f"Error loading pending approvals: {e}")


# ===================== TAB 3: WAITING FOR EDIT =====================

with tab3:
    st.markdown("### Emails Waiting for Edit")
    
    try:
        waiting = db.get_waiting_for_edit()
        
        if not waiting:
            st.info("No emails waiting for edit")
        else:
            for email in waiting:
                st.markdown(f"**{email['subject']}** - From: {email['sender_name']}")
                
                edited_reply = st.text_area(
                    f"Enter your edited reply for {email['sender_email']}:",
                    key=f"edit_{email['gmail_id']}"
                )
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button(f"📤 Send edited reply"):
                        if edited_reply:
                            message_id = gmail.send_email(
                                to_email=email['sender_email'],
                                subject=email['subject'],
                                body=edited_reply,
                                thread_id=email['thread_id']
                            )
                            
                            if message_id:
                                db.update_approval_status(
                                    email['gmail_id'],
                                    EmailStatus.REPLY_SENT,
                                    edited_reply
                                )
                                st.success("✅ Edited reply sent!")
                                st.rerun()
                            else:
                                st.error("❌ Failed to send reply")
                        else:
                            st.warning("⚠️ Please enter a reply")
                
                with col2:
                    if st.button(f"❌ Cancel"):
                        db.update_approval_status(
                            email['gmail_id'],
                            EmailStatus.REJECTED
                        )
                        st.info("Cancelled")
                        st.rerun()
                
                st.markdown("---")
    
    except Exception as e:
        st.error(f"Error loading edit queue: {e}")


# ===================== TAB 4: ANALYTICS =====================

with tab4:
    st.markdown("### Email Analytics")
    
    try:
        df = get_email_dataframe()
        
        if not df.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown("### 📧 Total Emails")
                st.markdown(f"<div class='metric-value'>{len(df)}</div>", unsafe_allow_html=True)
            
            with col2:
                approved = len(df[df["Status"] == "reply_sent"])
                st.markdown("### ✅ Approved")
                st.markdown(f"<div class='metric-value'>{approved}</div>", unsafe_allow_html=True)
            
            with col3:
                pending = len(df[df["Status"] == "waiting_for_approval"])
                st.markdown("### ⏳ Pending")
                st.markdown(f"<div class='metric-value'>{pending}</div>", unsafe_allow_html=True)
            
            with col4:
                rejected = len(df[df["Status"] == "rejected"])
                st.markdown("### ❌ Rejected")
                st.markdown(f"<div class='metric-value'>{rejected}</div>", unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Category distribution
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### Category Distribution")
                category_counts = df["Category"].value_counts()
                st.bar_chart(category_counts)
            
            with col2:
                st.markdown("### Status Distribution")
                status_counts = df["Status"].value_counts()
                st.bar_chart(status_counts)
            
            st.markdown("---")
            
            # Confidence distribution
            st.markdown("### Confidence Scores")
            confidence_data = df["Confidence"].str.rstrip('%').astype(float)
            st.histogram(confidence_data, buckets=10)
    
    except Exception as e:
        st.error(f"Error loading analytics: {e}")


# ===================== AUTO REFRESH =====================

# Auto-refresh every 30 seconds (or current setting)
refresh_interval = st.session_state.get("refresh_interval", 30)
st_autorefresh(interval=refresh_interval * 1000, key="datarefresh")
