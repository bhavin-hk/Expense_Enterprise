import os
from typing import List, Dict, Any, Optional
from supabase import create_client, ClientOptions

# ── Supabase Config ────────────────────────────────────────────────────────────
# Note: Do NOT read env vars at module level — dotenv may not be loaded yet.

def get_supabase_client(token=None):
    """Create a Supabase client, optionally scoped to a user JWT."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    if token:
        return create_client(
            url, key,
            options=ClientOptions(headers={"Authorization": f"Bearer {token}"})
        )
    return create_client(url, key)

def get_supabase_service_client():
    """Create a Supabase client bypassing RLS using the Service Role Key."""
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_key:
        return None
    return create_client(url, service_key)

DEFAULT_CATEGORIES = [
    'Food', 'Transport', 'Utilities', 'Entertainment', 'Shopping',
    'Health', 'Travel', 'Education', 'Salary', 'Freelance', 'Investment', 'Other'
]

# ── Service Interface ──────────────────────────────────────────────────────────
class BaseService:
    """Abstract interface — all methods raise NotImplementedError by default."""
    def get_user_organizations(self, user_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_organization_name(self, org_id: str) -> Optional[str]: raise NotImplementedError
    def get_org_id_by_name(self, user_id: str, org_name: str) -> Optional[str]: raise NotImplementedError
    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None, firm: str = None) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None, firm: str = None) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_revenue(self, org_id: str, data: Dict[str, Any]) -> bool: raise NotImplementedError
    def add_expense(self, org_id: str, data: Dict[str, Any]) -> bool: raise NotImplementedError
    def get_investments(self, org_id: str, start_date: str = None, end_date: str = None, inv_type: str = None, taken_by: str = None, firm: str = None) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_investment(self, org_id: str, data: dict) -> bool: raise NotImplementedError
    def get_members(self, org_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_member(self, org_id: str, user_id: str, role: str = 'member') -> bool: raise NotImplementedError
    def find_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]: raise NotImplementedError
    def get_personal_banks(self, user_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_enterprise_banks(self, user_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_banks_for_org(self, user_id: str, org_name: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_enterprise_bank(self, user_id: str, data: Dict[str, Any]) -> bool: raise NotImplementedError
    def update_enterprise_bank(self, user_id: str, bank_id: str, data: Dict[str, Any]) -> bool: raise NotImplementedError
    def delete_enterprise_bank(self, user_id: str, bank_id: str) -> bool: raise NotImplementedError
    def get_categories(self, user_id: str) -> List[str]: raise NotImplementedError
    def get_split_categories(self, user_id: str) -> dict: raise NotImplementedError
    def get_holding_payments(self, org_id: str, start_date: str = None, end_date: str = None, hold_type: str = None, handled_by: str = None, firm: str = None, status: str = None) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_holding_payment(self, org_id: str, user_id: str, data: dict) -> bool: raise NotImplementedError
    def settle_holding_payment(self, txn_id: str, org_id: str, settle_type: str, part_amount: float = 0) -> dict: raise NotImplementedError
    def provision_business_org(self, user_id: str, business_name: str) -> Optional[str]: raise NotImplementedError
    def add_org_member(self, org_id: str, name: str, designation: str) -> bool: raise NotImplementedError
    def get_org_members(self, org_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def verify_or_create_business_access(self, user_id: str, business_name: str) -> bool: raise NotImplementedError
    def get_user_businesses(self, user_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_personal_transactions(self, user_id: str, filters: dict) -> List[Dict[str, Any]]: raise NotImplementedError
    def get_enterprise_dashboard_data(self, org_id: str, filters: dict) -> Dict[str, Any]: raise NotImplementedError
    def get_available_org_opening_balance(self, org_id: str) -> float: raise NotImplementedError
    def get_firms(self, org_id: str) -> List[Dict[str, Any]]: raise NotImplementedError
    def add_firm(self, org_id: str, name: str, opening_balance: float) -> bool: raise NotImplementedError
    def delete_firm(self, firm_id: str, org_id: str) -> bool: raise NotImplementedError

# ── Supabase Implementation ────────────────────────────────────────────────────
class SupabaseService(BaseService):
    def __init__(self, client):
        self.db = client

    def __init__(self, client):
        self.db = client

    # ── Admin Methods (Require Service Role Client) ───────────────────────────
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Fetch all user profiles, bypassing RLS. Must be run with service client."""
        try:
            res = self.db.table('profiles').select('*').order('created_at', desc=True).execute()
            return res.data if res.data else []
        except Exception as e:
            print(f"[get_all_users] Error: {e}")
            return []

    def get_total_enterprises(self) -> int:
        """Fetch total number of enterprise organizations."""
        try:
            res = self.db.table('ent_organizations').select('id', count='exact').execute()
            return res.count if res.count is not None else len(res.data)
        except Exception as e:
            print(f"[get_total_enterprises] Error: {e}")
            return 0
            
    def check_is_admin(self, user_id: str) -> bool:
        """Check if a specific user is an admin using standard client."""
        try:
            res = self.db.table('profiles').select('is_admin').eq('id', user_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0].get('is_admin', False)
            return False
        except Exception as e:
            print(f"[check_is_admin] Error: {e}")
            return False

    def toggle_admin_status(self, target_user_id: str, new_status: bool) -> bool:
        """Toggle an account's admin status. Must be run with service client."""
        try:
            res = self.db.table('profiles').update({'is_admin': new_status}).eq('id', target_user_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[toggle_admin_status] Error: {e}")
            return False

    def log_admin_action(self, admin_id: str, action: str, target_table: str, target_record_id: str, old_data: dict = None, new_data: dict = None) -> bool:
        """Logs admin actions securely by bypassing RLS."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client:
                print("[log_admin_action] Error: Service client unavailable.")
                return False
                
            payload = {
                "admin_id": admin_id,
                "action": action,
                "target_table": target_table,
                "target_record_id": target_record_id,
                "old_data": old_data,
                "new_data": new_data
            }
            svc_client.table('admin_audit_logs').insert(payload).execute()
            return True
        except Exception as e:
            print(f"[log_admin_action] Error: {e}")
            return False

    def update_user_profile(self, user_id: str, data: dict) -> bool:
        """Update a user's full name or currency. Must be run with service client."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            res = svc_client.table('profiles').update(data).eq('id', user_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[update_user_profile] Error: {e}")
            return False

    def toggle_user_suspension(self, user_id: str, suspend_status: bool) -> bool:
        """Toggle an account's suspension status. Must be run with service client."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            res = svc_client.table('profiles').update({'is_suspended': suspend_status}).eq('id', user_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[toggle_user_suspension] Error: {e}")
            return False

    def delete_user_completely(self, user_id: str) -> bool:
        """Hard deletes a user using the Supabase Admin API. This wipes all linked data via CASCADE."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            # Call the admin.delete_user endpoint from the supabase client
            svc_client.auth.admin.delete_user(user_id)
            return True
        except Exception as e:
            print(f"[delete_user_completely] Error: {e}")
            return False

    def get_all_organizations(self) -> list:
        """Fetches all organizations using bypass service client, including member counts."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return []
            
            # Since Supabase rest API doesn't do complex joins natively well for counts,
            # we fetch all orgs, and then all members, and map them in python.
            org_res = svc_client.table('ent_organizations').select('*').execute()
            # Fetch all members to count them per org
            mem_res = svc_client.table('ent_members').select('organization_id').execute()
            
            orgs = org_res.data or []
            members = mem_res.data or []
            
            member_counts = {}
            for m in members:
                org_id = m.get('organization_id')
                if org_id:
                    member_counts[org_id] = member_counts.get(org_id, 0) + 1
                
            for o in orgs:
                o['member_count'] = member_counts.get(o['id'], 0)
                
            return orgs
        except Exception as e:
            print(f"[get_all_organizations] Error: {e}")
            return []

    def get_organization_members(self, org_id: str) -> list:
        """Fetches all members for an org, joined manually with their profile data."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return []
            
            # Fetch members
            res = svc_client.table('ent_members').select('*').eq('organization_id', org_id).execute()
            members = res.data or []
            
            if not members:
                return []
                
            # Fetch profiles for those user_ids
            user_ids = [m['user_id'] for m in members]
            prof_res = svc_client.table('profiles').select('id, full_name, email, is_suspended').in_('id', user_ids).execute()
            profiles_map = {p['id']: p for p in (prof_res.data or [])}
            
            # Attach profile data identically to how UI expects it
            for m in members:
                m['profiles'] = profiles_map.get(m['user_id'], {})
                
            return members
        except Exception as e:
            print(f"[get_organization_members] Error: {e}")
            return []

    def delete_organization_completely(self, org_id: str) -> bool:
        """Hard deletes an organization and all its children via CASCADE."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            res = svc_client.table('ent_organizations').delete().eq('id', org_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[delete_organization_completely] Error: {e}")
            return False

    # ── Global Ledger (Admin) ──────────────────────────────────────────────────
    def get_all_global_transactions(self) -> list:
        """Fetches all revenue and expenses globally, mapped together."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return []
            
            # Fetch revenues
            rev_res = svc_client.table('ent_revenue').select('*, ent_organizations(name)').execute()
            revenues = rev_res.data or []
            for r in revenues:
                r['type'] = 'revenue'
                r['category'] = r.get('status', 'Completed') # Map status as category for UI consistency
                r['business_name'] = r.get('ent_organizations', {}).get('name', 'Unknown')
                
            # Fetch expenses
            exp_res = svc_client.table('ent_expenses').select('*, ent_organizations(name)').execute()
            expenses = exp_res.data or []
            for e in expenses:
                e['type'] = 'expense'
                e['business_name'] = e.get('ent_organizations', {}).get('name', 'Unknown')
                
            # Merge and sort
            all_transactions = revenues + expenses
            all_transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
            
            return all_transactions
        except Exception as e:
            print(f"[get_all_global_transactions] Error: {e}")
            return []

    def update_global_transaction(self, trans_id: str, trans_type: str, data: dict) -> bool:
        """Updates a global transaction (revenue or expense)."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            
            table = 'ent_revenue' if trans_type == 'revenue' else 'ent_expenses'
            res = svc_client.table(table).update(data).eq('id', trans_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[update_global_transaction] Error: {e}")
            return False

    def delete_global_transaction(self, trans_id: str, trans_type: str) -> bool:
        """Deletes a global transaction (revenue or expense)."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            
            table = 'ent_revenue' if trans_type == 'revenue' else 'ent_expenses'
            res = svc_client.table(table).delete().eq('id', trans_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[delete_global_transaction] Error: {e}")
            return False

    # ── Global Holdings & Staff (Admin) ─────────────────────────────────────────
    def get_global_holdings(self) -> list:
        """Fetches all holding payments globally with business name and user profiles."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return []
            
            # Fetch holdings
            res = svc_client.table('ent_holding_payments').select('*, ent_organizations(name)').order('created_at', desc=True).execute()
            holdings = res.data or []
            
            if not holdings:
                return []
                
            # Manually join to Profiles for creator details
            user_ids = [h['created_by'] for h in holdings if h.get('created_by')]
            prof_res = svc_client.table('profiles').select('id, full_name, email').in_('id', user_ids).execute()
            profiles_map = {p['id']: p for p in (prof_res.data or [])}
            
            for h in holdings:
                h['profiles'] = profiles_map.get(h.get('created_by'), {})
                h['business_name'] = h.get('ent_organizations', {}).get('name', 'Unknown')
                
            return holdings
        except Exception as e:
            print(f"[get_global_holdings] Error: {e}")
            return []

    def delete_global_holding(self, holding_id: str) -> bool:
        """Hard deletes a global holding payment."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            res = svc_client.table('ent_holding_payments').delete().eq('id', holding_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[delete_global_holding] Error: {e}")
            return False

    def get_global_staff(self) -> list:
        """Fetches all staff globally mapped to their business names."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return []
            
            res = svc_client.table('ent_staff').select('*, ent_organizations(name)').order('created_at', desc=True).execute()
            staff_list = res.data or []
            
            for s in staff_list:
                s['business_name'] = s.get('ent_organizations', {}).get('name', 'Unknown')
                
            return staff_list
        except Exception as e:
            print(f"[get_global_staff] Error: {e}")
            return []

    def delete_global_staff(self, staff_id: str) -> bool:
        """Hard deletes a staff record globally."""
        try:
            svc_client = get_supabase_service_client()
            if not svc_client: return False
            res = svc_client.table('ent_staff').delete().eq('id', staff_id).execute()
            return len(res.data) > 0
        except Exception as e:
            print(f"[delete_global_staff] Error: {e}")
            return False

    # ── Enterprise Access (Secure Double Login) ───────────────────────────────
    def verify_business_pin(self, user_id: str, business_name: str, pin: str) -> bool:
        """Securely verify the business PIN against the hashed value in Supabase using the RPC."""
        try:
            res = self.db.rpc('verify_business_pin', {
                'p_user_id': user_id,
                'p_business_name': business_name,
                'p_pin': pin
            }).execute()
            return res.data is True
        except Exception as e:
            print(f"[verify_business_pin] Error: {e}")
            return False

    def setup_business_pin(self, user_id: str, business_name: str, pin: str) -> bool:
        """Create or update a business access row with a securely hashed PIN using the RPC."""
        try:
            res = self.db.rpc('setup_business_pin', {
                'p_user_id': user_id,
                'p_business_name': business_name,
                'p_pin': pin
            }).execute()
            return res.data is True
        except Exception as e:
            print(f"[setup_business_pin] Error: {e}")
            return False

    def get_user_businesses(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all businesses the user has access to via ent_members table."""
        try:
            res = self.db.table('ent_members') \
                .select('role, ent_organizations!inner(name)') \
                .eq('user_id', user_id) \
                .execute()
            businesses = []
            if res.data:
                for r in res.data:
                    org = r.get('ent_organizations')
                    if org:
                        businesses.append({'business_name': org.get('name'), 'role': r.get('role')})
            businesses.sort(key=lambda x: x['business_name'])
            return businesses
        except Exception as e:
            print(f"[get_user_businesses] {e}")
            return []

    # ── Organizations ──
    def get_user_organizations(self, user_id: str) -> List[Dict[str, Any]]:
        """Return orgs the user belongs to."""
        try:
            res = self.db.table('ent_members') \
                .select('organization_id, ent_organizations!inner(name)') \
                .eq('user_id', user_id) \
                .execute()
            orgs = []
            if res.data:
                for r in res.data:
                    org = r.get('ent_organizations')
                    if org:
                        orgs.append({'id': r['organization_id'], 'name': org.get('name')})
            orgs.sort(key=lambda x: x['name'])
            return orgs
        except Exception as e:
            print(f"[get_user_organizations] {e}")
            return []

    def get_organization_name(self, org_id: str) -> Optional[str]:
        try:
            res = self.db.table('ent_organizations').select('name').eq('id', org_id).execute()
            return res.data[0]['name'] if res.data else None
        except Exception as e:
            print(f"[get_organization_name] {e}")
            return None

    def get_org_id_by_name(self, user_id: str, org_name: str) -> Optional[str]:
        # User ID is ignored here but kept for interface compatibility
        try:
            res = self.db.table('ent_organizations').select('id').eq('name', org_name).execute()
            return str(res.data[0]['id']) if res.data else None
        except Exception as e:
            print(f"[get_org_id_by_name] {e}")
            return None

    def provision_business_org(self, user_id: str, business_name: str) -> Optional[str]:
        """Idempotently ensure business exists and user is owner."""
        try:
            res = self.db.table('ent_organizations').select('id').eq('name', business_name).execute()
            if res.data:
                org_id = str(res.data[0]['id'])
            else:
                res_create = self.db.table('ent_organizations').insert({'name': business_name}).execute()
                if not res_create.data: return None
                org_id = str(res_create.data[0]['id'])

            mem_res = self.db.table('ent_members').select('id').eq('organization_id', org_id).eq('user_id', user_id).execute()
            if not mem_res.data:
                self.db.table('ent_members').insert({
                    'organization_id': org_id,
                    'user_id': user_id,
                    'role': 'owner'
                }).execute()
            return org_id
        except Exception as e:
            print(f"[provision_business_org] {e}")
            return None

    def get_revenue(self, org_id: str, start_date: str = None, end_date: str = None, firm: str = None) -> List[Dict[str, Any]]:
        query = self.db.table('ent_revenue') \
            .select('*, enterprise_bank_accounts(bank_name)') \
            .eq('organization_id', org_id)
        if start_date: query = query.gte('date', start_date)
        if end_date:   query = query.lte('date', end_date)
        if firm and str(firm).lower() != 'all': query = query.eq('firm', firm)
        res = query.order('date', desc=True).execute()
        return [
            {
                'taken_by_name': r.get('taken_by') or 'Unknown',
                'bank_name':     r.get('enterprise_bank_accounts', {}) and r['enterprise_bank_accounts'].get('bank_name') or None,
                **r
            }
            for r in res.data
        ]

    def add_revenue(self, org_id: str, data: Dict[str, Any]) -> bool:
        try:
            data['organization_id'] = org_id
            self.db.table('ent_revenue').insert(data).execute()
            return True
        except Exception as e:
            print(f"[add_revenue] {e}")
            return False

    # ── Expenses ──────────────────────────────────────────────────────────────
    def get_expenses(self, org_id: str, start_date: str = None, end_date: str = None, firm: str = None) -> List[Dict[str, Any]]:
        query = self.db.table('ent_expenses') \
            .select('*, enterprise_bank_accounts(bank_name)') \
            .eq('organization_id', org_id)
        if start_date: query = query.gte('date', start_date)
        if end_date:   query = query.lte('date', end_date)
        if firm and str(firm).lower() != 'all': query = query.eq('firm', firm)
        res = query.order('date', desc=True).execute()
        return [
            {
                'taken_by_name': r.get('taken_by') or 'Unknown',
                'bank_name':     r.get('enterprise_bank_accounts', {}) and r['enterprise_bank_accounts'].get('bank_name') or None,
                **r
            }
            for r in res.data
        ]

    def add_expense(self, org_id: str, data: Dict[str, Any]) -> bool:
        try:
            data['organization_id'] = org_id
            self.db.table('ent_expenses').insert(data).execute()
            return True
        except Exception as e:
            print(f"[add_expense] {e}")
            return False

    # ── Investments ───────────────────────────────────────────────────────────
    def get_investments(self, org_id: str, start_date: str = None, end_date: str = None, inv_type: str = None, taken_by: str = None, firm: str = None) -> List[Dict[str, Any]]:
        try:
            query = self.db.table('ent_investments').select('*').eq('organization_id', org_id)
            if start_date: query = query.gte('date', start_date)
            if end_date:   query = query.lte('date', end_date)
            if inv_type and str(inv_type).lower() != 'all': query = query.eq('type', str(inv_type).lower())
            if taken_by and str(taken_by).lower() != 'all': query = query.eq('taken_by', taken_by)
            if firm and str(firm).lower() != 'all': query = query.eq('firm', firm)
            
            res = query.order('date', desc=True).execute()
            return res.data or []
        except Exception as e:
            print(f"[get_investments] {e}")
            return []

    def add_investment(self, org_id: str, data: dict) -> bool:
        try:
            taken_by  = (data.get('taken_by',  '') or '').strip() or None
            narrative = (data.get('narrative', '') or '').strip() or None
            self.db.table('ent_investments').insert({
                'organization_id': org_id,
                'amount':          float(data.get('amount', 0)),
                'date':            data.get('date'),
                'type':            data.get('type', 'investment'),
                'taken_by':        taken_by,
                'narrative':       narrative,
                'source':          taken_by,
                'description':     narrative,
                'firm':            data.get('firm') or None,
            }).execute()
            return True
        except Exception as e:
            print(f"[add_investment] {e}")
            return False

    # ── Holding Payments ──────────────────────────────────────────────────────
    def get_holding_payments(self, org_id: str, start_date: str = None, end_date: str = None, hold_type: str = None, handled_by: str = None, firm: str = None, status: str = None) -> List[Dict[str, Any]]:
        try:
            query = self.db.table('ent_holding_payments').select('*').eq('organization_id', org_id)
            
            if start_date: query = query.gte('created_at', f"{start_date}T00:00:00Z")
            if end_date:   query = query.lte('created_at', f"{end_date}T23:59:59Z")
            if hold_type and str(hold_type).lower() != 'all': query = query.eq('type', str(hold_type).lower())
            if handled_by and str(handled_by).lower() != 'all': query = query.eq('created_by', handled_by)
            if firm and str(firm).lower() != 'all': query = query.eq('firm', firm)
            if status and str(status).lower() != 'all': query = query.eq('status', str(status).lower())

            res = query.order('created_at', desc=True).execute()
            return res.data or []
        except Exception as e:
            print(f"[get_holding_payments] {e}")
            return []

    def add_holding_payment(self, org_id: str, user_id: str, data: dict) -> bool:
        try:
            amt = float(data.get('amount', 0))
            self.db.table('ent_holding_payments').insert({
                'organization_id': org_id,
                'created_by':      user_id,
                'name':            data.get('name'),
                'type':            data.get('type', 'receivable'),
                'amount':          amt,
                'expected_date':   data.get('expected_date') or None,
                'mobile_no':       data.get('mobile_no'),
                'narrative':       data.get('narrative'),
                'status':          'pending',
                'paid_amount':     0,
                'remaining_amount':amt,
                'firm':            data.get('firm') or None,
            }).execute()
            return True
        except Exception as e:
            print(f"[add_holding_payment] {e}")
            return False

    def settle_holding_payment(self, txn_id: str, org_id: str, settle_type: str, part_amount: float = 0) -> dict:
        try:
            res = self.db.table('ent_holding_payments') \
                .select('*').eq('id', txn_id).eq('organization_id', org_id) \
                .single().execute()
            if not res.data:
                return {'success': False, 'error': 'Transaction not found.'}
            txn         = res.data
            original    = float(txn.get('amount', 0))
            paid_so_far = float(txn.get('paid_amount', 0) or 0)

            if settle_type == 'full':
                new_paid, new_remaining, new_status = original, 0, 'settled'
            else:
                new_paid      = paid_so_far + part_amount
                new_remaining = max(original - new_paid, 0)
                new_status    = 'settled' if new_remaining == 0 else 'partial'

            self.db.table('ent_holding_payments').update({
                'paid_amount':      new_paid,
                'remaining_amount': new_remaining,
                'status':           new_status,
            }).eq('id', txn_id).execute()
            return {'success': True, 'status': new_status, 'paid': new_paid, 'remaining': new_remaining}
        except Exception as e:
            print(f"[settle_holding_payment] {e}")
            return {'success': False, 'error': str(e)}

    # ── Members / Staff ───────────────────────────────────────────────────────
    def get_members(self, org_id: str) -> List[Dict[str, Any]]:
        res = self.db.table('ent_members') \
            .select('role, profiles(id, full_name, email)') \
            .eq('organization_id', org_id).execute()
        return [
            {'role': m['role'], 'id': m['profiles']['id'],
             'full_name': m['profiles']['full_name'], 'email': m['profiles']['email']}
            for m in res.data
        ]

    def add_member(self, org_id: str, user_id: str, role: str = 'member') -> bool:
        try:
            self.db.table('ent_members').insert({
                'organization_id': org_id, 'user_id': user_id, 'role': role
            }).execute()
            return True
        except Exception as e:
            print(f"[add_member] {e}")
            return False

    def add_org_member(self, org_id: str, name: str, designation: str) -> bool:
        """Add a named staff member to ent_staff."""
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

    def find_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        res = self.db.table('profiles').select('*').eq('email', email).execute()
        return res.data[0] if res.data else None

    # ── Firms ─────────────────────────────────────────────────────────────────
    def get_available_org_opening_balance(self, org_id: str) -> float:
        try:
            org_name = self.get_organization_name(org_id)
            if not org_name:
                return 0.0

            # Sum of total bank opening balances for this organization
            banks_res = self.db.table('enterprise_bank_accounts').select('opening_balance').eq('business_name', org_name).execute()
            total_bank_balance = sum(float(b.get('opening_balance', 0) or 0) for b in (banks_res.data or []))

            # Sum of allocated firm opening balances
            firms_res = self.db.table('ent_firms').select('opening_balance').eq('organization_id', org_id).execute()
            total_firm_balance = sum(float(f.get('opening_balance', 0) or 0) for f in (firms_res.data or []))

            return float(total_bank_balance - total_firm_balance)
        except Exception as e:
            print(f"[get_available_org_opening_balance] {e}")
            return 0.0

    def get_firms(self, org_id: str) -> List[Dict[str, Any]]:
        try:
            res = self.db.table('ent_firms').select('*').eq('organization_id', org_id).order('created_at', desc=True).execute()
            firms = res.data or []
            
            # Fetch all transactions to compute the dynamic current balance
            rev_res = self.db.table('ent_revenue').select('amount, firm').eq('organization_id', org_id).execute()
            exp_res = self.db.table('ent_expenses').select('amount, firm').eq('organization_id', org_id).execute()
            inv_res = self.db.table('ent_investments').select('amount, type, firm').eq('organization_id', org_id).execute()
            hold_res = self.db.table('ent_holding_payments').select('paid_amount, type, firm').eq('organization_id', org_id).execute()
            
            for firm in firms:
                firm_name = firm['name']
                current_balance = float(firm.get('opening_balance', 0) or 0)
                
                # + Revenues
                for r in (rev_res.data or []):
                    if r.get('firm') == firm_name:
                        current_balance += float(r.get('amount', 0) or 0)
                        
                # - Expenses
                for e in (exp_res.data or []):
                    if e.get('firm') == firm_name:
                        current_balance -= float(e.get('amount', 0) or 0)
                        
                # +/- Investments In/Out
                for i in (inv_res.data or []):
                    if i.get('firm') == firm_name:
                        amt = float(i.get('amount', 0) or 0)
                        if i.get('type', 'investment') == 'investment':
                            current_balance += amt
                        else:  # withdraw
                            current_balance -= amt
                            
                # +/- Holding Payments Settled
                for h in (hold_res.data or []):
                    if h.get('firm') == firm_name:
                        paid = float(h.get('paid_amount', 0) or 0)
                        if h.get('type') == 'receivable':
                            current_balance += paid
                        elif h.get('type') == 'payable':
                            current_balance -= paid
                            
                firm['current_balance'] = current_balance
                
            return firms
        except Exception as e:
            print(f"[get_firms] {e}")
            return []

    def add_firm(self, org_id: str, name: str, opening_balance: float) -> bool:
        try:
            # Verify the requested balance does not exceed the available limit
            available = self.get_available_org_opening_balance(org_id)
            if opening_balance > available:
                return False

            self.db.table('ent_firms').insert({
                'organization_id': org_id,
                'name': name,
                'opening_balance': opening_balance
            }).execute()
            return True
        except Exception as e:
            print(f"[add_firm] {e}")
            return False

    def delete_firm(self, firm_id: str, org_id: str) -> bool:
        try:
            self.db.table('ent_firms').delete().eq('id', firm_id).eq('organization_id', org_id).execute()
            return True
        except Exception as e:
            print(f"[delete_firm] {e}")
            return False

    # ── Banks — Personal ──────────────────────────────────────────────────────
    def get_personal_banks(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            return self.db.table('bank_accounts').select('*').eq('user_id', user_id).execute().data or []
        except Exception as e:
            print(f"[get_personal_banks] {e}")
            return []

    # ── Banks — Enterprise ────────────────────────────────────────────────────
    def get_enterprise_banks(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch all enterprise bank accounts from Supabase enterprise_bank_accounts."""
        try:
            return self.db.table('enterprise_bank_accounts').select('*') \
                .eq('user_id', user_id).order('created_at', desc=True).execute().data or []
        except Exception as e:
            print(f"[get_enterprise_banks] {e}")
            return []

    def get_banks_for_org(self, user_id: str, org_name: str) -> List[Dict[str, Any]]:
        """Return enterprise bank accounts scoped to a specific business name."""
        try:
            return self.db.table('enterprise_bank_accounts').select('*') \
                .eq('user_id', user_id).eq('business_name', org_name) \
                .order('created_at', desc=True).execute().data or []
        except Exception as e:
            print(f"[get_banks_for_org] {e}")
            return []

    def add_enterprise_bank(self, user_id: str, data: Dict[str, Any]) -> bool:
        try:
            self.db.table('enterprise_bank_accounts').insert({
                'user_id':         user_id,
                'business_name':   data.get('business_name'),
                'bank_name':       data.get('bank_name'),
                'account_number':  data.get('account_number'),
                'ifsc_code':       data.get('ifsc_code'),
                'opening_balance': data.get('opening_balance', 0.00),
                'account_type':    data.get('account_type', 'Current'),
            }).execute()
            return True
        except Exception as e:
            print(f"[add_enterprise_bank] {e}")
            return False

    def update_enterprise_bank(self, user_id: str, bank_id: str, data: Dict[str, Any]) -> bool:
        try:
            self.db.table('enterprise_bank_accounts').update({
                'business_name':   data.get('business_name'),
                'bank_name':       data.get('bank_name'),
                'account_number':  data.get('account_number'),
                'ifsc_code':       data.get('ifsc_code'),
                'opening_balance': data.get('opening_balance', 0.00),
                'account_type':    data.get('account_type', 'Current'),
            }).eq('id', bank_id).eq('user_id', user_id).execute()
            return True
        except Exception as e:
            print(f"[update_enterprise_bank] {e}")
            return False

    def delete_enterprise_bank(self, user_id: str, bank_id: str) -> bool:
        try:
            self.db.table('enterprise_bank_accounts').delete() \
                .eq('id', bank_id).eq('user_id', user_id).execute()
            return True
        except Exception as e:
            print(f"[delete_enterprise_bank] {e}")
            return False

    # ── Categories ────────────────────────────────────────────────────────────
    def get_categories(self, user_id: str) -> List[str]:
        try:
            res = self.db.table('user_categories').select('name').eq('user_id', user_id).execute()
            return DEFAULT_CATEGORIES + [r['name'] for r in res.data]
        except Exception:
            return DEFAULT_CATEGORIES

    def get_split_categories(self, user_id: str) -> dict:
        DEFAULT_EXPENSE_CATEGORIES = [
            'Food', 'Transport', 'Utilities', 'Entertainment', 'Shopping',
            'Health', 'Travel', 'Education', 'Other'
        ]
        DEFAULT_INCOME_CATEGORIES = [
            'Salary', 'Freelance', 'Investment', 'Business', 'Rental', 'Other'
        ]
        try:
            res = self.db.table('user_categories').select('name, type').eq('user_id', user_id).execute()
            income = DEFAULT_INCOME_CATEGORIES.copy()
            expense = DEFAULT_EXPENSE_CATEGORIES.copy()
            for r in res.data:
                if r.get('type') == 'income':
                    income.append(r['name'])
                else:
                    expense.append(r['name'])
            return {'income': income, 'expense': expense}
        except Exception:
            return {'income': DEFAULT_INCOME_CATEGORIES.copy(), 'expense': DEFAULT_EXPENSE_CATEGORIES.copy()}

    # ── Personal Transactions (Pocket Expense reports) ────────────────────────
    def get_personal_transactions(self, user_id: str, filters: dict) -> List[Dict[str, Any]]:
        """Fetch filtered personal transactions strictly from Supabase."""
        try:
            query = self.db.table('expenses').select(
                'id, date, category, description, amount, type, bank_account_id, bank_accounts(bank_name)'
            ).eq('user_id', user_id)

            if filters.get('start_date'):
                query = query.gte('date', filters['start_date'])
            if filters.get('end_date'):
                query = query.lte('date', filters['end_date'])
            if filters.get('category') and filters['category'] != 'all':
                query = query.eq('category', filters['category'])
            if filters.get('tx_type') and filters['tx_type'] != 'all':
                query = query.eq('type', filters['tx_type'])
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
                    'payment_method': bank_name or 'Cash',
                })
            return rows
        except Exception as e:
            print(f"[get_personal_transactions] {e}")
            return []

    # ── Enterprise Dashboard Unified Data ──────────────────────────────────────
    def get_enterprise_dashboard_data(self, org_id: str, filters: dict) -> Dict[str, Any]:
        """Fetch filtered dashboard data for enterprise summary and recent transactions."""
        try:
            start_date = filters.get('start_date')
            end_date   = filters.get('end_date')
            tx_type    = str(filters.get('type', 'All')).lower()
            staff      = str(filters.get('staff', 'All'))
            firm       = str(filters.get('firm', 'All'))
            method     = str(filters.get('method', 'All'))

            revenue_data = []
            expense_data = []
            invest_data  = []
            holding_data = []

            # 1. Revenue
            if tx_type in ['all', 'income']:
                q_rev = self.db.table('ent_revenue').select('*, enterprise_bank_accounts(bank_name)').eq('organization_id', org_id)
                if start_date: q_rev = q_rev.gte('date', start_date)
                if end_date:   q_rev = q_rev.lte('date', end_date)
                if staff.lower() != 'all': q_rev = q_rev.eq('taken_by', staff)
                if firm.lower() != 'all':  q_rev = q_rev.eq('firm', firm)
                if method.lower() == 'cash':
                    q_rev = q_rev.is_('bank_account_id', 'null')
                elif method.lower() != 'all':
                    q_rev = q_rev.eq('bank_account_id', method)
                try:
                    res = q_rev.execute()
                    for r in (res.data or []):
                        revenue_data.append({
                            'taken_by_name': r.get('taken_by') or 'Unknown',
                            'bank_name':     r.get('enterprise_bank_accounts', {}) and r['enterprise_bank_accounts'].get('bank_name') or None,
                            **r
                        })
                except Exception as e_rev:
                    print(f"[get_dashboard_data] Revenue Error: {e_rev}")

            # 2. Expenses
            if tx_type in ['all', 'expense']:
                q_exp = self.db.table('ent_expenses').select('*, enterprise_bank_accounts(bank_name)').eq('organization_id', org_id)
                if start_date: q_exp = q_exp.gte('date', start_date)
                if end_date:   q_exp = q_exp.lte('date', end_date)
                if staff.lower() != 'all': q_exp = q_exp.eq('taken_by', staff)
                if firm.lower() != 'all':  q_exp = q_exp.eq('firm', firm)
                if method.lower() == 'cash':
                    q_exp = q_exp.is_('bank_account_id', 'null')
                elif method.lower() != 'all':
                    q_exp = q_exp.eq('bank_account_id', method)
                try:
                    res = q_exp.execute()
                    for r in (res.data or []):
                        expense_data.append({
                            'taken_by_name': r.get('taken_by') or 'Unknown',
                            'bank_name':     r.get('enterprise_bank_accounts', {}) and r['enterprise_bank_accounts'].get('bank_name') or None,
                            **r
                        })
                except Exception as e_exp:
                    print(f"[get_dashboard_data] Expense Error: {e_exp}")

            # 3. Investments
            if tx_type in ['all', 'investment']:
                q_inv = self.db.table('ent_investments').select('*').eq('organization_id', org_id)
                if start_date: q_inv = q_inv.gte('date', start_date)
                if end_date:   q_inv = q_inv.lte('date', end_date)
                if staff.lower() != 'all': q_inv = q_inv.eq('taken_by', staff)
                if firm.lower() != 'all':  q_inv = q_inv.eq('firm', firm)
                # Ignore method filter for investments as it doesn't apply directly
                try:
                    res = q_inv.execute()
                    invest_data = res.data or []
                except Exception as e_inv:
                    print(f"[get_dashboard_data] Investment Error: {e_inv}")

            # 4. Holdings
            if tx_type in ['all', 'holding']:
                q_hol = self.db.table('ent_holding_payments').select('*').eq('organization_id', org_id)
                if start_date: q_hol = q_hol.gte('created_at', f"{start_date}T00:00:00Z")
                if end_date:   q_hol = q_hol.lte('created_at', f"{end_date}T23:59:59Z")
                if staff.lower() != 'all': q_hol = q_hol.eq('created_by', staff)
                if firm.lower() != 'all':  q_hol = q_hol.eq('firm', firm)
                # Ignore method filter for holdings as it doesn't apply directly
                try:
                    res = q_hol.execute()
                    holding_data = res.data or []
                except Exception as e_hol:
                    print(f"[get_dashboard_data] Holding Error: {e_hol}")

            return {
                'revenue': revenue_data,
                'expenses': expense_data,
                'investments': invest_data,
                'holdings': holding_data
            }
        except Exception as e:
            print(f"[get_enterprise_dashboard_data] {e}")
            return {'revenue': [], 'expenses': [], 'investments': [], 'holdings': []}
