"""
Configuration utilities for Ghost Email Agent.
Handles environment setup and validation.
"""

import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv, set_key
from typing import Dict, Any, Optional


class ConfigManager:
    """Manage application configuration."""
    
    # Required environment variables
    REQUIRED_VARS = {
        "GROQ_API_KEY": "Groq API key for LLM",
        "TELEGRAM_BOT_TOKEN": "Telegram Bot token from @BotFather",
        "TELEGRAM_USER_ID": "Your Telegram user ID (get from @userinfobot)",
    }
    
    # Optional environment variables
    OPTIONAL_VARS = {
        "GMAIL_CREDENTIALS_JSON": ("credentials.json", "Path to Gmail OAuth2 credentials"),
        "CHROMADB_PATH": ("./chroma_db", "ChromaDB storage path"),
        "DATABASE_PATH": ("./ghost_email.db", "SQLite database path"),
        "STREAMLIT_PORT": ("8501", "Streamlit app port"),
    }
    
    def __init__(self, env_file: str = ".env"):
        """
        Initialize config manager.
        
        Args:
            env_file: Path to .env file
        """
        self.env_file = env_file
        self.env_path = Path(env_file)
        load_dotenv(env_file)
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """
        Validate all required configuration.
        
        Returns:
            Tuple of (is_valid, missing_vars_list)
        """
        missing = []
        
        for var, description in self.REQUIRED_VARS.items():
            if not os.getenv(var):
                missing.append(f"{var}: {description}")
        
        return len(missing) == 0, missing
    
    def setup_interactive(self) -> bool:
        """
        Interactively set up configuration.
        
        Returns:
            True if setup successful
        """
        print("\n" + "=" * 60)
        print("  🔧 Ghost Email Agent - Configuration Setup")
        print("=" * 60 + "\n")
        
        config = {}
        
        # Required variables
        print("📋 REQUIRED CONFIGURATION\n")
        
        for var, description in self.REQUIRED_VARS.items():
            current_value = os.getenv(var, "")
            
            if current_value:
                prompt = f"{var} [{current_value[:20]}...]: "
            else:
                prompt = f"{var}: "
            
            print(f"ℹ️  {description}")
            value = input(prompt).strip()
            
            if not value and not current_value:
                print(f"❌ {var} is required!\n")
                return False
            
            if value:
                config[var] = value
            
            print()
        
        # Optional variables
        print("⚙️  OPTIONAL CONFIGURATION\n")
        
        for var, (default, description) in self.OPTIONAL_VARS.items():
            current_value = os.getenv(var, default)
            
            prompt = f"{var} [{current_value}]: "
            
            print(f"ℹ️  {description}")
            value = input(prompt).strip()
            
            config[var] = value or current_value
            
            print()
        
        # Save configuration
        print("💾 Saving configuration...")
        
        for var, value in config.items():
            set_key(self.env_file, var, value)
            os.environ[var] = value
        
        print(f"✅ Configuration saved to {self.env_file}\n")
        
        return True
    
    def verify_gmail_credentials(self) -> bool:
        """
        Verify Gmail credentials file exists.
        
        Returns:
            True if credentials found
        """
        creds_file = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
        
        if not Path(creds_file).exists():
            print(f"\n⚠️  Gmail credentials file not found: {creds_file}")
            print("\n📝 To set up Gmail API:")
            print("  1. Go to https://console.cloud.google.com/")
            print("  2. Create a new project")
            print("  3. Enable Gmail API")
            print("  4. Create OAuth2 credentials (Desktop app)")
            print("  5. Download credentials JSON")
            print(f"  6. Save as: {creds_file}\n")
            
            return False
        
        return True
    
    def verify_telegram_credentials(self) -> bool:
        """
        Verify Telegram bot credentials are set.
        
        Returns:
            True if credentials set
        """
        required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID"]
        
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            print(f"\n⚠️  Missing Telegram credentials: {', '.join(missing)}")
            print("\n🤖 To set up Telegram Bot:")
            print("  1. Open Telegram and find @BotFather")
            print("  2. Create a new bot (/newbot)")
            print("  3. Copy the bot token")
            print("  4. Find @userinfobot to get your User ID")
            print("  5. Add TELEGRAM_BOT_TOKEN and TELEGRAM_USER_ID to .env file\n")
            
            return False
        
        return True
    
    def verify_groq_api(self) -> bool:
        """
        Verify Groq API key is set.
        
        Returns:
            True if API key set
        """
        if not os.getenv("GROQ_API_KEY"):
            print("\n⚠️  Groq API key not configured")
            print("\n🤖 To set up Groq API:")
            print("  1. Go to https://console.groq.com/")
            print("  2. Create account and API key")
            print("  3. Add GROQ_API_KEY to .env file\n")
            
            return False
        
        return True
    
    def create_directories(self) -> bool:
        """
        Create necessary directories.
        
        Returns:
            True if successful
        """
        dirs = [
            os.getenv("CHROMADB_PATH", "./chroma_db"),
            "./logs",
            "./data"
        ]
        
        for dir_path in dirs:
            try:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
                print(f"✓ Directory ready: {dir_path}")
            except Exception as e:
                print(f"✗ Failed to create {dir_path}: {e}")
                return False
        
        return True
    
    def print_summary(self):
        """Print configuration summary."""
        print("\n" + "=" * 60)
        print("  ✅ Configuration Summary")
        print("=" * 60 + "\n")
        
        print("📧 Gmail API:")
        print(f"  Credentials: {os.getenv('GMAIL_CREDENTIALS_JSON', 'credentials.json')}")
        
        print("\n🤖 Groq LLM:")
        groq_key = os.getenv('GROQ_API_KEY', '')
        print(f"  API Key: {groq_key[:10]}...{groq_key[-10:]}" if groq_key else "  ❌ Not set")
        
        print("\n💬 Telegram Bot:")
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        user_id = os.getenv('TELEGRAM_USER_ID', '')
        print(f"  Bot Token: {bot_token[:20]}...{bot_token[-10:]}" if bot_token else "  ❌ Not set")
        print(f"  User ID: {user_id}" if user_id else "  ❌ Not set")
        
        print("\n🗄️  Storage:")
        print(f"  Database: {os.getenv('DATABASE_PATH', 'ghost_email.db')}")
        print(f"  ChromaDB: {os.getenv('CHROMADB_PATH', './chroma_db')}")
        
        print("\n🌐 Server:")
        print(f"  Streamlit Port: {os.getenv('STREAMLIT_PORT', '8501')}")
        
        print("\n🔗 URLs:")
        print(f"  Dashboard: http://localhost:{os.getenv('STREAMLIT_PORT', '8501')}")
        
        print()


def setup_wizard():
    """Run interactive setup wizard."""
    config = ConfigManager()
    
    # Check if .env exists
    if not config.env_path.exists():
        print(f"\n📂 Creating .env file from template...")
        from shutil import copy
        if Path(".env.example").exists():
            copy(".env.example", ".env")
            print(f"✓ Created .env from .env.example")
    
    # Run interactive setup
    if not config.setup_interactive():
        print("❌ Setup failed")
        return False
    
    # Verify components
    print("\n🔍 Verifying configuration...\n")
    
    checks = [
        ("Gmail API", config.verify_gmail_credentials),
        ("Groq API", config.verify_groq_api),
        ("Telegram Bot", config.verify_telegram_credentials),
        ("Directories", config.create_directories),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"Checking {name}...", end=" ")
        result = check_func()
        print("✓" if result else "⚠️")
        results.append(result)
    
    # Validate critical items
    is_valid, missing = config.validate_config()
    
    if not is_valid:
        print("\n❌ Configuration incomplete:")
        for item in missing:
            print(f"  - {item}")
        return False
    
    # Print summary
    config.print_summary()
    
    print("✅ Setup complete! You can now run:")
    print("  - Dashboard: streamlit run app.py")
    print("  - Webhook:   python main.py")
    
    return True


if __name__ == "__main__":
    success = setup_wizard()
    sys.exit(0 if success else 1)
