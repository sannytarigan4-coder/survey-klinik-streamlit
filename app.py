import streamlit as st
import sqlite3
import datetime
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
import plotly.express as px
import io 
import base64
import os

# Pastikan Anda sudah menginstal openpyxl, pandas, numpy, scikit-learn, plotly: 
# pip install streamlit sqlite3 pandas numpy scikit-learn plotly openpyxl

# --- SETUP SESSION STATE (PENTING UNTUK NAVIGASI TOMBOL) ---
if 'halaman' not in st.session_state:
    st.session_state.halaman = "Formulir Survei" # Set halaman default

# --- DATABASE SETUP ---

# Fungsi untuk setup database
def setup_database():
    """Membuat koneksi ke DB dan membuat tabel jika belum ada."""
    conn = sqlite3.connect('survei_klinik.db')
    c = conn.cursor()
    
    # Tabel Responden
    c.execute('''
    CREATE TABLE IF NOT EXISTS responden (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT,
        jenis_kelamin TEXT,
        usia TEXT,
        layanan TEXT,
        tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabel Jawaban (menyimpan setiap jawaban radio button)
    c.execute('''
    CREATE TABLE IF NOT EXISTS jawaban (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        responden_id INTEGER,
        pertanyaan_key TEXT,
        jawaban_teks TEXT,
        jawaban_skor INTEGER,
        FOREIGN KEY (responden_id) REFERENCES responden (id)
    )
    ''')
    
    # Tabel Saran
    c.execute('''
    CREATE TABLE IF NOT EXISTS saran_masukan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        responden_id INTEGER,
        saran TEXT,
        FOREIGN KEY (responden_id) REFERENCES responden (id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Panggil fungsi setup sekali saat aplikasi dimuat
setup_database()


# --- FUNGSI HELPER ---

# Konfigurasi halaman
st.set_page_config(page_title="Survei Klinik Theresia", layout="wide")

# --- TEMA WARNA SIDEBAR KLINIK ---
st.markdown("""
<style>
/* Warna latar sidebar */
[data-testid="stSidebar"] {
    background-color: #e3f2fd;  /* biru muda lembut */
}

/* Logo di tengah */
[data-testid="stSidebar"] img {
    display: block;
    margin-left: auto;
    margin-right: auto;
    margin-top: 10px;
    width: 90%;
    border-radius: 8px;
}

/* Judul di bawah logo */
[data-testid="stSidebar"] h3 {
    color: #0d47a1;  /* biru gelap profesional */
    text-align: center;
}

/* Tombol navigasi */
div[data-testid="stSidebar"] button {
    background-color: #bbdefb !important;  /* biru pastel */
    color: #0d47a1 !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    margin-bottom: 10px !important;
    transition: 0.3s;
}

/* Efek hover tombol */
div[data-testid="stSidebar"] button:hover {
    background-color: #64b5f6 !important;
    color: white !important;
    transform: scale(1.02);
}

/* Tombol aktif (secondary) */
div[data-testid="stSidebar"] button[kind="secondary"] {
    background-color: #1976d2 !important;
    color: white !important;
    border: 1px solid #0d47a1 !important;
}

/* Warna latar utama halaman */
[data-testid="stAppViewContainer"] {
    background-color: #f7fbff;
}

/* Warna garis pemisah */
hr {
    border: 1px solid #bbdefb !important;
}
</style>
""", unsafe_allow_html=True)

# --- SETUP SESSION STATE (PENTING UNTUK NAVIGASI TOMBOL) ---
if 'halaman' not in st.session_state:
    st.session_state.halaman = "Formulir Survei"

# Fungsi untuk menampilkan skala dengan emosi
def skala_emosi(pertanyaan, key):
    # Skala 5 Poin
    return st.radio(
        pertanyaan,
        [
            "1 😠 Sangat Tidak Puas",
            "2 😟 Tidak Puas",
            "3 😐 Netral",
            "4 🙂 Puas",
            "5 😄 Sangat Puas"
        ],
        key=key,
        horizontal=True,
    )

# Fungsi untuk mengekstrak skor dan teks dari nilai radio button
def extract_data_from_radio(radio_val):
    """Mengekstrak ('Teks Jawaban', skor) dari '1 😠 Sangat Tidak Puas'"""
    if radio_val is None:
        return None, 0
    parts = radio_val.split()
    skor = int(parts[0])
    teks = " ".join(parts[1:])
    return teks, skor

# Fungsi untuk menyimpan data ke DB
def simpan_ke_db(nama, jenis_kelamin, usia, layanan, semua_jawaban_dict, saran):
    """Menyimpan semua data form ke database SQLite."""
    try:
        conn = sqlite3.connect('survei_klinik.db')
        c = conn.cursor()
        
        # 1. Insert ke tabel responden
        c.execute(
            "INSERT INTO responden (nama, jenis_kelamin, usia, layanan) VALUES (?, ?, ?, ?)",
            (nama, jenis_kelamin, usia, layanan)
        )
        new_responden_id = c.lastrowid
        
        # 2. Insert semua jawaban
        for key, radio_val in semua_jawaban_dict.items():
            if radio_val: # Hanya jika sudah dijawab
                teks, skor = extract_data_from_radio(radio_val)
                c.execute(
                    "INSERT INTO jawaban (responden_id, pertanyaan_key, jawaban_teks, jawaban_skor) VALUES (?, ?, ?, ?)",
                    (new_responden_id, key, teks, skor)
                )
        
        # 3. Insert saran
        if saran:
            c.execute(
                "INSERT INTO saran_masukan (responden_id, saran) VALUES (?, ?)",
                (new_responden_id, saran)
            )
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Terjadi error saat menyimpan ke database: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Fungsi untuk generate Excel
def generate_excel(dataframes_dict):
    """Membuat file Excel di memori dari dictionary DataFrames."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dataframes_dict.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

# Fungsi untuk load data
def load_data_from_db():
    """Memuat semua data dari DB ke dalam pandas DataFrames."""
    conn = sqlite3.connect('survei_klinik.db')
    try:
        df_responden = pd.read_sql_query("SELECT * FROM responden ORDER BY id DESC", conn)
        df_jawaban = pd.read_sql_query("SELECT * FROM jawaban ORDER BY responden_id DESC, id ASC", conn)
        df_saran = pd.read_sql_query("SELECT * FROM saran_masukan ORDER BY responden_id DESC", conn)
        return df_responden, df_jawaban, df_saran
    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

# Fungsi untuk K-Means
def prepare_cluster_data(df_jawaban):
    """
    Mengubah data jawaban (long format) menjadi data per responden (wide format)
    untuk clustering. 
    """
    if df_jawaban.empty:
        return pd.DataFrame(columns=['responden_id', 'skor_layanan', 'skor_keseluruhan'])

    try:
        # Skor Layanan (u... or b...)
        df_layanan = df_jawaban[df_jawaban['pertanyaan_key'].str.contains('^[ub]', regex=True)]
        if not df_layanan.empty:
            df_layanan_skor = df_layanan.groupby('responden_id')['jawaban_skor'].mean().reset_index().rename(columns={'jawaban_skor': 'skor_layanan'})
        else:
            df_layanan_skor = pd.DataFrame(columns=['responden_id', 'skor_layanan'])

        # Skor Keseluruhan (k...)
        df_keseluruhan = df_jawaban[df_jawaban['pertanyaan_key'].str.contains('^k', regex=True)]
        if not df_keseluruhan.empty:
            df_keseluruhan_skor = df_keseluruhan.groupby('responden_id')['jawaban_skor'].mean().reset_index().rename(columns={'jawaban_skor': 'skor_keseluruhan'})
        else:
            df_keseluruhan_skor = pd.DataFrame(columns=['responden_id', 'skor_keseluruhan'])

        # Gabungkan
        if df_layanan_skor.empty or df_keseluruhan_skor.empty:
             return pd.DataFrame(columns=['responden_id', 'skor_layanan', 'skor_keseluruhan'])

        df_cluster_data = pd.merge(df_layanan_skor, df_keseluruhan_skor, on='responden_id', how='inner')
        return df_cluster_data.dropna()
        
    except Exception as e:
        st.error(f"Error saat menyiapkan data cluster: {e}")
        return pd.DataFrame(columns=['responden_id', 'skor_layanan', 'skor_keseluruhan'])


# Daftar halaman
menu_pages = ["Formulir Survei", "Beranda", "Tentang Klinik", "Admin Dashboard"]

# Tampilkan logo di atas tombol navigasi (masih dalam sidebar)
with st.sidebar:
    # 3 kolom: kiri-kecil, tengah-besar, kanan-kecil
    c1, c2, c3 = st.columns([0.5, 5, 0.5])
    with c2:
     st.image("assets/logo1.png", width=250    )  # atau width=120 kalau mau fix
    st.markdown("<br>", unsafe_allow_html=True)  # beri jarak sedikit

# Logika Tombol di Sidebar
for page in menu_pages:
    # Set halaman saat tombol diklik
    if st.sidebar.button(page, key=f"nav_{page}", use_container_width=True):
        st.session_state.halaman = page
        
# Ambil halaman aktif dari session state
halaman = st.session_state.halaman

st.image("assets/logo.jpeg", width=100)   # Logo muncul di bagian atas setiap halaman
st.markdown("", unsafe_allow_html=True)
st.markdown("---")

# --- HALAMAN FORMULIR SURVEI ---
if halaman == "Formulir Survei":
    st.title("📝Formulir Survei Kepuasan Pasien")
    
    with st.form("form_survei"):
        st.subheader("A. Data Diri Responden")

        nama = st.text_input("Nama Lengkap")
        usia = st.radio("Usia", ["Dibawah 20 tahun", "21–30 tahun", "31–40 tahun", "41–50 tahun", "Diatas 50 tahun"])
        jenis_kelamin = st.selectbox("Jenis Kelamin", ["Laki-laki", "Perempuan"])

        st.markdown("---")

        layanan = st.selectbox(
            "Silakan pilih jenis layanan yang Anda gunakan:",
            ["Umum", "BPJS"],
            key="pilihan_layanan"
        )

        st.markdown("---")
        
        # Pertanyaan
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
            # Perbaiki bug duplikasi key b1:
            jawaban_dict.pop("b1", None) # Hapus yang tadi (jika ada)
            jawaban_dict["b1"] = skala_emosi("Proses pendaftaran pasien BPJS mudah dan cepat.", "b1") # Ulangi
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
        jawaban_dict["k1"] = skala_emosi("Saya merasa Klinik Pratama Theresia memberikan pelayanan kesehatan yang baik secara keseluruhan.", "k1")
        jawaban_dict["k2"] = skala_emosi("Saya akan kembali menggunakan layanan di klinik ini di masa mendatang.", "k2")
        jawaban_dict["k3"] = skala_emosi("Saya akan merekomendasikan Klinik Theresia kepada keluarga atau teman.", "k3")

        st.markdown("---")
        st.subheader("D. Saran dan Masukan")
        saran = st.text_area("Tuliskan saran Anda:", key="saran_input")

        submit = st.form_submit_button("Kirim Survei")

    # Logika submit
    if submit:
        # Periksa apakah semua radio button diisi (opsional, tapi disarankan)
        semua_terisi = all(val is not None for key, val in jawaban_dict.items() if key.startswith(layanan[0].lower()))
        
        if not nama or not semua_terisi:
             st.error("Mohon isi Nama Lengkap dan semua pertanyaan di bagian Kepuasan Pelayanan.")
        else:
            berhasil_simpan = simpan_ke_db(
                nama, jenis_kelamin, usia, layanan,
                jawaban_dict,
                saran
            )
            
            if berhasil_simpan:
                nilai = [extract_data_from_radio(radio_val)[1] for radio_val in jawaban_dict.values() if radio_val]
                
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
                
                # Setelah berhasil submit, pindah ke halaman Beranda
                st.session_state.halaman = "Beranda"
                st.rerun() # Refresh untuk menampilkan halaman Beranda


# Halaman Beranda
elif halaman == "Beranda":
    from pathlib import Path
    st.image("assets/staf.jpg", use_container_width=True, caption="Dokter, Staff, dan Jajaran")
    
     # ---------- VIDEO PROFIL ----------
    # ✅ Definisikan path video di sini
    vid_path = Path("assets/video.mp4")

    if vid_path.exists():
        
          # ---------- VIDEO PROFIL ----------
        vid_path = Path("assets/video.mp4")

    if vid_path.exists():
        # Gunakan kolom Streamlit untuk memusatkan video
        col1, col2, col3 = st.columns([1, 2, 1])  # Rasio 1:2:1 → kolom tengah lebih lebar
        with col2:
            st.video(str(vid_path), start_time=0, format="video/mp4", width=350)

        
    st.markdown("""
    ---
    Klinik Pratama Theresia berkomitmen memberikan pelayanan medis terbaik 
    dengan tenaga profesional dan fasilitas yang nyaman bagi seluruh masyarakat Kabupaten Nias Selatan.  

    Silakan klik **Formulir Survei** di samping untuk berpartisipasi memberikan penilaian Anda.
    """)

# Halaman Tentang Klinik
elif halaman == "Tentang Klinik":
    st.title("📖 Tentang Klinik Pratama Theresia")
    
      # Membuat kolom untuk menampilkan gambar dalam satu baris
    col1, col2, col3, col4 = st.columns(4)  # Membuat empat kolom untuk gambar

    # Menampilkan gambar-gambar di masing-masing kolom
    with col1:
        st.image("assets/ftbersama.jpg", width=300)
    with col2:
        st.image("assets/penerima.jpg", width= 310)
    with col3:
        st.image("assets/piagam.jpg", width=280)
    with col4:
        st.image("assets/plakat.jpg", width=300)
        
    # Menambahkan caption dengan HTML untuk memposisikannya di tengah
    st.markdown("""
        <div style="text-align: center; margin-bottom: 80px;">
            Penerimaan Penghargaan sebagai Klinik Terbaik dan Klinik Berkomitmen Tahun 2024 yang diserahkan oleh Kepala BPJS Cabang Gunung Sitoli
        </div>
    """, unsafe_allow_html=True)
    
    
    st.markdown("""
    Klinik Pratama Theresia adalah fasilitas kesehatan yang berkomitmen memberikan pelayanan medis berkualitas tinggi dengan pendekatan yang ramah dan profesional.

    *Visi:* Menjadi klinik pilihan utama masyarakat dalam pelayanan kesehatan.

    *Misi:*
    * Memberikan pelayanan medis yang cepat, tepat, dan terpercaya.
    * Menjaga kenyamanan dan keamanan pasien.
    * Meningkatkan kualitas hidup masyarakat melalui edukasi kesehatan.

    ---
    *Informasi Kontak:* 📍 *Lokasi:* Jl. Imam Bonjol No.10
    Kel. Pasar Teluk Dalam, Kab. Nias Selatan,
    Prov. Sumatera Utara 
    📞 *Telepon:* 0852-1012-5773  
    📧 *Email:* info@kliniktheresia.id
    """)

# --- HALAMAN ADMIN DASHBOARD ---
elif halaman == "Admin Dashboard":
    st.title("📊 Admin Dashboard - Hasil Survei")

    # Proteksi password sederhana
    password = st.sidebar.text_input("Masukkan Password Admin", type="password", key="admin_pass")
    
    ADMIN_PASSWORD = "kliniktheresia" 
    
    if password == ADMIN_PASSWORD:
        st.sidebar.success("Login Berhasil")
        
        df_responden, df_jawaban, df_saran = load_data_from_db()
        
        if df_responden.empty:
            st.info("Belum ada data survei yang masuk.")
        else:
            # 1. Tampilkan Data
            st.subheader("1. Data Responden")
            st.info(f"Total Responden: {len(df_responden)}")
            st.dataframe(df_responden, use_container_width=True)
            
            st.subheader("2. Detail Semua Jawaban")
            st.dataframe(df_jawaban, use_container_width=True)
            
            st.subheader("3. Saran dan Masukan")
            st.dataframe(df_saran, use_container_width=True)
            
            # 4. Data Gabungan
            st.subheader("4. Data Gabungan (Responden + Saran)")
            df_gabung = pd.merge(
                df_responden, 
                df_saran.drop('id', axis=1), 
                left_on='id', 
                right_on='responden_id', 
                how='left'
            )
            st.dataframe(df_gabung, use_container_width=True)

            # 5. K-MEANS CLUSTERING
            st.subheader("5. Analisis Kluster Sentimen (K-Means)")
            df_cluster_data = prepare_cluster_data(df_jawaban)
            
            if df_cluster_data.shape[0] < 3:
                st.info("Tidak cukup data responden (minimum 3) untuk melakukan clustering.")
                df_cluster_data = pd.DataFrame() # Kosongkan jika tidak bisa clustering
            else:
                try:
                    X = df_cluster_data[['skor_layanan', 'skor_keseluruhan']]
                    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10).fit(X)
                    df_cluster_data['cluster'] = kmeans.labels_
                    
                    # Pemetaan Cluster ke Sentimen
                    centers = kmeans.cluster_centers_
                    center_means = centers.mean(axis=1)
                    order = np.argsort(center_means)
                    mapping = {order[0]: 'Negatif/Kurang Puas', order[1]: 'Netral', order[2]: 'Positif/Puas'}
                    
                    df_cluster_data['sentimen'] = df_cluster_data['cluster'].map(mapping)
                    df_cluster_data['sentimen'] = df_cluster_data['sentimen'].astype('category')
                    
                    st.markdown("#### Visualisasi Kluster Sentimen")
                    
                    fig = px.scatter(
                        df_cluster_data, 
                        x='skor_layanan', 
                        y='skor_keseluruhan', 
                        color='sentimen',
                        title='Kluster Sentimen Responden',
                        labels={'skor_layanan': 'Rata-rata Skor Layanan (Umum/BPJS)', 'skor_keseluruhan': 'Rata-rata Skor Keseluruhan'},
                        hover_data=['responden_id']
                    )
                    
                    # Tambahkan Pusat Kluster
                    centers_df = pd.DataFrame(centers, columns=['skor_layanan', 'skor_keseluruhan'])
                    centers_df['sentimen'] = [mapping[i] for i in range(3)]
                    
                    fig.add_scatter(
                        x=centers_df['skor_layanan'], 
                        y=centers_df['skor_keseluruhan'], 
                        mode='markers',
                        marker=dict(color='black', size=15, symbol='cross'),
                        name='Pusat Kluster'
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown("#### Detail Data Kluster")
                    st.dataframe(df_cluster_data, use_container_width=True)

                except Exception as e:
                    st.error(f"Terjadi error saat visualisasi K-Means: {e}")
                    df_cluster_data = pd.DataFrame() 
            
            # 6. DOWNLOAD EXCEL
            st.subheader("6. Download Data Excel")
            st.info("Klik tombol di bawah untuk mengunduh semua data dalam satu file Excel.")
            
            excel_data_dict = {
                "Responden": df_responden,
                "Detail Jawaban": df_jawaban,
                "Saran Masukan": df_saran,
                "Data Gabungan": df_gabung,
                "Analisis Kluster": df_cluster_data 
            }
            
            try:
                excel_bytes = generate_excel(excel_data_dict)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                file_name = f"hasil_survei_klinik_{timestamp}.xlsx"
                
                st.download_button(
                    label="📥 Download Data (Excel)",
                    data=excel_bytes,
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except Exception as e:
                st.error(f"Gagal membuat file Excel: {e}")

    elif password: 
        st.sidebar.error("Password salah. Coba lagi.")
        st.warning("Silakan masukkan password yang benar untuk melihat data.")
    else: 
        st.sidebar.warning("Silakan masukkan password admin di sidebar untuk melihat dashboard.")
        st.info("Halaman ini dilindungi password.")


# Footer
st.markdown("---")
st.caption("© 2025 Klinik Pratama Theresia Kabupaten Nias Selatan")
