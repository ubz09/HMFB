import os
import aiohttp
from datetime import datetime
from typing import Optional, List, Dict, Any
import asyncio
import json # <--- ¡CORRECCIÓN CLAVE!

DATABASE_FILE = "accounts.json"
LOG_FILE = "accounts.log"
GITHUB_ACCOUNTS_URL = "https://raw.githubusercontent.com/MierdaCraft/grkisdlnnnnnnnnnnnnnnnnnnd2304kfjasnofasnf39f82jfasioflasfjn93fnujanfnaskgalsg/refs/heads/main/accounts.json"


class DatabaseManager:
    """Manages the database for Minecraft accounts (fetches from GitHub)"""
    
    @staticmethod
    async def _fetch_from_github() -> Dict[str, Any]:
        """Fetch accounts from GitHub"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(GITHUB_ACCOUNTS_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            print(f"Error fetching from GitHub: {str(e)}")
        
        # Fallback to local file if GitHub fetch fails
        return DatabaseManager._load_local_database()
    
    @staticmethod
    def _load_local_database() -> Dict[str, Any]:
        """Load the database from local JSON file (fallback)"""
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, 'r') as f:
                return json.load(f)
        return {"accounts": []}
    
    @staticmethod
    def _load_database() -> Dict[str, Any]:
        """Load the database (uses async fetch)"""
        # Since this is called from sync context, we need to run the async function
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, use local database
                return DatabaseManager._load_local_database()
            return loop.run_until_complete(DatabaseManager._fetch_from_github())
        except:
            return DatabaseManager._load_local_database()
    
    @staticmethod
    def _save_database(data: Dict[str, Any]):
        """Save the database to local JSON file (fallback for GitHub)"""
        # Save locally as fallback
        with open(DATABASE_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        # Note: Direct GitHub push requires authentication
        # Consider implementing a separate push mechanism or use GitHub Actions
        print(f"Database saved locally to {DATABASE_FILE}")
        print(f"Note: Manual push to GitHub required or use CI/CD pipeline")
    
    
    @staticmethod
    def _log_action(status: str, account_data: Dict[str, str]):
        """Log account actions to the log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Build log message based on available data
        log_parts = [f"[{timestamp}] STATUS: {status}"]
        
        if "ign" in account_data:
            log_parts.append(f"User: {account_data['ign']}")
        
        if "email" in account_data:
            log_parts.append(f"Email: {account_data['email']}")
        
        if "password" in account_data:
            log_parts.append(f"Pass: {account_data['password']}")
        
        log_message = " | ".join(log_parts)
        
        with open(LOG_FILE, 'a') as f:
            f.write(log_message + "\n")
    
    @staticmethod
    def add_account(account_id: str, email: str, password: str, ign: str) -> tuple[bool, str]:
        """Add a new account to the database"""
        try:
            database = DatabaseManager._load_database()
            
            # Check if account already exists
            for account in database["accounts"]:
                if account["id"] == account_id:
                    return False, f"Account with ID `{account_id}` already exists!"
            
            # Create new account
            new_account = {
                "id": account_id,
                "email": email,
                "password": password,
                "ign": ign,
                "status": "ADDED",
                "added_at": datetime.now().isoformat()
            }
            
            database["accounts"].append(new_account)
            DatabaseManager._save_database(database)
            DatabaseManager._log_action("ADDED", {"ign": ign, "email": email, "password": password})
            
            return True, f"Account `{ign}` added successfully!"
        except Exception as e:
            return False, f"Error adding account: {str(e)}"
    
    @staticmethod
    def edit_account(account_id: str, email: str, password: str, ign: str) -> tuple[bool, str]:
        """Edit an existing account"""
        try:
            database = DatabaseManager._load_database()
            
            for account in database["accounts"]:
                if account["id"] == account_id:
                    account["email"] = email
                    account["password"] = password
                    account["ign"] = ign
                    DatabaseManager._save_database(database)
                    DatabaseManager._log_action("EDITED", {"ign": ign, "email": email, "password": password})
                    return True, f"Account `{account_id}` updated successfully!"
            
            return False, f"Account with ID `{account_id}` not found!"
        except Exception as e:
            return False, f"Error editing account: {str(e)}"
    
    @staticmethod
    def distribute_account(account_id: str) -> tuple[bool, str]:
        """Mark an account as distributed"""
        try:
            database = DatabaseManager._load_database()
            
            for account in database["accounts"]:
                if account["id"] == account_id:
                    account["status"] = "DISTRIBUTED"
                    DatabaseManager._save_database(database)
                    DatabaseManager._log_action("DISTRIBUTED", {"ign": account["ign"], "email": account["email"], "password": account["password"]})
                    return True, f"Account `{account_id}` marked as distributed!"
            
            return False, f"Account with ID `{account_id}` not found!"
        except Exception as e:
            return False, f"Error distributing account: {str(e)}"
    
    @staticmethod
    def get_account(account_id: str) -> Optional[Dict[str, Any]]:
        """Get an account by ID"""
        try:
            database = DatabaseManager._load_database()
            for account in database["accounts"]:
                if account["id"] == account_id:
                    return account
            return None
        except Exception as e:
            print(f"Error getting account: {str(e)}")
            return None
    
    @staticmethod
    def get_all_accounts() -> List[Dict[str, Any]]:
        """Get all accounts from the database"""
        try:
            database = DatabaseManager._load_database()
            return database["accounts"]
        except Exception as e:
            print(f"Error getting accounts: {str(e)}")
            return []
    
    @staticmethod
    def delete_account(account_id: str) -> tuple[bool, str]:
        """Delete an account from the database"""
        try:
            database = DatabaseManager._load_database()
            
            for i, account in enumerate(database["accounts"]):
                if account["id"] == account_id:
                    deleted_account = database["accounts"].pop(i)
                    DatabaseManager._save_database(database)
                    DatabaseManager._log_action("DELETED", {"ign": deleted_account["ign"], "email": deleted_account["email"], "password": deleted_account["password"]})
                    return True, f"Account `{account_id}` deleted successfully!"
            
            return False, f"Account with ID `{account_id}` not found!"
        except Exception as e:
            return False, f"Error deleting account: {str(e)}"
