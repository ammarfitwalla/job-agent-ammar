import sqlite3, os, json
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_agent.db")

def _now():
    return datetime.utcnow().isoformat()

def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn, conn.cursor()

def seed():
    conn, cur = connect()
    now = _now()

    # ── Users at the same company ──
    users = [
        ("ammarfitwalla@gmail.com", "ammarfitwalla", "Cognizant", "Software Engineer", "", 0),
        ("imdesubhranil@gmail.com", "imdesubhranil", "Cognizant", "Engineering Manager", "", 10),
    ]
    for email, name, company, position, linkedin, credits in users:
        cur.execute("""UPDATE users SET company = ?, position = ?, referral_credits = ?, updated_at = ? WHERE email = ?
            """, (company, position, credits, now, email))
        if cur.rowcount == 0:
            cur.execute("""INSERT INTO users
                (email, name, company, position, linkedin_url, referral_credits, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (email, name, company, position, linkedin, credits, now, now))

    # ── Referral requests ──
    requests = [
        ("imdesubhranil@gmail.com", "ammarfitwalla@gmail.com",
         "https://linkedin.com/jobs/view/123", "Software Engineer", "Cognizant",
         85, "Hi, would love a referral for this role!", "pending", 0, "", 0, 0),
        ("imdesubhranil@gmail.com", "ammarfitwalla@gmail.com",
         "https://linkedin.com/jobs/view/456", "Senior Backend Engineer", "Cognizant",
         92, "Great match for my skills!", "accepted", 0, (datetime.utcnow() - timedelta(hours=12)).isoformat(), 0, 0),
    ]
    for from_e, to_e, job_url, job_title, company, score, msg, status, credit, acc_at, rc, sc in requests:
        cur.execute("""INSERT OR IGNORE INTO referral_requests
            (from_email, to_email, job_url, job_title, company, match_score, message,
             status, credit_awarded, accepted_at, receiver_confirmed, sender_confirmed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (from_e, to_e, job_url, job_title, company, score, msg,
             status, credit, acc_at, rc, sc, now, now))

    # ── Custom company for search ──
    cur.execute("INSERT OR IGNORE INTO custom_companies (name, created_at) VALUES (?, ?)",
                ("Cognizant", now))

    conn.commit()
    conn.close()

    print("Seed data inserted:")
    cur2 = sqlite3.connect(DB).cursor()
    for table in ("users", "referral_requests", "custom_companies"):
        cur2.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur2.fetchone()[0]} rows")
    print("\nTest users:")
    print("  referral_test@example.com   (requester)")
    print("  referral_partner@example.com (has 10 referral credits)")

if __name__ == "__main__":
    seed()
