# markitdown-local — Implementation Plan & System Design

> Web app lokal, seringan mungkin, untuk mengonversi dokumen (PDF, Word, PowerPoint, Excel, HTML, dll.) ke Markdown. Tanpa upload ke layanan pihak ketiga, tanpa limit per file, open source.

Status dokumen: **draft v0.1** · Dibuat: 2 Nov 2026 · Lisensi repo yang direncanakan: **MIT**

---

## 0. Ringkasan Keputusan

| Topik | Keputusan | Alasan singkat |
|---|---|---|
| Mesin konversi | **Microsoft MarkItDown** (MIT) sebagai inti | Satu pintu untuk banyak format, murni kode, ringan |
| Backend | **FastAPI + uvicorn** (Python) | Ringan, async upload, OpenAPI gratis |
| Frontend | **1 file `index.html` + vanilla JS + CSS**, tanpa build step, tanpa CDN | Offline-friendly, tidak ada Node/npm, ukuran kecil |
| Database | **Tidak ada** | Stateless; job disimpan di memori + folder temp dengan TTL |
| OCR / PDF scan | **Opsional**, terpisah via Docker Compose profile (`docling-serve`) | Menjaga image utama tetap kecil |
| Deploy | Docker Compose (utama) + `git clone` ke `/var/www` dengan systemd + nginx (alternatif) | Sesuai rencana kamu |
| Auth | Tidak ada secara default, bind ke `127.0.0.1` | Alat lokal; proteksi lewat reverse proxy bila di-expose |

**Catatan jujur tentang "konversi file apapun":** tidak ada converter yang benar-benar bisa mengubah *semua* file. Target realistis: semua format yang didukung MarkItDown ditambah jalur OCR opsional untuk scan. Format di luar itu harus ditolak dengan pesan yang jelas, bukan gagal diam-diam. Daftar format yang didukung ditampilkan di UI lewat `GET /api/formats`.

---

## 1. Requirements

### 1.1 Functional

- F1. Upload satu atau banyak file (drag & drop), konversi ke `.md`.
- F2. Unduh hasil per file, atau semua sekaligus sebagai `.zip`.
- F3. Pratinjau Markdown hasil (teks mentah; render opsional).
- F4. Status per file: antre, proses, selesai, gagal (dengan alasan).
- F5. Deteksi PDF scan; jika OCR tidak aktif, tampilkan peringatan jelas.
- F6. Endpoint API ramah `curl` untuk satu file (`POST /api/convert/sync`).
- F7. Ekstraksi gambar dari dokumen (opsional, default mati) ke folder aset di dalam zip hasil.

### 1.2 Non-functional

| Aspek | Target (belum diukur, validasi di M5) |
|---|---|
| Image Docker utama | di bawah ~300 MB (target) |
| RAM idle | di bawah ~150 MB (target) |
| Cold start | di bawah 3 detik |
| Dependensi frontend | 0 (tanpa npm) |
| Privasi | Tidak ada panggilan jaringan keluar saat konversi; file dihapus setelah TTL |
| Skala | 1 pengguna / tim kecil, ratusan file per batch |

### 1.3 Constraints

- Developer tunggal, nyaman dengan Python, bukan ahli ML.
- Harus bisa jalan di laptop biasa tanpa GPU.
- Repo open source: pilih dependensi berlisensi permisif (lihat §9).

### 1.4 Non-goals (v1)

- Multi-user, akun, riwayat permanen, database.
- Editor Markdown, sinkronisasi cloud.
- Konversi dua arah (md → docx/pdf).
- Antrean terdistribusi / multi-node.

---

## 2. Arsitektur Tingkat Tinggi

```
 Browser (index.html + app.js)
        │  multipart upload / polling / download
        ▼
 ┌────────────────────────────── container: app ──────────────────────────────┐
 │  FastAPI (1 proses uvicorn)                                                  │
 │   ├─ routes: /, /api/*, /healthz                                            │
 │   ├─ validator: ekstensi, magic bytes, ukuran, jumlah file                  │
 │   ├─ JobManager (dict di memori + folder DATA_DIR/jobs/<id>/)               │
 │   └─ ProcessPoolExecutor (WORKERS, default 2)                               │
 │         └─ router.py → converter per tipe file                              │
 │               ├─ markitdown (docx, pptx, xlsx, html, csv, json, xml, zip…)  │
 │               ├─ pdf: cek text layer → markitdown | (scan) → docling_client │
 │               └─ fallback: tolak dengan pesan "format tidak didukung"       │
 └──────────────────────────────────────────────────────────────┬──────────────┘
                                                                │ HTTP (opsional)
                                                                ▼
                                          container: docling (profile "ocr")
                                          docling-serve, MIT, hanya jika dipakai
```

### Alur data (satu batch)

```
POST /api/convert (N file)
  → validasi tiap file → simpan ke jobs/<id>/in/<uuid>.<ext>
  → buat Job{items[]} status=queued → return {job_id}
  → worker pool ambil item → router → tulis jobs/<id>/out/<nama>.md
  → item.status = done | failed(+error)
GET /api/jobs/<id>           → polling status (tiap ~1 dtk)
GET /api/jobs/<id>/download  → zip semua .md (+ assets/)
Janitor (tiap 5 mnt)         → hapus job lebih tua dari JOB_TTL_MIN
```

---

## 3. Keputusan Teknis & Trade-off

| Keputusan | Pilihan | Alternatif | Trade-off |
|---|---|---|---|
| Framework | FastAPI | Flask, Starlette murni | FastAPI menambah pydantic (sedikit lebih berat) tapi validasi + docs gratis. Starlette murni lebih ringan jika ukuran image jadi masalah. |
| Frontend | Vanilla JS | React/Vite, Gradio | Tanpa build step dan tanpa CDN; UI harus ditulis manual. Gradio dihindari karena berat. |
| Konkurensi | ProcessPool kecil | Thread, Celery/Redis | Konversi CPU-bound, proses terpisah menghindari GIL dan memungkinkan timeout/kill. Celery/Redis berlebihan untuk skala ini. |
| State | Memori + folder temp | SQLite | Sederhana, tapi job hilang saat restart dan **wajib 1 proses uvicorn**. SQLite bisa jadi upgrade jika butuh riwayat. |
| PDF scan | Docling-serve terpisah | Tesseract di image utama, Marker | Image utama tetap kecil; konsekuensinya butuh service kedua. Marker 2.x butuh server inferensi lokal dan bobot modelnya berlisensi terbatas, jadi bukan default. |
| Scan detection | `pdfminer.six` (dependensi MarkItDown) | PyMuPDF | PyMuPDF berlisensi AGPL/komersial; menghindarinya menjaga repo tetap MIT. Konsekuensi: heuristik dibuat sendiri dan lebih kasar. |
| Format lama (.doc/.xls/.ppt) | Tidak didukung di v1 | LibreOffice headless | LibreOffice menambah ratusan MB. Jadikan profile opsional di v2. |

---

## 4. Cakupan Format

Tingkat dukungan (nama extras MarkItDown harus **diverifikasi** terhadap `pyproject.toml` versi yang dipakai):

| Tingkat | Format | Mekanisme |
|---|---|---|
| **Inti (default)** | `.docx`, `.pptx`, `.xlsx`, `.html/.htm`, `.csv`, `.json`, `.xml`, `.txt/.md`, `.zip` | MarkItDown, tanpa AI |
| **PDF digital** | `.pdf` dengan text layer | MarkItDown (pdfminer.six) |
| **OCR (opsional)** | PDF scan, `.png/.jpg/.tiff` | `docling-serve` via profile `ocr` |
| **Ditunda** | `.doc/.xls/.ppt`, `.epub`, audio, video | v2 / plugin |
| **Ditolak** | Sisanya | Error jelas: "format tidak didukung" |

Fitur MarkItDown yang melakukan akses jaringan (konversi dari URL, YouTube) **dimatikan** di app ini (lihat §8).

---

## 5. Desain API

Semua di bawah `/api`. Respons JSON kecuali disebutkan.

| Method | Path | Fungsi |
|---|---|---|
| GET | `/healthz` | Liveness (`{"status":"ok","version":"…"}`) |
| GET | `/api/formats` | Daftar ekstensi didukung + apakah OCR aktif |
| POST | `/api/convert` | Multipart `files[]`, opsi `extract_images=false`. Return `{job_id}` (202) |
| GET | `/api/jobs/{id}` | Status job + item |
| GET | `/api/jobs/{id}/files/{item_id}` | Unduh satu `.md` (`text/markdown`) |
| GET | `/api/jobs/{id}/download` | Zip semua hasil |
| DELETE | `/api/jobs/{id}` | Hapus job lebih awal |
| POST | `/api/convert/sync` | Satu file, return `text/markdown` langsung (untuk `curl`) |

Contoh:

```bash
curl -F "file=@laporan.docx" http://127.0.0.1:8080/api/convert/sync > laporan.md
```

Bentuk respons job:

```json
{
  "id": "8f1c…",
  "status": "running",
  "items": [
    {"id": "a1", "name": "laporan.docx", "status": "done", "converter": "markitdown", "seconds": 0.8},
    {"id": "a2", "name": "scan.pdf", "status": "failed", "error": "PDF terdeteksi scan; OCR tidak aktif"}
  ]
}
```

### Model data (tanpa DB)

```python
@dataclass
class Item:  id: str; name: str; ext: str; status: str; error: str|None; converter: str|None; seconds: float|None
@dataclass
class Job:   id: str; created: float; items: list[Item]   # status diturunkan dari items
```

---

## 6. Konfigurasi (environment variables)

| Variabel | Default | Fungsi |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8080` | Alamat bind |
| `DATA_DIR` | `/data` | Folder kerja job |
| `MAX_FILE_MB` | `50` | Batas ukuran per file |
| `MAX_FILES` | `50` | Batas file per batch |
| `WORKERS` | `2` | Jumlah proses konversi |
| `CONVERT_TIMEOUT_S` | `120` | Timeout per file |
| `JOB_TTL_MIN` | `60` | Umur job sebelum dihapus |
| `DOCLING_URL` | *(kosong)* | Jika diisi, PDF scan/gambar dikirim ke sini |

---

## 7. Struktur Repository

```
markitdown-local/
├─ app/
│  ├─ main.py            # FastAPI app, routes
│  ├─ config.py          # baca env
│  ├─ jobs.py            # JobManager, janitor TTL
│  ├─ router.py          # pilih converter per ekstensi + fallback
│  ├─ converters/
│  │   ├─ markitdown_conv.py
│  │   ├─ pdf.py         # is_scanned() + routing ke docling_client
│  │   └─ docling_client.py
│  ├─ validate.py        # ekstensi, magic bytes, ukuran
│  └─ static/
│      ├─ index.html
│      ├─ app.js
│      └─ style.css
├─ tests/
│  ├─ fixtures/          # file contoh kecil per format
│  └─ test_*.py
├─ deploy/
│  ├─ markitdown-local.service   # systemd
│  └─ nginx.conf.example
├─ Dockerfile
├─ docker-compose.yml
├─ pyproject.toml        # dikelola dengan uv
├─ .env.example
├─ LICENSE               # MIT
├─ README.md
└─ PLAN.md               # dokumen ini
```

---

## 8. Keamanan

Ancaman utama untuk alat lokal yang memproses file tak tepercaya:

1. **Hak akses proses.** MarkItDown berjalan dengan hak proses pemanggil. Gunakan API sempit (`convert_local` / `convert_stream`), jangan `convert()` yang menerima URL.
2. **SSRF.** Matikan konversi URL/YouTube; app hanya menerima file upload.
3. **Zip bomb / file raksasa.** Batasi ukuran upload, jumlah file, ukuran total hasil ekstraksi `.zip`, dan timeout per file; worker yang melewati timeout dihentikan.
4. **Path traversal.** Simpan file dengan nama `uuid.ext`; nama asli hanya untuk tampilan dan nama unduhan (disanitasi).
5. **XSS lewat pratinjau.** Tampilkan Markdown sebagai teks (`textContent`). Jika nanti ada render HTML, sanitasi dulu. Mammoth sendiri tidak melakukan sanitasi.
6. **Eksposur jaringan.** Default bind `127.0.0.1`. Jika di-expose, pasang basic auth / SSO di reverse proxy dan HTTPS.
7. **Container hardening.** User non-root, `read_only: true` dengan `tmpfs` untuk `/data`, batas memori dan CPU di Compose, tanpa `privileged`.
8. **Privasi.** Tanpa telemetri; catat log tanpa isi dokumen; hapus file saat TTL habis.

---

## 9. Lisensi & Dependensi

Repo: **MIT**. Dependensi inti dipilih agar tetap kompatibel:

| Komponen | Lisensi | Catatan |
|---|---|---|
| MarkItDown | MIT | Versi terverifikasi di riset: 0.1.9 (PyPI, 2 Nov 2026) |
| FastAPI, uvicorn | MIT / BSD | |
| docling-serve (opsional) | MIT | Lisensi bobot model **belum diverifikasi**; periksa sebelum dibundel |
| PyMuPDF | AGPL-3.0 / komersial | **Jangan** masukkan ke core jika repo ingin tetap MIT |
| Pandoc | GPL-2.0+ (belum diverifikasi ulang) | Tidak dipakai di v1; jika ditambah, panggil sebagai subprocess |
| Marker | Kode Apache-2.0, bobot terbatas | Tidak dipakai di v1 |

Tambahkan `THIRD_PARTY_LICENSES.md` dan pin versi di `uv.lock`.

---

## 10. Deployment

### 10.1 Docker Compose (direkomendasikan)

`Dockerfile` (sketsa, belum diuji):

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv && useradd -m -u 10001 app
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
USER app
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uv","run","uvicorn","app.main:app","--host","0.0.0.0","--port","8080","--workers","1"]
```

`docker-compose.yml` (sketsa):

```yaml
services:
  app:
    build: .
    ports: ["127.0.0.1:8080:8080"]
    environment:
      DATA_DIR: /data
      MAX_FILE_MB: "50"
      WORKERS: "2"
      DOCLING_URL: ${DOCLING_URL:-}
    tmpfs: ["/data"]
    read_only: true
    mem_limit: 1g
    restart: unless-stopped

  docling:                      # hanya jalan dengan: docker compose --profile ocr up
    image: quay.io/docling-project/docling-serve-cpu:latest   # verifikasi nama image & tag
    profiles: ["ocr"]
    ports: ["127.0.0.1:5001:5001"]
    mem_limit: 4g
    restart: unless-stopped
```

Pemakaian:

```bash
docker compose up -d                       # mode ringan (tanpa OCR)
DOCLING_URL=http://docling:5001 docker compose --profile ocr up -d   # dengan OCR
```

### 10.2 `git clone` ke `/var/www` (tanpa Docker)

`/var/www` lazimnya untuk PHP/static; aplikasi Python tetap butuh process manager. Pola yang disarankan: nginx menyajikan reverse proxy ke uvicorn yang dijalankan systemd.

```bash
sudo git clone https://github.com/<user>/markitdown-local /var/www/markitdown-local
cd /var/www/markitdown-local && sudo uv sync --frozen --no-dev
sudo cp deploy/markitdown-local.service /etc/systemd/system/
sudo systemctl enable --now markitdown-local
```

Unit systemd (sketsa): `User=www-data`, `WorkingDirectory=/var/www/markitdown-local`, `ExecStart=… uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1`, `Environment=DATA_DIR=/var/tmp/markitdown-local`, plus `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`.

Nginx: `proxy_pass http://127.0.0.1:8080;`, `client_max_body_size 100m;`, `proxy_read_timeout 300s;`, dan basic auth jika diakses dari luar mesin.

---

## 11. Implementation Plan

Estimasi untuk satu developer; sesuaikan dengan waktumu.

### M0 — Skeleton & riset kecil (0,5 hari)
- [ ] Inisialisasi repo, `uv init`, lisensi MIT, `.gitignore`, `.env.example`
- [ ] `uv add markitdown fastapi uvicorn python-multipart` lalu cek nama extras yang benar (`pdf`, `docx`, `pptx`, `xlsx`) di `pyproject.toml` MarkItDown
- [ ] Skrip percobaan: konversi 1 file tiap format, catat dependensi yang benar-benar dibutuhkan
- **Selesai jika:** kamu punya daftar dependensi minimal dan tahu format mana yang jalan.

### M1 — Core converter (1 hari)
- [ ] `router.py`: peta ekstensi → fungsi, fallback, error terstandar
- [ ] `validate.py`: ekstensi + magic bytes + batas ukuran
- [ ] `pdf.py`: `is_scanned()` berbasis jumlah karakter per halaman via pdfminer.six
- [ ] Unit test per format dengan fixture kecil
- **Selesai jika:** `python -m app.router file.ext` menghasilkan `.md` untuk semua format inti.

### M2 — API & job manager (1 hari)
- [ ] `ProcessPoolExecutor`, timeout per file, pembersihan proses macet
- [ ] `/api/convert`, `/api/jobs/*`, `/api/convert/sync`, zip download
- [ ] Janitor TTL, batas `MAX_FILES` dan `MAX_FILE_MB`
- **Selesai jika:** upload 20 file campuran via `curl` menghasilkan zip yang benar, satu file rusak tidak menghentikan batch.

### M3 — Frontend ringan (1 hari)
- [ ] Drag & drop, daftar file, status per item, polling
- [ ] Unduh per file / zip, pratinjau teks, pesan error yang ramah
- [ ] Mode gelap otomatis (`prefers-color-scheme`), layout responsif
- **Selesai jika:** semua alur utama berjalan tanpa request ke domain eksternal (cek tab Network).

### M4 — OCR opsional (0,5–1 hari)
- [ ] `docling_client.py` (HTTP ke `DOCLING_URL`), timeout dan retry sederhana
- [ ] Routing: PDF scan dan gambar → Docling jika aktif; jika tidak, error yang jelas
- [ ] Uji bahasa Indonesia + Inggris; catat akurasi nyata (belum diketahui)
- **Selesai jika:** PDF scan 5 halaman menghasilkan teks yang terbaca via profile `ocr`.

### M5 — Docker, hardening, pengukuran (1 hari)
- [ ] Dockerfile multi-stage, non-root, `read_only`, healthcheck
- [ ] Compose dengan profile `ocr`
- [ ] Ukur: ukuran image, RAM idle, waktu start, throughput 50 file; perbarui tabel §1.2
- [ ] Uji batas: file 0 byte, file korup, zip bomb, nama file berbahaya
- **Selesai jika:** target §1.2 tercapai atau angka riilnya dicatat di README.

### M6 — Rilis open source (0,5 hari)
- [ ] README (demo GIF, quick start, tabel format, konfigurasi, keamanan)
- [ ] `CONTRIBUTING.md`, template issue, GitHub Actions (lint + test + build image)
- [ ] `THIRD_PARTY_LICENSES.md`, tag `v0.1.0`, publikasi image ke GHCR (opsional)
- **Selesai jika:** orang lain bisa `git clone` lalu `docker compose up -d` dan berhasil.

---

## 12. Strategi Pengujian

| Level | Isi |
|---|---|
| Unit | Router, validator, `is_scanned()`, sanitasi nama file |
| Integrasi | Upload multi-file → job selesai → isi zip benar (pakai `httpx` + TestClient) |
| Fixture | 1 file kecil per format + kasus sulit (tabel gabung sel, PDF 2 kolom, PDF scan, file korup) |
| Keamanan | Path traversal, file besar, zip bomb, timeout |
| Smoke Docker | `docker compose up` lalu `curl /healthz` dan konversi satu file |
| Manual | 20–50 dokumen nyata milikmu yang paling sulit; bandingkan hasil antar jalur |

Kualitas Markdown sulit diuji otomatis; gunakan *golden file* untuk regresi dan terima bahwa ada perubahan akibat upgrade MarkItDown.

---

## 13. Observability (minimal)

- Log JSON ke stdout: `job_id`, `ext`, `converter`, `seconds`, `status` (tanpa isi dokumen).
- `/healthz` untuk healthcheck; opsional `/metrics` sederhana (jumlah job, error) jika dibutuhkan.
- Tidak ada Prometheus/Grafana di v1.

---

## 14. Risiko & Hal yang Belum Terverifikasi

| Item | Status | Tindakan |
|---|---|---|
| Nama extras MarkItDown | Dari ingatan | Cek `pyproject.toml` di M0 |
| Ukuran image dan RAM | Hanya target | Ukur di M5 |
| Nama image + tag `docling-serve` | Perlu dicek | Verifikasi di registry sebelum M4 |
| Lisensi bobot model Docling | Belum diverifikasi | Baca model card sebelum merekomendasikan |
| Akurasi OCR bahasa Indonesia | Tidak diketahui | Uji di M4 |
| Kompatibilitas plugin OCR MarkItDown dengan model lokal | Belum diverifikasi | Opsional, di luar v1 |
| Kualitas tabel rumit dan kolom ganda di jalur kode | Dapat gagal | Sediakan tombol "paksa Docling" per file di v2 |
| Semua sketsa kode di dokumen ini | **Belum dijalankan** | Perlakukan sebagai titik awal |

---

## 15. Yang Akan Ditinjau Ulang Saat Berkembang

1. **State di memori** → pindah ke SQLite bila butuh riwayat atau multi-proses.
2. **ProcessPool** → antrean persisten bila job panjang sering terputus restart.
3. **Format lama (.doc/.xls/.ppt)** → profile LibreOffice headless.
4. **Auth** → login sederhana bila dipakai tim.
5. **Pasca-proses** → bersihkan header/footer berulang, front matter YAML, penamaan gambar.
6. **Jalur VLM/GPU** → opsi Granite-Docling atau model OCR lain bila akurasi kurang.
7. **CLI** → `markitdown-local convert folder/ out/` memakai router yang sama.

---

## 16. Definition of Done (v0.1.0)

- [ ] `docker compose up -d` jalan di mesin bersih tanpa langkah tambahan
- [ ] Semua format inti (§4) lolos tes fixture
- [ ] Batch 50 file campuran selesai tanpa crash, error per file ditampilkan
- [ ] Tidak ada request jaringan keluar saat konversi (diverifikasi)
- [ ] Target ukuran/RAM tercapai atau angka riil didokumentasikan
- [ ] README, LICENSE, THIRD_PARTY_LICENSES, CI hijau
