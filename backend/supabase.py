import os
from supabase import create_client, Client
from dotenv import load_dotenv
 
# Load environment variables
load_dotenv()
 
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
 
supabase: Client | None = None
 
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
else:
    print("Warning: SUPABASE_URL and SUPABASE_KEY are not set. Supabase functions will not work.")
 
def sign_up(email, password):
    """Sign up a new user with email and password."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    return supabase.auth.sign_up({"email": email, "password": password})
 
def sign_in(email, password):
    """Sign in an existing user with email and password."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    return supabase.auth.sign_in_with_password({"email": email, "password": password})
 
def sign_out():
    """Sign out the current user session."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    return supabase.auth.sign_out()
 
def create_project(user_id: str, name: str) -> dict:
    """Create a new project associated with the user."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("projects").insert({
        "user_id": user_id,
        "name": name
    }).execute()
    return response.data[0] if response.data else {}
 
def get_projects(user_id: str) -> list[dict]:
    """Retrieve all projects created by the given user."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("projects")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .execute()
    return response.data or []
 
def upload_transcript(project_id: str, content: str) -> dict:
    """Upload or update a client transcript for a project."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("transcripts").upsert({
        "project_id": project_id,
        "content": content
    }, on_conflict="project_id").execute()
    return response.data[0] if response.data else {}
 
def get_transcript(project_id: str) -> dict:
    """Retrieve the transcript associated with a project."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("transcripts")\
        .select("*")\
        .eq("project_id", project_id)\
        .execute()
    return response.data[0] if response.data else {}
 
def save_report(project_id: str, report_data: dict) -> dict:
    """Upload or update project report data."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("reports").upsert({
        "project_id": project_id,
        "report_data": report_data
    }, on_conflict="project_id").execute()
    return response.data[0] if response.data else {}
 
def get_report(project_id: str) -> dict:
    """Retrieve the report associated with a project."""
    if not supabase:
        raise ValueError("Supabase is not initialized. Check your environment variables.")
    response = supabase.table("reports")\
        .select("*")\
        .eq("project_id", project_id)\
        .execute()
    return response.data[0] if response.data else {}