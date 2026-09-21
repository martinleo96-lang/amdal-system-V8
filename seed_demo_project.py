"""
Membuat satu proyek contoh (demo) di folder projects/ agar aplikasi langsung
berisi data saat pertama kali dibuka.

    python3 scripts/seed_demo_project.py

Proyek demo : PRJ-2026-001 (Pembangunan Pabrik Semen - PT. Usaha Bersama)
Password    : 123
"""
import json
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

PROJECTS_DIR = os.path.join(BASE, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

now = datetime.now()


def ts(days_ago, hh=9, mm=0):
    return (now - timedelta(days=days_ago)).strftime(f"%Y-%m-%d {hh:02d}:{mm:02d}")


demo = {
    "project_id": "PRJ-2026-001",
    "nama_proyek": "Pembangunan Pabrik Semen",
    "pemrakarsa": "PT. Usaha Bersama",
    "kbli": "23940",
    "luas_lahan": 55.0,
    "pic_project": "Ir. Hendra Kusuma, M.T.",
    "project_password": "123",
    "nib_oss": "1289000123456",
    "id_oss_project": "OSS-2026-9988123",
    "lokasi_proyek": "Kecamatan Katibung, Kabupaten Lampung Selatan, Provinsi Lampung",
    "lat_proyek": -5.3972,
    "lon_proyek": 105.2663,
    "item_checks": [
        {"id": "MAP-01", "item": "KKPR / PKKPR & Legalitas Lahan", "kategori": "1. Prasyarat OSS", "status": "Selesai / Valid", "catatan": "Kesesuaian Tata Ruang Disetujui"},
        {"id": "MAP-02", "item": "Penapisan Amdalnet & Sinkron NIB", "kategori": "1. Prasyarat OSS", "status": "Selesai / Valid", "catatan": "Terverifikasi Wajib AMDAL (Risiko Tinggi)"},
        {"id": "MAP-03", "item": "Pengumpulan Data Sekunder", "kategori": "2. Rona Awal", "status": "Selesai / Valid", "catatan": "Data BMKG & ISPU Terintegrasi"},
        {"id": "MAP-04", "item": "Penyusunan Form KA-ANDAL & DPH", "kategori": "3. Pelingkupan", "status": "Selesai / Valid", "catatan": "Pelingkupan DPH Fix"},
        {"id": "MAP-05", "item": "Pemenuhan Pertek BMAL & Cerobong", "kategori": "4. Pertek Penunjang", "status": "Sedang Diproses", "catatan": "Dalam Evaluasi DLH"},
        {"id": "MAP-06", "item": "Penyusunan Dokumen Laporan Utuh", "kategori": "5. Laporan AMDAL", "status": "Sedang Diproses", "catatan": "Draft Bab I - V Terkompilasi"},
        {"id": "MAP-07", "item": "Uji Ulang Masukan Revisi TPA/DLH", "kategori": "6. Revisi Laporan", "status": "Perlu Revisi", "catatan": "Perbaikan Sesuai Catatan Sidang"},
        {"id": "MAP-08", "item": "Penerbitan SKKL & Sync OSS RBA", "kategori": "7. SKKL & SLO", "status": "Belum Dimulai", "catatan": "Menunggu Final SKKL"},
    ],
    "perizinan_penunjang": [
        {"kode": "PERTEK-01", "nama_perizinan": "KKPR / PKKPR (Kesesuaian Tata Ruang)", "jenis": "Prasyarat Usaha", "dasar_hukum": "PP No. 21/2021 & PP No. 5/2021", "persyaratan_dokumen": "1. Peta Poligon Lokasi (SHP)\n2. Bukti Kepemilikan Lahan\n3. Proposal Tapak & NIB", "instansi_penerbit": "ATR / BPN & OSS RBA", "status": "Selesai / Valid"},
        {"kode": "PERTEK-02", "nama_perizinan": "Pertek Pembuangan Air Limbah (BMAL)", "jenis": "Persetujuan Teknis", "dasar_hukum": "Permen LHK No. 5/2021", "persyaratan_dokumen": "1. Kajian Teknis IPAL\n2. Design DED IPAL\n3. Modeling Sebaran Polutan", "instansi_penerbit": "DLH / KLHK", "status": "Sedang Diproses"},
        {"kode": "PERTEK-03", "nama_perizinan": "Pertek Emisi Udara Cerobong", "jenis": "Persetujuan Teknis", "dasar_hukum": "Permen LHK No. 5/2021", "persyaratan_dokumen": "1. Spesifikasi Cerobong\n2. Modeling AERMOD\n3. Sampling Hole Design", "instansi_penerbit": "DLH / KLHK", "status": "Sedang Diproses"},
        {"kode": "PERTEK-04", "nama_perizinan": "Persetujuan Teknis LB3 (Penyimpanan/Pengangkutan)", "jenis": "Persetujuan Teknis", "dasar_hukum": "PP No. 22/2021 & Permen LHK No. 6/2021", "persyaratan_dokumen": "1. Neraca LB3\n2. Desain TPS LB3\n3. Kontrak dengan Pengolah Berizin", "instansi_penerbit": "DLH / KLHK", "status": "Belum Dimulai"},
    ],
    "team_penyusun": [
        {"nama": "Dr. Ir. Ahmad Subagyo, M.Si.", "peran": "Ketua Tim Penyusun (KTPA)", "lisensi": "KTPA-001/KLHK/2024", "kontak": "0812-3456-7890"},
        {"nama": "Dewi Sartika, S.T., M.Sc.", "peran": "Anggota Tim (ATPA) - Fisika Kimia", "lisensi": "ATPA-088/KLHK/2025", "kontak": "0813-9876-5432"},
        {"nama": "Rahmat Hidayat, S.Si.", "peran": "Anggota Tim (ATPA) - Biologi", "lisensi": "ATPA-114/KLHK/2025", "kontak": "0815-2233-4455"},
    ],
    "saved_secondary_data": [
        {"sumber": "BMKG - Stasiun Meteorologi", "judul": "Data Curah Hujan 10 Tahun & Windrose Wilayah", "detail": "Curah Hujan Rata-rata: 2100 mm/tahun, Suhu: 27.5 C, Kecepatan Angin: 3.2 m/s", "kategori": "Iklim & Meteorologi", "tanggal_impor": ts(21, 10, 15)},
        {"sumber": "DLH / SIPSN KLHK", "judul": "Indeks Standar Pencemar Udara (ISPU) & Rona Udara Ambien", "detail": "PM10: 38 ug/Nm3, SO2: 12 ug/Nm3, NO2: 18 ug/Nm3 (Memenuhi Baku Mutu PP 22/2021)", "kategori": "Kualitas Udara & Ambient", "tanggal_impor": ts(20, 13, 5)},
        {"sumber": "Ditjen SDA / BMKG Hidrologi", "judul": "Data Debit Sungai, Neraca Air & Kualitas Air Permukaan", "detail": "Q80: 3.4 m3/detik | BOD: 12 mg/L | TSS: 45 mg/L", "kategori": "Hidrologi & Kualitas Air", "tanggal_impor": ts(18, 9, 40)},
    ],
    "data_dampak": [
        {"tahap": "Konstruksi", "kegiatan": "Mobilisasi Alat Berat & Clean Lahan", "komponen": "Udara & Kebisingan", "dampak": "Peningkatan Kebisingan dan Debu PM10", "status": "DPH", "pertek": "Pertek Emisi Udara", "mitigasi": "Penyiraman jalan 3x sehari dan barikade seng 2m", "lat": -5.3972, "lon": 105.2663},
        {"tahap": "Konstruksi", "kegiatan": "Pekerjaan Pondasi & Batching Plant", "komponen": "Air Permukaan", "dampak": "Peningkatan TSS pada saluran drainase", "status": "DPH", "pertek": "Pertek BMAL", "mitigasi": "Sediment trap 3 kompartemen + pengendapan sebelum dibuang", "lat": -5.4021, "lon": 105.2735},
        {"tahap": "Operasi", "kegiatan": "Pembakaran Klin (Rotary Kiln)", "komponen": "Udara Ambien", "dampak": "Emisi debu, SO2, dan NO2 dari cerobong utama", "status": "DPH", "pertek": "Pertek Emisi Udara", "mitigasi": "Baghouse filter + ESP, CEMS online, cerobong 45 m", "lat": -5.3945, "lon": 105.2611},
        {"tahap": "Operasi", "kegiatan": "Angkutan Bahan Baku & Produk", "komponen": "Sosial Ekonomi", "dampak": "Kerusakan jalan desa & konflik lalu lintas warga", "status": "DPH", "pertek": "-", "mitigasi": "Pembatasan jam angkut 06.00-18.00, perbaikan jalan, CSR", "lat": -5.3888, "lon": 105.2540},
        {"tahap": "Pasca-Operasi", "kegiatan": "Reklamasi Bekas Tambang Batu Kapur", "komponen": "Biologi & Landscape", "dampak": "Perubahan tutupan lahan dan habitat", "status": "DPH", "pertek": "-", "mitigasi": "Revegetasi bertahap 5 Ha/tahun dengan spesies lokal", "lat": -5.4102, "lon": 105.2801},
    ],
    "data_sptm": [
        {"tanggal": (now - timedelta(days=30)).strftime("%Y-%m-%d"), "metode": "Konsultasi Publik", "lokasi": "Balai Desa Sukamaju", "jumlah_peserta": 128, "pimpinan": "Camat Katibung / Notulis: DLH Kab.", "status": "Selesai / Valid", "catatan": "Warga meminta jaminan perbaikan jalan desa dan prioritas tenaga kerja lokal."},
        {"tanggal": (now - timedelta(days=24)).strftime("%Y-%m-%d"), "metode": "Pengumuman Media & Web", "lokasi": "Media lokal + laman DLH Provinsi", "jumlah_peserta": 0, "pimpinan": "Humas Pemrakarsa", "status": "Selesai / Valid", "catatan": "Pengumuman 10 hari kerja, tidak ada keberatan tertulis yang masuk."},
    ],
    "revisi_history": [
        {"tanggal": ts(9, 14, 20), "sumber": "Tim TPA Pusat / KLHK", "bab": "Bab IV - Pelingkupan Dampak (DPH & Mitigasi)", "catatan": "Tambahkan analisis modeling dispersi debu PM10 untuk kondisi musim kemarau beserta skenario kecepatan angin maksimum.", "teks_sebelum": "Penyiraman jalan dilakukan 1x sehari.", "teks_sesudah": "Penyiraman jalan ditingkatkan menjadi 3x sehari dan ditambah water spraying di area crusher serta stockpile.", "status_verifikasi": "COMPLETED / VERIFIED", "berkas_sumber": ""},
        {"tanggal": ts(5, 10, 5), "sumber": "DLH Provinsi / Kab-Kota", "bab": "Bab III - Persetujuan Teknis (Pertek Air/Udara/B3)", "catatan": "Lampirkan DED IPAL terbaru dan hasil uji debit air limbah 3 bulan terakhir sebelum Pertek BMAL diajukan.", "teks_sebelum": "Kajian teknis IPAL menggunakan desain lama kapasitas 120 m3/hari.", "teks_sesudah": "Kajian teknis IPAL diperbarui ke desain kapasitas 180 m3/hari dilengkapi hasil uji debit 3 bulan.", "status_verifikasi": "IN PROGRESS", "berkas_sumber": ""},
    ],
    "masukan_tpa": [
        {"tanggal": ts(9, 14, 20), "sumber": "Tim TPA Pusat / KLHK — Prof. Dr. Ir. Wijaya, M.Sc.", "bab": "Bab IV - Pelingkupan Dampak (DPH & Mitigasi)", "catatan": "[Perbaikan Wajib (Must Fix)] Tambahkan analisis modeling dispersi debu PM10 untuk kondisi musim kemarau.", "teks_sebelum": "(belum diubah)", "teks_sesudah": "(menunggu tindak lanjut penyusun)", "status_verifikasi": "COMPLETED / VERIFIED"},
    ],
    "masalah_dokumen": [],
    "uploaded_file_list": [],
    "skkl_log": [],
    "last_saved": now.strftime("%Y-%m-%d %H:%M:%S"),
}

target = os.path.join(PROJECTS_DIR, f"{demo['project_id']}.json")
with open(target, "w", encoding="utf-8") as f:
    json.dump(demo, f, indent=2, ensure_ascii=False)
print(f"Proyek demo dibuat: {target}")
print(f"  ID       : {demo['project_id']}")
print(f"  Password : {demo['project_password']}")
