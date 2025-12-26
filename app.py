import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import hashlib

import gspread
from google.oauth2.service_account import Credentials

# ======================================================
# APP CONFIG
# ======================================================
st.set_page_config(page_title="Daily Collection Tracker", page_icon="💰", layout="wide")

# ======================================================
# GOOGLE SHEETS CONNECTION
# ======================================================
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"], scopes=SCOPE
)

gc = gspread.authorize(creds)
SHEET = gc.open_by_key(st.secrets["sheets"]["spreadsheet_id"])

# ======================================================
# HELPERS
# ======================================================
def read_sheet(name):
    ws = SHEET.worksheet(name)
    return pd.DataFrame(ws.get_all_records())

def write_sheet(name, df):
    ws = SHEET.worksheet(name)
    ws.clear()
    ws.update([df.columns.tolist()] + df.astype(str).values.tolist())

# ======================================================
# AUTHENTICATION
# ======================================================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_users():
    return read_sheet("Users")

def verify_login(username, password):
    users = load_users()
    user = users[users["username"] == username]
    if not user.empty and user.iloc[0]["password_hash"] == hash_password(password):
        return True, user.iloc[0]["name"]
    return False, None

def change_password(username, old_password, new_password):
    users = load_users()
    idx = users[users["username"] == username].index
    if len(idx) == 1 and users.loc[idx[0], "password_hash"] == hash_password(old_password):
        users.loc[idx[0], "password_hash"] = hash_password(new_password)
        write_sheet("Users", users)
        return True
    return False

# ======================================================
# DATA LOADERS (CACHED)
# ======================================================
@st.cache_data(ttl=60)
def load_active_loans():
    return read_sheet("Active_Loans")

@st.cache_data(ttl=60)
def load_completed_loans():
    return read_sheet("Completed_Loans")

@st.cache_data(ttl=60)
def load_collections():
    return read_sheet("Collections")

def clear_cache():
    load_active_loans.clear()
    load_completed_loans.clear()
    load_collections.clear()

# ======================================================
# BUSINESS LOGIC
# ======================================================
def save_all_data(active_df, completed_df, collections_df):
    write_sheet("Active_Loans", active_df)
    write_sheet("Completed_Loans", completed_df)
    write_sheet("Collections", collections_df)
    clear_cache()

def add_loan(party, mobile, total, daily, days, mode):
    active = load_active_loans()
    completed = load_completed_loans()
    collections = load_collections()

    loan_id = f"L{len(active) + len(completed) + 1:04d}"
    now = datetime.now()
    end = now + timedelta(days=days)

    new = pd.DataFrame([{
        "Loan_ID": loan_id,
        "Date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Party_Name": party,
        "Mobile_Number": mobile,
        "Total_Amount": total,
        "Daily_Amount": daily,
        "Total_Days": days,
        "End_Date": end.strftime("%Y-%m-%d"),
        "Payment_Mode": mode,
        "Collected_Amount": 0,
        "Remaining_Amount": total,
        "Status": "Active"
    }])

    active = pd.concat([active, new], ignore_index=True)
    save_all_data(active, completed, collections)
    return loan_id

def add_collection(loan_id, amount, days_count, payment_mode):
    active = load_active_loans()
    completed = load_completed_loans()
    collections = load_collections()

    idx = active[active["Loan_ID"] == loan_id].index[0]
    party = active.loc[idx, "Party_Name"]

    active.loc[idx, "Collected_Amount"] += amount
    active.loc[idx, "Remaining_Amount"] -= amount

    if active.loc[idx, "Remaining_Amount"] <= 0:
        completed_loan = active.loc[idx].copy()
        completed_loan["Completion_Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        completed = pd.concat([completed, pd.DataFrame([completed_loan])], ignore_index=True)
        active = active.drop(idx).reset_index(drop=True)

    cid = f"C{len(collections) + 1:05d}"
    newc = pd.DataFrame([{
        "Collection_ID": cid,
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Loan_ID": loan_id,
        "Party_Name": party,
        "Amount_Collected": amount,
        "Days_Count": days_count,
        "Payment_Mode": payment_mode
    }])

    collections = pd.concat([collections, newc], ignore_index=True)
    save_all_data(active, completed, collections)

# ======================================================
# LOGIN
# ======================================================
def login_page():
    st.title("🔐 Daily Collection Tracker Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, name = verify_login(u, p)
        if ok:
            st.session_state.authenticated = True
            st.session_state.username = u
            st.session_state.user_name = name
            st.rerun()
        else:
            st.error("Invalid credentials")

# ======================================================
# MAIN APP
# ======================================================
def main():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        login_page()
        return

    st.sidebar.success(f"👤 {st.session_state.user_name}")
    menu = st.sidebar.selectbox(
        "Menu",
        ["💸 Give Money", "💰 Collect Money", "📊 Dashboard",
         "📋 Active Loans", "✅ Completed Loans",
         "📈 Collection History", "⚙️ Settings"]
    )

    # ---------------- GIVE MONEY ----------------
    if menu == "💸 Give Money":
        st.header("Give Money to Customer")

        col1, col2 = st.columns(2)
        with col1:
            party = st.text_input("Customer Name *")
            mobile = st.text_input("Mobile Number *", max_chars=10)
            total = st.number_input("Total Amount (₹) *", min_value=0.0)
        with col2:
            daily = st.number_input("Daily Amount (₹) *", min_value=0.0)
            days = st.number_input("Total Days *", min_value=1)
            mode = st.selectbox("Payment Mode *", ["Cash", "UPI", "Other"])

        if st.button("💾 Give Money", type="primary"):
            if not party.strip():
                st.error("Customer name required")
            elif not mobile.isdigit() or len(mobile) != 10:
                st.error("Enter valid 10-digit mobile number")
            elif total <= 0 or daily <= 0:
                st.error("Amounts must be greater than 0")
            else:
                loan_id = add_loan(party, mobile, total, daily, days, mode)
                st.success(f"Loan created: {loan_id}")
                st.balloons()

    # ---------------- COLLECT MONEY ----------------
    elif menu == "💰 Collect Money":
        active = load_active_loans()
        if not active.empty:
            choice = st.selectbox(
                "Select Customer *",
                active.apply(lambda r: f"{r['Party_Name']} ({r['Loan_ID']})", axis=1)
            )
            loan_id = choice.split("(")[-1].replace(")", "")
            loan = active[active["Loan_ID"] == loan_id].iloc[0]

            days = st.number_input("Days *", min_value=1)
            amt = st.number_input(
                "Amount (₹) *",
                min_value=0.0,
                max_value=float(loan["Remaining_Amount"])
            )
            mode = st.selectbox("Payment Mode *", ["Cash", "UPI", "Other"])

            if st.button("Collect Payment", type="primary"):
                if amt <= 0:
                    st.error("Amount must be > 0")
                elif amt > loan["Remaining_Amount"]:
                    st.error("Cannot exceed remaining amount")
                else:
                    add_collection(loan_id, amt, days, mode)
                    st.success("Payment collected")
                    st.balloons()
                    st.rerun()
        else:
            st.info("No active loans")

    # ---------------- DASHBOARD ----------------
    elif menu == "📊 Dashboard":
        active = load_active_loans()
        collections = load_collections()

        total_given = active["Total_Amount"].astype(float).sum() if not active.empty else 0
        total_collected = collections["Amount_Collected"].astype(float).sum() if not collections.empty else 0
        remaining = active["Remaining_Amount"].astype(float).sum() if not active.empty else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Given", f"₹{total_given:,.2f}")
        c2.metric("Total Collected", f"₹{total_collected:,.2f}")
        c3.metric("Remaining", f"₹{remaining:,.2f}")

    # ---------------- ACTIVE LOANS ----------------
    elif menu == "📋 Active Loans":
        st.dataframe(load_active_loans(), use_container_width=True)

    # ---------------- COMPLETED LOANS ----------------
    elif menu == "✅ Completed Loans":
        st.dataframe(load_completed_loans(), use_container_width=True)

    # ---------------- COLLECTION HISTORY ----------------
    elif menu == "📈 Collection History":
        df = load_collections()
        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"])
            start, end = st.date_input("Date Range", [df["Date"].min().date(), df["Date"].max().date()])
            filtered = df[(df["Date"].dt.date >= start) & (df["Date"].dt.date <= end)]
            st.success(f"Total: ₹{filtered['Amount_Collected'].astype(float).sum():,.2f}")
            st.dataframe(filtered, use_container_width=True)
        else:
            st.info("No data")

    # ---------------- SETTINGS ----------------
    elif menu == "⚙️ Settings":
        st.subheader("Change Password")
        old = st.text_input("Old Password", type="password")
        new = st.text_input("New Password", type="password")
        if st.button("Change Password"):
            if len(new) < 6:
                st.error("Password must be at least 6 characters")
            elif change_password(st.session_state.username, old, new):
                st.success("Password updated")
            else:
                st.error("Incorrect password")

if __name__ == "__main__":
    main()
