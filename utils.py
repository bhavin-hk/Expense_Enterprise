from fpdf import FPDF
from flask_mail import Message
import datetime
import os

class PDFReport(FPDF):
    def __init__(self, filters=None):
        super().__init__()
        self.filters = filters or {}

    def header(self):
        # Company/App Name
        self.set_font('Arial', 'B', 20)
        self.set_text_color(50, 50, 50)
        self.cell(0, 10, 'Pocket Expense Tracker', 0, 1, 'C')
        
        self.set_font('Arial', '', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, 'Monthly Transaction Report', 0, 1, 'C')
        
        self.ln(5)
        
        # Display Filters if any
        if self.filters:
            self.set_font('Arial', 'B', 9)
            self.set_text_color(0, 0, 0)
            filter_text = []
            
            if self.filters.get('start_date'):
                filter_text.append(f"From: {self.filters['start_date']}")
            if self.filters.get('end_date'):
                filter_text.append(f"To: {self.filters['end_date']}")
            if self.filters.get('category') and self.filters['category'] != 'All':
                filter_text.append(f"Category: {self.filters['category']}")
            if self.filters.get('bank_id'):
                 # We might only have ID here, ideally we'd pass bank name, but ID/Status is better than nothing or we leave it generic
                 # For now let's just show if specific bank filter is valid
                 if self.filters['bank_id'] == 'Cash':
                     filter_text.append("Account: Cash")
                 elif self.filters['bank_id'] != 'All':
                     filter_text.append("Account: Specific Bank") # Resolving name requires DB query or passing it in.
            
            if filter_text:
                self.cell(0, 5, "Applied Filters: " + ", ".join(filter_text), 0, 1, 'C')
                self.ln(5)

        # Line separator
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf_report(expenses, username, filters=None):
    """
    Generates a PDF report for the given expenses.
    Returns the filename of the generated PDF.
    """
    pdf = PDFReport(filters=filters)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # User Info Section
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Report For: {username}", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 6, f"Generated On: {datetime.date.today().strftime('%d-%m-%Y')}", 0, 1)
    pdf.ln(5)

    # Table Header
    pdf.set_fill_color(240, 240, 240)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.set_font("Arial", 'B', 10)
    
    # Column Widths
    col_date = 30
    col_cat = 35
    col_desc = 85
    col_amt = 40
    
    pdf.cell(col_date, 10, "Date", 1, 0, 'C', True)
    pdf.cell(col_cat, 10, "Category", 1, 0, 'C', True)
    pdf.cell(col_desc, 10, "Description", 1, 0, 'L', True) # Left align desc header matches content better usually, but C is fine
    pdf.cell(col_amt, 10, "Amount", 1, 1, 'R', True)

    # Table Body
    pdf.set_font("Arial", size=10)
    
    total_income = 0
    total_expense = 0
    
    fill = False # Zebra striping
    
    for expense in expenses:
        if isinstance(expense, dict):
             date_str = str(expense.get('date', ''))
             category = str(expense.get('category', ''))
             amount_val = float(expense.get('amount', 0))
             description = str(expense.get('description', ''))
             tx_type = expense.get('type', 'expense')
        else:
             date_str = str(expense[2])
             category = str(expense[3])
             amount_val = float(expense[4])
             description = str(expense[5])
             tx_type = 'expense'

        # Format Date
        try:
            d_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            date_display = d_obj.strftime("%d-%b-%Y")
        except:
            date_display = date_str

        # Color and Math
        if tx_type == 'income':
            total_income += amount_val
            amount_str = f"+ {amount_val:,.2f}"
            text_color = (0, 100, 0) # Dark Green
        else:
            total_expense += amount_val
            amount_str = f"- {amount_val:,.2f}"
            text_color = (200, 50, 50) # Red

        # Render Row
        pdf.set_fill_color(250, 250, 250) if fill else pdf.set_fill_color(255, 255, 255)
        
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_date, 8, date_display, 1, 0, 'C', True)
        pdf.cell(col_cat, 8, category, 1, 0, 'C', True)
        
        # Truncate description if too long
        desc_display = (description[:45] + '..') if len(description) > 45 else description
        pdf.cell(col_desc, 8, f" {desc_display}", 1, 0, 'L', True)
        
        pdf.set_text_color(*text_color)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(col_amt, 8, amount_str, 1, 1, 'R', True)
        
        pdf.set_font("Arial", size=10)
        fill = not fill

    pdf.ln(5)
    
    # Summary Section (Right Aligned)
    net_total = total_income - total_expense
    
    x_start = 120
    pdf.set_x(x_start)
    
    pdf.set_font("Arial", '', 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(40, 8, "Total Income:", 0, 0, 'R')
    pdf.set_text_color(0, 100, 0)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, f"{total_income:,.2f}", 0, 1, 'R')
    
    pdf.set_x(x_start)
    pdf.set_font("Arial", '', 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(40, 8, "Total Expense:", 0, 0, 'R')
    pdf.set_text_color(200, 50, 50)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, f"{total_expense:,.2f}", 0, 1, 'R')
    
    pdf.ln(2)
    pdf.set_x(x_start)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(x_start + 10, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)
    
    pdf.set_x(x_start)
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(40, 10, "NET TOTAL:", 0, 0, 'R')
    
    if net_total >= 0:
        pdf.set_text_color(0, 100, 0)
    else:
        pdf.set_text_color(200, 0, 0)
        
    pdf.cell(30, 10, f"{net_total:,.2f}", 0, 1, 'R')

    import tempfile
    temp_dir = tempfile.gettempdir()
    filename = os.path.join(temp_dir, f"Report_{username}_{datetime.date.today()}.pdf")
    
    pdf.output(filename)
    return filename

def send_email_report(mail, app, email_address, subject, body, attachment_path):
    """
    Sends an email with the PDF report attached.
    """
    try:
        msg = Message(subject, recipients=[email_address])
        msg.body = body
        
        with app.open_resource(attachment_path) as fp:
            msg.attach(os.path.basename(attachment_path), "application/pdf", fp.read())
            
        mail.send(msg)
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)
