"""
Startup script to run Ghost Email Agent.
Manages both Flask webhook server and Streamlit dashboard.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import signal
from threading import Thread
import warnings
import logging

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("start")

class GhostEmailStartup:
    """Manage startup of Ghost Email Agent."""
    
    def __init__(self):
        """Initialize startup manager."""
        load_dotenv()
        self.processes = []
        self.python_exe = self._get_python_executable()
    
    def _get_python_executable(self) -> str:
        """Get the best python executable to use (venv or current)."""
        # Check if we are already in a venv
        if sys.prefix != sys.base_prefix:
            return sys.executable
            
        # Check for common venv locations
        venv_paths = [
            Path("venv313/Scripts/python.exe"),
            Path("venv313/bin/python"),
            Path("venv/Scripts/python.exe"),
            Path("venv/bin/python"),
            Path(".venv/Scripts/python.exe"),
            Path(".venv/bin/python")
        ]
        
        for path in venv_paths:
            if path.exists():
                print(f"✓ Found virtual environment: {path}")
                return str(path.absolute())
                
        return sys.executable
    
    def check_prerequisites(self) -> bool:
        """Check if all prerequisites are met."""
        print("\n" + "=" * 60)
        print("  🔍 Checking Prerequisites")
        print("=" * 60 + "\n")
        
        # Check Python version
        if sys.version_info < (3, 10):
            print(f"❌ Python 3.10+ required (you have {sys.version})")
            return False
        print("✓ Python version OK")
        
        # Check required files
        required_files = [
            "requirements.txt",
            "app.py",
            "main.py",
            "database.py",
            "processor.py",
            "mcp_server.py"
        ]
        
        for file in required_files:
            if not Path(file).exists():
                print(f"❌ Missing file: {file}")
                return False
        print("✓ All required files present")
        
        # Check .env file
        if not Path(".env").exists():
            print("⚠️  .env file not found. Running setup wizard...")
            
            # Run config setup
            try:
                from config import setup_wizard
                if not setup_wizard():
                    return False
            except Exception as e:
                print(f"❌ Setup wizard failed: {e}")
                return False
        
        print("✓ .env configuration exists")
        
        # Check Gmail credentials
        gmail_creds = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
        if not Path(gmail_creds).exists():
            print(f"\n⚠️  Gmail credentials not found: {gmail_creds}")
            print("First run will prompt you to authorize Gmail API")
        else:
            print(f"✓ Gmail credentials found: {gmail_creds}")
        
        # Validate critical env vars
        required_vars = [
            "GROQ_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_USER_ID"
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            print(f"\n❌ Missing required environment variables: {', '.join(missing)}")
            print("Please run: python config.py")
            return False
        
        print("✓ All required environment variables set")
        return True
    
    def create_directories(self):
        """Create necessary directories."""
        dirs = [
            os.getenv("CHROMADB_PATH", "./chroma_db"),
            "./logs",
            "./data"
        ]
        
        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def run_fastapi_server(self):
        """Run FastAPI webhook server."""
        logger.info("Starting backend (Telegram bot + email scheduler)...")
        
        try:
            cmd = [self.python_exe, "main.py"]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.processes.append(("FastAPI", process))
            
            # Ensure we print important lines like OAuth prompts, while keeping others clean
            for line in process.stdout:
                stripped = line.strip()
                if not stripped:
                    continue
                important_keywords = ["ERROR", "CRITICAL", "FATAL", "❌", "[FAIL]", "Please visit", "http://localhost", "https://accounts.google.com"]
                if any(k in stripped for k in important_keywords):
                    print(f"  [Backend] {stripped}")
        
        except Exception as e:
            logger.error(f"Failed to start backend server: {e}")
    
    def run_streamlit_dashboard(self):
        """Run Streamlit dashboard."""
        print(f"\n📊 Starting Streamlit dashboard...")
        
        try:
            port = os.getenv("STREAMLIT_PORT", "8501")
            cmd = [
                self.python_exe, "-m", "streamlit", "run",
                "app.py",
                "--server.port=" + port,
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
                "--logger.level=info"
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.processes.append(("Streamlit", process))
            
            # Print output
            for line in process.stdout:
                print(f"  [Streamlit] {line.strip()}")
        
        except Exception as e:
            print(f"❌ Failed to start Streamlit: {e}")
    
    def print_startup_info(self):
        """Print startup information."""
        print("\n" + "=" * 60)
        print("  ✅ Ghost Email Agent is Running!")
        print("=" * 60 + "\n")
        
        print("🌐 ACCESS POINTS:")
        print(f"  📊 Dashboard:  http://localhost:{os.getenv('STREAMLIT_PORT', '8501')}")
        print(f"  ❤️  Health:     http://localhost:{os.getenv('API_PORT', '5000')}/health")
        
        print("\n💾 STORAGE:")
        print(f"  Database: {os.getenv('DATABASE_PATH', 'ghost_email.db')}")
        print(f"  ChromaDB: {os.getenv('CHROMADB_PATH', './chroma_db')}")
        
        print("\n⏱️  EMAIL SYNC:")
        print("  Scheduled: Every 5 minutes")
        print("  Last sync: Not started")
        
        print("\n🛑 TO STOP:")
        print("  Press Ctrl+C")
        
        print("\n📝 LOGS:")
        print("  Check console output above")
        print("  Errors will appear in red")
        
        print("\n" + "=" * 60 + "\n")
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signal."""
        print("\n\n⏸️  Shutting down Ghost Email Agent...")
        
        for name, process in self.processes:
            print(f"  Stopping {name}...", end=" ")
            try:
                process.terminate()
                process.wait(timeout=5)
                print("✓")
            except subprocess.TimeoutExpired:
                print("(force killed)")
                process.kill()
            except Exception as e:
                print(f"(error: {e})")
        
        print("✅ Shutdown complete\n")
        sys.exit(0)
    
    def run(self):
        """Run startup sequence."""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        # Check prerequisites
        if not self.check_prerequisites():
            sys.exit(1)
        
        # Create directories
        self.create_directories()
        print("✓ Directories ready")
        
        # Start services
        print("\n" + "=" * 60)
        print("  🚀 Starting Ghost Email Agent Services")
        print("=" * 60)
        
        # Start FastAPI in background thread
        fastapi_thread = Thread(target=self.run_fastapi_server, daemon=True)
        fastapi_thread.start()
        
        # Wait a bit for FastAPI to start
        time.sleep(2)
        
        # Start Streamlit in main thread (blocking)
        # This way Streamlit output goes to console
        print(f"\n📊 Starting Streamlit dashboard...")
        
        try:
            port = os.getenv("STREAMLIT_PORT", "8501")
            cmd = [
                self.python_exe, "-m", "streamlit", "run",
                "app.py",
                "--server.port=" + port,
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
                "--logger.level=info",
                "--client.showErrorDetails=true"
            ]
            
            self.print_startup_info()
            
            # Run Streamlit (blocking) - suppress its verbose output
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        except KeyboardInterrupt:
            self.handle_shutdown(None, None)
        except Exception as e:
            print(f"❌ Error: {e}")
            self.handle_shutdown(None, None)


def main():
    """Main entry point."""
    startup = GhostEmailStartup()
    startup.run()


if __name__ == "__main__":
    main()
