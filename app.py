import io
import datetime
import sqlite3
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
import plotly.express as px

# -------------------- KONFIGURASI HALAMAN --------------------
st.set_page_config(page_title="Survei Klinik Theresia", layout="wide")

# -------------------- PATH ABSOLUT PROYEK --------------------
BASE_DIR = Path(__file__).resolve().parent  # Lokasi file script Python
DB_PATH = BASE_DIR / "survei_klinik.db"  # Nama file database yang ada di folder yang sama

# -------------------- SETUP SESSION STATE --------------------
if "halaman" not in st.session_state:
    st.session_state.halaman = "Formulir Survei"  # default

# -------------------- DATABASE SETUP -------------------------
def setup_database():
    """Membuat DB dan tabel bila belum ada (pakai path absolut)."""
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

# -------------------- HELPER PERTANYAAN ----------------------
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
    """return (teks, skor) dari string radio '1 😠 Sangat Tidak Puas'"""
    if radio_val is None:
        return None, 0
    parts = radio_val.split()
    skor = int(parts[0])
    teks = " ".join(parts[1:])
    return teks, skor

def simpan_ke_db(nama, jenis_kelamin, usia, layanan, semua_jawaban_dict, saran):
    """Simpan semua data form ke DB."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()

        # 1) responden
        c.execute(
            "INSERT INTO responden (nama, jenis_kelamin, usia, layanan) VALUES (?, ?, ?, ?)",
            (nama, jenis_kelamin, usia, layanan),
        )
        new_responden_id = c.lastrowid

        # 2) semua jawaban
        for key, radio_val in semua_jawaban_dict.items():
            if radio_val:
                teks, skor = extract_data_from_radio(radio_val)
                c.execute(
                    "INSERT INTO jawaban (responden_id, pertanyaan_key, jawaban_teks, jawaban_skor) VALUES (?, ?, ?, ?)",
                    (new_responden_id, key, teks, skor),
                )

        # 3) saran
        if saran:
            c.execute(
                "INSERT INTO saran_masukan (responden_id, saran) VALUES (?, ?)",
                (new_responden_id, saran),
            )

        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Terjadi error saat menyimpan ke database: {e}")
        return False
    finally:
        try:
            conn.close()
        except:
            pass

def generate_excel(dataframes_dict):
    """Buat file Excel di memori dari dict DataFrame."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dataframes_dict.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

def load_data_from_db():
    """Load semua data dari DB -> DataFrame."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        df_responden = pd.read_sql_query("SELECT * FROM responden ORDER BY id DESC", conn)
        df_jawaban = pd.read_sql_query(
            "SELECT * FROM jawaban ORDER BY responden_id DESC, id ASC", conn
        )
        df_saran = pd.read_sql_query(
            "SELECT * FROM saran_masukan ORDER BY responden_id DESC", conn
        )
        return df_responden, df_jawaban, df_saran
    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

def prepare_cluster_data(df_jawaban):
    """
    Ubah jawaban (long) jadi per responden (wide) untuk clustering.
    - skor_layanan: rata2 pertanyaan yang diawali u... atau b...
    - skor_keseluruhan: rata2 pertanyaan k...
    """
    if df_jawaban.empty:
        return pd.DataFrame(columns=["responden_id", "skor_layanan", "skor_keseluruhan"])

    try:
        df_layanan = df_jawaban[df_jawaban["pertanyaan_key"].str.contains("^[ub]", regex=True)]
        if not df_layanan.empty:
            df_layanan_skor = (
                df_layanan.groupby("responden_id")["jawaban_skor"]
                .mean()
                .reset_index()
                .rename(columns={"jawaban_skor": "skor_layanan"})
            )
        else:
            df_layanan_skor = pd.DataFrame(columns=["responden_id", "skor_layanan"])

        df_keseluruhan = df_jawaban[df_jawaban["pertanyaan_key"].str.contains("^k", regex=True)]
        if not df_keseluruhan.empty:
            df_keseluruhan_skor = (
                df_keseluruhan.groupby("responden_id")["jawaban_skor"]
                .mean()
                .reset_index()
                .rename(columns={"jawaban_skor": "skor_keseluruhan"})
            )
        else:
            df_keseluruhan_skor = pd.DataFrame(columns=["responden_id", "skor_keseluruhan"])

        if df_layanan_skor.empty or df_keseluruhan_skor.empty:
            return pd.DataFrame(columns=["responden_id", "skor_layanan", "skor_keseluruhan"])

        df_cluster_data = pd.merge(df_layanan_skor, df_keseluruhan_skor, on="responden_id", how="inner")
        return df_cluster_data.dropna()
    except Exception as e:
        st.error(f"Error saat menyiapkan data cluster: {e}")
        return pd.DataFrame(columns=["responden_id", "skor_layanan", "skor_keseluruhan"])

# -------------------- NAVIGATION (SIDEBAR) -------------------
menu_pages = ["Formulir Survei", "Beranda", "Tentang Klinik", "Admin Dashboard"]

with st.sidebar:
    c1, c2, c3 = st.columns([0.5, 5, 0.5])
    with c2:
        st.image("logo.jpeg", width=250)  # logo sidebar
    st.markdown("<br>", unsafe_allow_html=True)

for page in menu_pages:
    if st.sidebar.button(page, key=f"nav_{page}", use_container_width=True):
        st.session_state.halaman = page

# -------------------- HEADER GLOBAL --------------------------
# logo header tiap halaman
st.image("logo.jpeg", width=100)
st.markdown("---")

# -------------------- HALAMAN: FORMULIR ----------------------
halaman = st.session_state.halaman

if halaman == "Formulir Survei":
    st.title("📝Formulir Survei Kepuasan Pasien")

    with st.form("form_survei"):
        st.subheader("A. Data Diri Responden")
        nama = st.text_input("Nama Lengkap")
        usia = st.radio(
            "Usia",
            ["Dibawah 20 tahun", "21–30 tahun", "31–40 tahun", "41–50 tahun", "Diatas 50 tahun"],
        )
        jenis_kelamin = st.selectbox("Jenis Kelamin", ["Laki-laki", "Perempuan"])

        st.markdown("---")

        layanan = st.selectbox(
            "Silakan pilih jenis layanan yang Anda gunakan:",
            ["Umum", "BPJS"],
            key="pilihan_layanan",
        )

        st.markdown("---")

        jawaban_dict = {}
        if layanan == "Umum":
            st.subheader("B1. Kepuasan Pelayanan – LAYANAN UMUM")
            jawaban_dict["u1"] = skala_emosi("Dokter menjelaskan kondisi dan pengobatan dengan jelas.", "u1")
            jawaban_dict["u2"] = skala_emosi("Dokter bersikap ramah dan profesional selama pemeriksaan.", "u2")
            jawaban_dict["u3"] = skala_emosi("Waktu tunggu sebelum pemeriksaan sesuai harapan.", "u3")
            jawaban_dict["u4"] = skala_emosi("Proses pendaftaran dan pembayaran berlangsung cepat dan mudah.", "u4")
            jawaban_dict["u5"] = skala_emosi("Petugas administrasi memberikan pelayanan yang sopan dan informatif.", "u5")
            jawaban_dict["u6"] = skala_emosi("Obat yang diberikan sesuai dengan keluhan dan ketersediaannya memadai.", "u6")
            jawaban_dict["u7"] = skala_emosi("Ruang tunggu dan fasilitas klinik bersih serta nyaman.", "u7")
            jawaban_dict["u8"] = skala_emosi("Biaya pelayanan sesuai dengan kualitas layanan yang diterima.", "u8")
            jawaban_dict["u9"] = skala_emosi("Secara keseluruhan, saya puas terhadap pelayanan pasien umum.", "u9")
            jawaban_dict["u10"] = skala_emosi("Saya bersedia datang kembali dan merekomendasikan klinik ini.", "u10")
        else:
            st.subheader("B2. Kepuasan Pelayanan – LAYANAN BPJS")
            jawaban_dict["b1"] = skala_emosi("Proses pendaftaran pasien BPJS mudah dan cepat.", "b1")
            jawaban_dict["b2"] = skala_emosi("Petugas BPJS memberikan informasi yang jelas dan membantu.", "b2")
            jawaban_dict["b3"] = skala_emosi("Dokter memberikan pelayanan yang ramah dan menjelaskan pengobatan dengan baik.", "b3")
            jawaban_dict["b4"] = skala_emosi("Waktu tunggu untuk pemeriksaan dokter sesuai harapan.", "b4")
            jawaban_dict["b5"] = skala_emosi("Proses administrasi dan pengambilan obat berjalan lancar.", "b5")
            jawaban_dict["b6"] = skala_emosi("Tidak ada perbedaan perlakuan antara pasien BPJS dan pasien umum.", "b6")
            jawaban_dict["b7"] = skala_emosi("Prosedur rujukan dilakukan dengan cepat dan jelas.", "b7")
            jawaban_dict["b8"] = skala_emosi("Fasilitas klinik bersih dan nyaman.", "b8")
            jawaban_dict["b9"] = skala_emosi("Secara keseluruhan, saya puas terhadap pelayanan pasien BPJS.", "b9")
            jawaban_dict["b10"] = skala_emosi("Saya bersedia datang kembali dan merekomendasikan klinik ini.", "b10")

        st.markdown("---")
        st.subheader("C. Keseluruhan Pengalaman")
        jawaban_dict["k1"] = skala_emosi(
            "Saya merasa Klinik Pratama Theresia memberikan pelayanan kesehatan yang baik secara keseluruhan.", "k1"
        )
        jawaban_dict["k2"] = skala_emosi(
            "Saya akan kembali menggunakan layanan di klinik ini di masa mendatang.", "k2"
        )
        jawaban_dict["k3"] = skala_emosi(
            "Saya akan merekomendasikan Klinik Theresia kepada keluarga atau teman.", "k3"
        )

        st.markdown("---")
        st.subheader("D. Saran dan Masukan")
        saran = st.text_area("Tuliskan saran Anda:", key="saran_input")

        submit = st.form_submit_button("Kirim Survei")

    if submit:
        # cek semua pertanyaan layanan (u... / b...) terisi
        prefix = layanan[0].lower()  # 'u' atau 'b'
        semua_terisi = all(
            (val is not None)
            for k, val in jawaban_dict.items()
            if k.startswith(prefix)
        )

        if not nama or not semua_terisi:
            st.error("Mohon isi Nama Lengkap dan semua pertanyaan di bagian Kepuasan Pelayanan.")
        else:
            if simpan_ke_db(nama, jenis_kelamin, usia, layanan, jawaban_dict, saran):
                nilai = [extract_data_from_radio(v)[1] for v in jawaban_dict.values() if v]
                if not nilai:
                    rata_rata = 0
                    sentimen = "Belum Diisi"
                else:
                    rata_rata = sum(nilai) / len(nilai)
                    if rata_rata >= 4.0:
                        sentimen = "😄 Positif"
                    elif rata_rata >= 2.5:
                        sentimen = "😐 Netral"
                    else:
                        sentimen = "😠 Negatif"

                st.success(f"Terima kasih, {nama if nama else 'Bapak/Ibu'}, atas masukan Anda! Data telah tersimpan di database.")
                st.subheader(f"Sentimen Anda: *{sentimen}* (Skor rata-rata: {rata_rata:.2f})")

                # pindah ke Beranda
                st.session_state.halaman = "Beranda"
                st.rerun()

# -------------------- HALAMAN: BERANDA -----------------------
elif halaman == "Beranda":
    st.image("staf.jpg", use_container_width=True, caption="Dokter, Staff, dan Jajaran")
    st.markdown("---")

    # Video profil (opsional)
    vid_path = BASE_DIR / "video.mp4"
    if vid_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.video(str(vid_path), start_time=0, format="video/mp4", width=350)
    else:
        st.info("Video profil belum tersedia.")

    st.markdown("""  
Klinik Pratama Theresia berkomitmen memberikan pelayanan medis terbaik 
dengan tenaga profesional dan fasilitas yang nyaman bagi seluruh masyarakat Kabupaten Nias Selatan.  

Silakan klik **Formulir Survei** di samping untuk berpartisipasi memberikan penilaian Anda.
""")

# -------------------- HALAMAN: TENTANG KLINIK ----------------
elif halaman == "Tentang Klinik":
    st.title("📖 Tentang Klinik Pratama Theresia")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.image("ftbersama.jpg", width=300)
    with col2:
        st.image("penerima.jpg", width=310)
    with col3:
        st.image("piagam.jpg", width=280)
    with col4:
        st.image("plakat.jpg", width=300)

    st.markdown("""  
        <div style="text-align: center; margin-bottom: 80px;">
            Penerimaan Penghargaan sebagai Klinik Terbaik dan Klinik Berkomitmen Tahun 2024
            yang diserahkan oleh Kepala BPJS Cabang Gunung Sitoli
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
Klinik Pratama Theresia adalah fasilitas kesehatan yang berkomitmen memberikan pelayanan medis berkualitas tinggi dengan pendekatan yang ramah dan profesional.

*Visi:* Menjadi klinik pilihan utama masyarakat dalam pelayanan kesehatan.

*Misi:*
- Memberikan pelayanan medis yang cepat, tepat, dan terpercaya.
- Menjaga kenyamanan dan keamanan pasien.
- Meningkatkan kualitas hidup masyarakat melalui edukasi kesehatan.

---
*Informasi Kontak:*  
📍 *Lokasi:* Jl. Imam Bonjol No.10, Kel. Pasar Teluk Dalam, Kab. Nias Selatan, Prov. Sumatera Utara  
📞 *Telepon:* 0852-1012-5773  
📧 *Email:* info@kliniktheresia.id
""")
