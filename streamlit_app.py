# app.py
# ==========================================
# 📊 Dashboard Rekapitulasi Karyawan (Streamlit)
# Dibuat oleh NanoZeta - HR/Personalia & Hubungan Industrial
# Fitur:
# - Rekap Karyawan per Employee Group & Unit
# - Demografi (Gender, Usia)
# - Daftar Karyawan (kolom terpilih)
# - Struktur Organisasi + Vacant tracking (berdasarkan sheet "Database Vacant")
# - Upload & push file .xlsx ke GitHub via Contents API (tanpa git)
# ==========================================

import streamlit as st
import pandas as pd
import requests
import base64
import subprocess
import os
from pathlib import Path
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime
from email.utils import parsedate_to_datetime
import time

# ==============================================================
#                    CONFIGURATION & CONSTANTS
# ==============================================================
# File database utama
LOCAL_FILE = "Cek Test Profile.xlsx"
ORG_STRUCTURE_FILE = "Struktur Organisasi.xlsx"

# URL untuk load data (dari Streamlit secrets atau hardcoded)
try:
    DEFAULT_URL = st.secrets.get("database_url")
    if not DEFAULT_URL:
        # Fallback: construct dari repo owner & name jika tersedia
        owner = st.secrets.get("repo_owner")
        repo = st.secrets.get("repo_name")
        branch = st.secrets.get("branch", "main")
        if owner and repo:
            DEFAULT_URL = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{LOCAL_FILE}"
        else:
            DEFAULT_URL = None
except Exception:
    DEFAULT_URL = None

if not DEFAULT_URL:
    st.error("❌ DEFAULT_URL tidak terkonfigurasi. Mohon atur 'database_url' atau 'repo_owner'/'repo_name' di Streamlit secrets.")
    st.stop()

# Construct ORG_STRUCTURE_URL similarly
owner = None
repo = None
branch = None
try:
    owner = st.secrets.get("repo_owner")
    repo = st.secrets.get("repo_name")
    branch = st.secrets.get("branch", "main")
except Exception:
    pass

if owner and repo:
    ORG_STRUCTURE_URL = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{ORG_STRUCTURE_FILE}"
else:
    ORG_STRUCTURE_URL = None

# 🧰 Utilitas Umum
# -----------------------------
def pick_col(cols, candidates):
    """Ambil nama kolom yang cocok (case-insensitive) dari kandidat."""
    lut = {c.upper(): c for c in cols}
    for cand in candidates:
        if cand.upper() in lut:
            return lut[cand.upper()]
    return None

def get_last_update_time():
    """Ambil waktu last-modified dari file lokal atau GitHub untuk database utama."""
    local_path = Path(LOCAL_FILE)
    if local_path.exists():
        try:
            mtime = local_path.stat().st_mtime
            last_mod = datetime.fromtimestamp(mtime)
            return last_mod.strftime("%d-%m-%Y %H:%M:%S")
        except Exception:
            return "Gagal mengambil info"
    
    # Jika tidak ada lokal, coba dari GitHub
    if DEFAULT_URL:
        try:
            resp = requests.head(DEFAULT_URL, timeout=30)
            if resp.status_code == 200 and "last-modified" in resp.headers:
                last_mod = parsedate_to_datetime(resp.headers["last-modified"])
                return last_mod.strftime("%d-%m-%Y %H:%M:%S")
            return "Tidak tersedia"
        except Exception:
            return "Gagal mengambil info"
    return "Tidak ada data"

# -----------------------------
# 📦 Loader Data (dengan cache)
# -----------------------------
@st.cache_data(ttl=3600)
def load_excel_data(url_or_path, sheet_name=0):
    """Load Excel dari local path (jika ada) atau remote URL."""
    # Cek apakah file ada secara lokal
    local_path = Path(url_or_path) if not url_or_path.startswith("http") else None
    if local_path and local_path.exists():
        try:
            df = pd.read_excel(local_path, sheet_name=sheet_name)
            return df, None
        except Exception as e:
            return None, str(e)
    
    # Jika tidak ada lokal atau parameter adalah URL, coba dari remote
    if url_or_path.startswith("http"):
        try:
            r = requests.get(url_or_path, timeout=60)
            r.raise_for_status()
            df = pd.read_excel(BytesIO(r.content), sheet_name=sheet_name)
            return df, None
        except Exception as e:
            return None, str(e)
    
    return None, "File tidak ditemukan (lokal maupun remote)"

@st.cache_data(ttl=3600)
def load_all_sheets(url):
    """Lebih efisien: parse sekali per file."""
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        bio = BytesIO(r.content)
        xls = pd.ExcelFile(bio)
        sheets_dict = {sheet: xls.parse(sheet_name=sheet) for sheet in xls.sheet_names}
        return sheets_dict, None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600)
def load_org_sheets(url_or_path):
    """Load Excel sheets dari local path (jika ada) atau remote URL.

    Mencari baris header jika header tidak berada di baris pertama.
    """
    def parse_sheets_from_xls(xls):
        sheets = {}
        header_keywords = ['PN', 'NAMA', 'NO', 'JABATAN', 'UNIT', 'LEVEL']
        import re
        pattern = re.compile('|'.join([kw for kw in header_keywords]), re.IGNORECASE)
        for sheet in xls.sheet_names:
            try:
                # baca 20 baris awal tanpa header untuk mendeteksi header
                df_preview = xls.parse(sheet_name=sheet, header=None, nrows=20)
                header_row = None
                for i, row in df_preview.iterrows():
                    row_str = row.astype(str).str.strip().fillna('').str.upper()
                    if any(cell in row_str.values for cell in ["PN","NAMA","NO","JABATAN","UNIT","LEVEL"]):
                        header_row = i
                        break
                # Parse dengan header terdeteksi jika ada
                if header_row is not None:
                    df = xls.parse(sheet_name=sheet, header=header_row)
                else:
                    df = xls.parse(sheet_name=sheet, header=0)
                # Drop kolom kosong penuh
                df = df.loc[:, ~df.columns.astype(str).str.contains('^Unnamed') | df.notna().any()]
                sheets[sheet] = df
            except Exception:
                try:
                    sheets[sheet] = xls.parse(sheet_name=sheet)
                except Exception:
                    sheets[sheet] = pd.DataFrame()
        return sheets

    # Cek lokal
    local_path = Path(url_or_path) if not url_or_path.startswith("http") else None
    if local_path and local_path.exists():
        try:
            bio = BytesIO(local_path.read_bytes())
            xls = pd.ExcelFile(bio)
            sheets = parse_sheets_from_xls(xls)
            return sheets, None
        except Exception as e:
            return None, str(e)

    # Cek remote
    if url_or_path and url_or_path.startswith("http"):
        try:
            r = requests.get(url_or_path, timeout=60)
            r.raise_for_status()
            bio = BytesIO(r.content)
            xls = pd.ExcelFile(bio)
            sheets = parse_sheets_from_xls(xls)
            return sheets, None
        except Exception as e:
            return None, str(e)

    return None, "File tidak ditemukan (lokal maupun remote)"

# -----------------------------
# 🔒 Upload ke GitHub via Contents API (tanpa git)
# -----------------------------
def has_github_secrets():
    required = ["github_token", "repo_owner", "repo_name"]
    try:
        return all(k in st.secrets for k in required)
    except Exception:
        return False

def upload_to_github_via_api(content_bytes: bytes, path_in_repo: str, commit_message: str):
    """
    Create / Update file di GitHub menggunakan Contents API.
    Memerlukan secrets:
      - github_token (PAT dengan scope repo)
      - repo_owner
      - repo_name
      - branch (opsional, default "main")
    
    Prioritas token: session_state.github_token_temp > st.secrets
    """
    try:
        token = st.session_state.get('github_token_temp') or st.secrets.get("github_token")
        owner = st.secrets.get("repo_owner")
        repo = st.secrets.get("repo_name")
        branch = st.secrets.get("branch", "main")
    except Exception:
        return False, "Secrets GitHub belum dikonfigurasi."

    if not token or not owner or not repo:
        return False, "Secrets GitHub belum lengkap (github_token/repo_owner/repo_name)."

    base_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_in_repo}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    # Cek SHA jika file sudah ada
    params = {"ref": branch}
    r_get = requests.get(base_url, headers=headers, params=params)
    sha = r_get.json().get("sha") if r_get.status_code == 200 else None

    payload = {
        "message": commit_message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r_put = requests.put(base_url, headers=headers, json=payload)
    if r_put.status_code in (200, 201):
        return True, "✅ Berhasil upload ke GitHub via API"
    else:
        return False, f"❌ Gagal upload: {r_put.status_code} – {r_put.text}"


def try_git_push(file_path: str, commit_message: str = "Update via Streamlit"):
    """Attempt to commit & push the saved file using local git (best-effort)."""
    try:
        repo_root = Path('.').resolve()

        # 1) Validasi file
        if not Path(file_path).exists():
            return False, f"File tidak ditemukan: {file_path}"

        # 2) Ambil identitas dari secrets (fallback ke default aman)
        try:
            git_user = st.secrets.get("git_user_name", "Streamlit Bot")
            git_email = st.secrets.get("git_user_email", "bot@example.com")
        except Exception:
            git_user = "Streamlit Bot"
            git_email = "bot@example.com"

        # 3) Siapkan environment author/committer untuk proses ini
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = git_user
        env["GIT_AUTHOR_EMAIL"] = git_email
        env["GIT_COMMITTER_NAME"] = git_user
        env["GIT_COMMITTER_EMAIL"] = git_email

        # 4) Stage
        subprocess.run(
            ["git", "add", str(file_path)],
            check=True, cwd=str(repo_root), env=env
        )

        # 5) Commit tanpa GPG signing + set user sementara (override config lokal)
        subprocess.run([
            "git",
            "-c", "commit.gpgsign=false",
            "-c", f"user.name={git_user}",
            "-c", f"user.email={git_email}",
            "commit",
            "-m", commit_message
        ], check=True, cwd=str(repo_root), env=env)

        # 6) Push (gunakan remote default; pastikan HTTPS/SSH sudah valid)
        push = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True,
            cwd=str(repo_root), env=env, timeout=45
        )

        if push.returncode == 0:
            return True, "✅ Berhasil push via git"
        else:
            stderr_msg = push.stderr.strip()
            # Kasus akses/credential/SSH
            if ("Host key verification failed" in stderr_msg or
                "Permission denied" in stderr_msg or
                "Authentication failed" in stderr_msg or
                "could not read Username" in stderr_msg):
                hint = (
                    "\n💡 Petunjuk: Pastikan remote sudah pakai HTTPS dengan token "
                    "(atau SSH key valid) dan Anda punya akses push."
                )
                return False, f"❌ Gagal push (akses): {stderr_msg}{hint}"
            # Kasus identitas author
            if ("Author identity unknown" in stderr_msg or
                "author is invalid" in stderr_msg.lower()):
                hint = (
                    "\n💡 Petunjuk: Set 'git_user_name' & 'git_user_email' di st.secrets "
                    "atau sesuaikan default di fungsi ini."
                )
                return False, f"❌ Identitas author tidak valid: {stderr_msg}{hint}"
            # Kasus GPG/signing
            if "gpg failed to sign the data" in stderr_msg.lower():
                hint = (
                    "\n💡 Petunjuk: Flag '-c commit.gpgsign=false' sudah diterapkan di fungsi ini. "
                    "Jika tetap muncul, cek config global repo atau hooks."
                )
                return False, f"❌ GPG signing error: {stderr_msg}{hint}"
            # Lainnya
            return False, f"❌ Gagal push: {stderr_msg}"

    except subprocess.TimeoutExpired:
        return False, "❌ Gagal push: Timeout (koneksi terlalu lama)"
    except subprocess.CalledProcessError as e:
        # Tangkap error stage/commit dengan detail
        return False, f"❌ Perintah git gagal: {e}"
    except Exception as e:
        return False, f"❌ Error git push: {str(e)}"


# 1) LOAD DATA UTAMA
df, error = load_excel_data(LOCAL_FILE if Path(LOCAL_FILE).exists() else DEFAULT_URL)
if error:
    st.error(f"❌ Gagal memuat data utama: {error}")
    st.stop()
assert df is not None, "Data utama tidak berhasil dimuat"

# Validasi minimal kolom inti
unit_col = pick_col(df.columns, ["Personel Subarea", "Personnel Subarea", "Personel Area", "Unit Kerja"])
eg_col = pick_col(df.columns, ["Employee Group", "Kategori", "EmployeeGroup"])
if not unit_col or not eg_col:
    st.error("Kolom wajib tidak ditemukan: Unit / Employee Group. Mohon cek struktur file Excel.")
    st.stop()

# 2) PILIHAN UNIT
st.divider()
st.subheader("🏢 Pilih Unit Kerja")

units = sorted(df[unit_col].dropna().astype(str).unique().tolist())
units_with_all = ["Semua Unit"] + units
selected_unit = st.selectbox(
    "Pilih Unit Kerja:",
    options=units_with_all,
    index=0,
    help="Pilih unit kerja untuk melihat rekapitulasi spesifik",
)

# Filter data
if selected_unit == "Semua Unit":
    df_filtered = df.copy()
    display_unit = "Semua Unit Kerja"
else:
    df_filtered = df[df[unit_col].astype(str) == selected_unit].copy()
    display_unit = selected_unit

st.divider()

# 3) REKAP KATEGORI + JENIS KARYAWAN TIDAK TETAP
jenis_kt_col = pick_col(df_filtered.columns, ["JENIS KARYAWAN TIDAK TETAP", "Jenis Karyawan Tidak Tetap"])

# Ambil Employee Group untuk semua karyawan
count_by_group = df_filtered[eg_col].value_counts(dropna=False).reset_index()
count_by_group.columns = ["Employee Group", "Jumlah"]
count_by_group = count_by_group.sort_values("Jumlah", ascending=False)

# Hitung Job Grade 11 (non-NaN dianggap approved)
jg11_col = pick_col(df_filtered.columns, ["JOB GRADE 11", "JOB GRADE", "JG 11"])
if jg11_col:
    approved_series = df_filtered[df_filtered[jg11_col].notna()][eg_col].value_counts()
    count_by_group["Approved_JG11"] = count_by_group["Employee Group"].map(approved_series).fillna(0).astype(int)
else:
    count_by_group["Approved_JG11"] = 0

# Build summary yang menggabungkan kategori tetap + breakdown karpim & karpel tidak tetap
summary_data = []

# Karpel - Tetap
karpel_tetap_count = len(df_filtered[df_filtered[eg_col] == "Karpel - Tetap"])
if karpel_tetap_count > 0:
    summary_data.append({"Kategori": "Karpel - Tetap", "Jumlah": karpel_tetap_count})

# Karpim - Tetap
karpim_tetap_count = len(df_filtered[df_filtered[eg_col] == "Karpim - Tetap"])
if karpim_tetap_count > 0:
    summary_data.append({"Kategori": "Karpim - Tetap", "Jumlah": karpim_tetap_count})

# Karpel - Tidak Tetap (breakdown jenis)
if jenis_kt_col:
    karpel_tt_mask = df_filtered[eg_col] == "Karpel - Tidak Tetap"
    if karpel_tt_mask.sum() > 0:
        karpel_tt_df = df_filtered[karpel_tt_mask]
        jenis_kt_series_karpel = karpel_tt_df[jenis_kt_col].dropna().astype(str).str.strip()
        jenis_kt_series_karpel = jenis_kt_series_karpel[jenis_kt_series_karpel != ""]
        jenis_counts_karpel = jenis_kt_series_karpel.value_counts()
        for jenis, count in jenis_counts_karpel.items():
            summary_data.append({"Kategori": f"Karpel - TT: {jenis}", "Jumlah": int(count)})

# Karpim - Tidak Tetap (breakdown jenis)
if jenis_kt_col:
    karpim_tt_mask = df_filtered[eg_col] == "Karpim - Tidak Tetap"
    if karpim_tt_mask.sum() > 0:
        karpim_tt_df = df_filtered[karpim_tt_mask]
        jenis_kt_series_karpim = karpim_tt_df[jenis_kt_col].dropna().astype(str).str.strip()
        jenis_kt_series_karpim = jenis_kt_series_karpim[jenis_kt_series_karpim != ""]
        jenis_counts_karpim = jenis_kt_series_karpim.value_counts()
        for jenis, count in jenis_counts_karpim.items():
            summary_data.append({"Kategori": f"Karpim - TT: {jenis}", "Jumlah": int(count)})

# Buat summary_df & total
if summary_data:
    summary_df = pd.DataFrame(summary_data)
    total_kategori = int(summary_df["Jumlah"].sum())
    total_tetap = karpel_tetap_count + karpim_tetap_count
    total_tidak_tetap = total_kategori - total_tetap
else:
    summary_df = pd.DataFrame(columns=["Kategori", "Jumlah"])
    total_kategori = 0
    total_tetap = 0
    total_tidak_tetap = 0

# 4) METRICS ATAS
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("📊 Total Karyawan", int(len(df_filtered)))
with col2:
    st.metric("✅ Karyawan Tetap", total_tetap)
with col3:
    st.metric("📂 Karyawan Tidak Tetap", total_tidak_tetap)
with col4:
    num_jenis = len(summary_df) if not summary_df.empty else 0
    st.metric("🔹 Jumlah Kategori", num_jenis)
with col5:
    st.metric("📈 Unit", display_unit)

st.caption(f"⏱️ Last update GitHub (database): {get_last_update_time()}")

st.divider()

# 5) DEMOGRAFI: GENDER & DISABILITAS
st.subheader("👥 Demografi Karyawan")

# --- Gender ---
gender_col = pick_col(df_filtered.columns, ["Gender Key", "Gender", "Jenis Kelamin"])

male_count = female_count = other_gender = 0

if gender_col:
    gender_series = (
        df_filtered[gender_col]
        .fillna("unknown")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    # Normalisasi variasi input
    is_male = gender_series.isin(["male", "m", "l"])
    is_female = gender_series.isin(["female", "f", "p"])

    male_count = int(is_male.sum())
    female_count = int(is_female.sum())
    other_gender = int(len(gender_series) - male_count - female_count)

# --- Disabilitas ---
# Catatan: kita hitung per orang (row) apakah PUNYA disabilitas di salah satu kolom.
disability_count = 0
disability_cols = [c for c in df_filtered.columns if ("disabilitas" in c.lower() or "disability" in c.lower())]

if disability_cols:
    # Gabungkan kondisi "memiliki disabilitas" lintas kolom:
    # - nilai tak kosong
    # - bukan "nan"
    # - bukan "tidak ada" / "tidak" / "none" / "no"
    norm = (
        df_filtered[disability_cols]
        .astype(str)
        .apply(lambda s: s.str.strip().str.lower())
    )

    negative_values = {"", "nan", "tidak ada", "tidak", "none", "no", "0"}
    has_disability_any = ~norm.isin(negative_values)

    # Agar tidak double count per orang:
    disability_count = int(has_disability_any.any(axis=1).sum())

# --- UI Streamlit ---
gcol1, gcol2, gcol3 = st.columns(3)
with gcol1:
    st.metric("👨 Laki-laki", male_count)
with gcol2:
    st.metric("👩 Perempuan", female_count)
with gcol3:
    st.metric("♿ Disabilitas", disability_count)
# 6) DEMOGRAFI: USIA
age_col = pick_col(df_filtered.columns, ["Age of employee", "Age", "Usia"])
if age_col:
    ages = pd.to_numeric(df_filtered[age_col], errors="coerce")
    bins = [0, 24, 30, 40, 50, 55, 200]
    labels = ["<24 Tahun", "25 - 30 Tahun", "31 - 40 Tahun", "41 - 50 Tahun", "51 - 55 Tahun", ">55 Tahun"]
    age_groups = pd.cut(ages, bins=bins, labels=labels, include_lowest=True, right=True)
    age_counts = age_groups.value_counts().reindex(labels).fillna(0).astype(int)
else:
    labels = ["<24 Tahun", "25 - 30 Tahun", "31 - 40 Tahun", "41 - 50 Tahun", "51 - 55 Tahun", ">55 Tahun"]
    age_counts = pd.Series([0] * 6, index=labels)

st.subheader("👥 Demografi Berdasarkan Usia")
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 28px !important; }
    [data-testid="stMetricLabel"] { font-size: 14px !important; }
    </style>
    """, unsafe_allow_html=True)

acols = st.columns(6)
for col, label in zip(acols, labels):
    with col:
        st.metric(label, int(age_counts[label]))

# Line + Bar chart usia
fig_age = go.Figure()
fig_age.add_trace(go.Bar(
    x=labels,
    y=age_counts.values,
    name='Jumlah Karyawan',
    marker_color='#3366CC',
    text=age_counts.values,
    textposition='auto',
))
fig_age.add_trace(go.Scatter(
    x=labels,
    y=age_counts.values,
    name='Tren',
    mode='lines+markers',
    line=dict(color='#FF4B4B', width=3),
    marker=dict(size=10)
))
fig_age.update_layout(
    title="Tren Distribusi Usia Karyawan",
    xaxis_title="Kelompok Usia",
    yaxis_title="Jumlah",
    height=450,
    font=dict(size=12),
    margin=dict(l=20, r=20, t=80, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig_age, use_container_width=True)

st.divider()

# 7) TABEL REKAP KATEGORI UTAMA + CHART
st.subheader("📋 Rekapitulasi Kategori Karyawan (Tetap & Breakdown Tidak Tetap)")

# 🔀 Toggle urutan kustom
use_custom_order = st.checkbox(
    "Prioritaskan Karyawan Tetap (Karpim → Karpel di urutan atas)",
    value=True,
    help="Jika aktif, 'Karpim - Tetap' ditampilkan paling atas, lalu 'Karpel - Tetap', diikuti kategori lain (diurutkan berdasarkan jumlah)."
)

def order_summary(df_src: pd.DataFrame, enable_custom: bool) -> pd.DataFrame:
    if df_src.empty:
        return df_src
    if enable_custom:
        def get_priority(kat: str) -> int:
            kat_norm = str(kat).strip().lower()
            if kat_norm == "karpim - tetap":
                return 0
            if kat_norm == "karpel - tetap":
                return 1
            return 2  # lainnya di bawah
        df_out = df_src.copy()
        df_out["__priority__"] = df_out["Kategori"].apply(get_priority)
        df_out = df_out.sort_values(by=["__priority__", "Jumlah"], ascending=[True, False]).reset_index(drop=True)
        return df_out
    else:
        return df_src.sort_values(by="Jumlah", ascending=False).reset_index(drop=True)

if len(summary_df) > 0:
    ordered_summary_df = order_summary(summary_df, use_custom_order)
    display_df = ordered_summary_df.rename(columns={"Kategori": "KATEGORI KARYAWAN", "Jumlah": "JUMLAH"})

    st.dataframe(
        display_df.drop(columns=["__priority__"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
        column_config={
            "KATEGORI KARYAWAN": st.column_config.TextColumn(width=300),
            "JUMLAH": st.column_config.NumberColumn(width=120),
        },
    )

    st.subheader("📈 Visualisasi Distribusi Kategori")
    fig = go.Figure(
        data=[
            go.Bar(
                x=ordered_summary_df["Kategori"],
                y=ordered_summary_df["Jumlah"],
                marker=dict(color=ordered_summary_df["Jumlah"], colorscale="Viridis", showscale=True),
                text=ordered_summary_df["Jumlah"],
                textposition="auto",
            )
        ]
    )
    fig.update_layout(
        title="Distribusi Karyawan Berdasarkan Kategori & Jenis Kontrak (Tetap & Tidak Tetap)",
        xaxis_title="Kategori Karyawan",
        yaxis_title="Jumlah Karyawan",
        height=400,
        showlegend=False,
        margin=dict(l=10, r=10, t=60, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("⚠️ Kategori yang dicari tidak ditemukan dalam data.")

# 8) TABEL SEMUA KATEGORI
st.divider()
st.subheader("📑 Semua Kategori Karyawan")

all_categories_df = count_by_group.copy()
all_categories_df = all_categories_df.drop(columns=["Approved_JG11"], errors="ignore")
all_categories_df = all_categories_df.rename(columns={"Employee Group": "KATEGORI", "Jumlah": "JUMLAH"})

st.dataframe(
    all_categories_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "KATEGORI": st.column_config.TextColumn(width=300),
        "JUMLAH": st.column_config.NumberColumn(width=120),
    },
)

# 9) DAFTAR KARYAWAN (kolom terpilih)
st.divider()
st.subheader("👥 Daftar Karyawan")

employee_columns_candidates = [
    ("Pers.No.", ["Pers.No.", "PN", "Pers No", "PersNo", "Personnel Number", "Personel Number"]),
    ("Personnel Number", ["Personnel Number", "Nama Karyawan", "Name", "Nama"]),
    ("Position", ["Position", "Jabatan", "Job Title"]),
    (unit_col, [unit_col]),
    ("Birth date", ["Birth date", "Tanggal Lahir", "Birthdate", "DOB"]),
    (age_col if age_col else "Age of employee", [age_col if age_col else "Age of employee"]),
    (gender_col if gender_col else "Gender Key", [gender_col if gender_col else "Gender Key"]),
    ("ESgrp", ["ESgrp", "Person Grade", "PG"]),
    ("Job Group Short (New)", ["Job Group Short (New)", "BOD Level", "BOD"]),
]

available_columns = []
for display_name, candidates in employee_columns_candidates:
    c = pick_col(df_filtered.columns, candidates)
    if c:
        available_columns.append(c)

if available_columns:
    employee_df = df_filtered[available_columns].copy()

    # Format tanggal lahir
    bd_col = pick_col(employee_df.columns, ["Birth date", "Tanggal Lahir", "Birthdate", "DOB"])
    if bd_col:
        employee_df[bd_col] = pd.to_datetime(employee_df[bd_col], errors="coerce").dt.strftime("%d/%m/%Y")

    # Convert ke string untuk stabilitas render
    for col in employee_df.columns:
        employee_df[col] = employee_df[col].astype(str)

    # Mapping nama tampilan
    column_display_names = {
        pick_col(employee_df.columns, ["Pers.No.", "PN", "Pers No", "PersNo"]): "NIK SAP",
        pick_col(employee_df.columns, ["Personnel Number", "Nama Karyawan", "Name", "Nama"]): "Nama Karyawan",
        pick_col(employee_df.columns, ["Position", "Jabatan", "Job Title"]): "Jabatan",
        unit_col: "Unit Kerja",
        bd_col: "TGL LAHIR",
        (age_col if age_col else pick_col(employee_df.columns, ["Age of employee", "Age", "Usia"])): "Usia",
        (gender_col if gender_col else pick_col(employee_df.columns, ["Gender Key", "Gender", "Jenis Kelamin"])): "Jenis Kelamin",
        pick_col(employee_df.columns, ["ESgrp", "Person Grade", "PG"]): "Person Grade",
        pick_col(employee_df.columns, ["Job Group Short (New)", "BOD Level", "BOD"]): "BOD Level",
    }
    column_display_names = {k: v for k, v in column_display_names.items() if k}

    employee_df = employee_df.rename(columns=column_display_names)

    st.dataframe(
        employee_df,
        use_container_width=True,
        hide_index=True,
        column_config={col: st.column_config.TextColumn(width=150) for col in employee_df.columns},
    )
    st.info(f"📊 Total karyawan ditampilkan: {len(employee_df)}")
else:
    st.warning("⚠️ Kolom karyawan tidak ditemukan dalam data.")

st.info(f"✅ Menampilkan data {display_unit} | Data dimuat dari: {LOCAL_FILE if Path(LOCAL_FILE).exists() else 'GitHub remote'}")


# ==================== SECTION STRUKTUR ORGANISASI ====================
st.divider()
st.header("🏛️ Struktur Organisasi & Vacant Tracking")

org_sheets, org_error = load_org_sheets(ORG_STRUCTURE_FILE if Path(ORG_STRUCTURE_FILE).exists() else ORG_STRUCTURE_URL)

if org_error:
    st.info(f"ℹ️ Menunggu file Struktur Organisasi: {org_error}")
elif org_sheets:
    sheets_lower = {s.lower(): s for s in org_sheets.keys()}
    if "struktur organisasi" in sheets_lower and "database vacant" in sheets_lower:
        org_df = org_sheets[sheets_lower["struktur organisasi"]].copy()
        vacant_df = org_sheets[sheets_lower["database vacant"]].copy()

        # Deteksi Kolom (org)
        u_col_org = pick_col(org_df.columns, ["Unit Kerja", "UNIT KERJA", "Unit", "UNIT"])
        b_col_org = pick_col(org_df.columns, ["BAGIAN", "DEPARTMENT", "DEPT", "Bagian"])

        # Deteksi Kolom (vacant DB)
        u_col_vac = pick_col(vacant_df.columns, ["Unit Kerja", "UNIT KERJA", "Unit", "UNIT"])
        b_col_vac = pick_col(vacant_df.columns, ["BAGIAN", "DEPARTMENT", "DEPT", "Bagian"])
        jab_vac_col = pick_col(vacant_df.columns, ["JABATAN", "Jabatan", "Position"])

        col_a, col_b = st.columns(2)

        # --- FILTER 1: UNIT KERJA ---
        with col_a:
            org_unit_list = sorted(org_df[u_col_org].dropna().unique().tolist()) if u_col_org else []
            sel_org_unit = st.selectbox("Pilih Unit Kerja:", org_unit_list, key="org_u")

        # Filter data awal berdasarkan Unit
        if u_col_org and sel_org_unit:
            temp_df = org_df[org_df[u_col_org].astype(str) == sel_org_unit].copy()
        else:
            temp_df = org_df.copy()

        # --- FILTER 2: BAGIAN (Dynamic Dropdown) ---
        final_org_df = temp_df.copy()
        with col_b:
            if b_col_org:
                bagian_list = ["Semua Bagian"] + sorted(temp_df[b_col_org].dropna().unique().tolist())
                sel_bagian = st.selectbox("Pilih Bagian/Divisi:", bagian_list, key="org_b")
                if sel_bagian != "Semua Bagian":
                    final_org_df = temp_df[temp_df[b_col_org].astype(str) == sel_bagian]

        # Kolom inti untuk status
        pn_col = pick_col(final_org_df.columns, ["PN", "Pers.No.", "Personnel Number", "NIK", "NIK SAP"])
        nama_col = pick_col(final_org_df.columns, ["NAMA", "Nama", "Name"])
        jab_col = pick_col(final_org_df.columns, ["JABATAN", "Jabatan", "Position"])

        # Helper normalisasi string
        def norm_str(x: object) -> str:
            try:
                s = str(x).strip()
            except Exception:
                return ""
            return s

        # Nilai yang dianggap "negatif/kosong"
        NEG_VALUES = {"", "nan", "none", "null", "-", "0"}

        # Deteksi PN valid (bukan kosong & bukan nol)
        def has_valid_pn(row) -> bool:
            val = row.get(pn_col, None) if pn_col else None
            if val is None:
                return False
            s = norm_str(val).lower()
            if s in NEG_VALUES:
                return False
            # Jika numerik dan > 0 -> valid
            try:
                # Tangani string numerik dengan koma/titik
                sn = s.replace(",", "").replace(" ", "")
                # kalau format float dengan .0 (contoh: 12345.0)
                f = float(sn)
                if f <= 0:
                    return False
                return True
            except Exception:
                # Jika bukan numerik, selama bukan nilai negatif, anggap valid (PN alfanumerik)
                return True

        # Fallback, kalau PN tidak ada: Nama terisi bisa menjadi indikator "TERISI"
        def has_name(row) -> bool:
            if not nama_col:
                return False
            s = norm_str(row.get(nama_col, "")).lower()
            return s not in NEG_VALUES

        # Siapkan set jabatan VACANT terfilter berdasarkan Unit/Bagian yang dipilih
        if jab_vac_col:
            vac_df_filtered = vacant_df.copy()

            # Filter per Unit bila kolom Unit ada pada vacant database
            if u_col_vac and sel_org_unit:
                vac_df_filtered = vac_df_filtered[vac_df_filtered[u_col_vac].astype(str) == sel_org_unit]

            # Filter per Bagian bila dipilih spesifik dan ada kolom Bagian pada vacant DB
            if b_col_vac and b_col_org and 'sel_bagian' in locals() and sel_bagian and sel_bagian != "Semua Bagian":
                vac_df_filtered = vac_df_filtered[vac_df_filtered[b_col_vac].astype(str) == sel_bagian]

            vacant_set = set(vac_df_filtered[jab_vac_col].dropna().astype(str).str.strip().str.upper().tolist())
        else:
            vacant_set = set()

        # Penentuan status baris
        def check_status(row) -> str:
            # 1) Jika PN valid → TERISI (prioritas tertinggi)
            if has_valid_pn(row) or has_name(row):
                return "🟢 TERISI"

            # 2) Jika tidak ada PN/Nama: cek apakah jabatan ini tercantum VACANT pada unit/bagian ini
            jv = norm_str(row.get(jab_col, "")).upper() if jab_col else ""
            if jv and jv in vacant_set:
                return "🔴 VACANT (DB)"

            # 3) Default: VACANT
            return "🔴 VACANT"

        final_org_df["STATUS"] = final_org_df.apply(check_status, axis=1)
        
        # Display Metrics Organisasi
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Posisi", len(final_org_df))
        m2.metric("Terisi", int((final_org_df["STATUS"] == "🟢 TERISI").sum()))
        m3.metric("Vacant", int(final_org_df["STATUS"].str.contains("🔴").sum()))

        # Tampilkan Tabel
        st.dataframe(final_org_df, use_container_width=True, hide_index=True)
    else:
        st.warning("⚠️ Sheet 'Struktur Organisasi' atau 'Database Vacant' tidak ditemukan.")


st.success("Aplikasi Berjalan Normal")
# ==================== END OF APP ====================
