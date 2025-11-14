# app.py — Perbaikan dan Penambahan Dashboard Admin

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

# PENAMBAHAN: DEFINISI PATH FILE MEDIA
LOGO_PATH = BASE_DIR / "logo.jpeg"
STAF_PATH = BASE_DIR / "staf.jpg"
VIDEO_PATH = BASE_DIR / "video.mp4"
# -------------------- INISIALISASI SESSION STATE --------------------
st.session_state.setdefault("halaman", "Formulir Survei")  # default halaman

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
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()

        c.execute(
            "INSERT INTO responden (nama, jenis_kelamin, usia, layanan) VALUES (?, ?, ?, ?)",
            (nama, jk, usia, layanan),
        )
        rid = c.lastrowid

        for k, v in semua_jawaban.items():
            if v:
                teks, skor = extract_data_from_radio(v)
                c.execute(
                    "INSERT INTO jawaban (responden_id, pertanyaan_key, jawaban_teks, jawaban_skor) VALUES (?, ?, ?, ?)",
                    (rid, k, teks, skor),
                )

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
        df_responden = pd.read_sql_query("SELECT * FROM responden ORDER BY id DESC", conn)
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
    # PERBAIKAN: Menggunakan LOGO_PATH
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=250)
    else:
        st.subheader("Klinik Theresia")
        st.caption("Logo tidak ditemukan")
        
    st.markdown("<br>", unsafe_allow_html=True)
    for page in menu_pages:
        if st.button(page, key=f"nav_{page}", use_container_width=True):
            st.session_state.halaman = page
            st.rerun()

# -------------------- HEADER --------------------
# PERBAIKAN: Menggunakan LOGO_PATH
if LOGO_PATH.exists():
    st.image(str(LOGO_PATH), width=100)
else:
    st.header("Survei Klinik Theresia")

st.markdown("---")

# -------------------- HALAMAN FORMULIR --------------------
halaman = st.session_state.get("halaman", "Formulir Survei")  # memastikan tidak kosong

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
        prefix = layanan[0].lower()  # 'u' atau 'b'
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

# -------------------- HALAMAN: BERANDA -----------------------
elif halaman == "Beranda":
    # PERBAIKAN: Menggunakan STAF_PATH
    if STAF_PATH.exists():
        st.image(str(STAF_PATH), use_container_width=True, caption="Dokter, Staff, dan Jajaran")
    else:
        st.info("Gambar staf tidak ditemukan.")

    st.markdown("---")

    # Video profil (opsional)
    vid_path = VIDEO_PATH # Menggunakan path yang sudah didefinisikan
    if vid_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            # PERBAIKAN: Menghapus width=350 agar menyesuaikan kolom
            st.video(str(vid_path), start_time=0, format="video/mp4")
    else:
        st.info("Video profil belum tersedia.")

# -------------------- HALAMAN: TENTANG KLINIK --------------------
# Perlu didefinisikan bersama dengan LOGO_PATH, STAF_PATH, VIDEO_PATH
FTBERSAMA_PATH = BASE_DIR / "ftbersama.jpg"
PENERIMA_PATH = BASE_DIR / "penerima.jpg"
PIAGAM_PATH = BASE_DIR / "piagam.jpg"
PLAKAT_PATH = BASE_DIR / "plakat.jpg"


# ... (lanjutan dari kode sebelumnya, pastikan kode di atas ditambahkan di bagian definisi path)


# -------------------- HALAMAN: TENTANG KLINIK --------------------
# Perlu didefinisikan bersama dengan LOGO_PATH, STAF_PATH, VIDEO_PATH
FTBERSAMA_PATH = BASE_DIR / "ftbersama.jpg"
PENERIMA_PATH = BASE_DIR / "penerima.jpg"
PIAGAM_PATH = BASE_DIR / "piagam.jpg"
PLAKAT_PATH = BASE_DIR / "plakat.jpg"


# ... (lanjutan dari kode sebelumnya, pastikan kode di atas ditambahkan di bagian definisi path)


# -------------------- HALAMAN: TENTANG KLINIK --------------------
elif halaman == "Tentang Klinik":
    st.title("🏥 Tentang Klinik Pratama Theresia")

    # BARIS BARU: Menampilkan 4 Gambar
    st.subheader("Galeri Dokumentasi")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        # Menggunakan Path baru dan menyesuaikan ukuran width
        if FTBERSAMA_PATH.exists():
            st.image(str(FTBERSAMA_PATH), width=300, caption="Foto Bersama Staf")
    with col2:
        if PENERIMA_PATH.exists():
            st.image(str(PENERIMA_PATH), width=300, caption="Prosesi Penerimaan")
    with col3:
        if PIAGAM_PATH.exists():
            st.image(str(PIAGAM_PATH), width=300, caption="Piagam Penghargaan")
    with col4:
        if PLAKAT_PATH.exists():
            st.image(str(PLAKAT_PATH), width=300, caption="Plakat Penghargaan")
            
    st.markdown("---") # Garis pemisah visual
    
    # Konten Teks
    st.write(
        """
        Klinik Pratama Theresia berkomitmen untuk memberikan pelayanan kesehatan 
        yang terbaik dan terjangkau bagi masyarakat Kabupaten Nias Selatan. 
        Kami melayani pasien umum maupun BPJS dengan sepenuh hati.
        """
    )
    st.subheader("Visi Kami")
    st.write("Menjadi klinik pilihan utama masyarakat dengan pelayanan yang profesional dan humanis.")
    
    st.subheader("Layanan Kami")
    st.markdown("""
    * Layanan Umum
    * Layanan BPJS Kesehatan
    * Pemeriksaan Dokter Umum
    * Pengobatan dan Farmasi
    """)
    st.info("Untuk informasi lebih lanjut, silakan hubungi kontak kami.")

# -------------------- HALAMAN ADMIN DASHBOARD --------------------
elif halaman == "Admin Dashboard":
    password = st.sidebar.text_input("Masukkan Password Admin", type="password", key="admin_pass")
    ADMIN_PASSWORD = "kliniktheresia"

    if password == ADMIN_PASSWORD:
        st.sidebar.success("Login Berhasil")
        st.title("📊 Admin Dashboard Survei Kepuasan")
        df_responden, df_jawaban, df_saran = load_data_from_db()

        if df_responden.empty:
            st.info("Belum ada data survei yang masuk.")
        else:
            # Filter Data Berdasarkan Tanggal
            st.subheader("Filter Data")
            col_start, col_end = st.columns(2)
            min_date = pd.to_datetime(df_responden['tanggal']).dt.date.min()
            max_date = pd.to_datetime(df_responden['tanggal']).dt.date.max()

            with col_start:
                start_date = st.date_input("Tanggal Mulai", value=min_date, min_value=min_date, max_value=max_date)
            with col_end:
                end_date = st.date_input("Tanggal Akhir", value=max_date, min_value=min_date, max_value=max_date)

            df_responden['tanggal_date'] = pd.to_datetime(df_responden['tanggal']).dt.date

            df_responden_filtered = df_responden[(df_responden['tanggal_date'] >= start_date) & 
                                                 (df_responden['tanggal_date'] <= end_date)]
            
            # Mendapatkan ID responden yang sudah difilter
            responden_ids = df_responden_filtered['id'].tolist()

            # Filter data jawaban dan saran
            df_jawaban_filtered = df_jawaban[df_jawaban['responden_id'].isin(responden_ids)]
            df_saran_filtered = df_saran[df_saran['responden_id'].isin(responden_ids)]

            st.markdown("---")
            st.success(f"Menampilkan **{len(df_responden_filtered)}** Responden (dari total **{len(df_responden)}**)")

            # 1. Data Responden
            st.subheader("1. Data Responden")
            st.dataframe(df_responden_filtered.drop(columns=["tanggal_date"]), use_container_width=True)

            # 2. Detail Jawaban
            st.subheader("2. Detail Semua Jawaban")
            st.dataframe(df_jawaban_filtered, use_container_width=True)

            # 3. Saran dan Masukan
            st.subheader("3. Saran dan Masukan")
            st.dataframe(df_saran_filtered, use_container_width=True)

            # 4. Data Gabungan
            st.subheader("4. Data Gabungan (Responden + Saran)")
            if not df_saran_filtered.empty:
                df_gabung = pd.merge(
                    df_responden_filtered.drop(columns=["tanggal_date"]),
                    df_saran_filtered.drop(columns=["id"], errors="ignore"),
                    left_on="id", right_on="responden_id", how="left",
                )
            else:
                df_gabung = df_responden_filtered.drop(columns=["tanggal_date"]).copy()
                df_gabung["responden_id"] = np.nan
                df_gabung["saran"] = np.nan
            st.dataframe(df_gabung, use_container_width=True)

            # 5. K-Means Clustering
            st.subheader("5. Analisis Kluster Sentimen (K-Means)")
            df_cluster_data = prepare_cluster_data(df_jawaban_filtered)
            if df_cluster_data.shape[0] < 3:
                st.info("Tidak cukup data responden (minimum 3) dalam rentang tanggal ini untuk clustering.")
            else:
                try:
                    X = df_cluster_data[["skor_layanan","skor_keseluruhan"]]
                    # Menghindari warning n_init pada scikit-learn versi terbaru
                    kmeans = KMeans(n_clusters=3, random_state=42, n_init='auto').fit(X) 
                    df_cluster_data["cluster"] = kmeans.labels_

                    centers = kmeans.cluster_centers_
                    # Mengurutkan kluster berdasarkan skor rata-rata untuk memberi label sentimen
                    order = np.argsort(centers.mean(axis=1))
                    mapping = {order[0]:"Negatif/Kurang Puas", order[1]:"Netral", order[2]:"Positif/Puas"}
                    df_cluster_data["sentimen"] = df_cluster_data["cluster"].map(mapping).astype("category")

                    fig = px.scatter(
                        df_cluster_data,
                        x="skor_layanan", y="skor_keseluruhan",
                        color="sentimen", title="Kluster Sentimen Responden",
                        labels={"skor_layanan":"Rata-rata Skor Layanan (Umum/BPJS)",
                                "skor_keseluruhan":"Rata-rata Skor Keseluruhan"},
                        hover_data=["responden_id"],
                        category_orders={"sentimen": ["Negatif/Kurang Puas", "Netral", "Positif/Puas"]}
                    )
                    centers_df = pd.DataFrame(centers, columns=["skor_layanan","skor_keseluruhan"])
                    centers_df["sentimen"] = [mapping[i] for i in range(3)]
                    fig.add_scatter(
                        x=centers_df["skor_layanan"], y=centers_df["skor_keseluruhan"],
                        mode="markers", marker=dict(color="black", size=15, symbol="cross"),
                        name="Pusat Kluster",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown("#### Detail Data Kluster")
                    st.dataframe(df_cluster_data, use_container_width=True)
                except Exception as e:
                    st.error(f"Terjadi error saat visualisasi K-Means: {e}")

            # 6. Download Data
            st.subheader("6. Download Data Excel")
            excel_data = {
                "Responden": df_responden_filtered.drop(columns=["tanggal_date"]),
                "Detail Jawaban": df_jawaban_filtered,
                "Saran Masukan": df_saran_filtered,
                "Data Gabungan": df_gabung,
                "Analisis Kluster": df_cluster_data,
            }
            try:
                excel_bytes = generate_excel(excel_data)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                st.download_button(
                    "📥 Download Data (Excel)",
                    data=excel_bytes,
                    file_name=f"hasil_survei_klinik_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.error(f"Gagal membuat file Excel: {e}")

    elif password:   # jika password salah
        st.sidebar.error("Password salah. Coba lagi.")
        st.warning("Silakan masukkan password yang benar untuk melihat data.")
    else:
        st.sidebar.warning("Masukkan password admin di sidebar untuk melihat dashboard.")
        st.info("Halaman ini dilindungi password.")


# -------------------- FOOTER -------------------
st.markdown("---")
st.caption("© 2025 Klinik Pratama Theresia Kabupaten Nias Selatan")


