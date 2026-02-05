import streamlit as st
import pandas as pd
import requests
from io import BytesIO
import plotly.graph_objects as go
import subprocess
import os
from pathlib import Path

st.set_page_config(page_title="Dashboard Karyawan", layout="wide")
st.title("📊 Dashboard Rekapitulasi Karyawan")

# URL default
DEFAULT_URL = "https://github.com/nanozeta/sgnblank-app/raw/refs/heads/main/Cek%20Test%20Profile.xlsx"
LOCAL_FILE = "Cek Test Profile.xlsx"
REPO_PATH = "/workspaces/sgnblank-app"

# Auto load data dengan support untuk multiple sheets
@st.cache_data(ttl=3600)
def load_excel_data(url, sheet_name=0):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), sheet_name=sheet_name)
            return df, None
        else:
            return None, f"Error: Status code {response.status_code}"
    except Exception as e:
        return None, str(e)

# Load semua sheets dari file
def load_all_sheets(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            xls = pd.ExcelFile(BytesIO(response.content))
            sheets_dict = {}
            for sheet in xls.sheet_names:
                sheets_dict[sheet] = pd.read_excel(BytesIO(response.content), sheet_name=sheet)
            return sheets_dict, None
        else:
            return None, f"Error: Status code {response.status_code}"
    except Exception as e:
        return None, str(e)

# Push file ke GitHub
def push_to_github(file_path, commit_message="Update database"):
    try:
        os.chdir(REPO_PATH)
        subprocess.run(["git", "config", "--global", "user.email", "bot@streamlit.app"], check=False)
        subprocess.run(["git", "config", "--global", "user.name", "Streamlit Bot"], check=False)
        subprocess.run(["git", "add", LOCAL_FILE], check=True, capture_output=True)
        result = subprocess.run(["git", "commit", "-m", commit_message], capture_output=True, text=True)
        push_result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        if push_result.returncode == 0:
            return True, "✅ File berhasil di-push ke GitHub!"
        else:
            return False, f"❌ Error push: {push_result.stderr}"
    except Exception as e:
        return False, f"❌ Error: {str(e)}"

# Load data
df, error = load_excel_data(DEFAULT_URL)

if error:
    st.error(f"❌ Gagal memuat data: {error}")
else:
    # Dropdown Unit Kerja
    st.divider()
    st.subheader("🏢 Pilih Unit Kerja")
    
    # Get unique units
    units = sorted(df['Personel Subarea'].unique().tolist())
    units_with_all = ['Semua Unit'] + units
    
    selected_unit = st.selectbox(
        "Pilih Unit Kerja:",
        options=units_with_all,
        index=0,
        help="Pilih unit kerja untuk melihat rekapitulasi spesifik"
    )
    
    # Filter data berdasarkan unit yang dipilih
    if selected_unit == 'Semua Unit':
        df_filtered = df.copy()
        display_unit = "Semua Unit Kerja"
    else:
        df_filtered = df[df['Personel Subarea'] == selected_unit].copy()
        display_unit = selected_unit
    
    st.divider()
    
    # Hitung jumlah per Employee Group
    count_by_group = df_filtered['Employee Group'].value_counts().reset_index()
    count_by_group.columns = ['Employee Group', 'Jumlah']
    count_by_group = count_by_group.sort_values('Jumlah', ascending=False)

    # Hitung Job Grade 11 yang disetujui (anggap nilai tidak-NaN sebagai disetujui)
    if 'JOB GRADE 11' in df_filtered.columns:
        approved_series = df_filtered[df_filtered['JOB GRADE 11'].notna()]['Employee Group'].value_counts()
        count_by_group['Approved_JG11'] = count_by_group['Employee Group'].map(approved_series).fillna(0).astype(int)
    else:
        count_by_group['Approved_JG11'] = 0

    # Kategori utama yang ingin ditampilkan
    categories_of_interest = [
        'Karpel - Tetap',
        'Karpim - Tetap',
        'Karpel - Tidak Tetap',
        'Karpim - Tidak Tetap',
        'Tidak Tetap'
    ]

    # Filter untuk kategori utama
    summary_df = count_by_group[count_by_group['Employee Group'].isin(categories_of_interest)].copy()
    summary_df = summary_df.sort_values('Jumlah', ascending=False)

    # Pastikan kolom Approved_JG11 ada di summary
    if 'Approved_JG11' not in summary_df.columns:
        summary_df['Approved_JG11'] = 0

    # Hitung total kategori utama dan approved
    total_kategori = summary_df['Jumlah'].sum()
    total_approved_kategori = summary_df['Approved_JG11'].sum()

    # Hitung semua kategori lainnya
    other_categories = count_by_group[~count_by_group['Employee Group'].isin(categories_of_interest)].copy()
    total_other = other_categories['Jumlah'].sum()
    total_other_approved = other_categories['Approved_JG11'].sum() if 'Approved_JG11' in other_categories.columns else 0
    
    # Info umum
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("📊 Total Karyawan", len(df_filtered))

    with col2:
        st.metric("✅ Kategori Utama", total_kategori)

    with col3:
        st.metric("✅ Job Grade 11", int(total_approved_kategori))

    with col4:
        # Buat daftar kategori lain untuk tooltip
        other_categories_list = other_categories['Employee Group'].unique().tolist()
        other_categories_str = ', '.join(sorted(other_categories_list))
        help_text = f"Kategori Lain berisi:\n{other_categories_str}"
        st.metric("🔹 Kategori Lain", total_other, help=help_text)

    with col5:
        st.metric("📈 Unit", display_unit)
    
    st.divider()
    
    # Rekap Gender dan Usia
    st.subheader("👥 Rekap Gender dan Usia")

    # Hitung jumlah berdasarkan gender (toleransi untuk 'M', 'F', 'Male', 'Female')
    if 'Gender Key' in df_filtered.columns:
        gender_series = df_filtered['Gender Key'].fillna('Unknown').astype(str).str.strip().str.lower()
        male_count = int(((gender_series == 'male') | (gender_series == 'm')).sum())
        female_count = int(((gender_series == 'female') | (gender_series == 'f')).sum())
        other_gender = int(len(gender_series) - male_count - female_count)
    else:
        male_count = female_count = other_gender = 0

    gcol1, gcol2, gcol3 = st.columns(3)
    with gcol1:
        st.metric("👨 Male", male_count)
    with gcol2:
        st.metric("👩 Female", female_count)
    with gcol3:
        st.metric("❓ Lainnya", other_gender)

    # Hitung rekap usia
    if 'Age of employee' in df_filtered.columns:
        ages = pd.to_numeric(df_filtered['Age of employee'], errors='coerce')
        bins = [0, 24, 30, 40, 50, 55, 200]
        labels = ['<24 Tahun', '25 - 30 Tahun', '31 - 40 Tahun', '41 - 50 Tahun', '51 - 55 Tahun', '>55 Tahun']
        age_groups = pd.cut(ages.fillna(-1), bins=bins, labels=labels, include_lowest=True, right=True)
        age_counts = age_groups.value_counts().reindex(labels).fillna(0).astype(int)
    else:
        labels = ['<24 Tahun', '25 - 30 Tahun', '31 - 40 Tahun', '41 - 50 Tahun', '51 - 55 Tahun', '>55 Tahun']
        age_counts = pd.Series([0]*6, index=labels)

    st.write("Usia karyawan (rekap):")
    acols = st.columns(6)
    for col, label in zip(acols, labels):
        with col:
            st.metric(label, int(age_counts[label]))

    st.divider()
    
    # Tabel Summary Kategori Utama
    st.subheader("📋 Rekapitulasi Kategori Utama")
    
    if len(summary_df) > 0:
        # Tampilkan tabel
        display_df = summary_df.copy()
        display_df['Employee Group'] = display_df['Employee Group'].str.upper()
        display_df = display_df.rename(columns={
            'Employee Group': 'KATEGORI KARYAWAN',
            'Jumlah': 'JUMLAH',
            'Approved_JG11': 'JG11_DISETUJUI'
        })

        st.dataframe(
            display_df,
            width='stretch',
            hide_index=True,
            column_config={
                "KATEGORI KARYAWAN": st.column_config.TextColumn(width=300),
                "JUMLAH": st.column_config.NumberColumn(width=120),
                "JG11_DISETUJUI": st.column_config.NumberColumn(width=120)
            }
        )
        
        # Chart
        st.subheader("📈 Visualisasi Distribusi")
        
        fig = go.Figure(data=[
            go.Bar(
                x=summary_df['Employee Group'],
                y=summary_df['Jumlah'],
                marker=dict(
                    color=summary_df['Jumlah'],
                    colorscale='Viridis',
                    showscale=True
                ),
                text=summary_df['Jumlah'],
                textposition='auto',
            )
        ])
        
        fig.update_layout(
            title="Distribusi Karyawan Berdasarkan Kategori",
            xaxis_title="Kategori Karyawan",
            yaxis_title="Jumlah Karyawan",
            height=400,
            showlegend=False
        )
        
        st.plotly_chart(fig, use_container_width=True, key="kategori_chart")
    else:
        st.warning("⚠️ Kategori yang dicari tidak ditemukan dalam data")
    
    # Tabel lengkap semua kategori
    st.divider()
    st.subheader("📑 Semua Kategori Karyawan")
    
    all_categories_df = count_by_group.copy()
    all_categories_df = all_categories_df.rename(columns={
        'Employee Group': 'KATEGORI',
        'Jumlah': 'JUMLAH',
        'Approved_JG11': 'JG11_DISETUJUI'
    })

    st.dataframe(
        all_categories_df,
        width='stretch',
        hide_index=True,
        column_config={
            "KATEGORI": st.column_config.TextColumn(width=300),
            "JUMLAH": st.column_config.NumberColumn(width=120),
            "JG11_DISETUJUI": st.column_config.NumberColumn(width=120)
        }
    )
    
    # Daftar Karyawan
    st.divider()
    st.subheader("👥 Daftar Karyawan")
    
    # Pilih kolom yang akan ditampilkan
    employee_columns = [
        'Pers.No.',
        'Personnel Number',
        'Position',
        'Personel Subarea',
        'Birth date',
        'Age of employee',
        'Gender Key',
        'ESgrp',
        'Job Group Short (New)'
    ]
    
    # Pastikan semua kolom ada
    available_columns = [col for col in employee_columns if col in df_filtered.columns]
    
    if available_columns:
        employee_df = df_filtered[available_columns].copy()
        
        # Convert semua kolom ke string untuk menghindari error Arrow conversion
        for col in employee_df.columns:
            employee_df[col] = employee_df[col].astype(str)
        
        # Rename kolom untuk tampilan yang lebih baik
        column_display_names = {
            'Pers.No.': 'PERS. NO',
            'Personnel Number': 'NAMA',
            'Position': 'POSISI',
            'Personel Subarea': 'UNIT KERJA',
            'Birth date': 'TGL LAHIR',
            'Age of employee': 'USIA',
            'Gender Key': 'GENDER',
            'ESgrp': 'SUBGROUP',
            'Job Group Short (New)': 'JOB GROUP'
        }
        
        employee_df = employee_df.rename(columns={k: v for k, v in column_display_names.items() if k in employee_df.columns})
        
        st.dataframe(
            employee_df,
            width='stretch',
            hide_index=True,
            column_config={
                col: st.column_config.TextColumn(width=150)
                for col in employee_df.columns
            }
        )
        
        st.info(f"📊 Total karyawan ditampilkan: {len(employee_df)}")
    else:
        st.warning("⚠️ Kolom karyawan tidak ditemukan dalam data")
    
    # Info terakhir
    st.info(f"✅ Menampilkan data {display_unit} | Data otomatis di-update setiap jam dari: {DEFAULT_URL}")

# ==================== SECTION UPLOAD & MANAGE DATABASE ====================
st.divider()
st.header("📥 Kelola Database")

st.subheader("Unggah File Baru")
uploaded_file = st.file_uploader(
    "Unggah file Excel (.xlsx) untuk mengganti database",
    type=["xlsx"],
    help="File harus memiliki struktur kolom yang sama dengan database asli"
)

if uploaded_file is not None:
    try:
        # Preview data dari file yang diupload
        st.write("**Preview Data Uploaded File:**")
        preview_df = pd.read_excel(uploaded_file, nrows=5)
        st.dataframe(preview_df, use_container_width=True)
        
        # Button untuk simpan
        col_confirm, col_cancel = st.columns([1, 1])
        with col_confirm:
            if st.button("💾 Simpan & Push ke GitHub", use_container_width=True, type="primary"):
                # Simpan file lokal
                file_path = os.path.join(REPO_PATH, LOCAL_FILE)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Push ke GitHub
                success, message = push_to_github(file_path, "Update database via upload")
                if success:
                    st.success(message)
                    # Clear cache untuk reload data baru
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)
    except Exception as e:
        st.error(f"❌ Error membaca file: {str(e)}")

# Form untuk download template
st.divider()
st.subheader("📄 Download Template")
st.write("Unduh template Excel untuk referensi struktur kolom:")

if st.button("⬇️ Download Database Saat Ini", use_container_width=False):
    try:
        response = requests.get(DEFAULT_URL)
        st.download_button(
            label="📥 Klik untuk download",
            data=response.content,
            file_name="Template_Database.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# Info git
st.divider()
st.info(
    "ℹ️ **Catatan**: File yang diupload akan secara otomatis di-push ke GitHub branch 'main' "
    "melalui Streamlit. Pastikan struktur kolom Excel sesuai dengan database asli."
)
