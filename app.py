import io
import datetime
import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np
import plotly.express as px
from sklearn.cluster import KMeans
import streamlit as st

# -------------------- KONFIGURASI HALAMAN --------------------
st.set_page_config(page_title="Survei Klinik Theresia", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "survei_klinik.db"

# ✅ DEFINISI SEMUA PATH FILE MEDIA SECARA GLOBAL
LOGO_PATH = BASE_DIR / "logo.jpeg"
STAF_PATH = BASE_DIR / "staf.jpg"
VIDEO_PATH = BASE_DIR / "video.mp4"
FTBERSAMA_PATH = BASE_DIR / "ftbersama.jpg"
PENERIMA_PATH = BASE_DIR / "penerima.jpg"
PIAGAM_PATH = BASE_DIR / "piagam.jpg"
PLAKAT_PATH = BASE_DIR / "plakat.jpg"

# -------------------- INISIALISASI SESSION STATE --------------------
st.session_state.setdefault("halaman", "Formulir Survei")

# -------------------- DATABASE SETUP --------------------
def setup_database():
    """Buat DB & tabel jika belum ada."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS responden (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT,
        jenis_kelamin TEXT,
        usia TEXT,
        layanan TEXT,
        tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS jawaban (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        responden_id INTEGER,
        pertanyaan_key TEXT,
        jawaban_teks TEXT,
        jawaban_skor INTEGER,
        FOREIGN KEY (responden_id) REFERENCES responden (id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS saran_masukan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        responden_id INTEGER,
        saran TEXT,
        FOREIGN KEY (responden_id) REFERENCES responden (id)
    )
    """)

    conn.commit()
    conn.close()

setup_database()

# -------------------- HELPERS --------------------
def skala_emosi(pertanyaan, key):
    return st.radio(
        pertanyaan,
        [
            "1 😠 Sangat Tidak Puas",
            "2 😟 Tidak Puas",
            "3 😐 Netral",
            "4 🙂 Puas",
            "5 😄 Sangat Puas",
        ],
        key=key,
        horizontal=True,
    )

def extract_data_from_radio(radio_val):
    if radio_val is None:
        return None, 0
    parts = radio_val.split()
    skor = int(parts[0])
    teks = " ".join(parts[1:])
    return teks, skor

def simpan_ke_db(nama, jk, usia, layanan, semua_jawaban, saran):
    try:
        if not nama or not semua_jawaban:
            raise ValueError("Nama atau jawaban belum lengkap.")
        
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()

        # Memasukkan data responden
        c.execute(
            "INSERT INTO responden (nama, jenis_kelamin, usia, layanan) VALUES (?, ?, ?, ?)",
            (nama, jk, usia, layanan),
        )
        rid = c.lastrowid

        # Memasukkan jawaban
        for k, v in semua_jawaban.items():
            if v:
                teks, skor = extract_data_from_radio(v)
                c.execute(
                    "INSERT INTO jawaban (responden_id, pertanyaan_key, jawaban_teks, jawaban_skor) VALUES (?, ?, ?, ?)",
                    (rid, k, teks, skor),
                )

        # Memasukkan saran
        if saran:
            c.execute(
                "INSERT INTO saran_masukan (responden_id, saran) VALUES (?, ?)",
                (rid, saran),
            )

        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"DB error: {e}")
        return False
    except ValueError as ve:
        st.error(f"Error: {ve}")
        return False
    finally:
        try: conn.close()
        except: pass

def generate_excel(dataframes_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dataframes_dict.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

def load_data_from_db():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Menampilkan tanggal dengan format yang sesuai
        df_responden = pd.read_sql_query("SELECT *, DATE(tanggal) as tanggal_date FROM responden ORDER BY id DESC", conn)
        df_jawaban   = pd.read_sql_query("SELECT * FROM jawaban ORDER BY responden_id DESC, id ASC", conn)
        df_saran     = pd.read_sql_query("SELECT * FROM saran_masukan ORDER BY responden_id DESC", conn)
        return df_responden, df_jawaban, df_saran
    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

def prepare_cluster_data(df_jawaban):
    if df_jawaban.empty:
        return pd.DataFrame(columns=["responden_id","skor_layanan","skor_keseluruhan"])
    try:
        # Mengambil semua skor pertanyaan yang dimulai dengan 'u' atau 'b' (Layanan Umum/BPJS)
        df_layanan = df_jawaban[df_jawaban["pertanyaan_key"].str.contains("^[ub]", regex=True)]
        # Mengambil semua skor pertanyaan yang dimulai dengan 'k' (Keseluruhan Pengalaman)
        df_keseluruhan = df_jawaban[df_jawaban["pertanyaan_key"].str.contains("^k", regex=True)]

        if df_layanan.empty or df_keseluruhan.empty:
            return pd.DataFrame(columns=["responden_id","skor_layanan","skor_keseluruhan"])

        df_layanan_skor = (df_layanan.groupby("responden_id")["jawaban_skor"]
                           .mean().reset_index().rename(columns={"jawaban_skor":"skor_layanan"}))
        df_keseluruhan_skor = (df_keseluruhan.groupby("responden_id")["jawaban_skor"]
                               .mean().reset_index().rename(columns={"jawaban_skor":"skor_keseluruhan"}))
        return pd.merge(df_layanan_skor, df_keseluruhan_skor, on="responden_id", how="inner").dropna()
    except Exception as e:
        st.error(f"Error siapkan data cluster: {e}")
        return pd.DataFrame(columns=["responden_id","skor_layanan","skor_keseluruhan"])

# -------------------- SIDEBAR NAV --------------------
menu_pages = ["Formulir Survei", "Beranda", "Tentang Klinik", "Admin Dashboard"]
with st.sidebar:
    # Menggunakan LOGO_PATH
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=250)
    else:
        st.subheader("Klinik Theresia")
        st.caption("Logo tidak ditemukan")
        
    st.markdown("<br>", unsafe_allow_html=True)
    for page in menu_pages:
        if st.button(page, key=f"nav_{page}", use_container_width=True):
            st.session_state.halaman = page
            st.rerun()  # Pastikan halaman dirender ulang

# -------------------- HEADER --------------------
# Menggunakan LOGO_PATH
if LOGO_PATH.exists():
    st.image(str(LOGO_PATH), width=100)
else:
    st.header("Survei Klinik Theresia")

st.markdown("---")

# -------------------- HALAMAN FORMULIR --------------------
halaman = st.session_state.get("halaman", "Formulir Survei")

if halaman == "Formulir Survei":
    st.title("📝 Formulir Survei Kepuasan Pasien")

    with st.form("form_survei"):
        st.subheader("A. Data Diri Responden")
        nama = st.text_input("Nama Lengkap")
        usia = st.radio(
            "Usia",
            ["Dibawah 20 tahun","21–30 tahun","31–40 tahun","41–50 tahun","Diatas 50 tahun"],
        )
        jenis_kelamin = st.selectbox("Jenis Kelamin", ["Laki-laki","Perempuan"])

        st.markdown("---")

        layanan = st.selectbox(
            "Silakan pilih jenis layanan yang Anda gunakan:",
            ["Umum","BPJS"],
            key="pilihan_layanan",
        )

        st.markdown("---")

        jawaban_dict = {}
        if layanan == "Umum":
            st.subheader("B1. Kepuasan Pelayanan – LAYANAN UMUM")
            jawaban_dict["u1"]  = skala_emosi("Dokter menjelaskan kondisi dan pengobatan dengan jelas.", "u1")
            jawaban_dict["u2"]  = skala_emosi("Dokter bersikap ramah dan profesional selama pemeriksaan.", "u2")
            jawaban_dict["u3"]  = skala_emosi("Waktu tunggu sebelum pemeriksaan sesuai harapan.", "u3")
            jawaban_dict["u4"]  = skala_emosi("Proses pendaftaran dan pembayaran berlangsung cepat dan mudah.", "u4")
            jawaban_dict["u5"]  = skala_emosi("Petugas administrasi sopan dan informatif.", "u5")
            jawaban_dict["u6"]  = skala_emosi("Obat sesuai keluhan & ketersediaan memadai.", "u6")
            jawaban_dict["u7"]  = skala_emosi("Ruang tunggu & fasilitas bersih/nyaman.", "u7")
            jawaban_dict["u8"]  = skala_emosi("Biaya sesuai kualitas layanan.", "u8")
            jawaban_dict["u9"]  = skala_emosi("Secara keseluruhan puas pada layanan umum.", "u9")
            jawaban_dict["u10"] = skala_emosi("Bersedia datang kembali & merekomendasikan.", "u10")
        else:
            st.subheader("B2. Kepuasan Pelayanan – LAYANAN BPJS")
            jawaban_dict["b1"]  = skala_emosi("Pendaftaran BPJS mudah & cepat.", "b1")
            jawaban_dict["b2"]  = skala_emosi("Petugas BPJS informatif & membantu.", "b2")
            jawaban_dict["b3"]  = skala_emosi("Dokter ramah & menjelaskan pengobatan dengan baik.", "b3")
            jawaban_dict["b4"]  = skala_emosi("Waktu tunggu dokter sesuai harapan.", "b4")
            jawaban_dict["b5"]  = skala_emosi("Administrasi & pengambilan obat lancar.", "b5")
            jawaban_dict["b6"]  = skala_emosi("Tidak ada perbedaan perlakuan dgn pasien umum.", "b6")
            jawaban_dict["b7"]  = skala_emosi("Prosedur rujukan cepat & jelas.", "b7")
            jawaban_dict["b8"]  = skala_emosi("Fasilitas klinik bersih & nyaman.", "b8")
            jawaban_dict["b9"]  = skala_emosi("Secara keseluruhan puas pada layanan BPJS.", "b9")
            jawaban_dict["b10"] = skala_emosi("Bersedia datang kembali & merekomendasikan.", "b10")

        st.markdown("---")
        st.subheader("C. Keseluruhan Pengalaman")
        jawaban_dict["k1"] = skala_emosi("Pelayanan keseluruhan klinik baik.", "k1")
        jawaban_dict["k2"] = skala_emosi("Akan kembali menggunakan layanan klinik.", "k2")
        jawaban_dict["k3"] = skala_emosi("Akan merekomendasikan ke keluarga/teman.", "k3")

        st.markdown("---")
        st.subheader("D. Saran dan Masukan")
        saran = st.text_area("Tuliskan saran Anda:", key="saran_input")

        submit = st.form_submit_button("Kirim Survei")

    if submit:
        # Pastikan bagian layanan terisi semua
        prefix = layanan[0].lower()
        semua_terisi = all((val is not None) for k, val in jawaban_dict.items() if k.startswith(prefix))

        if not nama or not semua_terisi:
            st.error("Mohon isi Nama Lengkap dan semua pertanyaan di bagian Kepuasan Pelayanan.")
        else:
            if simpan_ke_db(nama, jenis_kelamin, usia, layanan, jawaban_dict, saran):
                nilai = [extract_data_from_radio(v)[1] for v in jawaban_dict.values() if v]
                rata_rata = (sum(nilai)/len(nilai)) if nilai else 0
                if rata_rata >= 4.0:   sentimen = "😄 Positif"
                elif rata_rata >= 2.5: sentimen = "😐 Netral"
                else:                  sentimen = "😠 Negatif"

                st.success(f"Terima kasih, {nama}! Data tersimpan.")
                st.subheader(f"Sentimen Anda: *{sentimen}* (Skor rata-rata: {rata_rata:.2f})")

                st.session_state.halaman = "Beranda"
                st.rerun()
