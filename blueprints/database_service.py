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
    # added below:
    def get_holding_payments(self, org_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_banks_for_org(self, user_id: str, org_name: str) -> List[Dict[str, Any]]:
        """Return enterprise bank accounts scoped to the active business name."""
        raise NotImplementedError

    def provision_business_org(self, user_id: str, business_name: str) -> Optional[str]:
        """Ensure a dedicated org exists for this business_name; return its id."""
        raise NotImplementedError

    def add_org_member(self, org_id: str, name: str, designation: str) -> bool:
        """Add a named staff member to the org's ent_staff table."""
        raise NotImplementedError

    def get_org_members(self, org_id: str) -> List[Dict[str, Any]]:
        """Return all staff members for this org."""
        raise NotImplementedError

    def add_holding_payment(self, org_id: str, user_id: str, data: dict) -> bool:
        raise NotImplementedError

    def settle_holding_payment(self, txn_id: str, org_id: str, settle_type: str, part_amount: float = 0) -> dict:
        raise NotImplementedError

    def get_business_credentials(self, user_id: str, business_name: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def create_business_credentials(self, user_id: str, business_name: str, email: str, password_hash: str, token: str) -> bool:
        raise NotImplementedError

    def verify_business_email(self, token: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def add_investment(self, org_id: str, data: dict) -> bool:
        raise NotImplementedError

    def get_user_businesses(self, user_id: str) -> List[Dict[str, Any]]:
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

    def get_org_id_by_name(self, user_id: str, org_name: str) -> Optional[str]:
        """Return the org id whose name matches org_name for orgs the user belongs to."""
        res = self.db.table('ent_members').select('organization_id, ent_organizations(name)').eq('user_id', user_id).execute()
        for m in res.data:
            if m.get('ent_organizations', {}).get('name') == org_name:
                return str(m['organization_id'])
        return None

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

    def get_banks_for_org(self, user_id: str, org_name: str) -> List[Dict[str, Any]]:
        # Enterprise banks are local-only; Supabase has no enterprise_bank_accounts table
        return []

    def provision_business_org(self, user_id: str, business_name: str) -> Optional[str]:
        # Supabase orgs are managed separately; return None
        return None

    def add_org_member(self, org_id: str, name: str, designation: str) -> bool:
        try:
            self.db.table('ent_staff').insert(
                {'organization_id': org_id, 'name': name, 'designation': designation}
            ).execute()
            return True
        except Exception as e:
            print(f"[add_org_member] {e}")
            return False

    def get_org_members(self, org_id: str) -> List[Dict[str, Any]]:
        try:
            res = self.db.table('ent_staff').select('*').eq('organization_id', org_id).order('name').execute()
            return res.data or []
        except Exception:
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

    def get_personal_transactions(self, user_id: str, filters: dict) -> List[Dict[str, Any]]:
        """Fetch filtered personal transactions strictly from Supabase (personal data only)."""
        try:
            query = self.db.table('expenses').select(
                'id, date, category, description, amount, type, bank_account_id, bank_accounts(bank_name)'
            ).eq('user_id', user_id)

            # Date range
            if filters.get('start_date'):
                query = query.gte('date', filters['start_date'])
            if filters.get('end_date'):
                query = query.lte('date', filters['end_date'])

            # Category filter
            if filters.get('category') and filters['category'] != 'all':
                query = query.eq('category', filters['category'])

            # Transaction type filter (income / expense)
            if filters.get('tx_type') and filters['tx_type'] != 'all':
                query = query.eq('type', filters['tx_type'])

            # Payment method (cash = no bank_account_id, bank = has bank_account_id)
            if filters.get('payment_method') == 'cash':
                query = query.is_('bank_account_id', 'null')
            elif filters.get('payment_method') == 'bank':
                query = query.not_.is_('bank_account_id', 'null')

            res = query.order('date', desc=True).execute()
            rows = []
            for r in (res.data or []):
                bank_name = None
                if r.get('bank_accounts') and isinstance(r['bank_accounts'], dict):
                    bank_name = r['bank_accounts'].get('bank_name')
                rows.append({
                    'id':             r.get('id'),
                    'date':           r.get('date', ''),
                    'category':       r.get('category', 'Uncategorized'),
                    'description':    r.get('description', ''),
                    'amount':         float(r.get('amount', 0)),
                    'type':           r.get('type', 'expense'),
                    'payment_method': bank_name if bank_name else 'Cash',
                })
            return rows
        except Exception as e:
            print(f"get_personal_transactions error: {e}")
            return []


    def get_holding_payments(self, org_id: str) -> List[Dict[str, Any]]:
        try:
            res = self.db.table('ent_holding_payments').select('*').eq('organization_id', org_id).order('created_at', desc=True).execute()
            return res.data or []
        except Exception as e:
            print(f"Error fetching holding payments: {e}")
            return []

    def add_holding_payment(self, org_id: str, user_id: str, data: dict) -> bool:
        try:
            self.db.table('ent_holding_payments').insert({
                'organization_id': org_id,
                'created_by': user_id,
                'name': data.get('name'),
                'type': data.get('type', 'receivable'),
                'amount': float(data.get('amount', 0)),
                'expected_date': data.get('expected_date') or None,
                'mobile_no': data.get('mobile_no'),
                'narrative': data.get('narrative'),
                'status': 'pending',
                'paid_amount': 0,
                'remaining_amount': float(data.get('amount', 0))
            }).execute()
            return True
        except Exception as e:
            print(f"Error adding holding payment: {e}")
            return False

    def settle_holding_payment(self, txn_id: str, org_id: str, settle_type: str, part_amount: float = 0) -> dict:
        try:
            res = self.db.table('ent_holding_payments').select('*').eq('id', txn_id).eq('organization_id', org_id).single().execute()
            if not res.data:
                return {'success': False, 'error': 'Transaction not found.'}
            txn = res.data
            original = float(txn.get('amount', 0))
            paid_so_far = float(txn.get('paid_amount', 0))

            if settle_type == 'full':
                new_paid = original
                new_remaining = 0
                new_status = 'settled'
            else:
                new_paid = paid_so_far + part_amount
                new_remaining = max(original - new_paid, 0)
                new_status = 'settled' if new_remaining == 0 else 'partial'

            self.db.table('ent_holding_payments').update({
                'paid_amount': new_paid,
                'remaining_amount': new_remaining,
                'status': new_status
            }).eq('id', txn_id).execute()
            return {'success': True, 'status': new_status, 'paid': new_paid, 'remaining': new_remaining}
        except Exception as e:
            print(f"Error settling holding payment: {e}")
            return {'success': False, 'error': str(e)} 

    def add_investment(self, org_id: str, data: dict) -> bool:
        try:
            self.db.table('ent_investments').insert({
                'organization_id': org_id,
                'amount': float(data.get('amount', 0)),
                'date': data.get('date'),
                'type': data.get('type', 'investment'),
                'taken_by': data.get('taken_by', '').strip() or None,
                'narrative': data.get('narrative', '').strip() or None,
                'source': data.get('taken_by', '').strip() or None,
                'description': data.get('narrative', '').strip() or None,
            }).execute()
            return True
        except Exception as e:
            print(f"Error adding investment: {e}")
            return False

    # Enterprise Credentials — dummy (local-only feature)
    def get_business_credentials(self, user_id: str, business_name: str) -> Optional[Dict[str, Any]]:
        return None

    def create_business_credentials(self, user_id: str, business_name: str, email: str, password_hash: str, token: str) -> bool:
        return False

    def verify_business_email(self, token: str) -> Optional[Dict[str, Any]]:
        return None

    def add_investment(self, org_id: str, data: dict) -> bool:
        # Investment recording is local-only (PostgreSQL)
        return False

    def get_user_businesses(self, user_id: str) -> List[Dict[str, Any]]:
        # Business discovery via Supabase not yet implemented
        return []

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

    def get_org_id_by_name(self, user_id: str, org_name: str) -> Optional[str]:
        """Return org id whose name matches org_name, scoped to orgs the user belongs to."""
        query = """
            SELECT o.id FROM ent_organizations o
            JOIN ent_members m ON o.id = m.organization_id
            WHERE m.user_id = %s AND o.name = %s
            LIMIT 1
        """
        res = self._execute_query(query, (user_id, org_name))
        return str(res[0]['id']) if res else None

    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = """
            SELECT r.*, p.full_name as taken_by_name, b.bank_name, b.account_type 
            FROM ent_revenue r
            LEFT JOIN profiles p ON r.taken_by = p.id
            LEFT JOIN enterprise_bank_accounts b ON r.bank_account_id = b.id
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
        
        return data

    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        query = """
            SELECT e.*, p.full_name as taken_by_name, b.bank_name, b.account_type 
            FROM ent_expenses e
            LEFT JOIN profiles p ON e.taken_by = p.id
            LEFT JOIN enterprise_bank_accounts b ON e.bank_account_id = b.id
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
        """Fetch enterprise (Current/CC/OD) accounts from local PostgreSQL with computed current_balance."""
        query = """
            SELECT b.*,
                   COALESCE(b.opening_balance, 0)
                   + COALESCE((SELECT SUM(amount) FROM ent_revenue r WHERE r.bank_account_id = b.id), 0)
                   - COALESCE((SELECT SUM(amount) FROM ent_expenses e WHERE e.bank_account_id = b.id), 0)
                   AS current_balance
            FROM enterprise_bank_accounts b
            WHERE b.user_id = %s 
            ORDER BY b.created_at DESC
        """
        return self._execute_query(query, (user_id,))

    def get_banks_for_org(self, user_id: str, org_name: str) -> List[Dict[str, Any]]:
        """Return enterprise bank accounts scoped to the active business name with computed current_balance."""
        query = """
            SELECT b.*,
                   COALESCE(b.opening_balance, 0)
                   + COALESCE((SELECT SUM(amount) FROM ent_revenue r WHERE r.bank_account_id = b.id), 0)
                   - COALESCE((SELECT SUM(amount) FROM ent_expenses e WHERE e.bank_account_id = b.id), 0)
                   AS current_balance
            FROM enterprise_bank_accounts b
            WHERE b.user_id = %s AND b.business_name = %s 
            ORDER BY b.created_at DESC
        """
        return self._execute_query(query, (user_id, org_name))


    def provision_business_org(self, user_id: str, business_name: str) -> Optional[str]:
        """Idempotently create a dedicated org for this business and enroll the user. Returns org_id."""
        conn = PostgresService._pool.getconn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT o.id FROM ent_organizations o
                       JOIN ent_members m ON o.id = m.organization_id
                       WHERE o.name = %s AND m.user_id = %s
                       LIMIT 1""",
                    (business_name, user_id)
                )
                existing = cur.fetchone()
                if existing:
                    return str(existing['id'])

                cur.execute(
                    "INSERT INTO ent_organizations (name) VALUES (%s) RETURNING id",
                    (business_name,)
                )
                new_org = cur.fetchone()
                if not new_org:
                    return None
                org_id = str(new_org['id'])

                cur.execute(
                    """INSERT INTO ent_members (organization_id, user_id, role)
                       VALUES (%s, %s, 'admin')
                       ON CONFLICT (organization_id, user_id) DO NOTHING""",
                    (org_id, user_id)
                )

            conn.commit()
            return org_id
        except Exception as e:
            conn.rollback()
            print(f"[provision_business_org] Error: {e}")
            return None
        finally:
            PostgresService._pool.putconn(conn)

    def add_org_member(self, org_id: str, name: str, designation: str) -> bool:
        """Insert a named staff member into ent_staff for this org."""
        import uuid
        conn = PostgresService._pool.getconn()
        try:
            with conn.cursor() as cur:
                # Create table if it doesn't exist (no pgcrypto needed - id supplied by Python)
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS ent_staff (
                        id              TEXT PRIMARY KEY,
                        organization_id TEXT NOT NULL,
                        name            TEXT NOT NULL,
                        designation     TEXT,
                        created_at      TIMESTAMPTZ DEFAULT now()
                    )"""
                )
                cur.execute(
                    "INSERT INTO ent_staff (id, organization_id, name, designation) VALUES (%s, %s, %s, %s)",
                    (str(uuid.uuid4()), org_id, name, designation)
                )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"[add_org_member] {e}")
            return False
        finally:
            PostgresService._pool.putconn(conn)

    def get_org_members(self, org_id: str) -> List[Dict[str, Any]]:
        """Return all staff for this org. Returns [] if table doesn't exist yet."""
        conn = PostgresService._pool.getconn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ent_staff WHERE organization_id = %s ORDER BY name",
                    (org_id,)
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            # Table might not exist yet (no one has added a member)
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[get_org_members] {e}")
            return []
        finally:
            PostgresService._pool.putconn(conn)


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

# added

    def add_investment(self, org_id: str, data: dict) -> bool:
        query = """
            INSERT INTO ent_investments
                (organization_id, amount, date, type, taken_by, narrative, source, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            taken_by  = data.get('taken_by', '').strip() or None
            narrative = data.get('narrative', '').strip() or None
            self._execute_query(query, (
                org_id,
                float(data.get('amount', 0)),
                data.get('date'),
                data.get('type', 'investment'),
                taken_by,
                narrative,
                taken_by,
                narrative,
            ), fetch=False)
            return True
        except Exception as e:
            print(f"Error adding investment: {e}")
            return False


    def get_holding_payments(self, org_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT id, name, type, amount,
                   COALESCE(paid_amount, 0) AS paid_amount,
                   COALESCE(remaining_amount, amount) AS remaining_amount,
                   expected_date, mobile_no, narrative, status, created_at
            FROM ent_holding_payments
            WHERE organization_id = %s
            ORDER BY created_at DESC
        """
        try:
            return self._execute_query(query, (org_id,))
        except Exception as e:
            print(f"Error fetching holding payments: {e}")
            return []


    def add_holding_payment(self, org_id: str, user_id: str, data: dict) -> bool:
        query = """
            INSERT INTO ent_holding_payments
                (organization_id, created_by, name, type, amount, expected_date, mobile_no, narrative, status, paid_amount, remaining_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', 0, %s)
        """
        try:
            amt = float(data.get('amount', 0))
            self._execute_query(query, (
                org_id, user_id,
                data.get('name'),
                data.get('type', 'receivable'),
                amt,
                data.get('expected_date') or None,
                data.get('mobile_no'),
                data.get('narrative'),
                amt
            ), fetch=False)
            return True
        except Exception as e:
            print(f"Error adding holding payment: {e}")
            return False

    def settle_holding_payment(self, txn_id: str, org_id: str, settle_type: str, part_amount: float = 0) -> dict:
        try:
            res = self._execute_query(
                "SELECT amount, paid_amount, remaining_amount FROM ent_holding_payments WHERE id = %s AND organization_id = %s",
                (txn_id, org_id)
            )
            if not res:
                return {'success': False, 'error': 'Transaction not found.'}
            txn = res[0]
            original    = float(txn.get('amount', 0))
            paid_so_far = float(txn.get('paid_amount', 0) or 0)

            if settle_type == 'full':
                new_paid      = original
                new_remaining = 0
                new_status    = 'settled'
            else:
                new_paid      = paid_so_far + part_amount
                new_remaining = max(original - new_paid, 0)
                new_status    = 'settled' if new_remaining == 0 else 'partial'

            self._execute_query(
                "UPDATE ent_holding_payments SET paid_amount=%s, remaining_amount=%s, status=%s WHERE id=%s",
                (new_paid, new_remaining, new_status, txn_id), fetch=False
            )
            return {'success': True, 'status': new_status, 'paid': new_paid, 'remaining': new_remaining}
        except Exception as e:
            print(f"Error settling holding payment: {e}")
            return {'success': False, 'error': str(e)}


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

    def get_user_businesses(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all businesses registered by this user."""
        try:
            res = self._execute_query(
                "SELECT business_name, email FROM enterprise_credentials WHERE user_id = %s ORDER BY business_name",
                (user_id,)
            )
            return res or []
        except Exception as e:
            print(f"get_user_businesses error: {e}")
            return []

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
