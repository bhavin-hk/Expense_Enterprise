import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn_url = os.getenv("DATABASE_URL")

def remove_fks():
    print(f"Connecting to {conn_url}...")
    try:
        conn = psycopg2.connect(conn_url)
        cur = conn.cursor()
        
        # Drop FK constraints on bank_account_id for local testing
        print("Dropping FK constraints on bank_account_id for local dev...")
        
        # We need to find the constraint names first
        cur.execute("""
            SELECT constraint_name, table_name
            FROM information_schema.key_column_usage
            WHERE column_name = 'bank_account_id' AND table_name IN ('ent_revenue', 'ent_expenses');
        """)
        constraints = cur.fetchall()
        for cname, tname in constraints:
            print(f"- Dropping {cname} from {tname}")
            cur.execute(f"ALTER TABLE {tname} DROP CONSTRAINT IF EXISTS {cname};")
            
        conn.commit()
        print("Success.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    remove_fks()
