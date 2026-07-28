# PolyEdge — Whitepaper

**AGI Trading System untuk Prediction Markets**

| Metadata | |
|---|---|
| Dokumen | Whitepaper v1.1 |
| Tanggal | 2026-07-01 |
| Produk | [PolyEdge](https://polyedge.aitradepulse.com) |
| DOI | [10.5281/ZENODO.16966978](https://doi.org/10.5281/ZENODO.16966978) |
| Ekosistem | [BerkahKarya](https://berkahkarya.org) |
| Status | **Live in Production** |

---

## Ringkasan Eksekutif

PolyEdge adalah Sistem Trading AGI (Artificial General Intelligence) untuk prediction markets — Polymarket, Kalshi, dan venue lainnya. Berbeda dari bot trading konvensional yang menjalankan aturan tetap, PolyEdge menjalankan **loop riset terkendali**: membentuk hipotesis trading, menantangnya lewat debat multi-model, mengeksekusi hanya melalui gerbang risiko deterministik, mendiagnosis kegagalan, dan menggabungkan strategi yang bertahan ke generasi berikutnya.

Dengan 14+ strategi aktif, 641+ trade terlacak, dan paper riset ber-DOI, PolyEdge adalah salah satu sistem trading AGI otonom pertama yang beroperasi di prediction markets dengan tata kelola yang dapat diaudit.

**Market Context:** Prediction markets global tumbuh cepat pasca Pemilu AS 2024 ($3.7B volume Polymarket 2024). Indonesia sendiri memiliki 21.37 juta investor crypto terdaftar (OJK, Mar 2026) — base pengguna yang sangat relevan untuk adopsi prediction market ke depan.

---

## 1. Masalah

### 1.1 Bot Trading Konvensional Gagal di Rezim Dinamis

Strategi trading statis — bahkan yang di-backtest dengan baik — memiliki kelemahan fundamental:

| Masalah | Dampak |
|---|---|
| **Rezim pasar berubah** | Strategi yang profit di trending market hancur di ranging market |
| **Tidak ada adaptasi** | Bot terus menjalankan logika yang sudah obsolete |
| **Black box** | Tidak ada cara untuk memahami mengapa bot mengambil keputusan |
| **Overfitting** | Backtest bagus ≠ live trading bagus |

Prediction markets (Polymarket, Kalshi) memiliki karakteristik unik: event-driven, finite lifetime, dan dipengaruhi oleh faktor eksternal (berita, cuaca, flow CEX). Bot statis tidak bisa menangani ini.

### 1.2 Allocator Butuh Audit, Bukan Janji

Institusi yang ingin mengalokasi modal ke prediction markets menghadapi masalah:

- Bot trading biasanya **black box** — tidak ada cara verifikasi
- Track record mudah difabrikasi
- Tidak ada pemisahan antara sinyal, eksekusi, dan risk management
- Regulasi membutuhkan **jejak audit** yang jelas

### 1.3 Gap: Prediksi vs. Eksekusi

Bot yang ada di pasaran (Pionex, GoodCryptoX, Bitsgap, 3Commas) fokus pada **eksekusi** — DCA bot, grid bot, rebalancing. Tidak ada yang membangun siklus **riset → debat → eksekusi → forensik → evolusi** secara otonom. PolyEdge mengisi gap ini.

---

## 2. Solusi: PolyEdge AGI System

### 2.1 Arsitektur

```
                     ┌─────────────────────────┐
                     │      Market Feeds        │
                     │  Polymarket · Kalshi ·   │
                     │  CEX (BTC/USD) · Weather │
                     └───────────┬─────────────┘
                                 │
                     ┌───────────▼─────────────┐
                     │    Signal Engine         │
                     │  14+ Active Strategies    │
                     └───────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
     │  MiroFish    │   │  MiroFish    │   │  MiroFish    │
     │  Bull Agent  │   │  Bear Agent  │   │  Judge Agent │
     └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
            └──────────────────┼──────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Debate Consensus   │
                    │  (validasi atau      │
                    │   reject proposal)  │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │   Risk Gate          │
                    │  · Position sizing   │
                    │  · Bankroll mgmt     │
                    │  · Correlated exp    │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │   Execution Layer    │
                    │  · Order attempt     │
                    │  · Settlement        │
                    │  · Forensics         │
                    └─────────────────────┘
```

### 2.2 Strategy Lifecycle

Setiap strategi melewati tahapan ketat:

```
DRAFT → SHADOW → PAPER → LIVE → REVIEW → RETIRE/PROMOTE
```

| Tahap | Aktivitas | Gate |
|---|---|---|
| **DRAFT** | AGI menciptakan strategi baru (mutation dari yang ada) | Peer review |
| **SHADOW** | Berjalan paralel tanpa eksekusi — mengumpulkan data | Shadow profit check |
| **PAPER** | Trading simulated dengan modal virtual | 14+ hari paper trading |
| **LIVE** | Trading dengan modal real (risk-gated) | Risk gate approval |
| **REVIEW** | Forensik periodik — diagnosa loss/promosi | Health check |

### 2.3 MiroFish: Multi-Agent Debate

Sebelum trade dieksekusi, tiga agen AI berdebat:

1. **Bull Agent** — Membuat argumen mengapa trade ini bagus
2. **Bear Agent** — Membuat argumen mengapa trade ini buruk
3. **Judge Agent** — Memutuskan berdasarkan bukti dari kedua sisi

Ini memastikan setiap trade memiliki **lawan yang dapat diperiksa** — tidak ada keputusan tanpa validasi.

### 2.4 Risk Management Deterministik

| Komponen | Mekanisme |
|---|---|
| **Position Sizing** | Kelly Criterion dengan fraksi konservatif (5% max per posisi) |
| **Bankroll Management** | Alokasi dinamis berdasarkan confidence score |
| **Correlated Exposure** | Maksimal 50% exposure ke correlated markets |
| **Drawdown Limit** | 20% max drawdown per strategi — auto-kill jika breach |
| **Circuit Breakers** | Mode switch: PAPER → LIVE, manual override |

---

## 3. Traction

| Metrik | Nilai |
|---|---|
| **Strategi** | 14+ registered + AGI Orchestrator |
| **Trade Terlacak** | 641 (keputusan, order attempt, settlement) |
| **Eksperimen Otonom** | 25 kandidat lifecycle |
| **Paper Riset** | 33h — 15 referensi + suplemen |
| **Mode Operasi** | Paper · Testnet · Live |
| **DOI** | 10.5281/ZENODO.16966978 |
| **Dashboard** | Live — polyedge.aitradepulse.com |

**Market Context:**
- Prediction markets global: $3.7B volume Polymarket (2024), tumbuh exponensial pasca Pemilu AS
- Indonesia: 21.37 juta investor crypto terdaftar (OJK Mar 2026) — base pengguna relevan
- Regulasi OJK (POJK 27/2024) legitimasi aset kripto sebagai instrumen keuangan digital

---

## 4. Perbandingan

| Fitur | **PolyEdge** | Bot Konvensional | Trading Manual |
|---|---|---|---|
| **Adaptasi Rezim** | ✅ AGI | ❌ Fixed rules | ❌ Reaktif |
| **Multi-Model Validasi** | ✅ MiroFish debate | ❌ | ❌ |
| **Audit Trail** | ✅ Setiap trade | ❌ Black box | ❌ |
| **Risk Gate** | ✅ Deterministic | Opsional | Subjektif |
| **Paper → Live** | ✅ Tahapan gate | ❌ Langsung live | ❌ |
| **DOI Publication** | ✅ | ❌ | ❌ |

**vs. Bot Platforms (Pionex, GoodCryptoX, Bitsgap, Zignaly):**
- Mereka: DCA/grid bot — aturan tetap, personal use only
- PolyEdge: AGI yang berevolusi, allocator-grade, audit trail lengkap

---

## 5. Roadmap

| Phase | Timeline | Milestone |
|---|---|---|
| **V1 — AGI Core** | ✅ | Strategy factory, lifecycle, MiroFish |
| **V2 — Dashboard** | ✅ | Multi-language UI (EN/ID/RU/CH), real-time monitoring |
| **V3 — Multi-Venue** | Q3 2026 | Kalshi full integration, copy trading |
| **V4 — Institutional** | Q1 2027 | Allocator portal, audit reports, compliance framework |

---

## 6. Regulasi

PolyEdge beroperasi sebagai **SaaS infrastruktur riset dan eksekusi**:

- Tidak mengelola dana pihak ketiga
- Tidak menjanjikan return
- Semua keputusan trading terekam dalam audit trail
- Dirancang untuk memenuhi kebutuhan due diligence institusional
- Beroperasi di prediction markets (bukan sekuritas) — risiko regulasi lebih rendah
- Framework OJK sandbox (POJK 3/2024) tersedia jika perlu registrasi ke depan

---

## 7. Tim

Dibangun oleh **BerkahKarya** — 1-man AI company dengan 13 layanan otonom. 
$0 VC funding. 6 revenue streams. Produk live.

---

*Dokumen ini disusun oleh BerkahKarya AI Ecosystem. Paper riset lengkap: [DOI 10.5281/ZENODO.16966978](https://doi.org/10.5281/ZENODO.16966978)*
