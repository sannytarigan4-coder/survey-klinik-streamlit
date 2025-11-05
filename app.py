import streamlit as st
import sqlite3
import datetime
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
import plotly.express as px
import io  # <-- TAMBAHAN: Untuk menangani file di memori
# Pastikan Anda sudah menginstal openpyxl: pip install openpyxl

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

# Fungsi untuk menampilkan skala dengan emosi
def skala_emosi(pertanyaan, key):
    # --- KEMBALI KE 5 POIN ---
    # Skala 5 Poin sesuai permintaan
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

# --- FUNGSI BARU UNTUK EXCEL ---
def generate_excel(dataframes_dict):
    """
    Membuat file Excel di memori dari dictionary DataFrames.
    Setiap key di dict akan menjadi nama sheet.
    """
    output = io.BytesIO()
    # Gunakan 'with' agar writer tertutup otomatis
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dataframes_dict.items():
            # Hanya tulis sheet jika datanya ada
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    # Ambil data bytes dari buffer
    return output.getvalue()

# --- FUNGSI BARU UNTUK ADMIN ---
def load_data_from_db():
    """Memuat semua data dari DB ke dalam pandas DataFrames."""
    conn = sqlite3.connect('survei_klinik.db')
    try:
        # Muat tabel dan urutkan berdasarkan ID terbaru di atas
        df_responden = pd.read_sql_query("SELECT * FROM responden ORDER BY id DESC", conn)
        df_jawaban = pd.read_sql_query("SELECT * FROM jawaban ORDER BY responden_id DESC, id ASC", conn)
        df_saran = pd.read_sql_query("SELECT * FROM saran_masukan ORDER BY responden_id DESC", conn)
        return df_responden, df_jawaban, df_saran
    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

# --- FUNGSI BARU UNTUK K-MEANS ---
def prepare_cluster_data(df_jawaban):
    """
    Mengubah data jawaban (long format) menjadi data per responden (wide format)
    untuk clustering. Kita akan menggunakan 2 fitur:
    1. Rata-rata skor 'layanan' (pertanyaan u... atau b...)
    2. Rata-rata skor 'keseluruhan' (pertanyaan k...)
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
             # Jika salah satu kosong, tidak bisa merge, kembalikan frame kosong
             return pd.DataFrame(columns=['responden_id', 'skor_layanan', 'skor_keseluruhan'])

        # Gunakan 'inner' merge untuk memastikan responden menjawab kedua bagian
        df_cluster_data = pd.merge(df_layanan_skor, df_keseluruhan_skor, on='responden_id', how='inner')
        return df_cluster_data.dropna()
        
    except Exception as e:
        st.error(f"Error saat menyiapkan data cluster: {e}")
        return pd.DataFrame(columns=['responden_id', 'skor_layanan', 'skor_keseluruhan'])


# --- LAYOUT APLIKASI ---

# Sidebar navigasi
st.sidebar.title("📌 Navigasi")
# --- UBAH BAGIAN INI ---
halaman = st.sidebar.selectbox("Pilih Halaman", [ "Formulir Survei","Beranda", "Tentang Klinik", "Admin Dashboard"])

# --- HALAMAN FORMULIR SURVEI ---
if halaman == "Formulir Survei":
    st.title("📝 Formulir Survei Kepuasan Pasien")
    
 # ⛳️ Pakai WITH, bukan IF
    with st.form("form_survei"):
        st.subheader("Bagian A. Data Diri Responden")

        # Urut ke bawah (tanpa columns)
        nama = st.text_input("Nama Lengkap")
        usia = st.radio("Usia", ["Dibawah 20 tahun", "21–30 tahun", "31–40 tahun", "41–50 tahun", "Diatas 50 tahun"])
        jenis_kelamin = st.selectbox("Jenis Kelamin", ["Laki-laki", "Perempuan"])

        st.markdown("---")

        # Pilihan layanan DIPINDAH KE SINI (di dalam form, setelah data diri)
        layanan = st.selectbox(
            "Silakan pilih jenis layanan yang Anda gunakan:",
            ["Umum", "BPJS"],
            key="pilihan_layanan"
        )

        st.markdown("---")
        
        # Pertanyaan (contoh ringkas)
        jawaban_dict = {}
        if layanan == "Umum":
            st.subheader("Bagian B1. Kepuasan Pelayanan – LAYANAN UMUM")
            jawaban_dict["u1"] = skala_emosi("Dokter menjelaskan kondisi dan pengobatan dengan jelas.", "u1")
            jawaban_dict["u2"] = skala_emosi("Dokter bersikap ramah dan profesional selama pemeriksaan.", "u2")
            jawaban_dict["u3"] = skala_emosi("Waktu tunggu sebelum pemeriksaan sesuai harapan.", "u3") # Fix typo 'before'
            jawaban_dict["u4"] = skala_emosi("Proses pendaftaran dan pembayaran berlangsung cepat dan mudah.", "u4")
            jawaban_dict["u5"] = skala_emosi("Petugas administrasi memberikan pelayanan yang sopan dan informatif.", "u5")
            jawaban_dict["u6"] = skala_emosi("Obat yang diberikan sesuai dengan keluhan dan ketersediaannya memadai.", "u6")
            jawaban_dict["u7"] = skala_emosi("Ruang tunggu dan fasilitas klinik bersih serta nyaman.", "u7")
            jawaban_dict["u8"] = skala_emosi("Biaya pelayanan sesuai dengan kualitas layanan yang diterima.", "u8")
            jawaban_dict["u9"] = skala_emosi("Secara keseluruhan, saya puas terhadap pelayanan pasien umum.", "u9")
            jawaban_dict["u10"] = skala_emosi("Saya bersedia datang kembali dan merekomendasikan klinik ini.", "u10")
        
        else:
            st.subheader("Bagian B2. Kepuasan Pelayanan – LAYANAN BPJS")
            jawaban_dict["b1"] = skala_emosi("Proses pendaftaran pasien BPJS mudah dan cepat.", "b1")
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
        st.subheader("Bagian C. Keseluruhan Pengalaman")
        jawaban_dict["k1"] = skala_emosi("Saya merasa Klinik Pratama Theresia memberikan pelayanan kesehatan yang baik secara keseluruhan.", "k1")
        jawaban_dict["k2"] = skala_emosi("Saya akan kembali menggunakan layanan di klinik ini di masa mendatang.", "k2")
        jawaban_dict["k3"] = skala_emosi("Saya akan merekomendasikan Klinik Theresia kepada keluarga atau teman.", "k3")

        st.markdown("---")
        st.subheader("Bagian D. Saran dan Masukan")
        saran = st.text_area("Tuliskan saran Anda:", key="saran_input")

        # 🚨 Tombol submit HARUS di dalam blok form
        submit = st.form_submit_button("Kirim Survei")

    # Logika submit sekarang berada di luar form
    if submit:
        berhasil_simpan = simpan_ke_db(
            nama, jenis_kelamin, usia, layanan,
            jawaban_dict,
            saran
        )
        
        # 2. Jika berhasil, baru tampilkan ringkasan
        if berhasil_simpan:
            # Ambil semua nilai dari dict jawaban untuk dihitung rata-ratanya
            nilai = []
            for radio_val in jawaban_dict.values():
                if radio_val:
                    teks, skor = extract_data_from_radio(radio_val)
                    nilai.append(skor)
            
            if not nilai:
                st.warning("Anda belum mengisi pertanyaan kepuasan.")
                rata_rata = 0
                sentimen = "Belum Diisi"
            else:
                rata_rata = sum(nilai) / len(nilai)
                
                # --- KEMBALI KE LOGIKA 5 POIN ---
                if rata_rata >= 4.0:
                    sentimen = "😄 Positif"
                elif rata_rata >= 2.5:
                    sentimen = "😐 Netral"
                else:
                    sentimen = "😠 Negatif"
            
            st.success(f"Terima kasih, {nama if nama else 'Bapak/Ibu'}, atas masukan Anda! Data telah tersimpan di database.")
            st.subheader(f"Sentimen Anda: *{sentimen}* (Skor rata-rata: {rata_rata:.2f})")
            
            st.markdown("---")
            st.markdown("#### Ringkasan Jawaban:")
            st.write(f"- *Nama:* {nama if nama else 'Tidak disebutkan'}")
            st.write(f"- *Jenis Kelamin:* {jenis_kelamin}")
            st.write(f"- *Usia:* {usia}")
            st.write(f"- *Jenis Layanan:* {layanan}") 
            st.write(f"- *Saran:* {saran if saran else 'Tidak ada'}")
# Halaman Beranda
elif halaman == "Beranda":
    st.title("🏥 Klinik Pratama Theresia")
    st.markdown("""
    Selamat datang di aplikasi survei kepuasan pasien Klinik Pratama Theresia.  
    Kami menghargai waktu Anda untuk memberikan masukan demi peningkatan layanan kami.
    """)

# Halaman Tentang Klinik
elif halaman == "Tentang Klinik":
    st.title("📖 Tentang Klinik Pratama Theresia")
    st.image("https://placehold.co/800x300/e0f2fe/0c4a6e?text=Klinik+Pratama+Theresia", use_column_width=True)
    st.markdown("""
    Klinik Pratama Theresia adalah fasilitas kesehatan yang berkomitmen memberikan pelayanan medis berkualitas tinggi dengan pendekatan yang ramah dan profesional.

    *Visi:* Menjadi klinik pilihan utama masyarakat dalam pelayanan kesehatan.

    *Misi:*
    - Memberikan pelayanan medis yang cepat, tepat, dan terpercaya.
    - Menjaga kenyamanan dan keamanan pasien.
    - Meningkatkan kualitas hidup masyarakat melalui edukasi kesehatan.

    ---
    *Informasi Kontak:* 📍 *Lokasi:* Jl. Sehat No. 123, Medan  
    📞 *Telepon:* (061) 123-4567  
    📧 *Email:* info@kliniksaroha.id
    """)

# --- HALAMAN BARU UNTUK ADMIN ---
elif halaman == "Admin Dashboard":
    st.title("📊 Admin Dashboard - Hasil Survei")

    # Tambahkan proteksi password sederhana
    # Password diletakkan di sidebar agar tidak mengganggu view utama
    password = st.sidebar.text_input("Masukkan Password Admin", type="password", key="admin_pass")
    
    # Ganti "kliniktheresia" dengan password yang Anda inginkan
    ADMIN_PASSWORD = "kliniktheresia" 
    
    if password == ADMIN_PASSWORD:
        st.sidebar.success("Login Berhasil")
        
        df_responden, df_jawaban, df_saran = load_data_from_db()
        
        if df_responden.empty:
            st.info("Belum ada data survei yang masuk.")
        else:
            st.subheader("1. Data Responden")
            st.info(f"Total Responden: {len(df_responden)}")
            st.dataframe(df_responden, use_container_width=True)
            
            st.subheader("2. Detail Semua Jawaban")
            st.dataframe(df_jawaban, use_container_width=True)
            
            st.subheader("3. Saran dan Masukan")
            st.dataframe(df_saran, use_container_width=True)
            
            # Opsi untuk menggabungkan data
            st.subheader("4. Data Gabungan (Responden + Saran)")
            # Menggabungkan responden dengan saran berdasarkan ID
            df_gabung = pd.merge(
                df_responden, 
                df_saran.drop('id', axis=1), # Hapus kolom id dari df_saran agar tidak duplikat
                left_on='id', 
                right_on='responden_id', 
                how='left' # Gunakan 'left' untuk tetap menampilkan responden walau tidak ada saran
            )
            st.dataframe(df_gabung, use_container_width=True)

            # --- BAGIAN BARU K-MEANS CLUSTERING ---
            st.subheader("5. Analisis Kluster Sentimen (K-Means)")
            
            # Siapkan data untuk clustering
            df_cluster_data = prepare_cluster_data(df_jawaban)
            
            # Kita butuh minimal 3 data untuk 3 kluster
            if df_cluster_data.shape[0] < 3:
                st.info("Tidak cukup data responden (minimum 3) untuk melakukan clustering.")
            else:
                # Ambil fitur untuk clustering
                X = df_cluster_data[['skor_layanan', 'skor_keseluruhan']]
                
                # Terapkan K-Means
                kmeans = KMeans(n_clusters=3, random_state=42, n_init=10).fit(X)
                
                # Tambahkan label cluster ke dataframe
                df_cluster_data['cluster'] = kmeans.labels_
                
                # Petakan label cluster ke nama sentimen yang lebih mudah dibaca
                try:
                    centers = kmeans.cluster_centers_
                    # Hitung rata-rata gabungan dari pusat (skor layanan + skor keseluruhan)
                    center_means = centers.mean(axis=1)
                    # Urutkan index berdasarkan rata-rata
                    order = np.argsort(center_means)
                    
                    # Buat pemetaan: 0->Negatif, 1->Netral, 2->Positif
                    mapping = {order[0]: 'Negatif/Kurang Puas', order[1]: 'Netral', order[2]: 'Positif/Puas'}
                    
                    df_cluster_data['sentimen'] = df_cluster_data['cluster'].map(mapping)
                    df_cluster_data['sentimen'] = df_cluster_data['sentimen'].astype('category')
                    
                    st.markdown("#### Visualisasi Kluster Sentimen")
                    
                    # Buat scatter plot dengan Plotly
                    fig = px.scatter(
                        df_cluster_data, 
                        x='skor_layanan', 
                        y='skor_keseluruhan', 
                        color='sentimen',
                        title='Kluster Sentimen Responden',
                        labels={'skor_layanan': 'Rata-rata Skor Layanan (Umum/BPJS)', 'skor_keseluruhan': 'Rata-rata Skor Keseluruhan'},
                        hover_data=['responden_id']
                    )
                    
                    # Tambahkan pusat kluster ke plot
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
                    st.write(f"Total responden yang di-cluster: {len(df_cluster_data)}")
                    st.dataframe(df_cluster_data, use_container_width=True)

                except Exception as e:
                    st.error(f"Terjadi error saat visualisasi K-Means: {e}")
                    # Jika gagal, buat df kosong agar download excel tidak error
                    df_cluster_data = pd.DataFrame() 
            
            # --- BAGIAN BARU UNTUK DOWNLOAD EXCEL ---
            st.subheader("6. Download Data Excel")
            st.info("Klik tombol di bawah untuk mengunduh semua data (Responden, Jawaban, Saran, Gabungan, dan Kluster) dalam satu file Excel.")
            
            # Siapkan data untuk di-download
            excel_data_dict = {
                "Responden": df_responden,
                "Detail Jawaban": df_jawaban,
                "Saran Masukan": df_saran,
                "Data Gabungan": df_gabung,
                "Analisis Kluster": df_cluster_data # Gunakan df yang sudah dibuat di atas
            }
            
            # Generate file Excel di memori
            try:
                excel_bytes = generate_excel(excel_data_dict)
                
                # Buat nama file dengan tanggal
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

    elif password: # Jika password diisi tapi salah
        st.sidebar.error("Password salah. Coba lagi.")
        st.warning("Silakan masukkan password yang benar untuk melihat data.")
    else: # Jika password belum diisi
        st.sidebar.warning("Silakan masukkan password admin di sidebar untuk melihat dashboard.")
        st.info("Halaman ini dilindungi password.")


# Footer
st.markdown("---")
st.caption("© 2025 Klinik Pratama Theresia. Dibuat dengan Streamlit.")
