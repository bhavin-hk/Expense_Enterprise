from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, current_app, jsonify
from functools import wraps
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import io
import csv
import secrets
from .database_service import get_db_service

enterprise_bp = Blueprint('enterprise', __name__)

# ---------------------------------------------------------
# Enterprise Decorator
# ---------------------------------------------------------

def enterprise_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))

        # Check per-business auth gate
        if not session.get('active_business'):
            flash("Please sign in to a business account first.", "error")
            return redirect(url_for('banks'))

        token = session.get('access_token')
        db_service = get_db_service(token)
        user_id = session['user']

        try:
            member_orgs = db_service.get_user_organizations(user_id)

            if not member_orgs:
                flash("Access Denied: Enterprise Management is restricted to authorized members.", "error")
                return redirect(url_for('dashboard'))

            valid_org_ids = [str(m['id']) for m in member_orgs]

            # If curr_org_id is missing or no longer valid, re-derive it from the active business
            if 'curr_org_id' not in session or str(session['curr_org_id']) not in valid_org_ids:
                active_biz = session.get('active_business')
                if active_biz:
                    org_id = db_service.provision_business_org(user_id, active_biz)
                    if org_id:
                        session['curr_org_id'] = org_id
                        valid_org_ids = valid_org_ids + [org_id]
                    else:
                        session.pop('curr_org_id', None)
                        flash("Could not resolve your business organisation.", "error")
                        return redirect(url_for('dashboard'))
                elif len(member_orgs) == 1:
                    session['curr_org_id'] = member_orgs[0]['id']
                else:
                    return redirect(url_for('enterprise.select_organization'))

            if str(session.get('curr_org_id', '')) not in valid_org_ids:
                session.pop('curr_org_id', None)
                return redirect(url_for('enterprise.select_organization'))

        except Exception as e:
            import traceback
            current_app.logger.error(f"Enterprise RBAC Error: {e}")
            current_app.logger.error(traceback.format_exc())
            flash(f"An error occurred during enterprise verification: {str(e)}", "error")
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# Auth Routes (no decorator — must be accessible pre-login)
# ---------------------------------------------------------

@enterprise_bp.route('/check_auth/<business_name>')
def check_auth(business_name):
    """JSON API: returns whether the business has registered credentials."""
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    db_service = get_db_service(session.get('access_token'))
    creds = db_service.get_business_credentials(session['user'], business_name)
    return jsonify({'registered': creds is not None})


@enterprise_bp.route('/signup', methods=['POST'])
def enterprise_signup():
    if 'user' not in session:
        return redirect(url_for('login'))
    business_name = request.form.get('business_name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    if not business_name or not email or not password:
        flash('All fields are required.', 'error')
        return redirect(url_for('banks'))
    if password != confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('banks'))

    db_service = get_db_service(session.get('access_token'))
    existing = db_service.get_business_credentials(session['user'], business_name)
    if existing:
        flash('This business is already registered. Please sign in.', 'error')
        return redirect(url_for('banks'))

    pw_hash = generate_password_hash(password)
    token = secrets.token_urlsafe(32)
    ok = db_service.create_business_credentials(session['user'], business_name, email, pw_hash, token)
    if ok:
        # Automatically verify for local development
        db_service.verify_business_email(token)

        verify_url = url_for('enterprise.verify_email', token=token, _external=True)
        # Mock email — print to console for local testing reference
        print(f"\n=== VERIFICATION LINK (Auto-Verified) for {business_name} ===\n{verify_url}\n")

        # Create a dedicated organisation for this business and enrol the owner
        org_id = db_service.provision_business_org(session['user'], business_name)
        session['active_business'] = business_name
        if org_id:
            session['curr_org_id'] = org_id
        flash(f'Account created and auto-verified for development!', 'success')
        return redirect(url_for('enterprise.ent_dashboard'))
    else:
        flash('Sign-up failed. The email may already be in use.', 'error')
    return redirect(url_for('banks'))


@enterprise_bp.route('/login', methods=['POST'])
def enterprise_login():
    if 'user' not in session:
        return redirect(url_for('login'))
    business_name = request.form.get('business_name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if not business_name or not email or not password:
        flash('All fields are required.', 'error')
        return redirect(url_for('banks'))

    db_service = get_db_service(session.get('access_token'))
    creds = db_service.get_business_credentials(session['user'], business_name)
    if not creds:
        flash('No account found for this business. Please sign up first.', 'error')
        return redirect(url_for('banks'))
    if not check_password_hash(creds['password_hash'], password):
        flash('Invalid password.', 'error')
        return redirect(url_for('banks'))

    # Relaxation: Allow login even if is_verified is False for local development
    # (Original check removed to unblock development)

    session['active_business'] = business_name
    # Provision (or retrieve) the dedicated org for this business and lock in curr_org_id.
    # This is idempotent — safe for both new and existing businesses.
    org_id = db_service.provision_business_org(session['user'], business_name)
    print(f"[DEBUG LOGIN] business_name={business_name!r}, provisioned org_id={org_id!r}")
    if org_id:
        session['curr_org_id'] = org_id
    else:
        session.pop('curr_org_id', None)
    print(f"[DEBUG LOGIN] session curr_org_id is now: {session.get('curr_org_id')!r}")
    flash(f'Signed in to {business_name} successfully!', 'success')
    return redirect(url_for('enterprise.ent_dashboard'))



@enterprise_bp.route('/verify/<token>')
def verify_email(token):
    db_service = get_db_service(session.get('access_token'))
    result = db_service.verify_business_email(token)
    if result:
        flash('Email verified! You can now sign in.', 'success')
    else:
        flash('Invalid or expired verification token.', 'error')
    return redirect(url_for('banks'))


@enterprise_bp.route('/logout')
def enterprise_logout():
    session.pop('active_business', None)
    flash('Signed out of business account.', 'success')
    return redirect(url_for('banks'))

# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

@enterprise_bp.route('/select_organization')
def select_organization():
    if 'user' not in session: return redirect(url_for('login'))
    db_service = get_db_service(session.get('access_token'))
    try:
        businesses = db_service.get_user_businesses(session['user'])
        if not businesses:
            flash("You have no registered businesses. Register one below.", "warning")
            return redirect(url_for('banks'))
        return render_template('enterprise/select_organization.html', businesses=businesses)
    except Exception as e:
        flash(f"Error loading businesses: {str(e)}", "error")
        return redirect(url_for('banks'))

@enterprise_bp.route('/business-login/<path:business_name>')
def business_login_page(business_name):
    """Show the enterprise login form pre-filled for the selected business."""
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('enterprise/business_login.html', business_name=business_name)

@enterprise_bp.route('/')
@enterprise_required
def ent_dashboard():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    
    try:
        revenue_data = db_service.get_revenue(org_id)
        expense_data = db_service.get_expenses(org_id)
        invest_data  = db_service.get_investments(org_id)
        
        total_rev    = sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data])
        total_exp    = sum([Decimal(str(e.get('amount') or 0)) for e in expense_data])
        net_pl       = total_rev - total_exp
        total_invest = sum([Decimal(str(i.get('amount') or 0)) for i in invest_data])
        
        total_pending = sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data if r.get('status') == 'pending'])
        
        burn_rate = Decimal('0.00')
        if expense_data:
            months = {}
            for e in expense_data:
                dt_val = str(e['date'])
                m = dt_val[:7]
                amt = Decimal(str(e.get('amount') or 0))
                months[m] = months.get(m, Decimal('0.00')) + amt
            last_3_months = sorted(months.keys(), reverse=True)[:3]
            if last_3_months:
                total_last_3 = sum([months[m] for m in last_3_months])
                burn_rate = total_last_3 / len(last_3_months)
        
        margin_pct = "0.00%"
        if total_rev > 0:
            margin = (net_pl / total_rev) * 100
            margin_pct = f"{margin:,.2f}%"
            
        kpis = {
            'total_revenue':    f"{total_rev:,.2f}",
            'total_expenses':   f"{total_exp:,.2f}",
            'net_pl':           f"{net_pl:,.2f}",
            'pending_payments': f"{total_pending:,.2f}",
            'burn_rate':        f"{burn_rate:,.2f}",
            'margin_pct':       margin_pct,
            'total_investments':f"{total_invest:,.2f}",
            'is_profit':        net_pl >= 0
        }
        
        # --- Trend chart: last 6 months (fallback to calendar months when no data) ---
        data_months = sorted(list(set(
            [str(r['date'])[:7] for r in revenue_data] +
            [str(e['date'])[:7] for e in expense_data]
        )))
        if data_months:
            trend_months = data_months[-6:]
        else:
            # Fallback: last 6 calendar months
            today = datetime.date.today()
            trend_months = []
            for i in range(5, -1, -1):
                d = (today.replace(day=1) - datetime.timedelta(days=1)) if i == 0 else today
                # Go back i months
                month = today.month - i
                year  = today.year + (month - 1) // 12
                month = ((month - 1) % 12) + 1
                trend_months.append(f"{year}-{month:02d}")

        rev_trend = [float(sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(m)])) for m in trend_months]
        exp_trend = [float(sum([Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(m)])) for m in trend_months]

        # --- Executive Reports: compute real summary rows ---
        today = datetime.date.today()
        this_month_label = today.strftime('%B %Y')
        this_month_pfx   = today.strftime('%Y-%m')
        this_year_label  = str(today.year)

        month_rev = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(this_month_pfx))
        month_exp = sum(Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(this_month_pfx))
        year_rev  = sum(Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(this_year_label))
        year_exp  = sum(Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(this_year_label))

        report_data = [
            {
                'name':   f"{this_month_label} Summary",
                'range':  this_month_label,
                'income': f"{month_rev:,.2f}",
                'expense':f"{month_exp:,.2f}",
                'net':    f"{month_rev - month_exp:,.2f}",
                'positive': month_rev >= month_exp,
                'can_download': True,
                'dl_params': f"period=this_month",
            },
            {
                'name':   f"{this_year_label} Year-to-Date",
                'range':  f"Jan – {today.strftime('%b')} {this_year_label}",
                'income': f"{year_rev:,.2f}",
                'expense':f"{year_exp:,.2f}",
                'net':    f"{year_rev - year_exp:,.2f}",
                'positive': year_rev >= year_exp,
                'can_download': True,
                'dl_params': f"period=this_year",
            },
        ]

        org_name = db_service.get_organization_name(org_id) or 'Enterprise'

        return render_template('enterprise/dashboard.html',
                               kpis=kpis,
                               trend_labels=trend_months,
                               rev_trend=rev_trend,
                               exp_trend=exp_trend,
                               report_data=report_data,
                               org_name=org_name,
                               currency='₹')
                               
    except Exception as e:
        import traceback
        current_app.logger.error(f"Enterprise Dashboard Error: {e}")
        current_app.logger.error(traceback.format_exc())
        flash(f"An error occurred while loading financial data: {str(e)}", "error")
        return redirect(url_for('dashboard'))

@enterprise_bp.route('/revenue')
@enterprise_required
def revenue():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    period = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    today = datetime.date.today()
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    elif period == 'this_week':
        start_date = (today - datetime.timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last.replace(day=1).strftime('%Y-%m-%d')
        end_date = last.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    try:
        revenue_list = db_service.get_revenue(org_id, start_date, end_date)
        return render_template('enterprise/revenue.html',
                               revenue_list=revenue_list, period=period,
                               start_date=start_date, end_date=end_date, currency='₹')
    except Exception as e:
        flash(f"Error loading revenue: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/expenses')
@enterprise_required
def expenses():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    period = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    today = datetime.date.today()
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    elif period == 'this_week':
        start_date = (today - datetime.timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last.replace(day=1).strftime('%Y-%m-%d')
        end_date = last.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    try:
        expenses_list = db_service.get_expenses(org_id, start_date, end_date)
        return render_template('enterprise/expenses.html',
                               expenses_list=expenses_list, period=period,
                               start_date=start_date, end_date=end_date, currency='₹')
    except Exception as e:
        flash(f"Error loading expenses: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/members', methods=['GET', 'POST'])
@enterprise_required
def members():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        designation = request.form.get('designation', '').strip()
        if not name:
            flash("Staff name is required.", "error")
        else:
            ok = db_service.add_org_member(org_id, name, designation)
            if ok:
                flash(f"'{name}' added to team.", "success")
            else:
                flash("Error adding staff member.", "error")
        return redirect(url_for('enterprise.members'))

    staff_list = db_service.get_org_members(org_id)
    return render_template('enterprise/members.html', staff_list=staff_list)

@enterprise_bp.route('/combined-cashflow')
@enterprise_required
def revenue_expenses():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))

    period = request.args.get('period', 'this_month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    today = datetime.date.today()
    
    if period == 'this_month':
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        last_month = today.replace(day=1) - datetime.timedelta(days=1)
        start_date = last_month.replace(day=1).strftime('%Y-%m-%d')
        end_date = last_month.strftime('%Y-%m-%d')
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    # else custom: start_date and end_date are from args
    
    try:
        revenue = db_service.get_revenue(org_id, start_date, end_date)
        expenses = db_service.get_expenses(org_id, start_date, end_date)
        
        # Filter Payment Methods to Active Business Only
        all_ent_banks = db_service.get_enterprise_banks(session['user'])
        active_biz = session.get('active_business')
        enterprise_banks = [b for b in all_ent_banks if b.get('business_name') == active_biz]

        categories = db_service.get_categories(session['user'])
        
        # Merge into ledger
        ledger = []
        for r in revenue:
            ledger.append({**r, 'type': 'Income'})
        for e in expenses:
            ledger.append({**e, 'type': 'Expense'})
            
        # Sort by date desc
        ledger.sort(key=lambda x: str(x['date']), reverse=True)
        
        total_income = sum([Decimal(str(i['amount'])) for i in ledger if i['type'] == 'Income'])
        total_expenses = sum([Decimal(str(e['amount'])) for e in ledger if e['type'] == 'Expense'])
    except Exception as e:
        flash(f"Error loading cashflow: {e}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

    # Fetch org staff separately — isolated so it never breaks the page
    try:
        org_members = db_service.get_org_members(org_id)
    except Exception:
        org_members = []

    return render_template('enterprise/revenue_expenses.html',
                           ledger=ledger,
                           total_income=total_income,
                           total_expenses=total_expenses,
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           enterprise_banks=enterprise_banks,
                           categories=categories,
                           org_members=org_members,
                           currency='₹')

@enterprise_bp.route('/add-transaction', methods=['POST'])
@enterprise_required
def add_transaction():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    user_id = session['user']
    
    t_type = request.form.get('type') # 'Income' or 'Expense'
    amount = request.form.get('amount')
    date = request.form.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    method_val = request.form.get('method') # 'Cash' or a UUID bank_id
    narrative = request.form.get('narrative')
    category = request.form.get('category')
    
    if not amount or not t_type or not method_val:
        flash("Missing required fields", "error")
        return redirect(url_for('enterprise.revenue_expenses'))
        
    bank_account_id = None
    method = 'Cash'
    if method_val != 'Cash':
        bank_account_id = method_val
        method = 'Bank'

    data = {
        'amount': amount,
        'date': date,
        'method': method,
        'narrative': narrative,
        'category': category,
        'taken_by': request.form.get('taken_by', user_id),
        'bank_account_id': bank_account_id
    }
    
    try:
        if not data.get('category'):
            data['category'] = 'Other'
            
        if t_type == 'Income':
            # ent_revenue table has no 'category' column
            if 'category' in data:
                del data['category']
            success = db_service.add_revenue(org_id, data)
        else:
            success = db_service.add_expense(org_id, data)
            
        if success:
            flash(f"Successfully added {t_type.lower()}.", "success")
        else:
            flash(f"Error adding {t_type.lower()}.", "error")
            
    except Exception as e:
        flash(f"Transaction failed: {e}", "error")
        
    return redirect(url_for('enterprise.revenue_expenses'))

@enterprise_bp.route('/add-member-fast', methods=['POST'])
@enterprise_required
def add_member_fast():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    
    data = request.get_json()
    full_name = data.get('full_name')
    email = data.get('email')
    
    if not full_name or not email:
        return jsonify({'success': False, 'error': 'Missing name or email'}), 400
        
    try:
        # Check if profile exists
        profile = db_service.find_profile_by_email(email)
        if not profile:
            # Create a simple profile if it doesn't exist (Local/Mock)
            # In a real app, this would be an invitation.
            import uuid
            user_id = str(uuid.uuid4())
            # We need a method to create a profile if it doesn't exist.
            # For now, let's assume we can insert into profiles.
            if hasattr(db_service, '_execute_query'): # Postgres
                db_service._execute_query("INSERT INTO profiles (id, full_name, email) VALUES (%s, %s, %s)", (user_id, full_name, email), fetch=False)
            else: # Supabase
                db_service.db.table('profiles').insert({'id': user_id, 'full_name': full_name, 'email': email}).execute()
        else:
            user_id = profile['id']
            
        success = db_service.add_member(org_id, user_id)
        if success:
            return jsonify({'success': True, 'member': {'id': user_id, 'full_name': full_name}})
        else:
            return jsonify({'success': False, 'error': 'Could not add to organization'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------------------------------------------------------------------------
@enterprise_bp.route('/holding-payments', methods=['GET', 'POST'])
@enterprise_required
def holding_payments():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    user_id = session['user']

    if request.method == 'POST':
        # Handle Add Transaction via AJAX
        data = {
            'name': request.form.get('name', '').strip(),
            'type': request.form.get('type', 'receivable'),
            'amount': request.form.get('amount', 0),
            'expected_date': request.form.get('expected_date', '').strip() or None,
            'mobile_no': request.form.get('mobile_no', '').strip(),
            'narrative': request.form.get('narrative', '').strip(),
        }
        if not data['name'] or not data['amount']:
            return jsonify({'success': False, 'error': 'Name and Amount are required.'}), 400
        try:
            ok = db_service.add_holding_payment(org_id, user_id, data)
            if ok:
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Failed to save transaction.'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # GET — load transactions and compute KPIs
    try:
        transactions = db_service.get_holding_payments(org_id)
    except Exception as e:
        flash(f"Error loading holding payments: {str(e)}", "error")
        transactions = []

    # Fetch org-scoped bank accounts for Payment Method dropdown
    active_biz = session.get('active_business', '')
    try:
        enterprise_banks = db_service.get_banks_for_org(user_id, active_biz)
    except Exception:
        enterprise_banks = []

    try:
        org_members = db_service.get_org_members(org_id)
    except Exception:
        org_members = []

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
                           enterprise_banks=enterprise_banks,
                           org_members=org_members)


@enterprise_bp.route('/holding-payments/settle', methods=['POST'])
@enterprise_required
def settle_holding_payment():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))

    txn_id      = request.form.get('txn_id', '').strip()
    settle_type = request.form.get('settle_type', 'full')   # 'full' or 'part'
    part_amount = 0.0

    if settle_type == 'part':
        try:
            part_amount = float(request.form.get('part_amount', 0))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid partial amount.'}), 400
        if part_amount <= 0:
            return jsonify({'success': False, 'error': 'Partial amount must be greater than zero.'}), 400

    if not txn_id:
        return jsonify({'success': False, 'error': 'Transaction ID is required.'}), 400

    try:
        result = db_service.settle_holding_payment(txn_id, org_id, settle_type, part_amount)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
# ------------------------------------------------------------------------------


@enterprise_bp.route('/investments', methods=['GET', 'POST'])
@enterprise_required
def investments():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))

    if request.method == 'POST':
        data = {
            'date':      request.form.get('date', '').strip(),
            'type':      request.form.get('type', 'investment'),
            'taken_by':  request.form.get('taken_by', '').strip(),
            'narrative': request.form.get('narrative', '').strip(),
            'amount':    request.form.get('amount', 0),
        }
        if not data['date'] or not data['amount']:
            return jsonify({'success': False, 'error': 'Date and Amount are required.'}), 400
        try:
            ok = db_service.add_investment(org_id, data)
            if ok:
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Failed to save entry.'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    try:
        investments_list = db_service.get_investments(org_id)
    except Exception as e:
        flash(f"Error loading investments: {str(e)}", "error")
        investments_list = []

    # Fetch org-scoped bank accounts for Payment Method dropdown
    active_biz = session.get('active_business', '')
    try:
        enterprise_banks = db_service.get_banks_for_org(session['user'], active_biz)
    except Exception:
        enterprise_banks = []

    try:
        org_members = db_service.get_org_members(org_id)
    except Exception:
        org_members = []

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
                           enterprise_banks=enterprise_banks,
                           org_members=org_members)
# -------------------------------------------------------------------------------------

@enterprise_bp.route('/export/<format>')
@enterprise_required
def export(format):
    org_id   = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))

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

            revenue  = db_service.get_revenue(org_id, start_date, end_date)
            expenses = db_service.get_expenses(org_id, start_date, end_date)

            if not revenue and not expenses:
                flash("No data available for export.", "info")
                return redirect(url_for('enterprise.ent_dashboard'))

            # Build a unified ledger rows with consistent columns
            fieldnames = ['Type', 'Date', 'Amount', 'Category', 'Method', 'Taken By', 'Narrative']
            rows = []
            for r in revenue:
                rows.append({
                    'Type':      'Income',
                    'Date':      str(r.get('date', '')),
                    'Amount':    r.get('amount', ''),
                    'Category':  r.get('category', ''),
                    'Method':    r.get('method', ''),
                    'Taken By':  r.get('taken_by', ''),
                    'Narrative': r.get('narrative', ''),
                })
            for e in expenses:
                rows.append({
                    'Type':      'Expense',
                    'Date':      str(e.get('date', '')),
                    'Amount':    e.get('amount', ''),
                    'Category':  e.get('category', ''),
                    'Method':    e.get('method', ''),
                    'Taken By':  e.get('taken_by', ''),
                    'Narrative': e.get('narrative', ''),
                })

            # Sort by date descending
            rows.sort(key=lambda x: x['Date'], reverse=True)

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

            filename = f"enterprise_ledger_{period}_{today}.csv"
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8-sig')),  # utf-8-sig for Excel compatibility
                mimetype='text/csv',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            flash(f"CSV Export Error: {e}", "error")
            return redirect(url_for('enterprise.ent_dashboard'))

    return redirect(url_for('enterprise.ent_dashboard'))
