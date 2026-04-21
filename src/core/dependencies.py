from supabase import create_client, Client, ClientOptions
from src.core.config import settings

SUPABASE_POSTGREST_TIMEOUT_SECONDS = 18
SUPABASE_STORAGE_TIMEOUT_SECONDS = 20

# Initialize the client using the config object
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_key,
    options=ClientOptions(
        postgrest_client_timeout=SUPABASE_POSTGREST_TIMEOUT_SECONDS,
        storage_client_timeout=SUPABASE_STORAGE_TIMEOUT_SECONDS,
    ),
)

supabase_pub: Client = create_client(
    settings.supabase_url, 
    settings.supabase_anon_key,
    options=ClientOptions(
        postgrest_client_timeout=SUPABASE_POSTGREST_TIMEOUT_SECONDS,
        storage_client_timeout=SUPABASE_STORAGE_TIMEOUT_SECONDS,
    ),
)
