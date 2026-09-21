"""
================================================================================
 DR Martin Amdal System v8.0 - Document Report & Revision Engine
 System Architect & Penulis : DR. Leo Martin
================================================================================
 Aplikasi Streamlit pengelolaan penyusunan dokumen AMDAL / UKL-UPL / SPPL
 terintegrasi alur OSS RBA & Amdalnet.

 Dijalankan dengan:
     streamlit run app.py --server.address 0.0.0.0 --server.port 8501
================================================================================
"""

import functools
import io
import json
import math
import os
import re
from datetime import datetime

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from folium.plugins import Fullscreen, MarkerCluster
from streamlit_folium import st_folium

# Graphviz dipakai untuk render diagram alur Master Map (opsional / degrade aman)
try:
    import graphviz

    HAS_GRAPHVIZ = True
except Exception:  # pragma: no cover
    HAS_GRAPHVIZ = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# 1. KONFIGURASI HALAMAN
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="DR Martin Amdal System v8.0 - Document Report & Revision Engine",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# 2. DIREKTORI PENYIMPANAN PROYEK, ATTACHMENTS & REVISIONS
# --------------------------------------------------------------------------- #
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
ATTACHMENTS_DIR = os.path.join(PROJECTS_DIR, "attachments")
REVISIONS_DIR = os.path.join(PROJECTS_DIR, "revisions")
REPORTS_DIR = os.path.join(PROJECTS_DIR, "reports")

for _folder in (PROJECTS_DIR, ATTACHMENTS_DIR, REVISIONS_DIR, REPORTS_DIR):
    os.makedirs(_folder, exist_ok=True)


def _bootstrap_demo_project() -> None:
    """Seed satu proyek contoh HANYA jika folder projects/ masih kosong.

    Penting untuk deploy (mis. Streamlit Community Cloud) yang menjalankan
    ``streamlit run app.py`` langsung tanpa run.sh, sehingga pengunjung
    pertama langsung bisa login dengan proyek demo (password: 123).
    """
    try:
        if any(f.endswith(".json") for f in os.listdir(PROJECTS_DIR)):
            return
        _kandidat_seed = (
            os.path.join(BASE_DIR, "scripts", "seed_demo_project.py"),
            os.path.join(BASE_DIR, "seed_demo_project.py"),  # repo flat (upload web)
        )
        _seed = next((p for p in _kandidat_seed if os.path.exists(p)), None)
        if _seed:
            import subprocess
            import sys

            subprocess.run(
                [sys.executable, _seed],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


_bootstrap_demo_project()

STATUS_OPTIONS = ["Selesai / Valid", "Sedang Diproses", "Perlu Revisi", "Belum Dimulai"]
STATUS_WEIGHTS = {"Selesai / Valid": 100, "Sedang Diproses": 50, "Perlu Revisi": 25, "Belum Dimulai": 0}
STATUS_COLORS = {
    "Selesai / Valid": "#1f9d55",
    "Sedang Diproses": "#2f6fd0",
    "Perlu Revisi": "#e08a00",
    "Belum Dimulai": "#8a8f98",
}

# --------------------------------------------------------------------------- #
# 3. UTILITAS: SANITASI DATA (NaN / numpy / tanggal -> JSON-safe)
# --------------------------------------------------------------------------- #
def sanitize(obj):
    """Ubah objek apa pun menjadi struktur yang aman untuk json.dump."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, int):
        return obj
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return sanitize(obj.to_dict("records"))
    if hasattr(obj, "item"):  # numpy scalar
        try:
            return sanitize(obj.item())
        except Exception:
            return str(obj)
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return str(obj)


def clean_records(df):
    """DataFrame hasil st.data_editor -> list[dict] tanpa NaN/NaT."""
    if df is None or len(df) == 0:
        return []
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or str(df[col].dtype) == "string":
            df[col] = df[col].where(df[col].notna(), "")
    return sanitize(df.to_dict("records"))


def slugify(text, maxlen=28):
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return (text or "proyek")[:maxlen]


def safe_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name))[:120] or "file"


def now_str(fmt="%Y-%m-%d %H:%M"):
    return datetime.now().strftime(fmt)


# --------------------------------------------------------------------------- #
# 3b. FLASH MESSAGE (tahan st.rerun, unlike st.success yang ikut terhapus)
# --------------------------------------------------------------------------- #
def flash(kind, text):
    """Antrekan notifikasi yang baru dirender pada siklus script berikutnya."""
    st.session_state.setdefault("_flash", []).append((kind, text))


def render_flash():
    """Tampilkan & kosongkan antrean notifikasi (dipanggil di awal setiap run)."""
    for kind, text in st.session_state.pop("_flash", []):
        getattr(st, kind)(text)
        try:
            st.toast(text[:90], icon={"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(kind, "🌿"))
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 4. MANAJEMEN BERKAS PROYEK
# --------------------------------------------------------------------------- #
def list_projects():
    """Daftar seluruh berkas proyek (.json) di folder projects/."""
    if not os.path.isdir(PROJECTS_DIR):
        return []
    return sorted(f for f in os.listdir(PROJECTS_DIR) if f.endswith(".json"))


def project_path(project_id):
    return os.path.join(PROJECTS_DIR, f"{safe_filename(project_id)}.json")


def save_project_to_file(data):
    """Simpan data proyek aktif ke berkas JSON di folder projects/."""
    filepath = project_path(data["project_id"])
    payload = sanitize(data)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False, default=str)
    return filepath


def load_project_from_file(filename):
    """Muat data proyek dari berkas JSON di folder projects/."""
    filepath = filename if os.path.isabs(filename) else os.path.join(PROJECTS_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_project_file(filename):
    filepath = os.path.join(PROJECTS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False


def attachment_dir_for(project_id):
    folder = os.path.join(ATTACHMENTS_DIR, slugify(project_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def collect_session_payload():
    """Kumpulkan seluruh state proyek menjadi satu dict siap simpan."""
    s = st.session_state
    return {
        "project_id": s.current_project_id,
        "nama_proyek": s.nama_proyek,
        "pemrakarsa": s.pemrakarsa,
        "kbli": s.kbli,
        "luas_lahan": s.luas_lahan,
        "pic_project": s.pic_project,
        "project_password": s.project_password,
        "nib_oss": s.nib_oss,
        "id_oss_project": s.id_oss_project,
        "lokasi_proyek": s.get("lokasi_proyek", ""),
        "lat_proyek": s.get("lat_proyek", -5.3972),
        "lon_proyek": s.get("lon_proyek", 105.2663),
        "item_checks": s.item_checks,
        "perizinan_penunjang": s.perizinan_penunjang,
        "team_penyusun": s.team_penyusun,
        "uploaded_file_list": s.uploaded_file_list,
        "saved_secondary_data": s.saved_secondary_data,
        "data_dampak": s.data_dampak,
        "data_sptm": s.data_sptm,
        "revisi_history": s.revisi_history,
        "masukan_tpa": s.get("masukan_tpa", []),
        "masalah_dokumen": s.get("masalah_dokumen", []),
        "skkl_log": s.get("skkl_log", []),
        "last_saved": now_str("%Y-%m-%d %H:%M:%S"),
    }


# --------------------------------------------------------------------------- #
# 5. LOGIKA BISNIS: PROGRES, PENAPISAN OSS RBA
# --------------------------------------------------------------------------- #
def calculate_item_progress(item_checks):
    """Persentase kelengkapan berdasarkan bobot status per item."""
    if not item_checks:
        return 0.0
    total = sum(STATUS_WEIGHTS.get(str(i.get("status", "")).strip(), 0) for i in item_checks)
    return round(total / len(item_checks), 1)


def run_oss_risk_screening(kbli, luas_ha):
    """Penapisan otomatis risiko OSS RBA (PP 5/2021 & Permen LHK 4/2021)."""
    try:
        luas_ha = float(luas_ha)
    except (TypeError, ValueError):
        luas_ha = 0.0

    if luas_ha >= 50.0:
        return {
            "tingkat_risiko": "Risiko Tinggi (RT)",
            "dokumen_wajib": "AMDAL (Surat Keputusan Kelayakan Lingkungan - SKKL)",
            "keterangan": "Luas lahan >= 50 Ha termasuk kegiatan berdampak penting luas, wajib AMDAL.",
            "status_oss": "Wajib Perizinan Berusaha Izin (Amdalnet Approval)",
            "jangka_waktu": "Penilaian KA-ANDAL 30 HK + ANDAL/RKL-RPL 75 HK",
            "kewenangan": "Komisi Penilai AMDAL (KPA) Pusat / Provinsi sesuai kewenangan",
            "kode_emoji": "🔴",
        }
    if luas_ha >= 5.0:
        return {
            "tingkat_risiko": "Risiko Menengah Tinggi (RMT)",
            "dokumen_wajib": "UKL-UPL (Persetujuan Pernyataan Kesanggupan - PKPL)",
            "keterangan": "Luas lahan 5 Ha - <50 Ha wajib dokumen UKL-UPL Standar.",
            "status_oss": "Wajib Perizinan Berusaha Sertifikat Standar Terverifikasi",
            "jangka_waktu": "Verifikasi UKL-UPL maksimal 10 HK",
            "kewenangan": "DLH Provinsi / Kabupaten-Kota",
            "kode_emoji": "🟠",
        }
    return {
        "tingkat_risiko": "Risiko Menengah Rendah / Rendah (RMR/RR)",
        "dokumen_wajib": "SPPL (Surat Pernyataan Kesanggupan Pengelolaan Lingkungan)",
        "keterangan": "Skala usaha mikro/kecil, integrasi otomatis NIB + SPPL di OSS RBA.",
        "status_oss": "NIB Berlaku sebagai Perizinan Berusaha & SPPL Auto-Approved",
        "jangka_waktu": "Otomatis saat penerbitan NIB (0 HK)",
        "kewenangan": "OSS RBA (auto-approval)",
        "kode_emoji": "🟢",
    }


def html_workflow_diagram(df_cat, cat_order):
    """Diagram alur Master Map murni HTML/CSS (fallback tanpa binari graphviz)."""
    cards = []
    for cat in cat_order:
        sub = df_cat[df_cat["kategori"] == cat]
        done = int((sub["status"] == "Selesai / Valid").sum())
        proc = int((sub["status"] == "Sedang Diproses").sum())
        rev = int((sub["status"] == "Perlu Revisi").sum())
        belum = int((sub["status"] == "Belum Dimulai").sum())
        pct = calculate_item_progress(sub.to_dict("records"))
        accent = "#1f9d55" if (proc == 0 and rev == 0 and belum == 0) else ("#e08a00" if (proc or rev) else "#8a8f98")
        cards.append(
            f"""<div style="flex:1 1 150px;min-width:150px;border:1px solid #d8dee7;border-left:4px solid {accent};
                 border-radius:8px;padding:10px 12px;background:#fff;">
                  <div style="font-size:12px;font-weight:700;color:#1b2430;">{cat}</div>
                  <div style="font-size:11px;color:#5b6b7f;margin-top:2px;">{len(sub)} item &middot; {pct}%</div>
                  <div style="font-size:11px;margin-top:6px;">&#9989;{done} &#128260;{proc} &#9888;&#65039;{rev} &#9203;{belum}</div>
                  <div style="height:5px;border-radius:3px;background:#eef1f5;margin-top:7px;">
                    <div style="height:5px;border-radius:3px;width:{pct}%;background:{accent};"></div>
                  </div>
                </div>"""
        )
    arrow = '<div style="align-self:center;color:#5b6b7f;font-size:18px;padding:0 4px;">&#10132;</div>'
    body = arrow.join(cards)
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:stretch;padding:6px 0;">'
        f"{body}</div>"
    )


def extract_uploaded_text(uploaded_file):
    """Ekstrak teks dari berkas catatan perbaikan (TXT/MD/CSV/DOCX/PDF)."""
    name = (uploaded_file.name or "").lower()
    raw = uploaded_file.getvalue()
    try:
        if name.endswith((".txt", ".md", ".csv", ".log")):
            return raw.decode("utf-8", errors="replace")
        if name.endswith(".docx"):
            try:
                import docx  # python-docx (opsional)

                return "\n".join(p.text for p in docx.Document(io.BytesIO(raw)).paragraphs)
            except ImportError:
                return "[Berkas .docx terunggah - pasang `python-docx` untuk ekstraksi otomatis teks]"
        if name.endswith(".pdf"):
            for mod in ("pypdf", "PyPDF2", "fitz"):
                try:
                    if mod == "fitz":
                        import fitz

                        doc = fitz.open(stream=raw, filetype="pdf")
                        return "\n".join(page.get_text() for page in doc)
                    mod_obj = __import__(mod)
                    reader = mod_obj.PdfReader(io.BytesIO(raw))
                    return "\n".join((page.extract_text() or "") for page in reader.pages)
                except ImportError:
                    continue
                except Exception:
                    continue
            return "[Berkas PDF terunggah - pasang `pypdf` untuk ekstraksi otomatis teks]"
    except Exception as exc:  # pragma: no cover
        return f"[Gagal membaca isi berkas: {exc}]"
    return "[Format berkas tidak mendukung ekstraksi teks otomatis]"


# --------------------------------------------------------------------------- #
# 6. GENERATOR DOKUMEN LAPORAN
# --------------------------------------------------------------------------- #
def generate_full_report_text():
    """Laporan AMDAL & RKL-RPL menyeluruh (full report)."""
    p = st.session_state
    oss_info = run_oss_risk_screening(p.kbli, p.luas_lahan)
    progress = calculate_item_progress(p.item_checks)
    ktpa = p.team_penyusun[0]["nama"] if p.team_penyusun else "N/A"
    bar = "=" * 88
    line = "-" * 88

    text = f"""{bar}
          DOKUMEN LAPORAN AMDAL & RKL-RPL TERINTEGRASI OSS RBA & AMDALNET
{bar}
TANGGAL CETAK   : {now_str('%d %B %Y %H:%M:%S')}
ID PROYEK       : {p.current_project_id}
NAMA KEGIATAN   : {p.nama_proyek}
PEMRAKARSA      : {p.pemrakarsa}
NIB OSS RBA     : {p.nib_oss}
ID OSS PROYEK   : {p.id_oss_project}
KBLI            : {p.kbli} | LUAS LAHAN: {p.luas_lahan} Ha
LOKASI          : {p.get('lokasi_proyek') or '-'} ({p.get('lat_proyek', '-')}, {p.get('lon_proyek', '-')})
PIC PROYEK      : {p.pic_project}
KETUA TIM (KTPA): {ktpa}
PROGRES MAP     : {progress}%
{line}

BAB I. PENDAHULUAN & PENAPISAN OSS RBA
1.1 Latar Belakang Rencana Kegiatan
    Rencana usaha {p.nama_proyek} oleh {p.pemrakarsa} berlokasi dengan luas {p.luas_lahan} Ha.
1.2 Hasil Penapisan Risiko OSS RBA (PP 5/2021 & Permen LHK 4/2021)
    - Tingkat Risiko : {oss_info['tingkat_risiko']}
    - Dokumen Wajib  : {oss_info['dokumen_wajib']}
    - Status Sistem  : {oss_info['status_oss']}
    - Jangka Waktu   : {oss_info['jangka_waktu']}
    - Kewenangan     : {oss_info['kewenangan']}

BAB II. PERMITTING & PERIZINAN PENUNJANG (PERTEK)
2.1 Status Persetujuan Teknis & Prasyarat
"""
    if p.perizinan_penunjang:
        for per in p.perizinan_penunjang:
            text += (
                f"    - [{per.get('kode','-')}] {per.get('nama_perizinan','-')}: "
                f"Status ({per.get('status','-')}) - Instansi ({per.get('instansi_penerbit','-')})\n"
            )
            if per.get("dasar_hukum"):
                text += f"      Dasar Hukum: {per['dasar_hukum']}\n"
    else:
        text += "    - Belum ada data perizinan penunjang.\n"

    text += f"""
BAB III. RONA LINGKUNGAN HIDUP AWAL (DATA SEKUNDER & PRIMER)
3.1 Data Sekunder Terintegrasi:
"""
    if p.saved_secondary_data:
        for sec in p.saved_secondary_data:
            text += f"    - {sec.get('sumber','-')}: {sec.get('judul','-')} ({sec.get('detail','')})\n"
    else:
        text += "    - Belum ada data sekunder yang diimpor ke DB proyek.\n"

    text += "\nBAB IV. PELINGKUPAN DAMPAK PENTING HIPOTETIS (DPH)\n"
    if p.data_dampak:
        for d in p.data_dampak:
            text += (
                f"    - Tahap {d.get('tahap','-')} | Kegiatan: {d.get('kegiatan','-')} | "
                f"Komponen: {d.get('komponen','-')}\n"
                f"      Dampak  : {d.get('dampak','-')} [{d.get('status','-')}]\n"
                f"      Mitigasi: {d.get('mitigasi','-')}\n"
            )
    else:
        text += "    - Belum ada dampak terlingkup.\n"

    text += "\nBAB V. PELIBATAN MASYARAKAT (SPTM / KONSULTASI PUBLIK)\n"
    if p.data_sptm:
        for sp in p.data_sptm:
            text += (
                f"    - {sp.get('tanggal','-')} | {sp.get('metode','-')} | {sp.get('lokasi','-')} | "
                f"Peserta: {sp.get('jumlah_peserta','-')} orang | Status: {sp.get('status','-')}\n"
            )
            if sp.get("catatan"):
                text += f"      Catatan: {sp['catatan']}\n"
    else:
        text += "    - Belum ada kegiatan pelibatan masyarakat tercatat.\n"

    text += "\nBAB VI. MASTER MAP & PROGRES PENYUSUNAN\n"
    for it in p.item_checks:
        text += (
            f"    - [{it.get('id','-')}] {it.get('kategori','-')} | {it.get('item','-')} -> "
            f"{it.get('status','-')} ({STATUS_WEIGHTS.get(str(it.get('status','')).strip(),0)}%)\n"
        )
    text += f"    Total Progres Penyusunan: {progress}%\n"

    text += "\nBAB VII. CATATAN HISTORI REVISI & MASUKAN PERBAIKAN\n"
    if p.revisi_history:
        for idx, rev in enumerate(p.revisi_history, 1):
            text += (
                f"    {idx}. Tanggal: {rev.get('tanggal','-')} | Sumber: {rev.get('sumber','-')} | "
                f"Bab: {rev.get('bab','-')}\n"
                f"       Catatan : {rev.get('catatan','-')}\n"
                f"       Sebelum : {rev.get('teks_sebelum','-')}\n"
                f"       Sesudah : {rev.get('teks_sesudah','-')}\n"
            )
    else:
        text += "    - Belum ada catatan revisi terdaftar.\n"

    text += f"""
{bar}
Diterbitkan Oleh System Architect: DR. Leo Martin (DR Martin Amdal System v8.0)
Dokumen ini adalah draf kerja (draft of record) untuk keperluan internal penyusunan
dan verifikasi Tim Uji Kelayakan, bukan pengganti dokumen legal bertanda tangan basah.
{bar}
"""
    return text


def generate_full_report_markdown():
    """Versi Markdown dari laporan utuh (siap tempel ke Notion/Docs/GitHub)."""
    p = st.session_state
    oss_info = run_oss_risk_screening(p.kbli, p.luas_lahan)
    progress = calculate_item_progress(p.item_checks)
    md = [
        f"# Laporan AMDAL & RKL-RPL — {p.nama_proyek}",
        "",
        f"> **ID Proyek:** `{p.current_project_id}`  ",
        f"> **Pemrakarsa:** {p.pemrakarsa}  ",
        f"> **NIB OSS RBA:** `{p.nib_oss}` | **ID OSS:** `{p.id_oss_project}`  ",
        f"> **KBLI:** {p.kbli} | **Luas Lahan:** {p.luas_lahan} Ha  ",
        f"> **PIC:** {p.pic_project}  ",
        f"> **Dicetak:** {now_str('%d %B %Y %H:%M:%S')}",
        "",
        "## 1. Penapisan Risiko OSS RBA",
        f"- **Tingkat Risiko:** {oss_info['kode_emoji']} {oss_info['tingkat_risiko']}",
        f"- **Dokumen Wajib:** {oss_info['dokumen_wajib']}",
        f"- **Status Sistem:** {oss_info['status_oss']}",
        f"- **Kewenangan:** {oss_info['kewenangan']}",
        "",
        "## 2. Perizinan Penunjang (Pertek)",
        "| Kode | Perizinan | Dasar Hukum | Instansi | Status |",
        "|---|---|---|---|---|",
    ]
    for per in p.perizinan_penunjang:
        md.append(
            f"| {per.get('kode','')} | {per.get('nama_perizinan','')} | {per.get('dasar_hukum','')} "
            f"| {per.get('instansi_penerbit','')} | {per.get('status','')} |"
        )
    md += ["", "## 3. Rona Lingkungan Awal (Data Sekunder)", "| Sumber | Judul | Parameter Kunci |", "|---|---|---|"]
    for sec in p.saved_secondary_data or [{"sumber": "-", "judul": "Belum ada data", "detail": ""}]:
        md.append(f"| {sec.get('sumber','')} | {sec.get('judul','')} | {sec.get('detail','')} |")
    md += ["", "## 4. Pelingkupan DPH", "| Tahap | Kegiatan | Komponen | Dampak | Status | Mitigasi |", "|---|---|---|---|---|---|"]
    for d in p.data_dampak:
        md.append(
            f"| {d.get('tahap','')} | {d.get('kegiatan','')} | {d.get('komponen','')} | {d.get('dampak','')} "
            f"| {d.get('status','')} | {d.get('mitigasi','')} |"
        )
    md += ["", "## 5. Master Map Penyusunan", "| ID | Kategori | Item | Status | Catatan |", "|---|---|---|---|---|"]
    for it in p.item_checks:
        md.append(
            f"| {it.get('id','')} | {it.get('kategori','')} | {it.get('item','')} | {it.get('status','')} | {it.get('catatan','')} |"
        )
    md += ["", f"**Total Progres: {progress}%**", "", "## 6. Histori Revisi"]
    if p.revisi_history:
        md += ["| # | Tanggal | Sumber | Bab | Catatan | Sebelum | Sesudah |", "|---|---|---|---|---|---|---|"]
        for i, rev in enumerate(p.revisi_history, 1):
            md.append(
                f"| {i} | {rev.get('tanggal','')} | {rev.get('sumber','')} | {rev.get('bab','')} "
                f"| {rev.get('catatan','')} | {rev.get('teks_sebelum','')} | {rev.get('teks_sesudah','')} |"
            )
    else:
        md.append("_Belum ada catatan revisi._")
    md += ["", "---", "_Diterbitkan oleh DR Martin Amdal System v8.0 — DR. Leo Martin_"]
    return "\n".join(md)


def generate_delta_report_text():
    """Matriks track-changes: hanya bagian dokumen yang berubah."""
    p = st.session_state
    bar = "=" * 88
    line = "-" * 88
    text = f"""{bar}
           MATRIKS TRACK CHANGES & PERUBAHAN BAGIAN DOKUMEN LAPORAN AMDAL
{bar}
ID PROYEK     : {p.current_project_id} | NAMA: {p.nama_proyek}
PEMRAKARSA    : {p.pemrakarsa} | NIB OSS: {p.nib_oss}
TANGGAL DELTA : {now_str('%d %B %Y %H:%M:%S')}
JUMLAH REVISI : {len(p.revisi_history)} catatan
{line}
Daftar Khusus Bagian/Bab yang Mengalami Perubahan & Penyesuaian Masukan:

"""
    if not p.revisi_history:
        text += "TIDAK ADA PERUBAHAN / BELUM ADA REVISI YANG DIINPUT.\n"
    else:
        for idx, rev in enumerate(p.revisi_history, 1):
            text += f"""--- PERUBAHAN # {idx} ---
• Tanggal Revisi     : {rev.get('tanggal','-')}
• Sumber Masukan     : {rev.get('sumber','-')} (Penguji / DLH / TPA / Warga)
• Bagian/Bab Direvisi: {rev.get('bab','-')}
• Catatan Masukan    : {rev.get('catatan','-')}
• Teks Sebelum       : {rev.get('teks_sebelum','-')}
• Teks Perubahan     : {rev.get('teks_sesudah','-')}
• Status Perbaikan   : {rev.get('status_verifikasi','COMPLETED / VERIFIED')}
{line}
"""
    text += "\nDokumen Delta ini diterbitkan khusus untuk kemudahan verifikasi Tim Uji Kelayakan.\n"
    return text


def generate_skkl_text():
    """Draf Keputusan Kelayakan Lingkungan (SKKL) otomatis."""
    p = st.session_state
    oss_info = run_oss_risk_screening(p.kbli, p.luas_lahan)
    bar = "=" * 88
    return f"""{bar}
                     DRAF - SURAT KEPUTUSAN KELAYAKAN LINGKUNGAN HIDUP (SKKL)
                              (Diterbitkan otomatis oleh DR Martin Amdal System v8.0)
{bar}
Menimbang :
  a. bahwa rencana usaha/kegiatan "{p.nama_proyek}" oleh {p.pemrakarsa}
     dengan luas lahan {p.luas_lahan} Ha tergolong {oss_info['tingkat_risiko']};
  b. bahwa dokumen {oss_info['dokumen_wajib']} telah dinilai oleh Komisi Penilai
     AMDAL dan seluruh masukan perbaikan ({len(p.revisi_history)} catatan revisi)
     telah ditindaklanjuti;
  c. bahwa berdasarkan pertimbangan a dan b perlu ditetapkan Keputusan Kelayakan
     Lingkungan Hidup.

Mengingat :
  1. Undang-Undang No. 32 Tahun 2009 tentang PPLH;
  2. Peraturan Pemerintah No. 22 Tahun 2021;
  3. Peraturan Pemerintah No. 5 Tahun 2021 (OSS RBA);
  4. Permen LHK No. 4 Tahun 2021 & No. 5 Tahun 2021;
  5. NIB Pemrakarsa: {p.nib_oss} | ID Proyek OSS: {p.id_oss_project} | KBLI: {p.kbli}.

MEMUTUSKAN
KESATU  : Menyatakan rencana usaha/kegiatan {p.nama_proyek} LAYAK LINGKUNGAN.
KEDUA   : Pemrakarsa wajib melaksanakan seluruh pengelolaan & pemantauan pada
          matriks RKL-RPL ({len(p.data_dampak)} dampak terlingkup).
KETIGA  : Pemrakarsa wajib memiliki Persetujuan Teknis:
{chr(10).join('          - [' + str(x.get('kode','')) + '] ' + str(x.get('nama_perizinan','')) + ' (' + str(x.get('status','')) + ')' for x in p.perizinan_penunjang) or '          - (tidak ada)'}
KEEMPAT : Keputusan ini berlaku sejak tanggal ditetapkan dan menjadi prasyarat
          penerbitan Perizinan Berusaha melalui OSS RBA serta SLO.
KELIMA  : Penanggung jawab pelaksanaan: {p.pic_project} | Ketua Tim Penyusun:
          {p.team_penyusun[0]['nama'] if p.team_penyusun else 'N/A'}.

Ditetapkan di : {p.get('lokasi_proyek') or '....................'}
Tanggal       : {now_str('%d %B %Y')}
Progres Map   : {calculate_item_progress(p.item_checks)}%
{bar}
"""


# --------------------------------------------------------------------------- #
# 7. DATABASE KATALOG DATA SEKUNDER INTERNET
# --------------------------------------------------------------------------- #
PUBLIC_SECONDARY_DATA_DB = [
    {
        "id": "SEC-001",
        "sumber": "BMKG - Stasiun Meteorologi",
        "kategori": "Iklim & Meteorologi",
        "judul": "Data Curah Hujan 10 Tahun & Windrose Wilayah",
        "deskripsi": "Data deret waktu curah hujan bulanan, suhu udara, kelembaban, dan arah angin dominan.",
        "url": "https://data.bmkg.go.id/",
        "parameter_key": "Curah Hujan Rata-rata: 2100 mm/tahun, Suhu: 27.5 C, Kecepatan Angin: 3.2 m/s",
        "file_mock": "BMKG_Climate_Data_Baseline.csv",
    },
    {
        "id": "SEC-002",
        "sumber": "DLH / SIPSN KLHK",
        "kategori": "Kualitas Udara & Ambient",
        "judul": "Indeks Standar Pencemar Udara (ISPU) & Rona Udara Ambien",
        "deskripsi": "Baseline konsentrasi debu PM10, PM2.5, SO2, NO2, dan CO dari stasiun pemantau pemda.",
        "url": "https://ispu.menlhk.go.id/",
        "parameter_key": "PM10: 38 ug/Nm3, SO2: 12 ug/Nm3, NO2: 18 ug/Nm3 (Memenuhi Baku Mutu PP 22/2021)",
        "file_mock": "DLH_ISPU_Baseline_Air_Quality.xlsx",
    },
    {
        "id": "SEC-003",
        "sumber": "BPS - Statistik Daerah",
        "kategori": "Sosial Ekonomi Budaya",
        "judul": "Data Demografi, Mata Pencaharian & Pendapatan per Kapita",
        "deskripsi": "Jumlah penduduk, kepadatan, struktur umur, tingkat pengangguran, dan PDRB kecamatan terdampak.",
        "url": "https://www.bps.go.id/",
        "parameter_key": "Penduduk: 42.318 jiwa | Kepadatan: 1.120 jiwa/km2 | UMR wilayah berlaku",
        "file_mock": "BPS_Demografi_Kecamatan.xlsx",
    },
    {
        "id": "SEC-004",
        "sumber": "BIG / Badan Informasi Geospasial",
        "kategori": "Tata Ruang & Lahan",
        "judul": "Peta RBI Skala 1:25.000 & Tutupan Lahan",
        "deskripsi": "Peta dasar rupa bumi, tutupan lahan, kemiringan lereng, dan batas administrasi desa.",
        "url": "https://tanahair.indonesia.go.id/",
        "parameter_key": "Tutupan lahan: 62% kebun campuran, 24% sawah, 14% permukiman",
        "file_mock": "BIG_RBI_25K_TutupanLahan.shp",
    },
    {
        "id": "SEC-005",
        "sumber": "Kementerian ATR/BPN - GISTARU",
        "kategori": "Kesesuaian Tata Ruang (KKPR)",
        "judul": "Peta Rencana Pola Ruang RTRW Kabupaten/Provinsi",
        "deskripsi": "Verifikasi kesesuaian pola ruang lokasi kegiatan terhadap RTRW untuk penerbitan PKKPR.",
        "url": "https://gistaru.atrbpn.go.id/",
        "parameter_key": "Pola ruang: Kawasan Peruntukan Industri (sesuai RTRW)",
        "file_mock": "GISTARU_PolaRuang_RTRW.geojson",
    },
    {
        "id": "SEC-006",
        "sumber": "PUSDATIN KESDA / Dinas Kesehatan",
        "kategori": "Kesehatan Masyarakat",
        "judul": "Profil Kesehatan & Data ISPA Wilayah Kerja Puskesmas",
        "deskripsi": "Baseline angka ISPA, DBD, diare, serta ketersediaan fasilitas kesehatan sekitar lokasi.",
        "url": "https://www.kemkes.go.id/",
        "parameter_key": "ISPA: 214 kasus/tahun | Puskesmas: 3 unit dalam radius 5 km",
        "file_mock": "Dinkes_ProfilKesehatan_ISPA.xlsx",
    },
    {
        "id": "SEC-007",
        "sumber": "Ditjen SDA / BMKG Hidrologi",
        "kategori": "Hidrologi & Kualitas Air",
        "judul": "Data Debit Sungai, Neraca Air & Kualitas Air Permukaan",
        "deskripsi": "Debit andalan (Q80/Q50), tinggi muka air, dan parameter BOD/COD/TSS sungai penerima.",
        "url": "https://sda.pu.go.id/",
        "parameter_key": "Q80: 3.4 m3/detik | BOD: 12 mg/L | TSS: 45 mg/L",
        "file_mock": "SDA_DebitSungai_NeracaAir.csv",
    },
]

# --------------------------------------------------------------------------- #
# 8. MASTER DATABASE PERIZINAN PENUNJANG
# --------------------------------------------------------------------------- #
DEFAULT_PERIZINAN_PENUNJANG = [
    {
        "kode": "PERTEK-01",
        "nama_perizinan": "KKPR / PKKPR (Kesesuaian Tata Ruang)",
        "jenis": "Prasyarat Usaha",
        "dasar_hukum": "PP No. 21/2021 & PP No. 5/2021",
        "persyaratan_dokumen": "1. Peta Poligon Lokasi (SHP)\n2. Bukti Kepemilikan Lahan\n3. Proposal Tapak & NIB",
        "instansi_penerbit": "ATR / BPN & OSS RBA",
        "status": "Selesai / Valid",
    },
    {
        "kode": "PERTEK-02",
        "nama_perizinan": "Pertek Pembuangan Air Limbah (BMAL)",
        "jenis": "Persetujuan Teknis",
        "dasar_hukum": "Permen LHK No. 5/2021",
        "persyaratan_dokumen": "1. Kajian Teknis IPAL\n2. Design DED IPAL\n3. Modeling Sebaran Polutan",
        "instansi_penerbit": "DLH / KLHK",
        "status": "Sedang Diproses",
    },
    {
        "kode": "PERTEK-03",
        "nama_perizinan": "Pertek Emisi Udara Cerobong",
        "jenis": "Persetujuan Teknis",
        "dasar_hukum": "Permen LHK No. 5/2021",
        "persyaratan_dokumen": "1. Spesifikasi Cerobong\n2. Modeling AERMOD\n3. Sampling Hole Design",
        "instansi_penerbit": "DLH / KLHK",
        "status": "Sedang Diproses",
    },
    {
        "kode": "PERTEK-04",
        "nama_perizinan": "Persetujuan Teknis LB3 (Penyimpanan/Pengangkutan)",
        "jenis": "Persetujuan Teknis",
        "dasar_hukum": "PP No. 22/2021 & Permen LHK No. 6/2021",
        "persyaratan_dokumen": "1. Neraca LB3\n2. Desain TPS LB3\n3. Kontrak dengan Pengolah Berizin",
        "instansi_penerbit": "DLH / KLHK",
        "status": "Belum Dimulai",
    },
]

DEFAULT_ITEM_CHECKS = [
    {"id": "MAP-01", "item": "KKPR / PKKPR & Legalitas Lahan", "kategori": "1. Prasyarat OSS", "status": "Selesai / Valid", "catatan": "Kesesuaian Tata Ruang Disetujui"},
    {"id": "MAP-02", "item": "Penapisan Amdalnet & Sinkron NIB", "kategori": "1. Prasyarat OSS", "status": "Selesai / Valid", "catatan": "Terverifikasi Wajib AMDAL (Risiko Tinggi)"},
    {"id": "MAP-03", "item": "Pengumpulan Data Sekunder", "kategori": "2. Rona Awal", "status": "Selesai / Valid", "catatan": "Data BMKG & ISPU Terintegrasi"},
    {"id": "MAP-04", "item": "Penyusunan Form KA-ANDAL & DPH", "kategori": "3. Pelingkupan", "status": "Selesai / Valid", "catatan": "Pelingkupan DPH Fix"},
    {"id": "MAP-05", "item": "Pemenuhan Pertek BMAL & Cerobong", "kategori": "4. Pertek Penunjang", "status": "Sedang Diproses", "catatan": "Dalam Evaluasi DLH"},
    {"id": "MAP-06", "item": "Penyusunan Dokumen Laporan Utuh", "kategori": "5. Laporan AMDAL", "status": "Sedang Diproses", "catatan": "Draft Bab I - V Terkompilasi"},
    {"id": "MAP-07", "item": "Uji Ulang Masukan Revisi TPA/DLH", "kategori": "6. Revisi Laporan", "status": "Sedang Diproses", "catatan": "Perbaikan Sesuai Catatan Sidang"},
    {"id": "MAP-08", "item": "Penerbitan SKKL & Sync OSS RBA", "kategori": "7. SKKL & SLO", "status": "Belum Dimulai", "catatan": "Menunggu Final SKKL"},
]

DEFAULT_TEAM = [
    {"nama": "Dr. Ir. Ahmad Subagyo, M.Si.", "peran": "Ketua Tim Penyusun (KTPA)", "lisensi": "KTPA-001/KLHK/2024", "kontak": "0812-3456-7890"},
    {"nama": "Dewi Sartika, S.T., M.Sc.", "peran": "Anggota Tim (ATPA) - Fisika Kimia", "lisensi": "ATPA-088/KLHK/2025", "kontak": "0813-9876-5432"},
]

DEFAULT_DAMPAK = [
    {
        "tahap": "Konstruksi",
        "kegiatan": "Mobilisasi Alat Berat & Clean Lahan",
        "komponen": "Udara & Kebisingan",
        "dampak": "Peningkatan Kebisingan dan Debu PM10",
        "status": "DPH",
        "pertek": "Pertek Emisi Udara",
        "mitigasi": "Penyiraman jalan 2x sehari dan barikade seng 2m",
        "lat": -5.3972,
        "lon": 105.2663,
    }
]


# --------------------------------------------------------------------------- #
# 9. INITIALISATION SESSION STATE
# --------------------------------------------------------------------------- #
def init_default_session(
    project_id="PRJ-2026-001",
    nama="Pembangunan Pabrik Semen",
    pemrakarsa="PT. Usaha Bersama",
    kbli="23940",
    luas=55.0,
    pic="Ir. Hendra Kusuma, M.T.",
    password="123",
    nib="1289000123456",
    id_oss="OSS-2026-9988123",
    lokasi="Kabupaten Lampung Selatan, Provinsi Lampung",
    lat=-5.3972,
    lon=105.2663,
):
    s = st.session_state
    s.current_project_id = project_id
    s.nama_proyek = nama
    s.pemrakarsa = pemrakarsa
    s.kbli = kbli
    s.luas_lahan = float(luas or 0)
    s.pic_project = pic
    s.project_password = password
    s.nib_oss = nib
    s.id_oss_project = id_oss
    s.lokasi_proyek = lokasi
    s.lat_proyek = float(lat or 0)
    s.lon_proyek = float(lon or 0)

    s.saved_secondary_data = []
    s.perizinan_penunjang = [dict(x) for x in DEFAULT_PERIZINAN_PENUNJANG]
    s.revisi_history = []
    s.item_checks = [dict(x) for x in DEFAULT_ITEM_CHECKS]
    s.team_penyusun = [dict(x) for x in DEFAULT_TEAM]
    s.uploaded_file_list = []
    s.data_dampak = [dict(x) for x in DEFAULT_DAMPAK]
    s.masalah_dokumen = []
    s.data_sptm = []
    s.masukan_tpa = []
    s.skkl_log = []
    s.project_loaded_from_file = None


def apply_loaded_project(pdata, filename):
    """Muat dict proyek dari JSON ke session state dengan fallback aman."""
    s = st.session_state
    s.current_project_id = pdata.get("project_id") or os.path.splitext(filename)[0]
    s.nama_proyek = pdata.get("nama_proyek", "")
    s.pemrakarsa = pdata.get("pemrakarsa", "")
    s.kbli = pdata.get("kbli", "")
    try:
        s.luas_lahan = float(pdata.get("luas_lahan", 0) or 0)
    except (TypeError, ValueError):
        s.luas_lahan = 0.0
    s.pic_project = pdata.get("pic_project", "N/A")
    s.project_password = pdata.get("project_password", "")
    s.nib_oss = pdata.get("nib_oss", "-")
    s.id_oss_project = pdata.get("id_oss_project", "-")
    s.lokasi_proyek = pdata.get("lokasi_proyek", "")
    try:
        s.lat_proyek = float(pdata.get("lat_proyek", -5.3972))
        s.lon_proyek = float(pdata.get("lon_proyek", 105.2663))
    except (TypeError, ValueError):
        s.lat_proyek, s.lon_proyek = -5.3972, 105.2663
    s.item_checks = pdata.get("item_checks") or [dict(x) for x in DEFAULT_ITEM_CHECKS]
    s.perizinan_penunjang = pdata.get("perizinan_penunjang") or [dict(x) for x in DEFAULT_PERIZINAN_PENUNJANG]
    s.team_penyusun = pdata.get("team_penyusun") or []
    s.uploaded_file_list = pdata.get("uploaded_file_list") or []
    s.saved_secondary_data = pdata.get("saved_secondary_data") or []
    s.data_dampak = pdata.get("data_dampak") or []
    s.data_sptm = pdata.get("data_sptm") or []
    s.revisi_history = pdata.get("revisi_history") or []
    s.masalah_dokumen = pdata.get("masalah_dokumen") or []
    s.masukan_tpa = pdata.get("masukan_tpa") or []
    s.skkl_log = pdata.get("skkl_log") or []
    s.project_loaded_from_file = filename


if "current_project_id" not in st.session_state:
    init_default_session()

# --------------------------------------------------------------------------- #
# 9b. CALLBACK AKSI
#     Callback Streamlit dieksekusi SEBELUM badan script, sehingga seluruh
#     widget langsung ter-render ulang dengan data terbaru tanpa st.rerun()
#     (yang akan membuang semua output, termasuk pesan sukses).
#     PENTING: nilai widget dibaca dari st.session_state[key], BUKAN dari args,
#     karena args di-snapshot pada render sebelumnya.
# --------------------------------------------------------------------------- #
_MISSING = object()


def safe_callback(fn):
    """Bungkus callback widget: kegagalan diproses jadi pesan error, bukan
    memutus seluruh render halaman (tab lain tetap tampil)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - jalur pengaman
            flash("error", f"⚠️ Aksi gagal dijalankan ({type(exc).__name__}): {exc}")

    return wrapper


def wval(key, default=None):
    """Ambil nilai widget terbaru dari session state (dipakai di dalam callback)."""
    val = st.session_state.get(key, _MISSING)
    if val is _MISSING or val is None:
        return default
    return val


def cb_open_project():
    """Buka proyek terproteksi password dari folder projects/."""
    filename = wval("select_project_file", "-- Pilih Proyek --")
    password = wval("pass_check_input", "")
    if not filename or filename == "-- Pilih Proyek --":
        flash("warning", "Pilih salah satu berkas proyek terlebih dahulu.")
        return
    try:
        pdata = load_project_from_file(filename)
    except Exception as exc:
        flash("error", f"Berkas proyek gagal dibaca: {exc}")
        return
    if password == pdata.get("project_password", ""):
        apply_loaded_project(pdata, filename)
        flash("success", f"🔓 Proyek `{filename}` berhasil dimuat!")
    else:
        flash("error", "❌ Password Salah! Proyek tidak dimuat.")


def cb_delete_project():
    """Hapus berkas JSON proyek (attachment & revisi tetap tersimpan di disk)."""
    filename = wval("del_target")
    if filename and delete_project_file(filename):
        flash("success", f"🗑️ Berkas proyek `{filename}` dihapus.")
    else:
        flash("error", "Berkas proyek tidak ditemukan.")


def cb_register_project():
    """Registrasi proyek baru sekaligus menyimpan berkas JSON-nya."""
    prj_id = str(wval("new_prj_id", "")).strip()
    if not prj_id:
        flash("error", "ID Proyek wajib diisi.")
        return
    if os.path.exists(project_path(prj_id)):
        flash("error", f"ID `{prj_id}` sudah ada. Gunakan ID lain atau buka proyek tersebut.")
        return
    init_default_session(
        prj_id,
        wval("new_nama", ""),
        wval("new_pemrakarsa", ""),
        wval("new_kbli", ""),
        float(wval("new_luas", 0) or 0),
        wval("new_pic", ""),
        wval("new_pass", ""),
        wval("new_nib", ""),
        wval("new_id_oss", ""),
        wval("new_lokasi", ""),
        float(wval("new_lat", 0) or 0),
        float(wval("new_lon", 0) or 0),
    )
    path = save_project_to_file(collect_session_payload())
    flash("success", f"✨ Proyek baru `{prj_id}` terdaftar & tersimpan: `{os.path.basename(path)}`")


def cb_save_project():
    """Simpan seluruh data proyek aktif ke folder projects/."""
    path = save_project_to_file(collect_session_payload())
    flash("success", f"💾 Proyek tersimpan di: `{path}`")


def _editor_records(key, fallback):
    """Ambil isi st.data_editor (berdasarkan key) sebagai list[dict] bersih."""
    df = st.session_state.get(key)
    if isinstance(df, pd.DataFrame):
        return clean_records(df)
    return fallback


def cb_apply_master_map():
    st.session_state.item_checks = _editor_records("editor_master_map", st.session_state.item_checks)
    flash("success", "🗺️ Master Map berhasil diperbarui!")


def cb_reset_master_map():
    st.session_state.item_checks = [dict(x) for x in DEFAULT_ITEM_CHECKS]
    flash("info", "♻️ Master Map dikembalikan ke template default.")


def cb_apply_perizinan():
    st.session_state.perizinan_penunjang = _editor_records("editor_perizinan", st.session_state.perizinan_penunjang)
    flash("success", "📜 Matriks perizinan tersimpan ke sesi proyek!")


def cb_reset_perizinan():
    st.session_state.perizinan_penunjang = [dict(x) for x in DEFAULT_PERIZINAN_PENUNJANG]
    flash("info", "♻️ Matriks perizinan dikembalikan ke master database default.")


def cb_apply_sec_data():
    st.session_state.saved_secondary_data = _editor_records("editor_sec_data", st.session_state.saved_secondary_data)
    flash("success", "🌐 Data sekunder tersimpan!")


def cb_add_sec_manual():
    sumber = str(wval("sec_m_sumber", "")).strip()
    judul = str(wval("sec_m_judul", "")).strip()
    if not sumber or not judul:
        flash("error", "Sumber dan judul data wajib diisi.")
        return
    st.session_state.saved_secondary_data.append(
        {
            "sumber": sumber,
            "judul": judul,
            "detail": wval("sec_m_detail", ""),
            "kategori": wval("sec_m_kategori", "Data Primer Lapangan"),
            "tanggal_impor": now_str(),
        }
    )
    flash("success", f"➕ Data sekunder ditambahkan: {judul}")


def cb_import_secondary(sumber, judul, detail, kategori):
    """Impor entri katalog statis (nilai berasal dari database, bukan widget)."""
    exists = any(x.get("sumber") == sumber and x.get("judul") == judul for x in st.session_state.saved_secondary_data)
    if exists:
        flash("warning", f"Data sudah ada di DB proyek: {judul}")
        return
    st.session_state.saved_secondary_data.append(
        {"sumber": sumber, "judul": judul, "detail": detail, "kategori": kategori, "tanggal_impor": now_str()}
    )
    flash("success", f"💾 Diimpor ke DB proyek: {judul}")


def cb_apply_oss():
    st.session_state.nib_oss = wval("oss_nib", "")
    st.session_state.id_oss_project = wval("oss_id", "")
    st.session_state.kbli = str(wval("oss_kbli", ""))
    st.session_state.luas_lahan = float(wval("oss_luas", 0) or 0)
    st.session_state.pic_project = wval("oss_pic", "")
    flash("success", "🔄 Parameter OSS diperbarui — penapisan risiko dirender ulang.")


def cb_apply_team():
    st.session_state.team_penyusun = _editor_records("editor_team", st.session_state.team_penyusun)
    flash("success", "👥 Data tim penyusun tersimpan.")


def cb_reset_team():
    st.session_state.team_penyusun = [dict(x) for x in DEFAULT_TEAM]
    flash("info", "♻️ Tim penyusun dikembalikan ke data default.")


def cb_save_vault():
    """Simpan berkas hasil unggahan ke vault proyek (folder attachments)."""
    files = wval("vault_files", []) or []
    if not files:
        flash("error", "Pilih minimal satu berkas untuk disimpan ke vault.")
        return
    kategori = wval("vault_kategori", "Lainnya")
    catatan = wval("vault_catatan", "")
    folder = attachment_dir_for(st.session_state.current_project_id)
    saved = 0
    for uf in files:
        try:
            payload = uf.getvalue()
            nama_asli = uf.name
            ukuran = uf.size
        except Exception:
            continue
        target = os.path.join(folder, f"{now_str('%Y%m%d%H%M%S')}_{safe_filename(nama_asli)}")
        with open(target, "wb") as f:
            f.write(payload)
        st.session_state.uploaded_file_list.append(
            {
                "nama_berkas": os.path.basename(target),
                "nama_asli": nama_asli,
                "kategori": kategori,
                "catatan": catatan,
                "ukuran_kb": round((ukuran or 0) / 1024, 1),
                "tanggal_upload": now_str(),
                "path_server": target,
            }
        )
        saved += 1
    st.session_state.vault_files = []
    flash("success", f"📁 {saved} berkas tersimpan ke vault proyek.")


def cb_clear_vault_list():
    st.session_state.uploaded_file_list = []
    flash("info", "🗑️ Daftar vault dikosongkan (berkas di disk tetap ada).")


def cb_add_sptm():
    tanggal = wval("sptm_tanggal")
    st.session_state.data_sptm.append(
        {
            "tanggal": tanggal.strftime("%Y-%m-%d") if hasattr(tanggal, "strftime") else str(tanggal),
            "metode": wval("sptm_metode", ""),
            "lokasi": wval("sptm_lokasi", ""),
            "jumlah_peserta": int(wval("sptm_peserta", 0) or 0),
            "pimpinan": wval("sptm_pimpinan", ""),
            "status": wval("sptm_status", "Selesai / Valid"),
            "catatan": wval("sptm_catatan", ""),
        }
    )
    flash("success", "📢 Kegiatan pelibatan masyarakat tersimpan.")


def cb_apply_sptm():
    st.session_state.data_sptm = _editor_records("editor_sptm", st.session_state.data_sptm)
    flash("success", "📢 Perubahan data SPTM tersimpan.")


def cb_apply_dampak():
    st.session_state.data_dampak = _editor_records("editor_dampak", st.session_state.data_dampak)
    flash("success", "🧪 Data DPH tersimpan — peta di tab GIS ikut diperbarui.")


def cb_reset_dampak():
    st.session_state.data_dampak = [dict(x) for x in DEFAULT_DAMPAK]
    flash("info", "♻️ Data dampak dikembalikan ke contoh default.")


def cb_update_gis():
    st.session_state.lokasi_proyek = wval("gis_lokasi", "")
    st.session_state.lat_proyek = float(wval("gis_lat", 0) or 0)
    st.session_state.lon_proyek = float(wval("gis_lon", 0) or 0)
    flash("success", "📍 Lokasi tapak proyek diperbarui.")


def cb_add_revision():
    """Engine revisi: catat masukan perbaikan + simpan berkas sumbernya bila ada."""
    catatan = str(wval("rev_catatan", "")).strip()
    if not catatan:
        flash("warning", "Mohon isi catatan perbaikan terlebih dahulu!")
        return
    uploaded_file = wval("uploader_revisi")
    st.session_state.revisi_history.append(
        {
            "tanggal": now_str(),
            "sumber": wval("rev_sumber", ""),
            "bab": wval("rev_bab", ""),
            "catatan": catatan,
            "teks_sebelum": wval("rev_sebelum", ""),
            "teks_sesudah": wval("rev_sesudah", ""),
            "status_verifikasi": wval("rev_status", "COMPLETED / VERIFIED"),
            "berkas_sumber": uploaded_file.name if uploaded_file is not None else "",
        }
    )
    if uploaded_file is not None:
        try:
            folder = attachment_dir_for(st.session_state.current_project_id)
            target = os.path.join(folder, f"REVISI_{now_str('%Y%m%d%H%M')}_{safe_filename(uploaded_file.name)}")
            with open(target, "wb") as f:
                f.write(uploaded_file.getvalue())
            st.session_state.uploaded_file_list.append(
                {
                    "nama_berkas": os.path.basename(target),
                    "nama_asli": uploaded_file.name,
                    "kategori": "Catatan Revisi",
                    "ukuran_kb": round((uploaded_file.size or 0) / 1024, 1),
                    "tanggal_upload": now_str(),
                    "path_server": target,
                }
            )
        except Exception as exc:
            flash("warning", f"Berkas masukan gagal disimpan ke vault: {exc}")
    flash("success", "✅ Masukan perbaikan berhasil diterapkan dan masuk ke histori dokumen!")


def cb_clear_revisi():
    st.session_state.revisi_history = []
    flash("info", "🗑️ Histori revisi dikosongkan.")


def cb_save_report(mode):
    """mode: 'full' | 'full_md' | 'delta' | 'full_updated'."""
    base_name = safe_filename(st.session_state.current_project_id)
    if mode == "full":
        content, folder, fname, pesan = generate_full_report_text(), REPORTS_DIR, f"FULL_REPORT_{base_name}.txt", "Draf laporan utuh"
    elif mode == "full_md":
        content, folder, fname, pesan = generate_full_report_markdown(), REPORTS_DIR, f"FULL_REPORT_{base_name}.md", "Laporan versi Markdown"
    elif mode == "delta":
        content, folder, fname, pesan = generate_delta_report_text(), REVISIONS_DIR, f"DELTA_CHANGES_{base_name}.txt", "Matriks perubahan delta"
    else:
        content, folder, fname, pesan = generate_full_report_text(), REVISIONS_DIR, f"FULL_UPDATED_{base_name}.txt", "Dokumen utuh versi terbaru"
    fpath = os.path.join(folder, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    flash("success", f"💾 {pesan} tersimpan: `{fpath}`")


def cb_publish_skkl():
    """Terbitkan draf SKKL dan catat log push ke OSS RBA."""
    base_name = safe_filename(st.session_state.current_project_id)
    text = generate_skkl_text()
    fpath = os.path.join(REPORTS_DIR, f"SKKL_{base_name}_{now_str('%Y%m%d%H%M%S')}.txt")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(text)
    progress_now = calculate_item_progress(st.session_state.item_checks)
    menggantung = sum(
        1 for r in st.session_state.revisi_history
        if str(r.get("status_verifikasi", "")).upper().startswith("IN PROGRESS")
    )
    layak = (
        progress_now >= 75
        and menggantung == 0
        and any("KTPA" in str(t.get("peran", "")) for t in st.session_state.team_penyusun)
        and len(st.session_state.saved_secondary_data) > 0
        and len(st.session_state.data_dampak) > 0
        and len(st.session_state.data_sptm) > 0
    )
    st.session_state.skkl_log.append(
        {
            "tanggal": now_str(),
            "berkas": os.path.basename(fpath),
            "status": "TERBIT (DRAF)",
            "gerbang_layak": "YA" if layak else "TIDAK",
            "progres": f"{progress_now}%",
        }
    )
    flash("success", f"📜 SKKL diterbitkan & ter-push ke Portal OSS RBA: `{fpath}`")


def cb_submit_tpa():
    """Masukan Tim Penilai (TPA) langsung diteruskan ke engine revisi."""
    catatan = str(wval("tpa_catatan", "")).strip()
    if not catatan:
        flash("error", "Catatan arahan wajib diisi.")
        return
    tanggal = wval("tpa_tgl")
    entry = {
        "tanggal": tanggal.strftime("%Y-%m-%d") if hasattr(tanggal, "strftime") else str(tanggal),
        "sumber": f"Tim TPA Pusat / KLHK — {wval('tpa_nama') or 'Anonim'}",
        "bab": wval("tpa_bab", ""),
        "catatan": f"[{wval('tpa_kat', '')}] {catatan}",
        "teks_sebelum": "(belum diubah)",
        "teks_sesudah": "(menunggu tindak lanjut penyusun)",
        "status_verifikasi": "IN PROGRESS",
    }
    st.session_state.revisi_history.append(entry)
    st.session_state.masukan_tpa.append(entry)
    flash("success", "📨 Masukan TPA diteruskan ke Tab Upload Masukan & Auto-Revisi.")




# Semua callback dibungkus pengaman agar satu aksi gagal tidak merusak seluruh halaman.
cb_add_revision = safe_callback(cb_add_revision)
cb_add_sec_manual = safe_callback(cb_add_sec_manual)
cb_add_sptm = safe_callback(cb_add_sptm)
cb_apply_dampak = safe_callback(cb_apply_dampak)
cb_apply_master_map = safe_callback(cb_apply_master_map)
cb_apply_oss = safe_callback(cb_apply_oss)
cb_apply_perizinan = safe_callback(cb_apply_perizinan)
cb_apply_sec_data = safe_callback(cb_apply_sec_data)
cb_apply_sptm = safe_callback(cb_apply_sptm)
cb_apply_team = safe_callback(cb_apply_team)
cb_clear_revisi = safe_callback(cb_clear_revisi)
cb_clear_vault_list = safe_callback(cb_clear_vault_list)
cb_delete_project = safe_callback(cb_delete_project)
cb_import_secondary = safe_callback(cb_import_secondary)
cb_open_project = safe_callback(cb_open_project)
cb_publish_skkl = safe_callback(cb_publish_skkl)
cb_register_project = safe_callback(cb_register_project)
cb_reset_dampak = safe_callback(cb_reset_dampak)
cb_reset_master_map = safe_callback(cb_reset_master_map)
cb_reset_perizinan = safe_callback(cb_reset_perizinan)
cb_reset_team = safe_callback(cb_reset_team)
cb_save_project = safe_callback(cb_save_project)
cb_save_report = safe_callback(cb_save_report)
cb_save_vault = safe_callback(cb_save_vault)
cb_submit_tpa = safe_callback(cb_submit_tpa)
cb_update_gis = safe_callback(cb_update_gis)

# --------------------------------------------------------------------------- #
# 10. HEADER APLIKASI
# --------------------------------------------------------------------------- #
st.title("🌿 DR Martin Amdal System v8.0")
st.caption(
    "👨‍🔬 **System Architect & Penulis: DR. Leo Martin** | Full AMDAL Report Generator, "
    "Input/Upload Feedback Revision Engine, & Dual-Mode Save/Export Options"
)
render_flash()

# --------------------------------------------------------------------------- #
# 11. SIDEBAR: MANAJEMEN FOLDER & ENTRY PROJECT
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("## 🌿 DR Martin Amdal System")
    st.markdown("**Author:** DR. Leo Martin  \n**Versi:** 8.0 (Document Report & Revision Engine)")
    st.divider()

    # ---- SECTION 1: CEK & BUKA PROYEK ----
    st.header("📂 1. Cek & Buka Project")
    saved_files = list_projects()
    del_target = None
    if saved_files:
        selected_file = st.selectbox(
            "Pilih Proyek di `projects/`:", ["-- Pilih Proyek --"] + saved_files, key="select_project_file"
        )
        input_password = st.text_input("🔑 Password Proyek", type="password", key="pass_check_input")

        st.button(
            "📖 Buka Proyek",
            type="primary",
            width="stretch",
            key="btn_open_project",
            on_click=cb_open_project,
        )

        with st.expander("🗑️ Kelola berkas proyek"):
            del_target = st.selectbox("Berkas yang dihapus:", saved_files, key="del_target")
            st.caption("Menghapus berkas JSON proyek (attachment & revisi tetap tersimpan).")
            st.button(
                "🗑️ Hapus Proyek",
                width="stretch",
                key="btn_delete_project",
                on_click=cb_delete_project,
            )
    else:
        st.info("Belum ada file proyek tersimpan di `projects/`")

    st.divider()

    # ---- SECTION 2: ENTRY PROJECT BARU ----
    st.header("📝 2. Entry Project Baru")
    with st.expander("➕ Form Registrasi Proyek Baru"):
        new_prj_id = st.text_input("ID Proyek Baru", value=f"PRJ-{datetime.now().strftime('%Y%m%d-%H%M')}", key="new_prj_id")
        new_nib = st.text_input("Nomor Induk Berusaha (NIB)", value="1299000887766", key="new_nib")
        new_id_oss = st.text_input("ID Proyek OSS RBA", value=f"OSS-{datetime.now().strftime('%Y%m%d%H%M')}", key="new_id_oss")
        new_nama = st.text_input("Nama Kegiatan", value="Pembangunan Kawasan Industri Baru", key="new_nama")
        new_pemrakarsa = st.text_input("Pemrakarsa Proyek", value="PT. Industri Nusantara", key="new_pemrakarsa")
        new_pic = st.text_input("👤 PIC Proyek", value="Ir. Budi Santoso, M.T.", key="new_pic")
        new_pass = st.text_input("🔑 Set Password", type="password", value="123456", key="new_pass")
        new_kbli = st.text_input("KBLI", value="20111", key="new_kbli")
        new_luas = st.number_input("Luas Lahan (Ha)", value=25.0, min_value=0.0, step=0.5, format="%.2f", key="new_luas")
        new_lokasi = st.text_input("📍 Lokasi Kegiatan (Deskriptif)", value="Kabupaten Gresik, Jawa Timur", key="new_lokasi")
        c_lat, c_lon = st.columns(2)
        new_lat = c_lat.number_input("Latitude", value=-7.1500, format="%.5f", step=0.001, key="new_lat")
        new_lon = c_lon.number_input("Longitude", value=112.6000, format="%.5f", step=0.001, key="new_lon")

        st.button(
            "✨ Daftarkan & Buat Proyek",
            type="primary",
            width="stretch",
            key="btn_register_project",
            on_click=cb_register_project,
        )
        st.caption("Proyek baru langsung disimpan sebagai berkas JSON di folder `projects/`.")

    st.divider()

    # ---- SECTION 3: SIMPAN KE FOLDER ----
    st.header("💾 3. Simpan Ke Folder Proyek")
    st.button(
        "💾 Save Project Complete Data",
        type="primary",
        width="stretch",
        key="btn_save_project",
        on_click=cb_save_project,
    )

    st.caption(
        f"📁 Folder aktif: `{PROJECTS_DIR}`  \n"
        f"Berkas proyek: **{len(saved_files)}** | Attachment: "
        f"**{len(st.session_state.get('uploaded_file_list', []))}**"
    )

# --------------------------------------------------------------------------- #
# 12. HEADER METRIK & PROGRES
# --------------------------------------------------------------------------- #
current_progress = calculate_item_progress(st.session_state.item_checks)
oss_risk_info = run_oss_risk_screening(st.session_state.kbli, st.session_state.luas_lahan)

col_p1, col_p2, col_p3, col_p4 = st.columns([2.4, 1.2, 1, 1])
with col_p1:
    st.subheader(f"📌 [{st.session_state.current_project_id}] {st.session_state.nama_proyek}")
    st.caption(
        f"Pemrakarsa: **{st.session_state.pemrakarsa}** | NIB: `{st.session_state.nib_oss}` | "
        f"👤 PIC: `{st.session_state.pic_project}`"
    )
with col_p2:
    st.metric("Penapisan OSS RBA", f"{oss_risk_info['kode_emoji']} {oss_risk_info['tingkat_risiko']}")
with col_p3:
    st.metric("Histori Revisi", f"{len(st.session_state.revisi_history)} Catatan")
with col_p4:
    st.metric("Progres Map AMDAL", f"{current_progress}%", delta=f"{len(st.session_state.item_checks)} tahapan")

st.progress(min(max(current_progress / 100.0, 0.0), 1.0), text=f"Progres penyusunan dokumen: {current_progress}%")

# --------------------------------------------------------------------------- #
# 13. TAB UTAMA
# --------------------------------------------------------------------------- #
(
    tab_roadmap,
    tab_doc_gen,
    tab_revision,
    tab_perizinan,
    tab_sec_data,
    tab_oss,
    tab_team,
    tab_upload,
    tab_sptm,
    tab_dampak,
    tab_gis,
    tab_tpa,
) = st.tabs(
    [
        "🗺️ Master Map Penyusunan",
        "📄 Generator Laporan Dokumen",
        "📝 Upload Masukan & Auto-Revisi",
        "📜 Perizinan Penunjang",
        "🌐 Data Sekunder Internet",
        "🔄 Integrasi OSS RBA & Amdalnet",
        "👥 Tim Penyusun AMDAL",
        "📁 Vault Berkas Proyek",
        "📢 Pelibatan Masyarakat (SPTM)",
        "🧪 Pelingkupan Dampak (DPH)",
        "🗺️ GIS & Spasial",
        "👨‍⚖️ Portal TPA & Auto-SKKL/SLO",
    ]
)

# ============================ TAB 1: MASTER MAP ============================ #
with tab_roadmap:
    st.subheader("🗺️ Master Map Penyusunan AMDAL & Workflow Status")
    col_rm1, col_rm2 = st.columns([1.7, 1])

    with col_rm1:
        df_map = pd.DataFrame(st.session_state.item_checks)
        if df_map.empty:
            df_map = pd.DataFrame(columns=["id", "kategori", "item", "status", "catatan"])
        edited_map = st.data_editor(
            df_map,
            column_config={
                "id": st.column_config.TextColumn("ID Tahapan", width="small"),
                "kategori": st.column_config.TextColumn("Kategori", width="medium"),
                "item": st.column_config.TextColumn("Item Pekerjaan", width="large"),
                "status": st.column_config.SelectboxColumn(
                    "Status Tahapan",
                    options=STATUS_OPTIONS,
                    required=True,
                    default="Belum Dimulai",
                ),
                "catatan": st.column_config.TextColumn("Catatan", width="large"),
            },
            width="stretch",
            height=420,
            num_rows="dynamic",
            key="editor_master_map",
        )
        c_btn1, c_btn2 = st.columns(2)
        c_btn1.button(
            "💾 Simpan Perubahan Master Map",
            type="primary",
            width="stretch",
            key="btn_save_master_map",
            on_click=cb_apply_master_map,
        )
        c_btn2.button(
            "♻️ Reset ke Template Default",
            width="stretch",
            key="btn_reset_master_map",
            on_click=cb_reset_master_map,
        )

        st.markdown("#### 📥 Unduh Master Map")
        st.download_button(
            "⬇️ Master Map (.csv)",
            data=pd.DataFrame(st.session_state.item_checks).to_csv(index=False).encode("utf-8"),
            file_name=f"MASTER_MAP_{safe_filename(st.session_state.current_project_id)}.csv",
            mime="text/csv",
            width="stretch",
        )

    with col_rm2:
        st.markdown("#### 📊 Distribusi Status")
        if st.session_state.item_checks:
            status_series = pd.DataFrame(st.session_state.item_checks)["status"].astype(str).value_counts().reset_index()
            status_series.columns = ["Status", "Jumlah Tahapan"]
            fig_pie = px.pie(
                status_series,
                values="Jumlah Tahapan",
                names="Status",
                hole=0.45,
                color="Status",
                color_discrete_map=STATUS_COLORS,
            )
            fig_pie.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320, showlegend=True)
            st.plotly_chart(fig_pie, width="stretch")

            fig_bar = px.bar(
                pd.DataFrame(st.session_state.item_checks),
                x="kategori",
                color="status",
                title="Beban Kerja per Kategori",
                color_discrete_map=STATUS_COLORS,
            )
            fig_bar.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300, xaxis_title=None, yaxis_title="Jumlah")
            st.plotly_chart(fig_bar, width="stretch")
        else:
            st.info("Belum ada tahapan di Master Map.")

    st.divider()
    st.markdown("#### 🧭 Diagram Alur Workflow (Graphviz)")
    if HAS_GRAPHVIZ and st.session_state.item_checks:
        df_cat = pd.DataFrame(st.session_state.item_checks)
        df_cat["status"] = df_cat["status"].astype(str)
        signature = df_cat.groupby(["kategori", "status"]).size().to_dict()
        cat_order = sorted(df_cat["kategori"].dropna().unique().tolist())

        dot = graphviz.Digraph(format="png")
        dot.attr(rankdir="LR", bgcolor="transparent", nodesep="0.35", ranksep="0.55")
        dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="11", margin="0.18,0.10")
        for idx, cat in enumerate(cat_order):
            sub = df_cat[df_cat["kategori"] == cat]
            done = int((sub["status"] == "Selesai / Valid").sum())
            proc = int((sub["status"] == "Sedang Diproses").sum())
            rev = int((sub["status"] == "Perlu Revisi").sum())
            belum = int((sub["status"] == "Belum Dimulai").sum())
            pct = calculate_item_progress(sub.to_dict("records"))
            color = "#d7f5e0" if belum == 0 and rev == 0 and proc == 0 else ("#fff2cc" if proc or rev else "#eef1f5")
            dot.node(
                f"c{idx}",
                label=f"{cat}\n{len(sub)} item | {pct}%\n✅{done}  🔄{proc}  ⚠️{rev}  ⏳{belum}",
                fillcolor=color,
                color="#9aa4b2",
            )
        for idx in range(len(cat_order) - 1):
            dot.edge(f"c{idx}", f"c{idx+1}", color="#5b6b7f", arrowsize="0.7")
        try:
            st.image(dot.pipe(), width="stretch")
        except Exception as exc:
            st.caption(f"Renderer Graphviz tidak tersedia ({exc}) — memakai diagram alur HTML.")
            st.markdown(html_workflow_diagram(df_cat, cat_order), unsafe_allow_html=True)
    else:
        st.caption("Diagram alur HTML (Graphviz tidak terpasang di mesin ini).")
        df_cat_fb = pd.DataFrame(st.session_state.item_checks)
        df_cat_fb["status"] = df_cat_fb["status"].astype(str)
        st.markdown(
            html_workflow_diagram(df_cat_fb, sorted(df_cat_fb["kategori"].dropna().unique().tolist())),
            unsafe_allow_html=True,
        )

# ======================= TAB 2: GENERATOR LAPORAN ========================== #
with tab_doc_gen:
    st.subheader("📄 Generator Laporan Dokumen AMDAL Utuh (Real-time Auto Render)")
    st.caption("Seluruh data terinput dikompilasi otomatis menjadi Draf Dokumen Laporan siap cetak / ekspor.")

    view_mode = st.radio(
        "Format pratinjau:",
        ["Plain Text (siap cetak)", "Markdown (tabel)"],
        horizontal=True,
        key="report_view_mode",
    )
    full_report_content = generate_full_report_text()
    full_report_md = generate_full_report_markdown()

    if view_mode.startswith("Plain"):
        st.text_area(
            "Preview Dokumen Laporan AMDAL & RKL-RPL Utuh:",
            value=full_report_content,
            height=460,
            key="preview_full_report",
        )
    else:
        with st.container(border=True):
            st.markdown(full_report_md)

    st.markdown("### 💾 Opsi Ekspor & Penyimpanan Laporan Dokumen")
    col_ex1, col_ex2, col_ex3 = st.columns(3)
    base_name = safe_filename(st.session_state.current_project_id)

    with col_ex1:
        st.download_button(
            label="📥 Laporan Menyeluruh (.txt)",
            data=full_report_content.encode("utf-8"),
            file_name=f"Laporan_AMDAL_Utuh_{base_name}_v8.txt",
            mime="text/plain",
            type="primary",
            width="stretch",
        )
    with col_ex2:
        st.download_button(
            label="📥 Laporan Menyeluruh (.md)",
            data=full_report_md.encode("utf-8"),
            file_name=f"Laporan_AMDAL_Utuh_{base_name}_v8.md",
            mime="text/markdown",
            width="stretch",
        )
    with col_ex3:
        st.download_button(
            label="📥 Berkas Proyek (.json)",
            data=json.dumps(sanitize(collect_session_payload()), indent=2, ensure_ascii=False).encode("utf-8"),
            file_name=f"{base_name}.json",
            mime="application/json",
            width="stretch",
        )

    c_srv1, c_srv2 = st.columns(2)
    with c_srv1:
        st.button(
            "💾 Save Draft Dokumen Utuh ke Folder Server",
            width="stretch",
            key="btn_save_report_txt",
            on_click=cb_save_report,
            args=("full",),
        )
    with c_srv2:
        st.button(
            "💾 Save Versi Markdown ke Folder Server",
            width="stretch",
            key="btn_save_report_md",
            on_click=cb_save_report,
            args=("full_md",),
        )

    with st.expander("🗂️ Berkas laporan yang sudah tersimpan di server"):
        saved_reports = sorted(
            (os.path.join(REPORTS_DIR, f) for f in os.listdir(REPORTS_DIR)),
            key=os.path.getmtime,
            reverse=True,
        )
        if not saved_reports:
            st.info("Belum ada laporan tersimpan di folder `projects/reports/`.")
        for rp in saved_reports[:20]:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"📄 `{os.path.basename(rp)}`")
            c2.caption(f"{round(os.path.getsize(rp)/1024, 1)} KB")
            with open(rp, "rb") as fh:
                c3.download_button(
                    "⬇️",
                    data=fh.read(),
                    file_name=os.path.basename(rp),
                    mime="text/plain",
                    key=f"dl_{os.path.basename(rp)}",
                )

# ==================== TAB 3: UPLOAD MASUKAN & AUTO-REVISI ================== #
with tab_revision:
    st.subheader("📝 Modul Upload Masukan Perbaikan & Processing Engine Revisi Laporan")
    st.caption("Kelola catatan revisi dari Tim TPA / DLH / Masyarakat dan perbarui bagian dokumen terkait secara presisi.")

    col_rev1, col_rev2 = st.columns([1, 1.1])

    with col_rev1:
        st.markdown("### 📥 Input / Upload Catatan Masukan Perbaikan")
        uploaded_rev_file = st.file_uploader(
            "Upload Berkas Catatan Perbaikan (TXT/MD/PDF/DOCX):",
            type=["txt", "md", "docx", "pdf", "csv"],
            key="uploader_revisi",
        )
        extracted_text = ""
        if uploaded_rev_file:
            extracted_text = extract_uploaded_text(uploaded_rev_file)
            st.info(
                f"File terunggah: `{uploaded_rev_file.name}` "
                f"({round((uploaded_rev_file.size or 0)/1024, 1)} KB)"
            )
            with st.expander("🔎 Hasil ekstraksi teks berkas", expanded=False):
                st.code(extracted_text[:4000] or "(kosong)", language=None)

        sumber_masukan = st.selectbox(
            "Sumber Masukan / Penguji:",
            ["Tim TPA Pusat / KLHK", "DLH Provinsi / Kab-Kota", "Konsultasi Publik (MTD)", "Tim Ahli Independen", "Masyarakat Terdampak"],
            key="rev_sumber",
        )
        bab_direvisi = st.selectbox(
            "Bab / Bagian Dokumen yang Direvisi:",
            [
                "Bab I - Latar Belakang & Penapisan OSS",
                "Bab II - Rona Lingkungan Awal & Data Sekunder",
                "Bab III - Persetujuan Teknis (Pertek Air/Udara/B3)",
                "Bab IV - Pelingkupan Dampak (DPH & Mitigasi)",
                "Bab V - Matriks RKL-RPL & Pemantauan",
            ],
            key="rev_bab",
        )
        catatan_revisi = st.text_area(
            "Catatan / Masukan Saran Perbaikan:",
            value=extracted_text[:1500] if extracted_text and not extracted_text.startswith("[") else "",
            placeholder="Misal: Tambahkan analisis modeling dispersi debu PM10 untuk musim kemarau...",
            height=140,
            key="rev_catatan",
        )
        teks_sebelum = st.text_area(
            "Teks / Kondisi Dokumen Sebelum Revisi:",
            value="Penyiraman jalan dilakukan 1x sehari.",
            height=90,
            key="rev_sebelum",
        )
        teks_sesudah = st.text_area(
            "Usulan Teks / Kondisi Dokumen Setelah Perbaikan:",
            value="Penyiraman jalan ditingkatkan menjadi 3x sehari dan ditambah water spraying di area crusher.",
            height=90,
            key="rev_sesudah",
        )
        status_verif = st.selectbox(
            "Status Tindak Lanjut:",
            ["COMPLETED / VERIFIED", "IN PROGRESS", "MENUNGGU KONFIRMASI PEMRAKARSA"],
            key="rev_status",
        )

        st.button(
            "✨ Terapkan Perbaikan & Update Dokumen Laporan",
            type="primary",
            width="stretch",
            key="btn_apply_revision",
            on_click=cb_add_revision,
        )

    with col_rev2:
        st.markdown("### 📋 Histori Catatan Revisi & Perubahan Dokumen")
        if st.session_state.revisi_history:
            df_rev = pd.DataFrame(st.session_state.revisi_history)
            kolom = [c for c in ["tanggal", "sumber", "bab", "catatan", "status_verifikasi"] if c in df_rev.columns]
            st.dataframe(df_rev[kolom], width="stretch", height=240, hide_index=True)

            with st.expander("🔍 Detail Before / After tiap revisi"):
                for idx, rev in enumerate(st.session_state.revisi_history, 1):
                    st.markdown(f"**#{idx} — {rev.get('bab','')}** ({rev.get('tanggal','')})")
                    cA, cB = st.columns(2)
                    cA.markdown(f"🔴 **Sebelum:**  \n{rev.get('teks_sebelum','')}")
                    cB.markdown(f"🟢 **Sesudah:**  \n{rev.get('teks_sesudah','')}")
                    st.caption(f"Catatan: {rev.get('catatan','')}")
                    st.divider()

            st.button(
                "🗑️ Kosongkan seluruh histori revisi",
                width="stretch",
                key="btn_clear_revisi",
                on_click=cb_clear_revisi,
            )

            st.markdown("---")
            st.markdown("### 🎯 Opsi Penyimpanan & Ekspor File Perbaikan")

            delta_content = generate_delta_report_text()
            full_updated_content = generate_full_report_text()

            st.markdown("#### 🟢 Opsi A: Penyimpanan Ter-update Menyeluruh (Full Updated Version)")
            st.caption("Menyimpan & mengunduh seluruh dokumen laporan Bab I-VII versi paling baru secara utuh.")
            col_oa1, col_oa2 = st.columns(2)
            with col_oa1:
                st.download_button(
                    label="📥 Download Full Updated Doc",
                    data=full_updated_content.encode("utf-8"),
                    file_name=f"FULL_UPDATED_AMDAL_{base_name}.txt",
                    mime="text/plain",
                    width="stretch",
                )
            with col_oa2:
                st.button(
                    "💾 Save Full Version to Folder",
                    key="save_full_folder",
                    width="stretch",
                    on_click=cb_save_report,
                    args=("full_updated",),
                )

            st.divider()

            st.markdown("#### 🟡 Opsi B: Perubahan Bagian yang Diganti (Delta / Track Changes Only)")
            st.caption("Khusus Matriks Perubahan Bagian (sebelum & sesudah revisi) untuk verifikasi cepat TPA.")
            col_ob1, col_ob2 = st.columns(2)
            with col_ob1:
                st.download_button(
                    label="📥 Download Delta Changes Only",
                    data=delta_content.encode("utf-8"),
                    file_name=f"DELTA_CHANGES_{base_name}.txt",
                    mime="text/plain",
                    width="stretch",
                )
            with col_ob2:
                st.button(
                    "💾 Save Delta Version to Folder",
                    key="save_delta_folder",
                    width="stretch",
                    on_click=cb_save_report,
                    args=("delta",),
                )
        else:
            st.info("Belum ada histori revisi diinput.")
            st.caption("Gunakan form di sebelah kiri untuk menambahkan catatan perbaikan pertama.")

# ===================== TAB 4: PERIZINAN PENUNJANG ========================== #
with tab_perizinan:
    st.subheader("📜 Matriks Perizinan Penunjang & Persyaratan Dokumen")
    df_perizinan = pd.DataFrame(st.session_state.perizinan_penunjang)
    if df_perizinan.empty:
        df_perizinan = pd.DataFrame(
            columns=["kode", "nama_perizinan", "jenis", "dasar_hukum", "persyaratan_dokumen", "instansi_penerbit", "status"]
        )
    edited_pertek = st.data_editor(
        df_perizinan,
        column_config={
            "kode": st.column_config.TextColumn("Kode", width="small"),
            "nama_perizinan": st.column_config.TextColumn("Nama Perizinan", width="large"),
            "jenis": st.column_config.SelectboxColumn(
                "Jenis", options=["Prasyarat Usaha", "Persetujuan Teknis", "Perizinan Penunjang", "Kewajiban Pasca-Operasi"]
            ),
            "status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, required=True),
        },
        width="stretch",
        height=360,
        num_rows="dynamic",
        key="editor_perizinan",
    )
    c_per1, c_per2 = st.columns([1, 3])
    c_per1.button(
        "💾 Simpan Matriks Perizinan",
        type="primary",
        width="stretch",
        key="btn_save_perizinan",
        on_click=cb_apply_perizinan,
    )
    c_per2.button(
        "♻️ Reset ke Master Database Default",
        width="stretch",
        key="btn_reset_perizinan",
        on_click=cb_reset_perizinan,
    )

    st.divider()
    st.markdown("#### 📑 Rincian Persyaratan Dokumen per Perizinan")
    if st.session_state.perizinan_penunjang:
        for per in st.session_state.perizinan_penunjang:
            with st.expander(f"[{per.get('kode','-')}] {per.get('nama_perizinan','-')} — {per.get('status','-')}"):
                st.markdown(f"**Dasar Hukum:** {per.get('dasar_hukum','-')}")
                st.markdown(f"**Instansi Penerbit:** {per.get('instansi_penerbit','-')}")
                st.markdown("**Persyaratan Dokumen:**")
                st.code(per.get("persyaratan_dokumen", "-") or "-", language=None)
        st.download_button(
            "⬇️ Unduh Matriks Perizinan (.csv)",
            data=pd.DataFrame(st.session_state.perizinan_penunjang).to_csv(index=False).encode("utf-8"),
            file_name=f"PERIZINAN_{base_name}.csv",
            mime="text/csv",
        )
    else:
        st.info("Belum ada data perizinan penunjang.")

# ========================= TAB 5: DATA SEKUNDER ============================ #
with tab_sec_data:
    st.subheader("🌐 Modul Data Sekunder Internet — Rona Lingkungan Hidup Awal")
    st.caption("Katalog sumber data publik. Klik **Impor** untuk memasukkan ringkasan parameter ke database proyek.")

    df_katalog = pd.DataFrame(PUBLIC_SECONDARY_DATA_DB)
    st.dataframe(
        df_katalog[["id", "sumber", "kategori", "judul", "parameter_key"]],
        width="stretch",
        hide_index=True,
        height=260,
    )

    for item in PUBLIC_SECONDARY_DATA_DB:
        with st.expander(f"📌 [{item['sumber']}] {item['judul']}"):
            st.write(item["deskripsi"])
            st.markdown(f"**Kategori:** {item['kategori']}  \n**Parameter kunci:** {item['parameter_key']}")
            st.markdown(f"**Sumber daring:** [{item['url']}]({item['url']}) *(tautan terbuka di browser — data mock tersedia offline)*")
            c1, c2 = st.columns([1, 2])
            c1.button(
                "💾 Impor ke DB Proyek",
                key=f"sec_{item['id']}",
                width="stretch",
                on_click=cb_import_secondary,
                args=(item["sumber"], item["judul"], item["parameter_key"], item["kategori"]),
            )

    st.divider()
    col_sd1, col_sd2 = st.columns([1.1, 1])
    with col_sd1:
        st.markdown("#### 🗃️ Data Sekunder Tersimpan di Proyek")
        if st.session_state.saved_secondary_data:
            df_sec = pd.DataFrame(st.session_state.saved_secondary_data)
            edited_sec = st.data_editor(df_sec, width="stretch", num_rows="dynamic", height=240, key="editor_sec_data")
            st.button(
                "💾 Simpan Data Sekunder",
                type="primary",
                width="stretch",
                key="btn_save_sec_data",
                on_click=cb_apply_sec_data,
            )
        else:
            st.info("Belum ada data sekunder diimpor.")
    with col_sd2:
        st.markdown("#### ➕ Tambah Data Sekunder Manual / Primer")
        with st.form("form_sec_manual", clear_on_submit=True):
            m_sumber = st.text_input("Sumber / Lembaga", key="sec_m_sumber")
            m_judul = st.text_input("Judul Data", key="sec_m_judul")
            m_kategori = st.text_input("Kategori", value="Data Primer Lapangan", key="sec_m_kategori")
            m_detail = st.text_area("Parameter / Ringkasan Hasil", height=90, key="sec_m_detail")
            st.form_submit_button(
                "➕ Tambahkan",
                width="stretch",
                on_click=cb_add_sec_manual,
            )

# ==================== TAB 6: INTEGRASI OSS RBA & AMDALNET ================== #
with tab_oss:
    st.subheader("🔄 Modul Integrasi OSS RBA & Amdalnet")
    st.info(
        f"NIB: `{st.session_state.nib_oss}` | ID Proyek OSS: `{st.session_state.id_oss_project}` | "
        f"Tingkat Risiko: **{oss_risk_info['kode_emoji']} {oss_risk_info['tingkat_risiko']}**"
    )

    col_oss1, col_oss2 = st.columns([1, 1.3])
    with col_oss1:
        st.markdown("#### ⚙️ Parameter Penapisan (dapat diubah)")
        with st.form("form_oss"):
            f_nib = st.text_input("Nomor Induk Berusaha (NIB)", value=st.session_state.nib_oss, key="oss_nib")
            f_idoss = st.text_input("ID Proyek OSS RBA", value=st.session_state.id_oss_project, key="oss_id")
            f_kbli = st.text_input("Kode KBLI", value=str(st.session_state.kbli), key="oss_kbli")
            f_luas = st.number_input(
                "Luas Lahan (Ha)", value=float(st.session_state.luas_lahan),
                min_value=0.0, step=0.5, format="%.2f", key="oss_luas",
            )
            f_pic = st.text_input("PIC Proyek", value=st.session_state.pic_project, key="oss_pic")
            st.form_submit_button(
                "🔄 Jalankan Ulang Penapisan Risiko",
                type="primary",
                width="stretch",
                on_click=cb_apply_oss,
            )

        st.markdown("#### 📏 Ambang Batas Penapisan (Permen LHK 4/2021 - disederhanakan)")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Rentang Luas Lahan": ">= 50 Ha", "Tingkat Risiko": "Risiko Tinggi (RT)", "Dokumen": "AMDAL (SKKL)", "Status OSS": "Izin (Amdalnet)"},
                    {"Rentang Luas Lahan": "5 - <50 Ha", "Tingkat Risiko": "Menengah Tinggi (RMT)", "Dokumen": "UKL-UPL (PKPL)", "Status OSS": "Sertifikat Standar Terverifikasi"},
                    {"Rentang Luas Lahan": "< 5 Ha", "Tingkat Risiko": "Menengah Rendah / Rendah", "Dokumen": "SPPL", "Status OSS": "NIB + SPPL Auto-Approved"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with col_oss2:
        st.markdown("#### 🧾 Hasil Penapisan Otomatis")
        st.metric("Tingkat Risiko Kegiatan", oss_risk_info["tingkat_risiko"])
        st.markdown(f"**Dokumen Lingkungan Wajib:** {oss_risk_info['dokumen_wajib']}")
        st.markdown(f"**Status Perizinan OSS:** {oss_risk_info['status_oss']}")
        st.markdown(f"**Kewenangan Penilai:** {oss_risk_info['kewenangan']}")
        st.markdown(f"**Jangka Waktu Layanan:** {oss_risk_info['jangka_waktu']}")
        st.markdown(f"**Keterangan Sistem:** {oss_risk_info['keterangan']}")

        fig_gauge = px.bar(
            pd.DataFrame(
                {
                    "Komponen": ["Skor Risiko Luas Lahan"],
                    "Skor": [min(float(st.session_state.luas_lahan), 100.0)],
                }
            ),
            x="Skor",
            y="Komponen",
            orientation="h",
            range_x=[0, 100],
            text_auto=".1f",
            color_discrete_sequence=["#2f6fd0"],
        )
        fig_gauge.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=160, title="Indeks Skala Kegiatan (0-100 Ha)")
        st.plotly_chart(fig_gauge, width="stretch")

        screening_text = (
            "HASIL PENAPISAN OSS RBA & AMDALNET\n"
            f"Proyek : {st.session_state.current_project_id} - {st.session_state.nama_proyek}\n"
            f"NIB    : {st.session_state.nib_oss}\n"
            f"KBLI   : {st.session_state.kbli} | Luas: {st.session_state.luas_lahan} Ha\n"
            + "\n".join(f"{k}: {v}" for k, v in oss_risk_info.items())
        )
        st.download_button(
            "⬇️ Unduh Berita Acara Penapisan (.txt)",
            data=screening_text.encode("utf-8"),
            file_name=f"PENAPISAN_OSS_{base_name}.txt",
            mime="text/plain",
            width="stretch",
        )

# ========================= TAB 7: TIM PENYUSUN ============================= #
with tab_team:
    st.subheader("👥 Tim Penyusun AMDAL (KTPA / ATPA)")
    df_team = pd.DataFrame(st.session_state.team_penyusun)
    if df_team.empty:
        df_team = pd.DataFrame(columns=["nama", "peran", "lisensi", "kontak"])
    edited_team = st.data_editor(
        df_team,
        column_config={
            "nama": st.column_config.TextColumn("Nama Lengkap & Gelar", width="large"),
            "peran": st.column_config.SelectboxColumn(
                "Peran dalam Tim",
                options=[
                    "Ketua Tim Penyusun (KTPA)",
                    "Anggota Tim (ATPA) - Fisika Kimia",
                    "Anggota Tim (ATPA) - Biologi",
                    "Anggota Tim (ATPA) - Sosial Ekonomi",
                    "Anggota Tim (ATPA) - Kesehatan Masyarakat",
                    "Anggota Tim (ATPA) - Infrastruktur/Teknik",
                ],
            ),
            "lisensi": st.column_config.TextColumn("No. Sertifikat KTPA/ATPA", width="medium"),
            "kontak": st.column_config.TextColumn("Kontak", width="medium"),
        },
        width="stretch",
        num_rows="dynamic",
        height=280,
        key="editor_team",
    )
    c_t1, c_t2 = st.columns([1, 3])
    c_t1.button(
        "💾 Simpan Tim Penyusun",
        type="primary",
        width="stretch",
        key="btn_save_team",
        on_click=cb_apply_team,
    )
    c_t2.button(
        "♻️ Reset ke Tim Default",
        width="stretch",
        key="btn_reset_team",
        on_click=cb_reset_team,
    )

    st.divider()
    col_tp1, col_tp2 = st.columns([1, 1])
    with col_tp1:
        st.markdown("#### ✅ Checklist Kelengkapan Legitimasi Penyusun")
        if st.session_state.team_penyusun:
            ada_ktpa = any("KTPA" in str(t.get("peran", "")) for t in st.session_state.team_penyusun)
            semua_lisensi = all(str(t.get("lisensi", "")).strip() for t in st.session_state.team_penyusun)
            minimal_tim = len(st.session_state.team_penyusun) >= 3
            st.write(("✅" if ada_ktpa else "❌") + " Terdapat Ketua Tim bersertifikat KTPA")
            st.write(("✅" if semua_lisensi else "❌") + " Seluruh anggota memiliki nomor sertifikat")
            st.write(("✅" if minimal_tim else "⚠️") + f" Jumlah anggota tim: {len(st.session_state.team_penyusun)} (disarankan >= 3)")
        else:
            st.warning("Belum ada anggota tim terdaftar.")
    with col_tp2:
        st.download_button(
            "⬇️ Unduh Daftar Tim (.csv)",
            data=pd.DataFrame(st.session_state.team_penyusun).to_csv(index=False).encode("utf-8"),
            file_name=f"TIM_PENYUSUN_{base_name}.csv",
            mime="text/csv",
            width="stretch",
        )

# ========================= TAB 8: VAULT BERKAS ============================= #
with tab_upload:
    st.subheader("📁 Vault Berkas Proyek (Attachments)")
    st.caption(
        f"Berkas disimpan di `{ATTACHMENTS_DIR}/{slugify(st.session_state.current_project_id)}/` "
        "dan tetap ada walau aplikasi dimuat ulang."
    )

    col_up1, col_up2 = st.columns([1, 1.2])
    with col_up1:
        st.markdown("#### ⬆️ Unggah Berkas Baru")
        with st.form("form_vault"):
            kategori_berkas = st.selectbox(
                "Kategori Berkas",
                [
                    "Dokumen AMDAL",
                    "Data Sekunder",
                    "Peta / SHP / GeoJSON",
                    "Perizinan (KKPR/Pertek)",
                    "Foto Lapangan",
                    "Notulen / BAP",
                    "Lainnya",
                ],
                key="vault_kategori",
            )
            catatan_berkas = st.text_input("Catatan / Deskripsi", key="vault_catatan")
            st.file_uploader(
                "Pilih berkas (multi-upload didukung)", accept_multiple_files=True, key="vault_files"
            )
            st.form_submit_button(
                "💾 Simpan ke Vault",
                type="primary",
                width="stretch",
                on_click=cb_save_vault,
            )

    with col_up2:
        st.markdown("#### 🗂️ Daftar Berkas Tersimpan")
        if st.session_state.uploaded_file_list:
            df_files = pd.DataFrame(st.session_state.uploaded_file_list)
            show_cols = [c for c in ["nama_berkas", "kategori", "ukuran_kb", "tanggal_upload", "catatan"] if c in df_files.columns]
            st.dataframe(df_files[show_cols], width="stretch", hide_index=True, height=260)

            st.markdown("**⬇️ Unduh berkas dari vault:**")
            for idx, rec in enumerate(st.session_state.uploaded_file_list):
                path = rec.get("path_server", "")
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"📎 `{rec.get('nama_asli') or rec.get('nama_berkas','')}` — {rec.get('kategori','')}")
                c2.caption(f"{rec.get('ukuran_kb','-')} KB")
                if path and os.path.exists(path):
                    with open(path, "rb") as fh:
                        c3.download_button("⬇️", data=fh.read(), file_name=rec.get("nama_asli") or os.path.basename(path), key=f"vault_dl_{idx}")
                else:
                    c3.caption("(berkas tidak ditemukan)")

            st.button(
                "🗑️ Kosongkan daftar vault (berkas di disk tetap ada)",
                width="stretch",
                key="btn_clear_vault",
                on_click=cb_clear_vault_list,
            )
        else:
            st.info("Vault masih kosong — unggah berkas pertama Anda.")

# ========================= TAB 9: SPTM / PUBLIK ============================ #
with tab_sptm:
    st.subheader("📢 Pelibatan Masyarakat — Konsultasi Publik & SPTM")
    st.caption("Rekam kegiatan sosialisasi, konsultasi publik, dan tanggapan masyarakat sebagai bukti pelibatan (Permen LHK 17/2012).")

    col_sp1, col_sp2 = st.columns([1, 1.2])
    with col_sp1:
        with st.form("form_sptm", clear_on_submit=True):
            sp_tanggal = st.date_input("Tanggal Kegiatan", value=datetime.now().date(), key="sptm_tanggal")
            sp_metode = st.selectbox(
                "Metode Pelibatan",
                ["Konsultasi Publik", "Sosialisasi / Penyuluhan", "Survei Tanggapan (Kuesioner)", "Musyawarah Desa", "Pengumuman Media & Web"],
                key="sptm_metode",
            )
            sp_lokasi = st.text_input("Lokasi / Desa Terdampak", key="sptm_lokasi")
            sp_peserta = st.number_input("Jumlah Peserta", value=45, min_value=0, step=1, key="sptm_peserta")
            sp_pimpinan = st.text_input("Pimpinan / Notulis Kegiatan", key="sptm_pimpinan")
            sp_status = st.selectbox("Status", STATUS_OPTIONS, key="sptm_status")
            sp_catatan = st.text_area("Ringkasan Tanggapan & Kesimpulan", height=100, key="sptm_catatan")
            st.form_submit_button(
                "➕ Simpan Kegiatan Pelibatan",
                type="primary",
                width="stretch",
                on_click=cb_add_sptm,
            )

    with col_sp2:
        if st.session_state.data_sptm:
            df_sptm = pd.DataFrame(st.session_state.data_sptm)
            edited_sptm = st.data_editor(df_sptm, width="stretch", num_rows="dynamic", height=300, key="editor_sptm")
            st.button(
                "💾 Simpan Perubahan Data SPTM",
                width="stretch",
                key="btn_save_sptm",
                on_click=cb_apply_sptm,
            )

            total_peserta = sum(int(x.get("jumlah_peserta", 0) or 0) for x in st.session_state.data_sptm)
            m1, m2, m3 = st.columns(3)
            m1.metric("Kegiatan", len(st.session_state.data_sptm))
            m2.metric("Total Peserta", f"{total_peserta} orang")
            m3.metric("Rata-rata/Kegiatan", f"{round(total_peserta/len(st.session_state.data_sptm),1)} orang")

            fig_sptm = px.bar(
                pd.DataFrame(st.session_state.data_sptm),
                x="tanggal",
                y="jumlah_peserta",
                color="metode",
                title="Partisipasi Masyarakat per Kegiatan",
            )
            fig_sptm.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
            st.plotly_chart(fig_sptm, width="stretch")

            st.download_button(
                "⬇️ Unduh Data SPTM (.csv)",
                data=pd.DataFrame(st.session_state.data_sptm).to_csv(index=False).encode("utf-8"),
                file_name=f"SPTM_{base_name}.csv",
                mime="text/csv",
                width="stretch",
            )
        else:
            st.info("Belum ada kegiatan pelibatan masyarakat tercatat.")

# ======================= TAB 10: PELINGKUPAN DAMPAK ======================== #
with tab_dampak:
    st.subheader("🧪 Pelingkupan Dampak Penting Hipotetis (DPH)")
    df_dampak = pd.DataFrame(st.session_state.data_dampak)
    if df_dampak.empty:
        df_dampak = pd.DataFrame(columns=["tahap", "kegiatan", "komponen", "dampak", "status", "pertek", "mitigasi", "lat", "lon"])
    edited_dampak = st.data_editor(
        df_dampak,
        column_config={
            "tahap": st.column_config.SelectboxColumn("Tahap", options=["Pra-Konstruksi", "Konstruksi", "Operasi", "Pasca-Operasi"]),
            "status": st.column_config.SelectboxColumn("Status Dampak", options=["DPH", "Non-DPH", "Diteliti Lebih Lanjut"]),
            "lat": st.column_config.NumberColumn("Latitude", format="%.5f"),
            "lon": st.column_config.NumberColumn("Longitude", format="%.5f"),
        },
        width="stretch",
        num_rows="dynamic",
        height=360,
        key="editor_dampak",
    )
    c_d1, c_d2 = st.columns([1, 3])
    c_d1.button(
        "💾 Simpan Pelingkupan Dampak",
        type="primary",
        width="stretch",
        key="btn_save_dampak",
        on_click=cb_apply_dampak,
    )
    c_d2.button(
        "♻️ Reset ke Contoh Default",
        width="stretch",
        key="btn_reset_dampak",
        on_click=cb_reset_dampak,
    )

    st.divider()
    if st.session_state.data_dampak:
        df_d = pd.DataFrame(st.session_state.data_dampak)
        col_dmp1, col_dmp2 = st.columns(2)
        with col_dmp1:
            st.markdown("#### Dampak per Tahap Kegiatan")
            fig_tahap = px.bar(df_d, x="tahap", color="status", title="Jumlah Dampak per Tahap")
            fig_tahap.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
            st.plotly_chart(fig_tahap, width="stretch")
        with col_dmp2:
            st.markdown("#### Dampak per Komponen Lingkungan")
            fig_komp = px.pie(df_d, names="komponen", title="Komposisi Komponen Terdampak", hole=0.4)
            fig_komp.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
            st.plotly_chart(fig_komp, width="stretch")

        st.download_button(
            "⬇️ Unduh Matriks DPH (.csv)",
            data=df_d.to_csv(index=False).encode("utf-8"),
            file_name=f"DPH_{base_name}.csv",
            mime="text/csv",
        )
    else:
        st.info("Belum ada dampak terlingkup.")

# ============================ TAB 11: GIS ================================== #
with tab_gis:
    st.subheader("🗺️ Spasial Map — Titik Dampak & Tapak Proyek")
    try:
        lat_p = float(st.session_state.lat_proyek)
        lon_p = float(st.session_state.lon_proyek)
    except (TypeError, ValueError):
        lat_p, lon_p = -5.3972, 105.2663

    col_gis1, col_gis2 = st.columns([1, 3])
    with col_gis1:
        with st.form("form_gis"):
            g_lokasi = st.text_input("Deskripsi Lokasi", value=st.session_state.lokasi_proyek or "", key="gis_lokasi")
            g_lat = st.number_input("Latitude Tapak Proyek", value=lat_p, format="%.5f", step=0.001, key="gis_lat")
            g_lon = st.number_input("Longitude Tapak Proyek", value=lon_p, format="%.5f", step=0.001, key="gis_lon")
            st.slider("Zoom Peta", 6, 18, 13, key="gis_zoom")
            st.form_submit_button(
                "📍 Perbarui Lokasi",
                type="primary",
                width="stretch",
                on_click=cb_update_gis,
            )
        st.caption(
            "🛰️ Peta memakai tile OpenStreetMap/CartoDB. Jika area peta tampak kosong, "
            "perangkat Anda sedang offline — data titik tetap tersimpan."
        )

    with col_gis2:
        zoom_level = int(st.session_state.get("gis_zoom", 13) or 13)
        m = folium.Map(location=[lat_p, lon_p], zoom_start=zoom_level, control_scale=True)
        folium.TileLayer("CartoDB positron", name="CartoDB Positron").add_to(m)
        folium.TileLayer("OpenTopoMap", name="OpenTopoMap").add_to(m)

        folium.Circle(
            location=[lat_p, lon_p],
            radius=max(float(st.session_state.luas_lahan or 1) ** 0.5 * 120, 250),
            popup=folium.Popup(
                f"<b>{st.session_state.nama_proyek}</b><br>Pemrakarsa: {st.session_state.pemrakarsa}<br>"
                f"Luas: {st.session_state.luas_lahan} Ha<br>NIB: {st.session_state.nib_oss}",
                max_width=320,
            ),
            color="#1f9d55",
            fill=True,
            fill_color="#1f9d55",
            fill_opacity=0.18,
            weight=2,
            name="Tapak Proyek",
        ).add_to(m)
        folium.Marker(
            [lat_p, lon_p],
            icon=folium.Icon(color="green", icon="industry", prefix="fa"),
            tooltip="Tapak Proyek",
        ).add_to(m)

        cluster = MarkerCluster(name="Titik Dampak").add_to(m)
        for idx, d in enumerate(st.session_state.data_dampak, 1):
            try:
                d_lat = float(d.get("lat") or lat_p)
                d_lon = float(d.get("lon") or lon_p)
            except (TypeError, ValueError):
                d_lat, d_lon = lat_p, lon_p
            html = (
                f"<div style='font-family:Arial;font-size:12px;min-width:210px'>"
                f"<b>#{idx} {d.get('kegiatan','-')}</b><br>"
                f"Tahap: {d.get('tahap','-')}<br>Komponen: {d.get('komponen','-')}<br>"
                f"Dampak: {d.get('dampak','-')} <b>[{d.get('status','-')}]</b><br>"
                f"<i>Mitigasi: {d.get('mitigasi','-')}</i></div>"
            )
            folium.Marker(
                [d_lat + 0.0012 * idx, d_lon + 0.0016 * idx],
                icon=folium.Icon(color="red" if d.get("status") == "DPH" else "orange", icon="exclamation-triangle", prefix="fa"),
                popup=folium.Popup(html, max_width=340),
                tooltip=f"{d.get('tahap','')} - {d.get('dampak','')[:40]}",
            ).add_to(cluster)

        Fullscreen(position="topleft").add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, width=None, height=520, use_container_width=True, returned_objects=[], key="folium_gis")

    st.divider()
    col_geo1, col_geo2 = st.columns(2)
    with col_geo1:
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon_p, lat_p]},
                    "properties": {
                        "nama": st.session_state.nama_proyek,
                        "pemrakarsa": st.session_state.pemrakarsa,
                        "luas_ha": st.session_state.luas_lahan,
                        "jenis": "Tapak Proyek",
                    },
                }
            ],
        }
        for d in st.session_state.data_dampak:
            try:
                coords = [float(d.get("lon") or lon_p), float(d.get("lat") or lat_p)]
            except (TypeError, ValueError):
                coords = [lon_p, lat_p]
            geojson["features"].append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": coords},
                    "properties": {k: v for k, v in d.items() if k not in ("lat", "lon")},
                }
            )
        st.download_button(
            "⬇️ Unduh Titik Spasial (.geojson)",
            data=json.dumps(geojson, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
            file_name=f"SPASIAL_{base_name}.geojson",
            mime="application/geo+json",
            width="stretch",
        )
    with col_geo2:
        try:
            st.download_button(
                "⬇️ Unduh Peta HTML Interaktif (.html)",
                data=m.get_root().render().encode("utf-8"),
                file_name=f"PETA_{base_name}.html",
                mime="text/html",
                width="stretch",
            )
        except Exception as exc:
            st.warning(f"Ekspor peta HTML gagal: {exc}")

# =================== TAB 12: PORTAL TPA & AUTO-SKKL/SLO ==================== #
with tab_tpa:
    st.subheader("👨‍⚖️ Portal Uji Kelayakan TPA & Auto-SKKL / SLO Generator")
    st.caption("Simulasi alur penilaian Komisi/TPA sampai penerbitan SKKL dan kewajiban SLO pasca-operasi.")

    col_tpa1, col_tpa2 = st.columns([1.1, 1])
    with col_tpa1:
        st.markdown("#### 📥 Input Masukan Tim Penilai (TPA / Komisi)")
        with st.form("form_tpa", clear_on_submit=True):
            tpa_tanggal = st.date_input("Tanggal Sidang / Penilaian", value=datetime.now().date(), key="tpa_tgl")
            tpa_anggota = st.text_input("Nama Penguji / Anggota TPA", key="tpa_nama")
            tpa_bab = st.selectbox(
                "Bagian yang Dinilai",
                [
                    "Bab I - Latar Belakang & Penapisan OSS",
                    "Bab II - Rona Lingkungan Awal & Data Sekunder",
                    "Bab III - Persetujuan Teknis (Pertek Air/Udara/B3)",
                    "Bab IV - Pelingkupan Dampak (DPH & Mitigasi)",
                    "Bab V - Matriks RKL-RPL & Pemantauan",
                ],
                key="tpa_bab",
            )
            tpa_kategori = st.selectbox("Kategori Temuan", ["Perbaikan Wajib (Must Fix)", "Saran (Recommended)", "Catatan Administratif"], key="tpa_kat")
            tpa_catatan = st.text_area("Catatan / Arahan Perbaikan", height=110, key="tpa_catatan")
            st.form_submit_button(
                "📨 Kirim Masukan ke Engine Revisi",
                type="primary",
                width="stretch",
                on_click=cb_submit_tpa,
            )

        st.markdown("#### 📋 Riwayat Masukan TPA")
        if st.session_state.masukan_tpa:
            st.dataframe(pd.DataFrame(st.session_state.masukan_tpa), width="stretch", hide_index=True, height=200)
        else:
            st.info("Belum ada masukan TPA terdaftar.")

    with col_tpa2:
        st.markdown("#### 🚦 Gerbang Kelayakan Penerbitan SKKL")
        progress_now = calculate_item_progress(st.session_state.item_checks)
        wajib_revisi = sum(1 for r in st.session_state.revisi_history if str(r.get("status_verifikasi", "")).upper().startswith("IN PROGRESS"))
        ada_ktpa = any("KTPA" in str(t.get("peran", "")) for t in st.session_state.team_penyusun)
        checks = {
            "Progres Master Map >= 75%": progress_now >= 75,
            "Terdapat Ketua Tim (KTPA)": ada_ktpa,
            "Tidak ada revisi menggantung": wajib_revisi == 0,
            "Ada data rona awal (sekunder)": len(st.session_state.saved_secondary_data) > 0,
            "Pelingkupan DPH terisi": len(st.session_state.data_dampak) > 0,
            "Pelibatan masyarakat tercatat": len(st.session_state.data_sptm) > 0,
        }
        for label, ok in checks.items():
            st.write(("✅" if ok else "❌") + f" {label}")
        layak = all(checks.values())
        st.divider()
        if layak:
            st.success("🟢 **Seluruh gerbang terpenuhi — SKKL siap diterbitkan.**")
        else:
            st.warning("🟡 Beberapa gerbang belum terpenuhi. SKKL tetap dapat diterbitkan sebagai DRAF simulasi.")

        st.button(
            "📜 Terbitkan Draf SKKL Utuh",
            type="primary",
            width="stretch",
            key="btn_publish_skkl",
            on_click=cb_publish_skkl,
        )
        if st.session_state.get("skkl_log"):
            last_skkl = st.session_state.skkl_log[-1]
            last_path = os.path.join(REPORTS_DIR, last_skkl.get("berkas", ""))
            if os.path.exists(last_path):
                with open(last_path, "r", encoding="utf-8") as fh:
                    skkl_text = fh.read()
                st.balloons()
                with st.expander(f"📜 Pratinjau SKKL terakhir — {last_skkl.get('berkas')}", expanded=True):
                    st.code(skkl_text[:2200], language=None)
                st.download_button(
                    "⬇️ Unduh Draf SKKL (.txt)",
                    data=skkl_text.encode("utf-8"),
                    file_name=last_skkl.get("berkas", "SKKL.txt"),
                    mime="text/plain",
                    width="stretch",
                    key="dl_skkl_last",
                )

        if st.session_state.skkl_log:
            st.markdown("#### 🗂️ Log Penerbitan SKKL / Push OSS RBA")
            st.dataframe(pd.DataFrame(st.session_state.skkl_log), width="stretch", hide_index=True)

        st.markdown("#### 🔁 Alur Pasca-SKKL (OSS RBA → SLO)")
        st.markdown(
            "1. **SKKL Terbit** → sinkron ke portal OSS RBA (status: Izin Lingkungan Terbit)\n"
            "2. **Perizinan Berusaha** terbit otomatis berdasar NIB + SKKL\n"
            "3. **Persetujuan Teknis** (BMAL, Emisi, LB3) wajib dilengkapi sebelum operasi\n"
            "4. **Konstruksi** berjalan dengan pengawasan RKL-RPL\n"
            "5. **Uji Coba Operasi** → pengajuan **SLO** (Surat Layak Operasional)\n"
            "6. **Pelaporan RKL-RPL** berkala tiap 6 bulan ke DLH & OSS"
        )

# --------------------------------------------------------------------------- #
# 14. FOOTER
# --------------------------------------------------------------------------- #
st.divider()
st.caption(
    f"🌿 **DR Martin Amdal System v8.0** — System Architect & Penulis: **DR. Leo Martin** | "
    f"Sesi proyek aktif: `{st.session_state.current_project_id}` | Terakhir disimpan: "
    f"{datetime.now().strftime('%d %b %Y %H:%M:%S')} | Basis data lokal: `{BASE_DIR}`"
)
