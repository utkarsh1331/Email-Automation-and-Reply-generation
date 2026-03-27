"""
MCP Server for Gmail and Google Calendar integration.
"""

import json
from typing import Dict, Any
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from google_utils import GoogleAuth, GmailService, CalendarService

def create_mcp_server() -> Server:
    """
    Create MCP server with Gmail and Calendar tools.
    """
    server = Server("ghost-scheduler-mcp")
    
    # Initialize services
    auth = GoogleAuth()
    creds = auth.authenticate()
    gmail = GmailService(creds)
    calendar = CalendarService(creds)
    
    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List available tools."""
        return [
            types.Tool(
                name="list_unread_emails",
                description="Fetch the latest unread emails from Gmail",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of emails to fetch (default: 10)",
                            "default": 10
                        }
                    }
                }
            ),
            types.Tool(
                name="send_email",
                description="Send an email or reply to a thread",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "to_email": {
                            "type": "string",
                            "description": "Recipient email address"
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject"
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body content"
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Optional thread ID to reply to"
                        }
                    },
                    "required": ["to_email", "subject", "body"]
                }
            ),
            types.Tool(
                name="check_calendar",
                description="Check for meeting conflicts on a specific date and time",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date in YYYY-MM-DD format"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time in HH:MM format (24h)"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End time in HH:MM format (24h)"
                        }
                    },
                    "required": ["date", "start_time", "end_time"]
                }
            ),
            types.Tool(
                name="schedule_meeting",
                description="Create a confirmed meeting on the calendar",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Meeting title"
                        },
                        "date": {
                            "type": "string",
                            "description": "Date in YYYY-MM-DD format"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time in HH:MM format (24h)"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End time in HH:MM format (24h)"
                        }
                    },
                    "required": ["summary", "date", "start_time", "end_time"]
                }
            )
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> str:
        """Execute a tool."""
        try:
            if name == "list_unread_emails":
                max_results = arguments.get("max_results", 10)
                emails = gmail.list_unread_emails(max_results)
                return json.dumps(emails, indent=2)
            
            elif name == "send_email":
                to_email = arguments.get("to_email")
                subject = arguments.get("subject")
                body = arguments.get("body")
                thread_id = arguments.get("thread_id")
                success = gmail.send_email(to_email, subject, body, thread_id)
                return json.dumps({"success": success})
            
            elif name == "check_calendar":
                date = arguments.get("date")
                start_time = arguments.get("start_time")
                end_time = arguments.get("end_time")
                result = calendar.check_calendar(date, start_time, end_time)
                return json.dumps(result, indent=2)
            
            elif name == "schedule_meeting":
                summary = arguments.get("summary")
                date = arguments.get("date")
                start_time = arguments.get("start_time")
                end_time = arguments.get("end_time")
                link = calendar.schedule_meeting(summary, date, start_time, end_time)
                return json.dumps({"success": link is not None, "link": link})
            
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    return server

if __name__ == "__main__":
    server = create_mcp_server()
    stdio_server(server).run()
