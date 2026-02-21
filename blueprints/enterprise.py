from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, current_app, jsonify
from functools import wraps
from decimal import Decimal
import datetime
import io
import csv
from .database_service import SupabaseService, get_supabase_client

enterprise_bp = Blueprint('enterprise', __name__)

# ── Helper ────────────────────────────────────────────────────────────────────
def _svc() -> SupabaseService:
    """Return a SupabaseService scoped to the current user's JWT."""
    return SupabaseService(get_supabase_client(session.get('access_token')))

# ── Decorator ─────────────────────────────────────────────────────────────────
def enterprise_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))

        # Must have an active business in session
        if not session.get('active_business'):
            flash("Please activate a business account first.", "error")
            return redirect(url_for('banks'))

        user_id    = session['user']
        active_biz = session['active_business']

        try:
            svc = _svc()

            # ── Actively verify access via Supabase ent_members table ──
            res = svc.db.table('ent_members') \
                .select('id, pin_hash, ent_organizations!inner(name)') \
                .eq('user_id', user_id).eq('ent_organizations.name', active_biz) \
                .execute()
            if not res.data:
                session.pop('active_business', None)
                session.pop('curr_org_id', None)
                session.pop(f"business_unlocked_{active_biz}", None)
                flash("Access denied: you do not have permission for this business.", "error")
                return redirect(url_for('dashboard'))

            # ── Check if business is unlocked via PIN this session ──
            if not session.get(f"business_unlocked_{active_biz}"):
                # If they have no PIN set (e.g. newly added staff), redirect to banks to trigger setup modal
                # Or if they have a PIN, trigger login modal
                flash(f"Please sign in to access {active_biz}.", "info")
                return redirect(url_for('banks'))

            # ── Ensure curr_org_id is set and valid ──
            member_orgs    = svc.get_user_organizations(user_id)
            valid_org_ids  = [str(m['id']) for m in member_orgs]

            if 'curr_org_id' not in session or str(session['curr_org_id']) not in valid_org_ids:
                org_id = svc.provision_business_org(user_id, active_biz)
                if org_id:
                    session['curr_org_id'] = org_id
                else:
                    session.pop('curr_org_id', None)
                    flash("Could not resolve your business organisation.", "error")
                    return redirect(url_for('dashboard'))

        except Exception as e:
            current_app.logger.error(f"Enterprise RBAC Error: {e}", exc_info=True)
            flash("An error occurred during enterprise verification.", "error")
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)
    return decorated_function

import base64
@enterprise_bp.route('/check_auth')
def check_auth():
    """JSON API: Returns if the business has a PIN registered for this user."""
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    encoded_bname = request.args.get('bname', '')
    try:
        business_name = base64.b64decode(encoded_bname).decode('utf-8')
    except Exception:
        business_name = encoded_bname # Fallback if not base64 encoded

    try:
        res = _svc().db.table('ent_members') \
            .select('pin_hash, ent_organizations!inner(name)') \
            .eq('user_id', session['user']) \
            .eq('ent_organizations.name', business_name) \
            .execute()
        has_pin = len(res.data) > 0 and res.data[0].get('pin_hash') is not None
        return jsonify({'registered': has_pin})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@enterprise_bp.route('/signup', methods=['POST'])
def enterprise_signup():
    """Sets a new PIN for a business."""
    if 'user' not in session: return redirect(url_for('login'))
    business_name = request.form.get('business_name', '').strip()
    pin = request.form.get('password', '') # The modal uses name='password'
    confirm = request.form.get('confirm_password', '')

    if not business_name or not pin:
        flash('Business name and PIN are required.', 'error')
        return redirect(url_for('banks'))
    if pin != confirm:
        flash('PINs do not match.', 'error')
        return redirect(url_for('banks'))

    svc = _svc()
    
    # Check if a PIN is already set
    res = svc.db.table('ent_members') \
        .select('pin_hash, ent_organizations!inner(name)').eq('user_id', session['user']).eq('ent_organizations.name', business_name) \
        .execute()
    if res.data and res.data[0].get('pin_hash') is not None:
        flash('Security PIN already set for this business. Please sign in.', 'error')
        return redirect(url_for('banks'))

    # Setup the PIN via secure RPC
    ok = svc.setup_business_pin(session['user'], business_name, pin)
    if ok:
        session['active_business'] = business_name
        session[f"business_unlocked_{business_name}"] = True
        
        # Provision the current org ID for this session
        org_id = svc.provision_business_org(session['user'], business_name)
        if org_id: session['curr_org_id'] = org_id
        
        flash(f'Security PIN set for {business_name}!', 'success')
        return redirect(url_for('enterprise.ent_dashboard'))
    
    flash('Failed to setup Security PIN.', 'error')
    return redirect(url_for('banks'))

@enterprise_bp.route('/login', methods=['POST'])
def enterprise_login():
    """Verifies a PIN for an existing business."""
    if 'user' not in session: return redirect(url_for('login'))
    business_name = request.form.get('business_name', '').strip()
    pin = request.form.get('password', '')

    if not business_name or not pin:
        flash('Business name and PIN are required.', 'error')
        return redirect(url_for('banks'))

    svc = _svc()
    # Verify the PIN via secure RPC
    is_valid = svc.verify_business_pin(session['user'], business_name, pin)
    
    if is_valid:
        session['active_business'] = business_name
        session[f"business_unlocked_{business_name}"] = True
        
        # Provision the current org ID for this session
        org_id = svc.provision_business_org(session['user'], business_name)
        if org_id: session['curr_org_id'] = org_id
        
        flash(f'Signed into {business_name}', 'success')
        return redirect(url_for('enterprise.ent_dashboard'))
    else:
        flash('Invalid Security PIN.', 'error')
        return redirect(url_for('banks'))

@enterprise_bp.route('/reset_pin', methods=['POST'])
def enterprise_reset_pin():
    """Resets a Security PIN by verifying the user's primary account password."""
    if 'user' not in session: return redirect(url_for('login'))
    
    business_name = request.form.get('business_name', '').strip()
    account_password = request.form.get('account_password', '')
    new_pin = request.form.get('new_pin', '')
    confirm_pin = request.form.get('confirm_pin', '')
    email = session.get('user_email')

    if not all([business_name, account_password, new_pin, confirm_pin]):
        flash('All fields are required for PIN reset.', 'error')
        return redirect(url_for('banks'))

    if new_pin != confirm_pin:
        flash('New PINs do not match.', 'error')
        return redirect(url_for('banks'))

    svc = _svc()
    
    try:
        # 1. Verify primary account ownership by attempting a re-authentication
        # We use a fresh client or the existing auth service to check password validity
        from supabase import create_client
        import os
        temp_supabase = create_client(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_KEY'))
        
        # This will throw an error if the password is wrong
        auth_res = temp_supabase.auth.sign_in_with_password({
            "email": email,
            "password": account_password
        })
        
        if not auth_res.user:
            flash('Account verification failed.', 'error')
            return redirect(url_for('banks'))

        # 2. Reset the business PIN
        ok = svc.setup_business_pin(session['user'], business_name, new_pin)
        if ok:
            flash(f'Security PIN reset successful for {business_name}!', 'success')
            # Clear unlock session to force re-login with new PIN
            session.pop(f"business_unlocked_{business_name}", None)
            return redirect(url_for('banks'))
        else:
            flash('Failed to reset Security PIN.', 'error')
            
    except Exception as e:
        print(f"[reset_pin] Error: {e}")
        flash('Account verification failed. Please check your account password.', 'error')

    return redirect(url_for('banks'))

@enterprise_bp.route('/logout')
def enterprise_logout():
    active_biz = session.get('active_business')
    if active_biz:
        session.pop(f"business_unlocked_{active_biz}", None)
    session.pop('active_business', None)
    session.pop('curr_org_id', None)
    flash('Signed out of business account.', 'success')
    return redirect(url_for('banks'))

# ── Organisation selector ─────────────────────────────────────────────────────
@enterprise_bp.route('/select_organization')
def select_organization():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        businesses = _svc().get_user_businesses(session['user'])
        if not businesses:
            flash("You have no registered businesses. Click 'Manage' on a bank card to get started.", "info")
            return redirect(url_for('banks'))
        return render_template('enterprise/select_organization.html', businesses=businesses)
    except Exception as e:
        flash(f"Error loading businesses: {str(e)}", "error")
        return redirect(url_for('banks'))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@enterprise_bp.route('/')
@enterprise_required
def ent_dashboard():
    org_id = session.get('curr_org_id')
    svc    = _svc()

    try:
        revenue_data = svc.get_revenue(org_id)
        expense_data = svc.get_expenses(org_id)
        invest_data  = svc.get_investments(org_id)

        total_rev    = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data)
        total_exp    = sum(Decimal(str(e.get('amount') or 0)) for e in expense_data)
        net_pl       = total_rev - total_exp
        total_invest = sum(Decimal(str(i.get('amount') or 0)) for i in invest_data)
        total_pending = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if r.get('status') == 'pending')

        burn_rate = Decimal('0.00')
        if expense_data:
            months = {}
            for e in expense_data:
                m = str(e['date'])[:7]
                months[m] = months.get(m, Decimal('0.00')) + Decimal(str(e.get('amount') or 0))
            last_3 = sorted(months.keys(), reverse=True)[:3]
            if last_3:
                burn_rate = sum(months[m] for m in last_3) / len(last_3)

        margin_pct = f"{(net_pl / total_rev * 100):,.2f}%" if total_rev > 0 else "0.00%"

        kpis = {
            'total_revenue':     f"{total_rev:,.2f}",
            'total_expenses':    f"{total_exp:,.2f}",
            'net_pl':            f"{net_pl:,.2f}",
            'pending_payments':  f"{total_pending:,.2f}",
            'burn_rate':         f"{burn_rate:,.2f}",
            'margin_pct':        margin_pct,
            'total_investments': f"{total_invest:,.2f}",
            'is_profit':         net_pl >= 0,
        }

        data_months = sorted(set(
            [str(r['date'])[:7] for r in revenue_data] +
            [str(e['date'])[:7] for e in expense_data]
        ))
        if not data_months:
            today = datetime.date.today()
            data_months = [
                f"{today.year}-{((today.month - i - 1) % 12 + 1):02d}"
                for i in range(5, -1, -1)
            ]
        trend_months = data_months[-6:]
        rev_trend = [float(sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(m))) for m in trend_months]
        exp_trend = [float(sum(Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(m))) for m in trend_months]

        today     = datetime.date.today()
        this_mth  = today.strftime('%Y-%m')
        this_yr   = str(today.year)
        month_rev = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(this_mth))
        month_exp = sum(Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(this_mth))
        year_rev  = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(this_yr))
        year_exp  = sum(Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(this_yr))

        report_data = [
            {'name': f"{today.strftime('%B %Y')} Summary",   'range': today.strftime('%B %Y'),
             'income': f"{month_rev:,.2f}", 'expense': f"{month_exp:,.2f}", 'net': f"{month_rev - month_exp:,.2f}",
             'positive': month_rev >= month_exp, 'can_download': True, 'dl_params': "period=this_month"},
            {'name': f"{this_yr} Year-to-Date", 'range': f"Jan – {today.strftime('%b')} {this_yr}",
             'income': f"{year_rev:,.2f}", 'expense': f"{year_exp:,.2f}", 'net': f"{year_rev - year_exp:,.2f}",
             'positive': year_rev >= year_exp, 'can_download': True, 'dl_params': "period=this_year"},
        ]

        org_name = svc.get_organization_name(org_id) or 'Enterprise'
        return render_template('enterprise/dashboard.html',
                               kpis=kpis, trend_labels=trend_months,
                               rev_trend=rev_trend, exp_trend=exp_trend,
                               report_data=report_data, org_name=org_name, currency='₹')

    except Exception as e:
        current_app.logger.error(f"Enterprise Dashboard Error: {e}", exc_info=True)
        flash(f"An error occurred while loading financial data: {str(e)}", "error")
        return redirect(url_for('dashboard'))

# ── Revenue ───────────────────────────────────────────────────────────────────
@enterprise_bp.route('/revenue')
@enterprise_required
def revenue():
    org_id     = session.get('curr_org_id')
    period     = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')
    today      = datetime.date.today()
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    elif period == 'this_week':
        start_date = (today - datetime.timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last.replace(day=1).strftime('%Y-%m-%d')
        end_date   = last.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    try:
        revenue_list = _svc().get_revenue(org_id, start_date, end_date)
        return render_template('enterprise/revenue.html',
                               revenue_list=revenue_list, period=period,
                               start_date=start_date, end_date=end_date, currency='₹')
    except Exception as e:
        flash(f"Error loading revenue: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

# ── Expenses ──────────────────────────────────────────────────────────────────
@enterprise_bp.route('/expenses')
@enterprise_required
def expenses():
    org_id     = session.get('curr_org_id')
    period     = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')
    today      = datetime.date.today()
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    elif period == 'this_week':
        start_date = (today - datetime.timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last.replace(day=1).strftime('%Y-%m-%d')
        end_date   = last.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    try:
        expenses_list = _svc().get_expenses(org_id, start_date, end_date)
        return render_template('enterprise/expenses.html',
                               expenses_list=expenses_list, period=period,
                               start_date=start_date, end_date=end_date, currency='₹')
    except Exception as e:
        flash(f"Error loading expenses: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

# ── Staff / Members ───────────────────────────────────────────────────────────
@enterprise_bp.route('/members', methods=['GET', 'POST'])
@enterprise_required
def members():
    org_id = session.get('curr_org_id')
    svc    = _svc()
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        designation = request.form.get('designation', '').strip()
        if not name:
            flash("Staff name is required.", "error")
        else:
            ok = svc.add_org_member(org_id, name, designation)
            flash(f"'{name}' added to team." if ok else "Error adding staff member.", "success" if ok else "error")
        return redirect(url_for('enterprise.members'))
    staff_list = svc.get_org_members(org_id)
    return render_template('enterprise/members.html', staff_list=staff_list)

# ── Combined Cashflow ─────────────────────────────────────────────────────────
@enterprise_bp.route('/combined-cashflow')
@enterprise_required
def revenue_expenses():
    org_id     = session.get('curr_org_id')
    svc        = _svc()
    period     = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')
    today      = datetime.date.today()
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last.replace(day=1).strftime('%Y-%m-%d')
        end_date   = last.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date   = today.strftime('%Y-%m-%d')

    try:
        revenue  = svc.get_revenue(org_id, start_date, end_date)
        expenses = svc.get_expenses(org_id, start_date, end_date)

        active_biz      = session.get('active_business', '')
        enterprise_banks = svc.get_banks_for_org(session['user'], active_biz)
        categories       = svc.get_categories(session['user'])

        ledger = sorted(
            [{**r, 'type': 'Income'} for r in revenue] +
            [{**e, 'type': 'Expense'} for e in expenses],
            key=lambda x: str(x['date']), reverse=True
        )
        total_income   = sum(Decimal(str(i['amount'])) for i in ledger if i['type'] == 'Income')
        total_expenses = sum(Decimal(str(e['amount'])) for e in ledger if e['type'] == 'Expense')
    except Exception as e:
        flash(f"Error loading cashflow: {e}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

    try:
        org_members = svc.get_org_members(org_id)
    except Exception:
        org_members = []

    return render_template('enterprise/revenue_expenses.html',
                           ledger=ledger, total_income=total_income,
                           total_expenses=total_expenses, period=period,
                           start_date=start_date, end_date=end_date,
                           enterprise_banks=enterprise_banks,
                           categories=categories, org_members=org_members, currency='₹')

# ── Add Transaction ───────────────────────────────────────────────────────────
@enterprise_bp.route('/add-transaction', methods=['POST'])
@enterprise_required
def add_transaction():
    org_id    = session.get('curr_org_id')
    svc       = _svc()
    user_id   = session['user']
    t_type    = request.form.get('type')
    amount    = request.form.get('amount')
    date      = request.form.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    method_val = request.form.get('method')
    narrative = request.form.get('narrative')
    category  = request.form.get('category') or 'Other'

    if not amount or not t_type or not method_val:
        flash("Missing required fields", "error")
        return redirect(url_for('enterprise.revenue_expenses'))

    bank_account_id = None if method_val == 'Cash' else method_val
    method          = 'Cash' if method_val == 'Cash' else 'Bank'

    taken_by_val = request.form.get('taken_by', '').strip()
    if not taken_by_val or taken_by_val == '__other__':
        taken_by_val = user_id

    data = {
        'amount': amount, 'date': date, 'method': method,
        'narrative': narrative, 'category': category,
        'taken_by': taken_by_val,
        'bank_account_id': bank_account_id,
    }
    try:
        if t_type == 'Income':
            data.pop('category', None)
            success = svc.add_revenue(org_id, data)
        else:
            success = svc.add_expense(org_id, data)
        flash(f"Successfully added {t_type.lower()}." if success else f"Error adding {t_type.lower()}.",
              "success" if success else "error")
    except Exception as e:
        flash(f"Transaction failed: {e}", "error")
    return redirect(url_for('enterprise.revenue_expenses'))

# ── Add Member (fast/AJAX) ────────────────────────────────────────────────────
@enterprise_bp.route('/add-member-fast', methods=['POST'])
@enterprise_required
def add_member_fast():
    org_id = session.get('curr_org_id')
    svc    = _svc()
    data   = request.get_json()
    full_name = data.get('full_name')
    email     = data.get('email')
    if not full_name or not email:
        return jsonify({'success': False, 'error': 'Missing name or email'}), 400
    try:
        profile = svc.find_profile_by_email(email)
        if not profile:
            # Invite-only: insert a placeholder profile
            svc.db.table('profiles').insert({'full_name': full_name, 'email': email}).execute()
            profile = svc.find_profile_by_email(email)
        if not profile:
            return jsonify({'success': False, 'error': 'Could not create profile'}), 500
        user_id = profile['id']
        success = svc.add_member(org_id, user_id)
        if success:
            return jsonify({'success': True, 'member': {'id': user_id, 'full_name': full_name}})
        return jsonify({'success': False, 'error': 'Could not add to organisation'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ── Holding Payments ──────────────────────────────────────────────────────────
@enterprise_bp.route('/holding-payments', methods=['GET', 'POST'])
@enterprise_required
def holding_payments():
    org_id  = session.get('curr_org_id')
    user_id = session['user']
    svc     = _svc()

    if request.method == 'POST':
        data = {
            'name':          request.form.get('name', '').strip(),
            'type':          request.form.get('type', 'receivable'),
            'amount':        request.form.get('amount', 0),
            'expected_date': request.form.get('expected_date', '').strip() or None,
            'mobile_no':     request.form.get('mobile_no', '').strip(),
            'narrative':     request.form.get('narrative', '').strip(),
        }
        if not data['name'] or not data['amount']:
            return jsonify({'success': False, 'error': 'Name and Amount are required.'}), 400
        try:
            ok = svc.add_holding_payment(org_id, user_id, data)
            return jsonify({'success': ok} if ok else {'success': False, 'error': 'Failed to save.'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    try:
        transactions = svc.get_holding_payments(org_id)
    except Exception as e:
        flash(f"Error loading holding payments: {str(e)}", "error")
        transactions = []

    active_biz = session.get('active_business', '')
    enterprise_banks = svc.get_banks_for_org(user_id, active_biz)
    org_members      = svc.get_org_members(org_id)

    total_receivable = sum(Decimal(str(t.get('amount') or 0)) for t in transactions if t.get('type') == 'receivable')
    total_payable    = sum(Decimal(str(t.get('amount') or 0)) for t in transactions if t.get('type') == 'payable')
    net_holding      = total_receivable - total_payable

    kpis = {
        'total_receivable': f"{total_receivable:,.2f}",
        'total_payable':    f"{total_payable:,.2f}",
        'net_holding':      f"{net_holding:,.2f}",
        'net_positive':     net_holding >= 0,
    }
    return render_template('enterprise/holding_payments.html',
                           transactions=transactions, kpis=kpis,
                           enterprise_banks=enterprise_banks, org_members=org_members)

@enterprise_bp.route('/holding-payments/settle', methods=['POST'])
@enterprise_required
def settle_holding_payment():
    org_id      = session.get('curr_org_id')
    txn_id      = request.form.get('txn_id', '').strip()
    settle_type = request.form.get('settle_type', 'full')
    part_amount = 0.0
    if settle_type == 'part':
        try:
            part_amount = float(request.form.get('part_amount', 0))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid partial amount.'}), 400
        if part_amount <= 0:
            return jsonify({'success': False, 'error': 'Partial amount must be > 0.'}), 400
    if not txn_id:
        return jsonify({'success': False, 'error': 'Transaction ID required.'}), 400
    try:
        result = _svc().settle_holding_payment(txn_id, org_id, settle_type, part_amount)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ── Investments ───────────────────────────────────────────────────────────────
@enterprise_bp.route('/investments', methods=['GET', 'POST'])
@enterprise_required
def investments():
    org_id = session.get('curr_org_id')
    svc    = _svc()

    if request.method == 'POST':
        # Safely determine taken_by or fallback to the logged in user
        taken_by_val = request.form.get('taken_by', '').strip()
        if not taken_by_val or taken_by_val == '__other__':
            taken_by_val = session.get('user')

        data = {
            'date':      request.form.get('date', '').strip(),
            'type':      request.form.get('type', 'investment'),
            'taken_by':  taken_by_val,
            'narrative': request.form.get('narrative', '').strip(),
            'amount':    request.form.get('amount', 0),
        }
        if not data['date'] or not data['amount']:
            return jsonify({'success': False, 'error': 'Date and Amount are required.'}), 400
        try:
            ok = svc.add_investment(org_id, data)
            return jsonify({'success': ok} if ok else {'success': False, 'error': 'Failed to save.'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    try:
        investments_list = svc.get_investments(org_id)
    except Exception as e:
        flash(f"Error loading investments: {str(e)}", "error")
        investments_list = []

    active_biz       = session.get('active_business', '')
    enterprise_banks = svc.get_banks_for_org(session['user'], active_biz)
    org_members      = svc.get_org_members(org_id)

    total_investment = sum(Decimal(str(i.get('amount') or 0)) for i in investments_list if i.get('type', 'investment') == 'investment')
    total_withdraw   = sum(Decimal(str(i.get('amount') or 0)) for i in investments_list if i.get('type') == 'withdraw')
    net_capital      = total_investment - total_withdraw

    kpis = {
        'total_investment': f"{total_investment:,.2f}",
        'total_withdraw':   f"{total_withdraw:,.2f}",
        'net_capital':      f"{net_capital:,.2f}",
        'net_positive':     net_capital >= 0,
    }
    return render_template('enterprise/investments.html',
                           investments_list=investments_list, kpis=kpis,
                           enterprise_banks=enterprise_banks, org_members=org_members)

# ── CSV Export ────────────────────────────────────────────────────────────────
@enterprise_bp.route('/export/<format>')
@enterprise_required
def export(format):
    org_id = session.get('curr_org_id')
    svc    = _svc()
    if format == 'csv':
        try:
            period     = request.args.get('period', 'all')
            today      = datetime.date.today()
            start_date = end_date = None
            if period == 'this_month':
                start_date = today.replace(day=1).strftime('%Y-%m-%d')
                end_date   = today.strftime('%Y-%m-%d')
            elif period == 'this_year':
                start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
                end_date   = today.strftime('%Y-%m-%d')

            revenue  = svc.get_revenue(org_id, start_date, end_date)
            expenses = svc.get_expenses(org_id, start_date, end_date)
            if not revenue and not expenses:
                flash("No data available for export.", "info")
                return redirect(url_for('enterprise.ent_dashboard'))

            fieldnames = ['Type', 'Date', 'Amount', 'Category', 'Method', 'Taken By', 'Narrative']
            rows = []
            for r in revenue:
                rows.append({'Type': 'Income', 'Date': str(r.get('date', '')),
                             'Amount': r.get('amount', ''), 'Category': r.get('category', ''),
                             'Method': r.get('method', ''), 'Taken By': r.get('taken_by', ''),
                             'Narrative': r.get('narrative', '')})
            for e in expenses:
                rows.append({'Type': 'Expense', 'Date': str(e.get('date', '')),
                             'Amount': e.get('amount', ''), 'Category': e.get('category', ''),
                             'Method': e.get('method', ''), 'Taken By': e.get('taken_by', ''),
                             'Narrative': e.get('narrative', '')})
            rows.sort(key=lambda x: x['Date'], reverse=True)

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8-sig')),
                mimetype='text/csv', as_attachment=True,
                download_name=f"enterprise_ledger_{period}_{today}.csv"
            )
        except Exception as e:
            flash(f"CSV Export Error: {e}", "error")
    return redirect(url_for('enterprise.ent_dashboard'))
