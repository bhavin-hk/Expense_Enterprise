from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.exceptions import HTTPException
from functools import wraps
from decimal import Decimal
from supabase import create_client, Client, ClientOptions
import os
import datetime
from datetime import timedelta
from dotenv import load_dotenv
from flask_mail import Mail, Message
from utils import generate_pdf_report, send_email_report
from blueprints.enterprise import enterprise_bp
from blueprints.database_service import get_db_service, SupabaseService, get_supabase_client

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------
# Configuration & Security through .env
# ---------------------------------------------------------
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-dev-secret")
app.config['SUPABASE_URL'] = os.getenv("SUPABASE_URL")
app.config['SUPABASE_KEY'] = os.getenv("SUPABASE_KEY")


# ---------------------------------------------------------
# Session Storage (Stateless Client-Side Signed Cookies)
# ---------------------------------------------------------
# Removed filesystem session to support Vercel (Serverless/Stateless)
app.config.update(
    SESSION_COOKIE_SECURE=True, # Require HTTPS (handled by Vercel/Localhost)
    SESSION_COOKIE_HTTPONLY=True, # Prevent JS access
    SESSION_COOKIE_SAMESITE='Lax',
)

# Timeouts
timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", 10))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) 
# Note: internal logic uses timeout_minutes for inactivity, cookie lifetime is 7 days to avoid frequent logins if active.

# Initialize Extensions
# server_session = Session(app) # Removed for stateless auth

# Mail Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME", "parthhkdigiverse@gmail.com")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD", "uqzm jykr xehs cmne") 
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_USERNAME", "parthhkdigiverse@gmail.com")
mail = Mail(app)

# Database Configuration
DB_BACKEND = os.getenv("DB_BACKEND", "supabase").lower()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
REFRESH_THRESHOLD = int(os.getenv("REFRESH_THRESHOLD_SECONDS", 120)) # 2 minutes

# Register Blueprints
app.register_blueprint(enterprise_bp, url_prefix='/enterprise')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("CRITICAL: SUPABASE_URL and SUPABASE_KEY must be set in .env")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Session & Token Management Logic
# ---------------------------------------------------------

@app.before_request
def manage_session_logic():
    """
    Global middleware to handle:
    1. Inactivity Timeout (strict 10 mins)
    2. Supabase Token Refresh (if < 2 mins left)
    3. Update Last Activity
    """
    # Skip session logic for auth routes
    if request.endpoint in ['login', 'register','verify','login_with_code','magic_login', 'static', 'forgot_credentials', 'reset_password']:
        return
    
    # Skip session logic for None endpoint (e.g. favicon.ico)
    if request.endpoint is None:
        return

    if 'user' in session:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. Check Inactivity Timeout
        last_activity = session.get('last_activity')
        if last_activity:
            # last_activity is stored as ISO string or timestamp
            if isinstance(last_activity, str):
                last_time = datetime.datetime.fromisoformat(last_activity)
            else:
                last_time = last_activity

            # Ensure timezone awareness compatibility
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)

            duration = now - last_time
            if duration > timedelta(minutes=timeout_minutes):
                session.clear()
                flash('Session expired due to inactivity. Please login again.', 'warning')
                return redirect(url_for('login'))

        # 2. Refresh Supabase Token if needed (Only for Supabase Backend)
        if DB_BACKEND == 'supabase':
            expires_at = session.get('access_expires_at')
            if expires_at:
                 # Check if nearing expiry
                 if isinstance(expires_at, int): # Timestamp
                     exp_time = datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc)
                 else:
                     exp_time = datetime.datetime.fromisoformat(expires_at)
                     if exp_time.tzinfo is None:
                         exp_time = exp_time.replace(tzinfo=datetime.timezone.utc)
                 
                 time_left = exp_time - now
                 if time_left < timedelta(seconds=REFRESH_THRESHOLD):
                     print("DEBUG: Refreshing Supabase Token...")
                     refresh_token = session.get('refresh_token')
                     if refresh_token:
                         try:
                             # Use Supabase client to refresh
                             res = supabase.auth.refresh_session(refresh_token)
                             if res and res.session:
                                 session['access_token'] = res.session.access_token
                                 session['refresh_token'] = res.session.refresh_token
                                 session['access_expires_at'] = res.session.expires_at
                                 print("DEBUG: Token refreshed successfully.")
                             else:
                                 raise Exception("Refresh failed")
                         except Exception as e:
                             print(f"DEBUG: Token refresh failed: {e}")
                             session.clear()
                             flash('Session expired. Please login again.', 'error')
                             return redirect(url_for('login'))

        # 3. Update Last Activity
        session['last_activity'] = now.isoformat()

# ---------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------

def check_db_config():
    if not supabase:
        flash("Critical Error: Database configuration missing. Please check server logs.", "error")
        return False
    return True

def get_db(token=None):
    """
    Returns an authenticated Supabase client if token is provided,
    otherwise returns the admin/anon client.
    """
    if token:
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    return supabase


def get_user_profile(token):
    try:
        res = get_db(token).table('profiles').select('*').eq('id', session['user']).execute()
        return res.data[0] if res.data else {}
    except:
        return {}

def check_recurring_expenses(user_id, token):
    """
    Checks for due recurring expenses and adds them.
    Adapted for Supabase.
    """
    try:
        today = datetime.date.today().isoformat()
        res = get_db(token).table('recurring_expenses').select('*').eq('user_id', user_id).lte('next_due_date', today).execute()
        due_items = res.data
        count = 0
        for item in due_items:
            desc = item['description'] + " (Auto-Recurring)" if item['description'] else "(Auto-Recurring)"
            expense_data = {
                'user_id': user_id,
                'date': item['next_due_date'],
                'category': item['category'],
                'amount': item['amount'],
                'description': desc,
                'recurring_rule_id': item['id']
            }
            get_db(token).table('expenses').insert(expense_data).execute()
            count += 1
            d_obj = datetime.datetime.strptime(item['next_due_date'], "%Y-%m-%d")
            new_due = (d_obj + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
            get_db(token).table('recurring_expenses').update({'next_due_date': new_due}).eq('id', item['id']).execute()
        return count
    except Exception as e:
        print(f"Error checking recurring expenses: {e}")
        return 0

DEFAULT_CATEGORIES = [
    'Food', 'Transport', 'Utilities', 'Entertainment', 'Shopping', 
    'Health', 'Travel', 'Education', 'Salary', 'Freelance', 'Investment', 'Other'
]

def get_all_categories(token, user_id):
    try:
        res = get_db(token).table('user_categories').select('name').eq('user_id', user_id).execute()
        custom_cats = [r['name'] for r in res.data]
        return DEFAULT_CATEGORIES + custom_cats
    except:
        return DEFAULT_CATEGORIES

def get_filtered_expenses(token, user_id, args):
    start_date = args.get('start_date')
    end_date = args.get('end_date')
    category = args.get('category')
    bank_id = args.get('bank_id')

    exp_query = get_db(token).table('expenses').select('*, bank_accounts(bank_name)').eq('user_id', user_id).order('date', desc=True).order('created_at', desc=True)

    if start_date: exp_query = exp_query.gte('date', start_date)
    if end_date: exp_query = exp_query.lte('date', end_date)
    if category and category != 'All': exp_query = exp_query.eq('category', category)
    if bank_id:
            if bank_id == 'Cash':
                exp_query = exp_query.is_('bank_account_id', 'null')
            elif bank_id != 'All':
                exp_query = exp_query.eq('bank_account_id', bank_id)
    
    expenses_res = exp_query.execute()
    return expenses_res.data


@app.template_filter('format_date')
def format_date(value, format="%d-%m-%Y"):
    if value is None:
        return ""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").strftime(format)
    except ValueError:
        return value

# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Clear session only when actually attempting to login
        session.clear()
        session.permanent = True
        
        if not check_db_config():
            return render_template('login.html')

        username = request.form.get('username')
        password = request.form.get('password')

        try:
            # 1. Lookup email from username
            user_res = supabase.table('profiles').select('email, id').eq('username', username).execute()
            if not user_res.data:
                flash('Invalid username or password', 'error')
                return render_template('login.html')
            
            email = user_res.data[0]['email']
            if not email:
                 flash('Account configuration error.', 'error')
                 return render_template('login.html')

            # 2. Sign in
            res = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            # 3. Secure Session Setup
            session.clear() # Prevent session fixation
            session.permanent = True # Enable timeout
            
            session['user'] = res.user.id
            session['user_email'] = email
            session['access_token'] = res.session.access_token
            session['refresh_token'] = res.session.refresh_token
            session['access_expires_at'] = res.session.expires_at # Auto-refresh trigger
            session['last_activity'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            print(f"Login Error: {e}")
            flash('Login failed. Please check credentials.', 'error')
            
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not check_db_config(): return render_template('register.html')

        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')

        try:
            existing_user = supabase.table('profiles').select('id').eq('username', username).execute()
            if existing_user.data:
                flash('Username already taken', 'error')
                return render_template('register.html')

            res = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "username": username,
                        "full_name": full_name,
                    }
                }
            })
            if res.user:
                 flash('Registration successful! Please login.', 'success')
                 return redirect(url_for('login'))
        except Exception as e:
            flash(f"Registration failed: {str(e)}", 'error')
    return render_template('register.html')

@app.route('/auth/magic_login', methods=['POST'])
def magic_login():
    data = request.get_json()
    access_token = data.get('access_token')
    if not access_token: return jsonify({'error': 'No access token provided'}), 400
    try:
        res = supabase.auth.get_user(access_token)
        user = res.user
        if user:
            session.clear()
            session.permanent = True
            session['user'] = user.id
            session['access_token'] = access_token
            session['refresh_token'] = data.get('refresh_token')
            # Without explicit expires_at from magic link payload, we might assume 1 hour or fetch info
            session['access_expires_at'] = int((datetime.datetime.now(datetime.timezone.utc) + timedelta(hours=1)).timestamp())
            session['last_activity'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return jsonify({'success': True, 'redirect_url': url_for('dashboard')})
        else:
            return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/login_with_code', methods=['POST'])
def login_with_code():
    if not check_db_config(): return render_template('login.html')
    email = request.form.get('email')
    try:
        redirect_url = url_for('verify', _external=True)
        res = supabase.auth.sign_in_with_otp({
            "email": email,
            "options": {"email_redirect_to": redirect_url}
        })
        flash('Magic link sent! Check your email.', 'info')
        return redirect(url_for('verify', email=email))
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('login'))

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    email = request.args.get('email')
    if request.method == 'POST':
        email = request.form.get('email')
        otp = request.form.get('otp')
        try:
            res = supabase.auth.verify_otp({"email": email, "token": otp, "type": "email"})
            
            session.clear()
            session.permanent = True
            session['user'] = res.user.id
            session['user_email'] = email
            session['access_token'] = res.session.access_token
            session['refresh_token'] = res.session.refresh_token
            session['access_expires_at'] = res.session.expires_at
            session['last_activity'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

            profile = get_user_profile(res.session.access_token)
            if not profile.get('email'):
                try:
                    get_db(res.session.access_token).table('profiles').update({'email': email}).eq('id', session['user']).execute()
                    profile['email'] = email
                except Exception as e:
                    print(f"Error updating email: {e}")

            if not profile.get('username'):
                session['setup_required'] = True
                flash('Please complete your profile setup.', 'info')
                return redirect(url_for('complete_profile'))
                
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Login failed: {str(e)}", 'error')
    return render_template('verify.html', email=email)

@app.route('/complete_profile', methods=['GET', 'POST'])
def complete_profile():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        token = session.get('access_token')
        try:
            existing_user = supabase.table('profiles').select('id').eq('username', username).execute()
            if existing_user.data:
                flash('Username already taken', 'error')
                return render_template('complete_profile.html')
            
            get_db(token).table('profiles').update({'username': username}).eq('id', session['user']).execute()
            
            refresh_token = session.get('refresh_token')
            if refresh_token:
                auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
                auth_client.auth.set_session(token, refresh_token)
                auth_client.auth.update_user({"password": password})
            else:
                 get_db(token).auth.update_user({"password": password})
            
            session.pop('setup_required', None)
            flash('Profile setup complete!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
             flash(f"Error: {str(e)}", 'error')
    return render_template('complete_profile.html')

# ---------------------------------------------------------
# Password Reset & Username Recovery Routes
# ---------------------------------------------------------

@app.route('/forgot_credentials', methods=['GET', 'POST'])
def forgot_credentials():
    """
    Handle forgot username and password requests.
    Implements rate limiting and prevents email enumeration.
    """
    if request.method == 'POST':
        if not check_db_config(): 
            return render_template('forgot_credentials.html')
        
        email = request.form.get('email', '').strip().lower()
        action = request.form.get('action')  # 'username' or 'password'
        
        # Rate limiting check
        rate_limit_key = f'forgot_cred_{email}'
        last_request = session.get(rate_limit_key)
        
        if last_request:
            time_since_last = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(last_request)
            if time_since_last < timedelta(minutes=1):
                # Too many requests - still show success to prevent enumeration
                flash('If this email exists in our system, we have sent instructions.', 'info')
                return redirect(url_for('login'))
        
        # Update rate limit timestamp
        session[rate_limit_key] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        try:
            if action == 'username':
                # Send username reminder
                try:
                    # Look up user by email
                    user_res = supabase.table('profiles').select('username, email, id').eq('email', email).execute()
                    
                    if user_res.data and len(user_res.data) > 0:
                        username = user_res.data[0].get('username')
                        
                        if username:
                            # Send email with username
                            msg = Message(
                                subject='Your Expense Tracker Username',
                                recipients=[email],
                                body=f"""Hello,

You requested a reminder of your username for the Expense Tracker application.

Your username is: {username}

If you did not request this, please ignore this email.

Best regards,
Expense Tracker Team
"""
                            )
                            mail.send(msg)
                except Exception as e:
                    print(f"Error sending username reminder: {e}")
                    # Don't reveal the error to user
                
            elif action == 'password':
                # Trigger Supabase password reset
                try:
                    # Get the base URL for redirect
                    base_url = request.url_root.rstrip('/')
                    reset_url = f"{base_url}/reset_password"
                    
                    supabase.auth.reset_password_for_email(
                        email,
                        options={"redirect_to": reset_url}
                    )
                except Exception as e:
                    print(f"Error sending password reset: {e}")
                    # Don't reveal the error to user
            
            # Always show the same success message (prevent email enumeration)
            flash('If this email exists in our system, we have sent instructions.', 'info')
            
        except Exception as e:
            print(f"Forgot credentials error: {e}")
            # Still show success message to prevent enumeration
            flash('If this email exists in our system, we have sent instructions.', 'info')
        
        # Redirect to login page after processing
        return redirect(url_for('login'))
    
    return render_template('forgot_credentials.html')


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    """
    Handle password reset with Supabase recovery token.
    Token comes from URL fragment and is submitted via form.
    """
    if request.method == 'POST':
        if not check_db_config():
            flash('System error. Please try again later.', 'error')
            return redirect(url_for('login'))
        
        access_token = request.form.get('access_token', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validation
        if not access_token:
            flash('Invalid or expired reset link.', 'error')
            return redirect(url_for('login'))
        
        if not new_password or not confirm_password:
            flash('Please enter and confirm your new password.', 'error')
            return render_template('reset_password.html')
        
        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html')
        
        if len(new_password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('reset_password.html')
        
        try:
            # Use the same logic as change_password route
            # Create auth client and set session with the recovery token
            auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            auth_client.auth.set_session(access_token, access_token)  # Use token as both access and refresh
            auth_client.auth.update_user({"password": new_password})
            
            flash('Password updated successfully! You can now login with your new password.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"Password reset error: {e}")
            flash('Invalid or expired reset link. Please request a new one.', 'error')
            return redirect(url_for('forgot_credentials'))
    
    # GET request - show the reset form
    return render_template('reset_password.html')



@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    try:
        if not session.get('recurring_checked'):
             added = check_recurring_expenses(session['user'], token)
             if added > 0: flash(f"{added} recurring expenses added.", 'info')
             session['recurring_checked'] = True

        profile_res = get_db(token).table('profiles').select('*').eq('id', session['user']).execute()
        profile = profile_res.data[0] if profile_res.data else {}
        
        expenses_res = get_db(token).table('expenses').select('*').eq('user_id', session['user']).order('date', desc=True).order('created_at', desc=True).limit(5).execute()
        expenses = expenses_res.data
        
        all_tx_res = get_db(token).table('expenses').select('amount, type').eq('user_id', session['user']).execute()
        total_expense = sum(ex['amount'] for ex in all_tx_res.data if ex['type'] == 'expense')
        total_income = sum(ex['amount'] for ex in all_tx_res.data if ex['type'] == 'income')
        
        banks_res_bal = get_db(token).table('bank_accounts').select('opening_balance').eq('user_id', session['user']).execute()
        total_opening = sum(float(b.get('opening_balance', 0)) for b in banks_res_bal.data)
        current_balance = total_opening + total_income - total_expense

        debts_res = get_db(token).table('debts').select('amount, type').eq('user_id', session['user']).eq('status', 'active').execute()
        total_lent = sum(d['amount'] for d in debts_res.data if d['type'] == 'lend')
        total_borrowed = sum(d['amount'] for d in debts_res.data if d['type'] == 'borrow')

        budget = float(profile.get('budget', 0) or 0)
        percentage = 0
        progress_class = "progress-safe"
        if budget > 0:
            percentage = min((total_expense / budget) * 100, 100)
            if percentage > 90: progress_class = "progress-danger"
            elif percentage > 75: progress_class = "progress-warning"
                
    except Exception as e:
        flash(f"Error fetching data: {str(e)}", 'error')
        profile, expenses = {}, []
        total_expense = total_income = current_balance = budget = percentage = 0
        progress_class = ""
        total_lent = total_borrowed = 0

    return render_template('dashboard.html', profile=profile, expenses=expenses, total=total_expense, total_income=total_income, current_balance=current_balance, budget=budget, percentage=percentage, progress_class=progress_class, currency=profile.get('currency', '₹'), total_lent=total_lent, total_borrowed=total_borrowed)

@app.route('/expenses')
def expenses():
    if 'user' not in session: return redirect(url_for('login'))
    categories = DEFAULT_CATEGORIES
    try:
        token = session.get('access_token')
        expenses = get_filtered_expenses(token, session['user'], request.args)
        banks_res = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', session['user']).execute()
        banks = banks_res.data
        profile_res = get_db(token).table('profiles').select('currency').eq('id', session['user']).execute()
        currency = profile_res.data[0]['currency'] if profile_res.data else '₹'
        categories = get_all_categories(token, session['user'])
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        expenses, banks = [], []
        currency, categories = '₹', DEFAULT_CATEGORIES
    return render_template('expenses.html', expenses=expenses, banks=banks, currency=currency, categories=categories)

@app.route('/banks')
def banks():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        db_service = get_db_service(token)

        # 1. Fetch Personal (Savings) Banks from Supabase
        banks = db_service.get_personal_banks(session['user'])

        # 2. Fetch Enterprise (Current/CC/OD) Banks from local PostgreSQL
        enterprise_banks = db_service.get_enterprise_banks(session['user'])

        # 3. Calculate running balance for personal banks
        tx_res = get_db(token).table('expenses').select('amount, type, bank_account_id').eq('user_id', session['user']).not_.is_('bank_account_id', 'null').execute()
        transactions = tx_res.data
        for bank in banks:
            current_bal = float(bank.get('opening_balance', 0))
            bank_txs = [t for t in transactions if t.get('bank_account_id') == bank['id']]
            for tx in bank_txs:
                amount = float(tx['amount'])
                if tx['type'] == 'income': current_bal += amount
                elif tx['type'] == 'expense': current_bal -= amount
            bank['current_balance'] = current_bal
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        banks, enterprise_banks = [], []
    return render_template('banks.html', banks=banks, enterprise_banks=enterprise_banks)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        new_username = request.form.get('username')
        avatar_url = request.form.get('avatar_url')
        budget_val = request.form.get('budget', 0)
        currency_val = request.form.get('currency', '₹')
        
        current_profile = get_user_profile(token)
        if new_username and new_username != current_profile.get('username'):
             existing_user = get_db(token).table('profiles').select('id').eq('username', new_username).execute()
             if existing_user.data:
                 flash('Username already taken', 'error')
                 return redirect(url_for('profile'))

        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                try:
                    file_content = file.read()
                    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                    file_path = f"{session['user']}/avatar_{int(datetime.datetime.now().timestamp())}.{file_ext}"
                    get_db(token).storage.from_('avatars').upload(file_path, file_content, {"content-type": f"image/{file_ext}"})
                    avatar_url = get_db(token).storage.from_('avatars').get_public_url(file_path)
                except Exception as e:
                    flash(f"Error uploading image: {str(e)}", 'error')

        try:
            get_db(token).table('profiles').update({
                'full_name': full_name, # 'username': new_username, 'avatar_url': avatar_url, 'budget': float(budget_val), 'currency': currency_val
                'username': new_username,
                'avatar_url': avatar_url,
                'budget': float(budget_val),
                'currency': currency_val
            }).eq('id', session['user']).execute()
            flash('Profile updated!', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            flash(f"Error updating profile: {str(e)}", 'error')

    try:
        profile = get_user_profile(token)
        u = supabase.auth.get_user(token)
        email = u.user.email if u and u.user else "Unknown"
    except Exception as e:
        profile, email = {}, "Unknown"
    return render_template('profile.html', profile=profile, email=email)

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user' not in session: return redirect(url_for('login'))
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    if new_pass != confirm_pass:
        flash("Passwords do not match", "error")
        return redirect(url_for('profile'))
    try:
        token = session.get('access_token')
        refresh_token = session.get('refresh_token')
        if refresh_token:
             auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
             auth_client.auth.set_session(token, refresh_token)
             auth_client.auth.update_user({"password": new_pass})
        else:
             get_db(token).auth.update_user({"password": new_pass})
        flash("Password updated successfully!", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
    return redirect(url_for('profile'))

@app.route('/add_bank', methods=['POST'])
def add_bank():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        data = {
            'user_id': session['user'],
            'bank_name': request.form.get('bank_name'),
            'account_number': request.form.get('account_number'),
            'ifsc_code': request.form.get('ifsc_code'),
            'opening_balance': float(request.form.get('opening_balance', 0))
        }
        get_db(token).table('bank_accounts').insert(data).execute()
        flash('Bank account added!', 'success')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))

@app.route('/edit_bank/<bank_id>', methods=['POST'])
def edit_bank(bank_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        data = {
            'bank_name': request.form.get('bank_name'),
            'account_number': request.form.get('account_number'),
            'ifsc_code': request.form.get('ifsc_code'),
            'opening_balance': float(request.form.get('opening_balance', 0))
        }
        get_db(token).table('bank_accounts').update(data).eq('id', bank_id).eq('user_id', session['user']).execute()
        flash('Bank account updated!', 'success')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))

@app.route('/delete_bank/<bank_id>')
def delete_bank(bank_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        get_db(token).table('bank_accounts').delete().eq('id', bank_id).eq('user_id', session['user']).execute()
        flash('Bank account removed.', 'info')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))

@app.route('/set_budget', methods=['POST'])
def set_budget():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        get_db(token).table('profiles').update({'budget': float(request.form.get('budget'))}).eq('id', session['user']).execute()
        flash('Budget updated!', 'success')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/categories')
def categories():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        res = get_db(token).table('user_categories').select('*').eq('user_id', session['user']).execute()
        custom_categories = res.data
    except:
        custom_categories = []
    return render_template('categories.html', custom_categories=custom_categories, default_categories=DEFAULT_CATEGORIES)

@app.route('/add_category', methods=['POST'])
def add_category():
    if 'user' not in session: return redirect(url_for('login'))
    name = request.form.get('name')
    if not name: return redirect(url_for('categories'))
    try:
        token = session.get('access_token')
        get_db(token).table('user_categories').insert({'user_id': session['user'], 'name': name}).execute()
        flash('Category added!', 'success')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('categories'))

@app.route('/delete_category/<cat_id>')
def delete_category(cat_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        get_db(token).table('user_categories').delete().eq('id', cat_id).execute()
        flash('Category deleted.', 'info')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('categories'))

@app.route('/add_expense', methods=['GET', 'POST'])
def add_expense():
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    if request.method == 'POST':
        date, category, amount = request.form['date'], request.form['category'], request.form['amount']
        desc, is_recurring = request.form['description'], request.form.get('is_recurring')
        tx_type, bank_id = request.form.get('type', 'expense'), request.form.get('bank_account_id')
        
        receipt_url = None
        if 'receipt_file' in request.files:
            file = request.files['receipt_file']
            if file and file.filename != '':
                try:
                    file_content = file.read()
                    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                    file_path = f"{session['user']}/receipt_{int(datetime.datetime.now().timestamp())}.{file_ext}"
                    get_db(token).storage.from_('receipts').upload(file_path, file_content, {"content-type": f"image/{file_ext}"})
                    receipt_url = get_db(token).storage.from_('receipts').get_public_url(file_path)
                except Exception as e:
                    print(f"Receipt Upload Error: {e}")

        try:
            msg = f"{tx_type.title()} added successfully!"
            recurring_id = None
            if is_recurring:
                d_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
                next_due = (d_obj + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
                rec_res = get_db(token).table('recurring_expenses').insert({
                    'user_id': session['user'], 'category': category, 'amount': float(amount),
                    'description': desc, 'next_due_date': next_due
                }).execute()
                if rec_res.data: recurring_id = rec_res.data[0]['id']
                msg += " (Set to recur monthly)"

            get_db(token).table('expenses').insert({
                'user_id': session['user'], 'date': date, 'category': category, 'amount': float(amount),
                'description': desc, 'type': tx_type, 'bank_account_id': bank_id or None,
                'receipt_url': receipt_url, 'recurring_rule_id': recurring_id
            }).execute()
            flash(msg, 'success')
            return redirect(url_for('expenses'))
        except Exception as e:
            flash(f"Error adding {tx_type}: {str(e)}", 'error')

    categories = DEFAULT_CATEGORIES
    try:
        banks = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', session['user']).execute().data
        prof = get_db(token).table('profiles').select('currency').eq('id', session['user']).execute()
        currency = prof.data[0]['currency'] if prof.data else '₹'
        categories = get_all_categories(token, session['user'])
    except:
        banks, currency = [], '₹'
    return render_template('add.html', today=datetime.date.today(), expense=None, banks=banks, currency=currency, categories=categories)

@app.route('/bulk_add', methods=['GET', 'POST'])
def bulk_add():
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    if request.method == 'POST':
        try:
            dates, cats = request.form.getlist('date[]'), request.form.getlist('category[]')
            amts, descs = request.form.getlist('amount[]'), request.form.getlist('description[]')
            types, bank_ids = request.form.getlist('type[]'), request.form.getlist('bank_account_id[]')
            count = 0
            for i in range(len(dates)):
                if not amts[i]: continue
                get_db(token).table('expenses').insert({
                    'user_id': session['user'], 'date': dates[i], 'category': cats[i],
                    'amount': float(amts[i]), 'description': descs[i], 'type': types[i],
                    'bank_account_id': bank_ids[i] if bank_ids[i] else None
                }).execute()
                count += 1
            flash(f'{count} transactions added successfully!', 'success')
            return redirect(url_for('expenses'))
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')
    
    try:
        banks = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', session['user']).execute().data
        prof = get_db(token).table('profiles').select('currency').eq('id', session['user']).execute()
        currency = prof.data[0]['currency'] if prof.data else '₹'
        categories = get_all_categories(token, session['user'])
    except:
        banks, currency, categories = [], '₹', DEFAULT_CATEGORIES
    return render_template('bulk_add.html', today=datetime.date.today(), banks=banks, currency=currency, categories=categories)

@app.route('/edit_expense/<expense_id>', methods=['GET', 'POST'])
def edit_expense(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    if request.method == 'POST':
        try:
            get_db(token).table('expenses').update({
                'date': request.form['date'], 'category': request.form['category'],
                'amount': float(request.form['amount']), 'description': request.form['description'],
                'type': request.form.get('type', 'expense'), 'bank_account_id': request.form.get('bank_account_id') or None
            }).eq('id', expense_id).execute()
            flash('Transaction updated!', 'success')
            return redirect(url_for('expenses'))
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')

    try:
        res = get_db(token).table('expenses').select('*').eq('id', expense_id).execute()
        expense = res.data[0] if res.data else None
        banks = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', session['user']).execute().data
        categories = get_all_categories(token, session['user'])
        prof = get_db(token).table('profiles').select('currency').eq('id', session['user']).execute()
        currency = prof.data[0]['currency'] if prof.data else '₹'
    except:
        expense, banks, currency, categories = None, [], '₹', DEFAULT_CATEGORIES

    if not expense:
        flash('Transaction not found', 'error')
        return redirect(url_for('dashboard'))
    return render_template('add.html', expense=expense, banks=banks, today=datetime.date.today(), currency=currency, categories=categories)

@app.route('/delete_expense/<expense_id>')
def delete_expense(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        get_db(session.get('access_token')).table('expenses').delete().eq('id', expense_id).execute()
        flash('Expense deleted.', 'info')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('expenses'))

@app.route('/reports')
def reports():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        user_id = session['user']

        # ── Read filter params (state persistence) ──
        period         = request.args.get('period', 'this_month')
        cat_filter     = request.args.get('category', 'all')
        payment_filter = request.args.get('payment_method', 'all')
        type_filter    = request.args.get('tx_type', 'all')
        custom_start   = request.args.get('start_date', '')
        custom_end     = request.args.get('end_date', '')

        # ── Resolve date range ──
        today = datetime.date.today()
        if period == 'this_month':
            start_date = today.replace(day=1).strftime('%Y-%m-%d')
            end_date   = today.strftime('%Y-%m-%d')
        elif period == 'last_3_months':
            m = today.month - 3
            y = today.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            start_date = today.replace(year=y, month=m, day=1).strftime('%Y-%m-%d')
            end_date   = today.strftime('%Y-%m-%d')
        elif period == 'ytd':
            start_date = today.replace(month=1, day=1).strftime('%Y-%m-%d')
            end_date   = today.strftime('%Y-%m-%d')
        elif period == 'custom' and custom_start:
            start_date = custom_start
            end_date   = custom_end or today.strftime('%Y-%m-%d')
        else:
            start_date = today.replace(day=1).strftime('%Y-%m-%d')
            end_date   = today.strftime('%Y-%m-%d')

        # ── Fetch all transactions (for charts — always from Supabase: personal data) ──
        # Personal transactions ALWAYS live in Supabase regardless of DB_BACKEND
        sb_svc = SupabaseService(get_db(token))
        all_txns = sb_svc.get_personal_transactions(user_id, {
            'start_date': None, 'end_date': None,
        })

        # ── Build chart data from personal transactions only ──
        monthly_data, exp_categories, inc_categories = {}, {}, {}
        for tx in all_txns:
            m   = str(tx['date'])[:7]
            cat = tx.get('category', 'Uncategorized')
            amt = float(tx.get('amount', 0))
            if m not in monthly_data: monthly_data[m] = {'income': 0, 'expense': 0}
            if tx['type'] == 'income':
                monthly_data[m]['income'] += amt
                inc_categories[cat] = inc_categories.get(cat, 0) + amt
            else:
                monthly_data[m]['expense'] += amt
                exp_categories[cat] = exp_categories.get(cat, 0) + amt

        bar_labels      = sorted(monthly_data.keys())
        bar_exp         = [monthly_data[m]['expense'] for m in bar_labels]
        bar_inc         = [monthly_data[m]['income']  for m in bar_labels]
        exp_pie_labels  = list(exp_categories.keys())
        exp_pie_values  = list(exp_categories.values())
        inc_pie_labels  = list(inc_categories.keys())
        inc_pie_values  = list(inc_categories.values())

        # ── Fetch filtered transactions for the table ──
        filters = {
            'start_date':     start_date,
            'end_date':       end_date,
            'category':       cat_filter,
            'payment_method': payment_filter,
            'tx_type':        type_filter,
        }
        transactions = sb_svc.get_personal_transactions(user_id, filters)

        # ── Mini-card totals ──
        total_income  = sum(t['amount'] for t in transactions if t['type'] == 'income')
        total_expense = sum(t['amount'] for t in transactions if t['type'] != 'income')
        net_savings   = total_income - total_expense

        # ── Category list for dropdown ──
        all_categories = sb_svc.get_categories(user_id)

        # ── Currency ──
        prof = get_db(token).table('profiles').select('currency').eq('id', user_id).execute()
        currency = prof.data[0]['currency'] if prof.data else '₹'

        # ── Collect personal banks for filter dropdown ──
        banks_res = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', user_id).execute()
        personal_banks = banks_res.data or []

    except Exception as e:
        import traceback; traceback.print_exc()
        bar_labels = bar_exp = bar_inc = []
        exp_pie_labels = exp_pie_values = inc_pie_labels = inc_pie_values = []
        transactions = []
        total_income = total_expense = net_savings = 0
        all_categories = []
        currency = '₹'
        personal_banks = []
        period = 'this_month'
        start_date = end_date = ''
        cat_filter = payment_filter = type_filter = 'all'
        custom_start = custom_end = ''

    return render_template('reports.html',
        exp_pie_labels=exp_pie_labels, exp_pie_values=exp_pie_values,
        inc_pie_labels=inc_pie_labels, inc_pie_values=inc_pie_values,
        bar_labels=bar_labels, bar_exp=bar_exp, bar_inc=bar_inc,
        currency=currency,
        transactions=transactions,
        total_income=total_income, total_expense=total_expense, net_savings=net_savings,
        all_categories=all_categories,
        personal_banks=personal_banks,
        # filter state for persistence
        f_period=period, f_category=cat_filter, f_payment=payment_filter,
        f_tx_type=type_filter, f_start=start_date, f_end=end_date,
        f_custom_start=custom_start, f_custom_end=custom_end,
    )


@app.route('/export_pdf')
def export_pdf_route():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        token = session.get('access_token')
        expenses = get_filtered_expenses(token, session['user'], request.args)
        prof = get_db(token).table('profiles').select('full_name').eq('id', session['user']).execute()
        username = prof.data[0]['full_name'] if prof.data else "User"
        pdf_path = generate_pdf_report(expenses, username, filters=request.args)
        return send_file(pdf_path, as_attachment=True)
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('dashboard'))

@app.route('/email_report', methods=['POST'])
def email_report_route():
    if 'user' not in session: return redirect(url_for('login'))
    email = request.form.get('email')
    token = session.get('access_token')
    if not email:
        try:
             email = supabase.auth.get_user(token).user.email
        except:
             flash('Could not determine email.', 'error')
             return redirect(url_for('dashboard'))
    try:
        expenses = get_filtered_expenses(token, session['user'], request.form)
        prof = get_db(token).table('profiles').select('full_name').eq('id', session['user']).execute()
        username = prof.data[0]['full_name'] if prof.data else "User"
        pdf_path = generate_pdf_report(expenses, username, filters=request.form)
        body = f"Hello {username},\n\nPlease find attached your transaction report.\n\nRegards,\nPocket Expense Tracker"
        success, msg = send_email_report(mail, app, email, f"Monthly Report for {username}", body, pdf_path)
        flash(msg, 'success' if success else 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('reports')) # Redirect to reports usually

@app.route('/delete_recurring/<recurring_id>')
def delete_recurring(recurring_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        get_db(session.get('access_token')).table('recurring_expenses').delete().eq('id', recurring_id).execute()
        flash('Recurring rule stopped.', 'info')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('expenses'))

@app.route('/debts', methods=['GET', 'POST'])
def debts():
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    if request.method == 'POST':
        try:
            name, amt = request.form.get('person_name'), float(request.form.get('amount'))
            dtype, bid = request.form.get('type'), request.form.get('bank_account_id')
            tx_date = request.form.get('transaction_date')
            
            user_desc = request.form.get('description')
            
            res = get_db(token).table('debts').insert({
                'user_id': session['user'], 'person_name': name, 'amount': amt,
                'type': dtype, 'due_date': request.form.get('due_date') or None,
                'transaction_date': tx_date,
                'description': user_desc
            }).execute()
            
            tx_type = 'expense' if dtype == 'lend' else 'income'
            
            # Construct description
            base_desc = f"Lent to {name}" if dtype == 'lend' else f"Borrowed from {name}"
            desc = f"{base_desc} - {user_desc}" if user_desc else base_desc
            
            get_db(token).table('expenses').insert({
                'user_id': session['user'], 'date': tx_date, 'category': 'Debt',
                'amount': amt, 'description': desc, 'type': tx_type, 
                'bank_account_id': bid if bid else None
            }).execute()
            flash('Debt record created!', 'success')
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('debts'))

    try:
        res = get_db(token).table('debts').select('*').eq('user_id', session['user']).eq('status', 'active').execute()
        debts_list = res.data
        lent_list, borrowed_list = [d for d in debts_list if d['type'] == 'lend'], [d for d in debts_list if d['type'] == 'borrow']
        banks = get_db(token).table('bank_accounts').select('id, bank_name').eq('user_id', session['user']).execute().data
        prof = get_db(token).table('profiles').select('currency').eq('id', session['user']).execute()
        currency = prof.data[0]['currency'] if prof.data else '₹'
    except:
        lent_list, borrowed_list, banks, currency = [], [], [], '₹'
    return render_template('debts.html', lent_list=lent_list, borrowed_list=borrowed_list, banks=banks, currency=currency, today=datetime.date.today())

@app.route('/settle_debt/<debt_id>', methods=['POST'])
def settle_debt(debt_id):
    if 'user' not in session: return redirect(url_for('login'))
    token = session.get('access_token')
    try:
        res = get_db(token).table('debts').select('*').eq('id', debt_id).eq('user_id', session['user']).execute()
        if not res.data:
            flash("Debt not found.", "error")
            return redirect(url_for('debts'))
        debt = res.data[0]
        amt, dtype, name = debt['amount'], debt['type'], debt['person_name']
        bid = request.form.get('bank_account_id')
        get_db(token).table('debts').update({'status': 'settled'}).eq('id', debt_id).execute()
        tx_type = 'income' if dtype == 'lend' else 'expense'
        desc = f"Settled: {'Received from' if dtype == 'lend' else 'Paid back to'} {name}"
        get_db(token).table('expenses').insert({
            'user_id': session['user'], 'date': str(datetime.date.today()),
            'category': 'Debt Settlement', 'amount': amt,
            'description': desc, 'type': tx_type,
            'bank_account_id': bid if bid else None
        }).execute()
        flash("Debt settled successfully.", "success")
    except Exception as e:
        flash(f"Error settling debt: {e}", "error")
    return redirect(url_for('debts'))


# ---------------------------------------------------------
# Enterprise Bank Account Routes
# ---------------------------------------------------------

@app.route('/add_enterprise_bank', methods=['POST'])
def add_enterprise_bank():
    if 'user' not in session: return redirect(url_for('login'))
    try:
        account_type = request.form.get('account_type', 'Current')
        if account_type not in ('Current', 'CC/OD'):
            flash('Invalid account type.', 'error')
            return redirect(url_for('banks'))
        data = {
            'business_name': request.form.get('business_name'),
            'bank_name': request.form.get('bank_name'),
            'account_number': request.form.get('account_number'),
            'ifsc_code': request.form.get('ifsc_code'),
            'opening_balance': float(request.form.get('opening_balance', 0) or 0),
            'account_type': account_type
        }
        db_service = get_db_service(session.get('access_token'))
        if db_service.add_enterprise_bank(session['user'], data):
            flash('Business account added!', 'success')
        else:
            flash('Failed to add business account. Check DB_BACKEND is set to local.', 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))

@app.route('/delete_enterprise_bank/<bank_id>')
def delete_enterprise_bank(bank_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        db_service = get_db_service(session.get('access_token'))
        if db_service.delete_enterprise_bank(session['user'], bank_id):
            flash('Business account removed.', 'info')
        else:
            flash('Failed to remove account.', 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))

@app.route('/edit_enterprise_bank/<bank_id>', methods=['POST'])
def edit_enterprise_bank(bank_id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        account_type = request.form.get('account_type', 'Current')
        if account_type not in ('Current', 'CC/OD'):
            flash('Invalid account type.', 'error')
            return redirect(url_for('banks'))
        data = {
            'business_name': request.form.get('business_name'),
            'bank_name': request.form.get('bank_name'),
            'account_number': request.form.get('account_number'),
            'ifsc_code': request.form.get('ifsc_code'),
            'opening_balance': float(request.form.get('opening_balance', 0) or 0),
            'account_type': account_type
        }
        db_service = get_db_service(session.get('access_token'))
        if db_service.update_enterprise_bank(session['user'], bank_id, data):
            flash('Business account updated!', 'success')
        else:
            flash('Failed to update business account.', 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
    return redirect(url_for('banks'))


# ---------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP exceptions (404, 405, etc.) — let Flask handle them normally
    if isinstance(e, HTTPException):
        return e

    # Check for specific Supabase JWT Expiry Error (PGRST303)
    error_str = str(e)
    if "JWT expired" in error_str or "PGRST303" in error_str:
        print("CRITICAL: Caught Dead JWT. Forcing Logout.")
        session.clear()
        flash("Security token expired. Please login again.", "warning")
        return redirect(url_for('login'))

    # For all other real code errors, log them
    print(f"Unhandled Server Error: {e}")
    import traceback; traceback.print_exc()
    if app.debug:
        raise e
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True)
