import os
from typing import List, Dict, Any, Optional
from flask import current_app, session
from decimal import Decimal
from supabase import create_client, ClientOptions

# Conditional import for psycopg2
try:
    import psycopg2
    from psycopg2 import pool, extras
except ImportError:
    psycopg2 = None

# SUPABASE CONFIG (Read once)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_supabase_client(token=None):
    """Helper to create a Supabase client without importing from app.py."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if token:
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    return create_client(SUPABASE_URL, SUPABASE_KEY)

class BaseService:
    """Base interface for database operations."""
    def get_user_organizations(self, user_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError
    
    def get_organization_name(self, org_id: str) -> Optional[str]:
        raise NotImplementedError

    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def add_revenue(self, org_id: str, data: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def add_expense(self, org_id: str, data: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def get_investments(self, org_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_members(self, org_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_personal_banks(self, user_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_enterprise_banks(self, user_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def add_enterprise_bank(self, user_id: str, data: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def update_enterprise_bank(self, user_id: str, bank_id: str, data: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def delete_enterprise_bank(self, user_id: str, bank_id: str) -> bool:
        raise NotImplementedError

    def add_member(self, org_id: str, user_id: str, role: str = 'member') -> bool:
        raise NotImplementedError

    def find_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def get_categories(self, user_id: str) -> List[str]:
        raise NotImplementedError

    # Enterprise Credentials
    def get_business_credentials(self, user_id: str, business_name: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def create_business_credentials(self, user_id: str, business_name: str, email: str, password_hash: str, token: str) -> bool:
        raise NotImplementedError

    def verify_business_email(self, token: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

DEFAULT_CATEGORIES = [
    'Food', 'Transport', 'Utilities', 'Entertainment', 'Shopping', 
    'Health', 'Travel', 'Education', 'Salary', 'Freelance', 'Investment', 'Other'
]

class SupabaseService(BaseService):
    def __init__(self, client):
        self.db = client

    def get_user_organizations(self, user_id: str) -> List[Dict[str, Any]]:
        res = self.db.table('ent_members').select('organization_id, ent_organizations(name)').eq('user_id', user_id).execute()
        # Flattening the join result for consistency
        return [{'id': m['organization_id'], 'name': m['ent_organizations']['name']} for m in res.data]

    def get_organization_name(self, org_id: str) -> Optional[str]:
        res = self.db.table('ent_organizations').select('name').eq('id', org_id).single().execute()
        return res.data.get('name') if res.data else None

    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = self.db.table('ent_revenue').select('*, profiles(full_name), bank_accounts(bank_name)').eq('organization_id', org_id)
        if start_date:
            query = query.gte('date', start_date)
        if end_date:
            query = query.lte('date', end_date)
        res = query.order('date', desc=True).execute()
        return [{'taken_by_name': r['profiles']['full_name'] if r.get('profiles') else 'Unknown', 
                 'bank_name': r['bank_accounts']['bank_name'] if r.get('bank_accounts') else None, **r} for r in res.data]

    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = self.db.table('ent_expenses').select('*, profiles(full_name), bank_accounts(bank_name)').eq('organization_id', org_id)
        if start_date:
            query = query.gte('date', start_date)
        if end_date:
            query = query.lte('date', end_date)
        res = query.order('date', desc=True).execute()
        return [{'taken_by_name': r['profiles']['full_name'] if r.get('profiles') else 'Unknown', 
                 'bank_name': r['bank_accounts']['bank_name'] if r.get('bank_accounts') else None, **r} for r in res.data]

    def add_revenue(self, org_id: str, data: Dict[str, Any]) -> bool:
        try:
            data['organization_id'] = org_id
            self.db.table('ent_revenue').insert(data).execute()
            
            # Sync with Personal Bank if applicable
            if data.get('bank_account_id'):
                self.db.table('expenses').insert({
                    'user_id': data['taken_by'],
                    'date': data['date'],
                    'category': 'Enterprise Income',
                    'amount': data['amount'],
                    'description': f"Enterprise Revenue: {data.get('narrative', '')}",
                    'type': 'income',
                    'bank_account_id': data['bank_account_id']
                }).execute()
            return True
        except:
            return False

    def add_expense(self, org_id: str, data: Dict[str, Any]) -> bool:
        try:
            data['organization_id'] = org_id
            self.db.table('ent_expenses').insert(data).execute()
            
            # Sync with Personal Bank if applicable
            if data.get('bank_account_id'):
                self.db.table('expenses').insert({
                    'user_id': data['taken_by'],
                    'date': data['date'],
                    'category': 'Enterprise Expense',
                    'amount': data['amount'],
                    'description': f"Enterprise Expense: {data.get('narrative', '')}",
                    'type': 'expense',
                    'bank_account_id': data['bank_account_id']
                }).execute()
            return True
        except:
            return False

    def get_personal_banks(self, user_id: str) -> List[Dict[str, Any]]:
        return self.db.table('bank_accounts').select('*').eq('user_id', user_id).execute().data or []

    def get_enterprise_banks(self, user_id: str) -> List[Dict[str, Any]]:
        # Enterprise banks are local-only; Supabase has no enterprise_bank_accounts table
        return []

    def add_enterprise_bank(self, user_id: str, data: Dict[str, Any]) -> bool:
        # Enterprise banks are local-only
        return False

    def update_enterprise_bank(self, user_id: str, bank_id: str, data: Dict[str, Any]) -> bool:
        # Enterprise banks are local-only
        return False

    def delete_enterprise_bank(self, user_id: str, bank_id: str) -> bool:
        # Enterprise banks are local-only
        return False

    def get_investments(self, org_id: str) -> List[Dict[str, Any]]:
        return self.db.table('ent_investments').select('*').eq('organization_id', org_id).execute().data or []

    def get_members(self, org_id: str) -> List[Dict[str, Any]]:
        # Join with profiles to get name, email, and id
        res = self.db.table('ent_members').select('role, profiles(id, full_name, email)').eq('organization_id', org_id).execute()
        return [{'role': m['role'], 'id': m['profiles']['id'], 'full_name': m['profiles']['full_name'], 'email': m['profiles']['email']} for m in res.data]

    def find_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        res = self.db.table('profiles').select('*').eq('email', email).execute()
        return res.data[0] if res.data else None

    def get_categories(self, user_id: str) -> List[str]:
        try:
            res = self.db.table('user_categories').select('name').eq('user_id', user_id).execute()
            custom_cats = [r['name'] for r in res.data]
            return DEFAULT_CATEGORIES + custom_cats
        except:
            return DEFAULT_CATEGORIES

    def add_member(self, org_id: str, user_id: str, role: str = 'member') -> bool:
        try:
            self.db.table('ent_members').insert({
                'organization_id': org_id,
                'user_id': user_id,
                'role': role
            }).execute()
            return True
        except:
            return False

    # Enterprise Credentials — dummy (local-only feature)
    def get_business_credentials(self, user_id: str, business_name: str) -> Optional[Dict[str, Any]]:
        return None

    def create_business_credentials(self, user_id: str, business_name: str, email: str, password_hash: str, token: str) -> bool:
        return False

    def verify_business_email(self, token: str) -> Optional[Dict[str, Any]]:
        return None

class PostgresService(BaseService):
    _pool = None

    def __init__(self, connection_url: str, token: str = None):
        if not psycopg2:
            raise ImportError("psycopg2-binary is required for local PostgreSQL support.")
        
        if PostgresService._pool is None:
            PostgresService._pool = pool.SimpleConnectionPool(1, 10, connection_url)
        
        # Add Supabase client for seamless cross-DB bank access
        self.sb = get_supabase_client(token)
    
    def _execute_query(self, query: str, params: tuple = None, fetch: bool = True) -> List[Dict[str, Any]]:
        conn = PostgresService._pool.getconn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    return list(cur.fetchall())
                conn.commit()
                return []
        finally:
            PostgresService._pool.putconn(conn)

    def get_user_organizations(self, user_id: str) -> List[Dict[str, Any]]:
        # 1. Check actual membership
        query = """
            SELECT o.id, o.name 
            FROM ent_organizations o
            JOIN ent_members m ON o.id = m.organization_id
            WHERE m.user_id = %s
        """
        orgs = self._execute_query(query, (user_id,))
        
        # 2. LOCAL DEV AUTO-TRUST: If no orgs, grant access to the first seeded org
        if not orgs and os.getenv("DB_BACKEND") == "local":
            all_orgs = self._execute_query("SELECT id, name FROM ent_organizations LIMIT 1")
            if all_orgs:
                # Auto-enroll user into this org locally if they don't exist
                profile_chk = self._execute_query("SELECT id FROM profiles WHERE id = %s", (user_id,))
                if not profile_chk:
                    current_email = session.get('user_email', 'local@dev.test')
                    self._execute_query("INSERT INTO profiles (id, full_name, email) VALUES (%s, %s, %s)", 
                                      (user_id, 'Auto Local User', current_email), fetch=False)
                
                self._execute_query("INSERT INTO ent_members (organization_id, user_id, role) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", 
                                  (all_orgs[0]['id'], user_id, 'admin'), fetch=False)
                return all_orgs
        
        return orgs

    def get_organization_name(self, org_id: str) -> Optional[str]:
        query = "SELECT name FROM ent_organizations WHERE id = %s"
        res = self._execute_query(query, (org_id,))
        return res[0]['name'] if res else None

    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = """
            SELECT r.*, p.full_name as taken_by_name 
            FROM ent_revenue r
            LEFT JOIN profiles p ON r.taken_by = p.id
            WHERE r.organization_id = %s
        """
        params = [org_id]
        if start_date:
            query += " AND r.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND r.date <= %s"
            params.append(end_date)
        query += " ORDER BY r.date DESC"
        data = self._execute_query(query, tuple(params))
        
        # If we have Supabase, map bank names
        if self.sb and data:
            try:
                # Fetch all banks for current user to map names
                # (Optimization: could use IN clause with unique bank_account_ids)
                email_query = "SELECT email FROM profiles WHERE id = %s"
                current_user_email = session.get('user_email')
                if current_user_email:
                    sb_user = self.sb.table('profiles').select('id').eq('email', current_user_email).execute()
                    if sb_user.data:
                        sb_uid = sb_user.data[0]['id']
                        banks = self.sb.table('bank_accounts').select('id, bank_name').eq('user_id', sb_uid).execute()
                        bank_map = {b['id']: b['bank_name'] for b in banks.data}
                        for r in data:
                            if r.get('bank_account_id') in bank_map:
                                r['bank_name'] = bank_map[r['bank_account_id']]
            except:
                pass
        return data

    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = """
            SELECT e.*, p.full_name as taken_by_name 
            FROM ent_expenses e
            LEFT JOIN profiles p ON e.taken_by = p.id
            WHERE e.organization_id = %s
        """
        params = [org_id]
        if start_date:
            query += " AND e.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND e.date <= %s"
            params.append(end_date)
        query += " ORDER BY e.date DESC"
        data = self._execute_query(query, tuple(params))

        # Map bank names from Supabase
        if self.sb and data:
            try:
                current_user_email = session.get('user_email')
                if current_user_email:
                    sb_user = self.sb.table('profiles').select('id').eq('email', current_user_email).execute()
                    if sb_user.data:
                        sb_uid = sb_user.data[0]['id']
                        banks = self.sb.table('bank_accounts').select('id, bank_name').eq('user_id', sb_uid).execute()
                        bank_map = {b['id']: b['bank_name'] for b in banks.data}
                        for e in data:
                            if e.get('bank_account_id') in bank_map:
                                e['bank_name'] = bank_map[e['bank_account_id']]
            except:
                pass
        return data

    def add_revenue(self, org_id: str, data: Dict[str, Any]) -> bool:
        data['organization_id'] = org_id
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"INSERT INTO ent_revenue ({cols}) VALUES ({placeholders})"
        try:
            self._execute_query(query, tuple(data.values()), fetch=False)
            
            # Mirror to REAL Supabase expenses for actual bank data effect
            if data.get('bank_account_id') and self.sb:
                try:
                    # Map local user to SB user via email for correct attribution
                    email_query = "SELECT email FROM profiles WHERE id = %s"
                    local_email_res = self._execute_query(email_query, (data['taken_by'],))
                    
                    if local_email_res:
                        user_email = local_email_res[0]['email']
                        sb_user = self.sb.table('profiles').select('id').eq('email', user_email).execute()
                        
                        if sb_user.data:
                            target_sb_id = sb_user.data[0]['id']
                            self.sb.table('expenses').insert({
                                'user_id': target_sb_id,
                                'date': data['date'],
                                'category': 'Enterprise Income',
                                'amount': float(data['amount']),
                                'description': f"Enterprise Revenue: {data.get('narrative', '')}",
                                'type': 'income',
                                'bank_account_id': data['bank_account_id']
                            }).execute()
                except Exception as sb_err:
                    print(f"Supabase Sync Error (Revenue): {sb_err}")

            return True
        except Exception as e:
            print(f"Error add_revenue: {e}")
            return False

    def add_expense(self, org_id: str, data: Dict[str, Any]) -> bool:
        data['organization_id'] = org_id
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"INSERT INTO ent_expenses ({cols}) VALUES ({placeholders})"
        try:
            self._execute_query(query, tuple(data.values()), fetch=False)
            
            # Mirror to REAL Supabase expenses for actual bank data effect
            if data.get('bank_account_id') and self.sb:
                try:
                    # Map local user to SB user via email
                    email_query = "SELECT email FROM profiles WHERE id = %s"
                    local_email_res = self._execute_query(email_query, (data['taken_by'],))
                    
                    if local_email_res:
                        user_email = local_email_res[0]['email']
                        sb_user = self.sb.table('profiles').select('id').eq('email', user_email).execute()
                        
                        if sb_user.data:
                            target_sb_id = sb_user.data[0]['id']
                            self.sb.table('expenses').insert({
                                'user_id': target_sb_id,
                                'date': data['date'],
                                'category': 'Enterprise Expense',
                                'amount': float(data['amount']),
                                'description': f"Enterprise Expense: {data.get('narrative', '')}",
                                'type': 'expense',
                                'bank_account_id': data['bank_account_id']
                            }).execute()
                except Exception as sb_err:
                    print(f"Supabase Sync Error (Expense): {sb_err}")
                    
            return True
        except Exception as e:
            print(f"Error add_expense: {e}")
            return False

    def get_personal_banks(self, user_id: str) -> List[Dict[str, Any]]:
        # Map local ID through email to Supabase ID for seamless cloud access
        if self.sb:
            try:
                # 1. Get email from local profile
                email_query = "SELECT email FROM profiles WHERE id = %s"
                local_res = self._execute_query(email_query, (user_id,))
                
                if local_res:
                    user_email = local_res[0]['email']
                    # 2. Find corresponding user in Supabase
                    sb_user = self.sb.table('profiles').select('id').eq('email', user_email).execute()
                    
                    if sb_user.data:
                        sb_uid = sb_user.data[0]['id']
                        # 3. Fetch their REAL bank accounts (all columns for template)
                        res = self.sb.table('bank_accounts').select('*').eq('user_id', sb_uid).execute()
                        if res.data:
                            return res.data
            except Exception as e:
                print(f"Postgres-to-Supabase Bank Mapping Error: {e}")
        
        # Fallback to local database if email mapping fails
        query = "SELECT * FROM bank_accounts WHERE user_id = %s"
        return self._execute_query(query, (user_id,))

    def get_enterprise_banks(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch enterprise (Current/CC/OD) accounts from local PostgreSQL."""
        query = "SELECT * FROM enterprise_bank_accounts WHERE user_id = %s ORDER BY created_at DESC"
        return self._execute_query(query, (user_id,))

    def add_enterprise_bank(self, user_id: str, data: Dict[str, Any]) -> bool:
        """Insert a new enterprise bank account into local PostgreSQL."""
        try:
            query = """
                INSERT INTO enterprise_bank_accounts 
                    (user_id, business_name, bank_name, account_number, ifsc_code, opening_balance, account_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            self._execute_query(query, (
                user_id,
                data.get('business_name'),
                data.get('bank_name'),
                data.get('account_number'),
                data.get('ifsc_code'),
                data.get('opening_balance', 0.00),
                data.get('account_type', 'Current')
            ), fetch=False)
            return True
        except Exception as e:
            print(f"add_enterprise_bank error: {e}")
            return False

    def update_enterprise_bank(self, user_id: str, bank_id: str, data: Dict[str, Any]) -> bool:
        """Update an existing enterprise bank account in local PostgreSQL."""
        try:
            query = """
                UPDATE enterprise_bank_accounts 
                SET business_name = %s, bank_name = %s, account_number = %s, ifsc_code = %s, opening_balance = %s, account_type = %s
                WHERE id = %s AND user_id = %s
            """
            self._execute_query(query, (
                data.get('business_name'),
                data.get('bank_name'),
                data.get('account_number'),
                data.get('ifsc_code'),
                data.get('opening_balance', 0.00),
                data.get('account_type', 'Current'),
                bank_id,
                user_id
            ), fetch=False)
            return True
        except Exception as e:
            print(f"update_enterprise_bank error: {e}")
            return False

    def delete_enterprise_bank(self, user_id: str, bank_id: str) -> bool:
        """Delete an enterprise bank account from local PostgreSQL."""
        try:
            query = "DELETE FROM enterprise_bank_accounts WHERE id = %s AND user_id = %s"
            self._execute_query(query, (bank_id, user_id), fetch=False)
            return True
        except Exception as e:
            print(f"delete_enterprise_bank error: {e}")
            return False

    def get_categories(self, user_id: str) -> List[str]:
        # Try cloud categories via email mapping first
        if self.sb:
            try:
                email_query = "SELECT email FROM profiles WHERE id = %s"
                local_res = self._execute_query(email_query, (user_id,))
                if local_res:
                    user_email = local_res[0]['email']
                    sb_user = self.sb.table('profiles').select('id').eq('email', user_email).execute()
                    if sb_user.data:
                        sb_uid = sb_user.data[0]['id']
                        res = self.sb.table('user_categories').select('name').eq('user_id', sb_uid).execute()
                        custom_cats = [r['name'] for r in res.data]
                        return DEFAULT_CATEGORIES + custom_cats
            except:
                pass
        
        # Fallback to local
        try:
            query = "SELECT name FROM user_categories WHERE user_id = %s"
            res = self._execute_query(query, (user_id,))
            custom_cats = [r['name'] for r in res]
            return DEFAULT_CATEGORIES + custom_cats
        except:
            return DEFAULT_CATEGORIES

    def get_investments(self, org_id: str) -> List[Dict[str, Any]]:
        query = "SELECT * FROM ent_investments WHERE organization_id = %s ORDER BY date DESC"
        return self._execute_query(query, (org_id,))

    def get_members(self, org_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT m.role, p.id, p.full_name, p.email 
            FROM ent_members m
            JOIN profiles p ON m.user_id = p.id
            WHERE m.organization_id = %s
        """
        return self._execute_query(query, (org_id,))

    def find_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM profiles WHERE email = %s"
        res = self._execute_query(query, (email,))
        return res[0] if res else None

    def add_member(self, org_id: str, user_id: str, role: str = 'member') -> bool:
        query = "INSERT INTO ent_members (organization_id, user_id, role) VALUES (%s, %s, %s)"
        try:
            self._execute_query(query, (org_id, user_id, role), fetch=False)
            return True
        except:
            return False

    # Enterprise Credentials
    def get_business_credentials(self, user_id: str, business_name: str) -> Optional[Dict[str, Any]]:
        """Check if a business already has registered credentials."""
        try:
            query = "SELECT * FROM enterprise_credentials WHERE user_id = %s AND business_name = %s"
            res = self._execute_query(query, (user_id, business_name))
            return res[0] if res else None
        except Exception as e:
            print(f"get_business_credentials error: {e}")
            return None

    def create_business_credentials(self, user_id: str, business_name: str, email: str, password_hash: str, token: str) -> bool:
        """Insert new business credentials into local PostgreSQL."""
        try:
            query = """
                INSERT INTO enterprise_credentials
                    (user_id, business_name, email, password_hash, verification_token)
                VALUES (%s, %s, %s, %s, %s)
            """
            self._execute_query(query, (user_id, business_name, email, password_hash, token), fetch=False)
            return True
        except Exception as e:
            print(f"create_business_credentials error: {e}")
            return False

    def verify_business_email(self, token: str) -> Optional[Dict[str, Any]]:
        """Mark a business credential as verified via token."""
        try:
            query = """
                UPDATE enterprise_credentials
                SET is_verified = TRUE, verification_token = NULL
                WHERE verification_token = %s
                RETURNING *
            """
            res = self._execute_query(query, (token,))
            return res[0] if res else None
        except Exception as e:
            print(f"verify_business_email error: {e}")
            return None

def get_db_service(token=None):
    """Factory function to get the correct database service."""
    backend = os.getenv("DB_BACKEND", "supabase").lower()
    
    if backend == "local":
        # Use DATABASE_URL from .env or a default
        db_url = os.getenv("DATABASE_URL")
        return PostgresService(db_url, token)
    else:
        # Pass the local helper instead of importing from app.py
        return SupabaseService(get_supabase_client(token))
