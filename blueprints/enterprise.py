from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, current_app
from functools import wraps
from decimal import Decimal
import datetime
import io
import csv
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
        
        token = session.get('access_token')
        # Note: In local mode, token might be None, handled in get_db_service
        db_service = get_db_service(token)
        user_id = session['user']
        
        try:
            # RBAC Check using Service
            member_orgs = db_service.get_user_organizations(user_id)
            
            if not member_orgs:
                flash("Access Denied: Enterprise Management is restricted to authorized members.", "error")
                return redirect(url_for('dashboard'))
            
            if 'curr_org_id' not in session:
                if len(member_orgs) == 1:
                    session['curr_org_id'] = member_orgs[0]['id']
                else:
                    return redirect(url_for('enterprise.select_organization'))
            
            valid_org_ids = [str(m['id']) for m in member_orgs]
            if str(session['curr_org_id']) not in valid_org_ids:
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
# Routes
# ---------------------------------------------------------

@enterprise_bp.route('/select_organization')
def select_organization():
    if 'user' not in session: return redirect(url_for('login'))
    db_service = get_db_service(session.get('access_token'))
    try:
        organizations = db_service.get_user_organizations(session['user'])
        
        if not organizations:
            flash("You are not a member of any organization.", "warning")
            return redirect(url_for('dashboard'))
            
        return render_template('enterprise/select_organization.html', organizations=organizations)
    except Exception as e:
        flash(f"Error loading organizations: {str(e)}", "error")
        return redirect(url_for('dashboard'))

@enterprise_bp.route('/switch_organization/<org_id>')
def switch_organization(org_id):
    if 'user' not in session: return redirect(url_for('login'))
    db_service = get_db_service(session.get('access_token'))
    try:
        member_orgs = db_service.get_user_organizations(session['user'])
        valid_org_ids = [str(m['id']) for m in member_orgs]
        
        if str(org_id) in valid_org_ids:
            session['curr_org_id'] = org_id
            flash("Switched to organization successfully.", "success")
        else:
            flash("You do not have access to this organization.", "error")
    except Exception as e:
        flash(f"Error switching organization: {str(e)}", "error")
    return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/')
@enterprise_required
def ent_dashboard():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    
    try:
        revenue_data = db_service.get_revenue(org_id)
        expense_data = db_service.get_expenses(org_id)
        invest_data = db_service.get_investments(org_id)
        
        total_rev = sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data])
        total_exp = sum([Decimal(str(e.get('amount') or 0)) for e in expense_data])
        net_pl = total_rev - total_exp
        total_invest = sum([Decimal(str(i.get('amount') or 0)) for i in invest_data])
        
        total_pending = sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data if r.get('status') == 'pending'])
        
        burn_rate = Decimal('0.00')
        if expense_data:
            months = {}
            for e in expense_data:
                # Handle both types of date objects/strings
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
            'total_revenue': f"{total_rev:,.2f}",
            'total_expenses': f"{total_exp:,.2f}",
            'net_pl': f"{net_pl:,.2f}",
            'pending_payments': f"{total_pending:,.2f}",
            'burn_rate': f"{burn_rate:,.2f}",
            'margin_pct': margin_pct,
            'total_investments': f"{total_invest:,.2f}",
            'is_profit': net_pl >= 0
        }
        
        all_months = sorted(list(set([str(r['date'])[:7] for r in revenue_data] + [str(e['date'])[:7] for e in expense_data])))
        trend_months = all_months[-6:]
        rev_trend = [float(sum([Decimal(str(r.get('amount') or 0)) for r in revenue_data if str(r['date']).startswith(m)])) for m in trend_months]
        exp_trend = [float(sum([Decimal(str(e.get('amount') or 0)) for e in expense_data if str(e['date']).startswith(m)])) for m in trend_months]
            
        org_name = db_service.get_organization_name(org_id) or 'Enterprise'

        return render_template('enterprise/dashboard.html', kpis=kpis, 
                               trend_labels=trend_months, rev_trend=rev_trend, exp_trend=exp_trend,
                               org_name=org_name, currency='₹') # TODO: Fetch currency from profile
                               
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
    try:
        revenue_list = db_service.get_revenue(org_id)
        return render_template('enterprise/revenue.html', revenue_list=revenue_list)
    except Exception as e:
        flash(f"Error loading revenue: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/expenses')
@enterprise_required
def expenses():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    try:
        expenses_list = db_service.get_expenses(org_id)
        return render_template('enterprise/expenses.html', expenses_list=expenses_list)
    except Exception as e:
        flash(f"Error loading expenses: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/members', methods=['GET', 'POST'])
@enterprise_required
def members():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        role = request.form.get('role', 'member')
        
        try:
            profile = db_service.find_profile_by_email(email)
            if not profile:
                flash(f"User with email {email} not found. They must register first.", "error")
                return redirect(url_for('enterprise.members'))
            
            target_user_id = profile['id']
            
            # Check if already a member
            current_members = db_service.get_members(org_id)
            if any(m['email'] == email for m in current_members):
                flash("User is already a member of this organization.", "info")
            else:
                success = db_service.add_member(org_id, target_user_id, role)
                if success:
                    flash(f"Successfully added {email} to the team.", "success")
                else:
                    flash("Error adding team member.", "error")
                
        except Exception as e:
            current_app.logger.error(f"Add Member Error: {e}")
            flash("Error processing member addition.", "error")
            
        return redirect(url_for('enterprise.members'))

    try:
        members_list = db_service.get_members(org_id)
        return render_template('enterprise/members.html', members_list=members_list)
    except Exception as e:
        flash(f"Error loading members: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

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
    # else if period is custom, start_date and end_date are from args
    
    try:
        revenue = db_service.get_revenue(org_id, start_date, end_date)
        expenses = db_service.get_expenses(org_id, start_date, end_date)
        banks = db_service.get_personal_banks(session['user'])
        categories = db_service.get_categories(session['user'])
        members = db_service.get_members(org_id)
        
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
        
        return render_template('enterprise/revenue_expenses.html', 
                               ledger=ledger, 
                               total_income=total_income,
                               total_expenses=total_expenses,
                               period=period,
                               start_date=start_date,
                               end_date=end_date,
                               banks=banks,
                               categories=categories,
                               members=members,
                               currency='₹')
    except Exception as e:
        flash(f"Error loading cashflow: {e}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

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

@enterprise_bp.route('/holding-payments')
@enterprise_required
def holding_payments():
    return render_template('enterprise/holding_payments.html')

@enterprise_bp.route('/investments')
@enterprise_required
def investments():
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    try:
        investments_list = db_service.get_investments(org_id)
        return render_template('enterprise/investments.html', investments_list=investments_list)
    except Exception as e:
        flash(f"Error loading investments: {str(e)}", "error")
        return redirect(url_for('enterprise.ent_dashboard'))

@enterprise_bp.route('/export/<format>')
@enterprise_required
def export(format):
    org_id = session.get('curr_org_id')
    db_service = get_db_service(session.get('access_token'))
    
    if format == 'csv':
        try:
            expenses = db_service.get_expenses(org_id)
            if not expenses:
                flash("No data available for export.", "info")
                return redirect(url_for('enterprise.ent_dashboard'))
                
            output = io.StringIO()
            # Ensure headers are consistent even if data is from different backends
            if expenses:
                writer = csv.DictWriter(output, fieldnames=expenses[0].keys())
                writer.writeheader()
                writer.writerows(expenses)
                
            return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name=f"enterprise_expenses_{datetime.date.today()}.csv")
        except Exception as e:
            flash(f"CSV Export Error: {e}", "error")
            return redirect(url_for('enterprise.ent_dashboard'))
    return redirect(url_for('enterprise.ent_dashboard'))
