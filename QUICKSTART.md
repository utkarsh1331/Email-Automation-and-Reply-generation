# 🚀 Quick Start Guide

Get Ghost Email Agent up and running in 5 minutes!

## Prerequisites

- Python 3.10 or higher
- A Gmail account
- Groq API key (free from https://console.groq.com)
- Twilio account with WhatsApp Business API enabled

## Step 1: Clone and Setup

```bash
cd ghost-email-manager
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

## Step 2: Configure Credentials

### Option A: Interactive Setup (Recommended)

```bash
python config.py
```

Follow the prompts to enter:
- Groq API key
- Twilio credentials
- WhatsApp numbers
- Gmail credentials path

### Option B: Manual Setup

1. Copy `.env.example` to `.env`
2. Edit `.env` with your credentials:

```env
GROQ_API_KEY=your_key_here
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+1234567890
RECIPIENT_WHATSAPP_NUMBER=whatsapp:+0987654321
```

## Step 3: Set Up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project: "Ghost Email Agent"
3. Enable Gmail API (search for it in API Library)
4. Create OAuth2 credentials:
   - Click "Create Credentials"
   - Choose "OAuth Client ID"
   - Desktop application
   - Download JSON
   - Save as `credentials.json` in project root

## Step 4: Run the Application

```bash
python start.py
```

This starts both:
- **FastAPI webhook server** (port 5000)
- **Streamlit dashboard** (port 8501)

The dashboard will open automatically. You'll see:
- 📬 Inbox with all emails
- ⏳ Pending approvals
- ✏️ Edit queue
- 📊 Analytics

## Step 5: Set Up WhatsApp Webhook

1. Get your public URL (use ngrok for testing):
   ```bash
   ngrok http 5000
   ```

2. In Twilio Dashboard:
   - Go to WhatsApp Settings
   - Find "Webhook URL"
   - Enter: `https://your-ngrok-url.ngrok.io/webhook`
   - Save

3. Test by sending an email

## 🎯 First Email

1. Send an email to your Gmail account
2. Click "Sync Emails" in dashboard
3. A WhatsApp message arrives with AI reply
4. Click ✅ Approve, ✏️ Edit, or ❌ No Need
5. View status update in dashboard

## 📊 Dashboard Overview

### Inbox Tab
- View all 100 emails
- Filter by category/status
- See AI-generated replies
- Check confidence scores

### Pending Approval Tab
- Manually approve/edit/reject
- Read full email
- See AI reply before sending

### Waiting for Edit Tab
- Send custom reply
- Override AI suggestion
- Track changes

### Analytics Tab
- Email statistics
- Category breakdown
- Status distribution
- Confidence analysis

## 🔧 Common Tasks

### Manual Approve/Reject
```python
# In dashboard's "Pending Approval" tab:
1. Click ✅ Approve to send AI reply
2. Click ✏️ Edit to customize
3. Click ❌ No Need to reject
```

### Sync Emails Manually
```
Click "Sync Emails" button in sidebar
```

### View Email History
```
1. Go to Inbox tab
2. Select email from "Subject" dropdown
3. View full body and AI reply
```

### Export Data
```python
# From database:
from database import Database
db = Database()
emails = db.get_all_emails_with_status()
```

## 🐛 Troubleshooting

### OAuth2 Error: "redirect_uri_mismatch"
- Delete `token.json` in project root
- Run application again
- Select "Yes" when prompted to authorize

### Groq API Errors
- Check API key in `.env`
- Verify account has API access
- Check rate limits (free tier has limits)

### Twilio Not Receiving Messages
- Verify phone numbers use country code (+1 for US)
- Check Twilio balance/credits
- Verify WhatsApp is enabled on account
- Test with Twilio's Test Console first

### Database Locked
- Close all instances of the app
- Delete `ghost_email.db`
- Restart application

### ChromaDB Issues
- Delete `./chroma_db/` folder
- Restart application
- It will rebuild vector store

## 📱 WhatsApp Interaction Flow

```
📧 New Email Arrives
    ↓
🤖 AI Classification & Reply Generation
    ↓
💬 WhatsApp Interactive Message:
   [✅ Approve] [✏️ Edit] [❌ No Need]
    ↓
┌───┴───┬─────────┐
│       │         │
✅     ✏️        ❌
Send  Edit      Reject
AI    Custom
Reply Reply
  ↓      ↓        ↓
Send  Wait    Mark
Email for     Rejected
      User
      Text
      ↓
      Send
      Custom
```

## 🚀 Production Deployment

### Using Gunicorn (Production)

```bash
pip install gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

### Using Docker

```dockerfile
FROM python:3.10
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 5000 8501
CMD ["python", "start.py"]
```

```bash
docker build -t ghost-email-agent .
docker run -p 5000:5000 -p 8501:8501 ghost-email-agent
```

### Environment Variables (Production)

Set via container/platform:
```env
GROQ_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
DATABASE_PATH=/data/ghost_email.db
CHROMADB_PATH=/data/chroma_db
```

## 📚 Project Structure

```
ghost-email-manager/
├── app.py                  # Streamlit dashboard
├── main.py                 # Flask webhook server
├── start.py               # Startup manager
├── config.py              # Configuration wizard
├── database.py            # SQLite operations
├── processor.py           # Groq + ChromaDB
├── mcp_server.py          # Gmail API tools
├── whatsapp_handler.py    # WhatsApp webhook
├── requirements.txt       # Dependencies
├── .env                   # Configuration
├── credentials.json       # Gmail OAuth2
├── token.json            # Gmail token (auto-generated)
├── ghost_email.db        # SQLite database
└── chroma_db/            # Vector store
```

## 🆘 Getting Help

1. Check [README.md](README.md) for detailed docs
2. Review logs in console output
3. Check browser console (F12) for frontend errors
4. Verify all credentials in `.env`

## ✅ Verification Checklist

- [ ] Python 3.10+ installed
- [ ] All files present in project
- [ ] `requirements.txt` installed
- [ ] `.env` file configured
- [ ] Gmail credentials (`credentials.json`) saved
- [ ] Twilio credentials in `.env`
- [ ] Groq API key in `.env`
- [ ] WhatsApp webhook URL set in Twilio
- [ ] Can send test email to Gmail
- [ ] Dashboard loads at `http://localhost:8501`

## 💡 Tips

- **First run**: Gmail will prompt for authorization
- **Email sync**: Runs every 5 minutes automatically
- **Testing**: Use "Sync Emails" button to force sync
- **Development**: Set `FLASK_DEBUG=True` in `.env`
- **Logs**: All activity logged to console
- **Database**: SQLite stores all state, safe to delete chroma_db

---

**Need more help?** See [README.md](README.md) for full documentation!
