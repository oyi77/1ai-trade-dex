# Vilona Trade FX — Whitepaper

**AI-Powered Trading Infrastructure untuk Forex, Crypto, dan Komoditas**

| Metadata | |
|---|---|
| Dokumen | Whitepaper v1.0 |
| Tanggal | 2026-07-01 |
| Produk | [Vilona Trade FX](https://phantomfx.aitradepulse.com) |
| Ekosistem | [BerkahKarya](https://berkahkarya.org) |
| Status | **Live in Production** |

---

## Ringkasan Eksekutif

Vilona Trade FX adalah infrastruktur trading automation berbasis AI yang menyediakan signal generation, risk management, dan eksekusi otomatis untuk pasar Forex, Crypto, dan Komoditas. Tidak seperti platform trading AI yang mengelola dana pengguna secara terpusat (model pool-of-funds), Vilona beroperasi sebagai **SaaS white-label** — pengguna tetap memegang kendali penuh atas dana mereka di broker/exchange masing-masing.

Model ini identik dengan Capitalise.ai ($18.8M funding, diakuisisi Kraken 2025): **platform teknologilah yang dijual, bukan return trading**. Perbedaan utama: Vilona menggunakan 3 model AI (DeepSeek, GPT-4o, Claude) yang melakukan voting paralel untuk memvalidasi setiap sinyal, plus integrasi MT5 Bridge untuk eksekusi langsung.

---

## 1. Masalah

### 1.1 Trader Retail vs. Pasar Keuangan

Mayoritas trader retail di Indonesia dan emerging market menghadapi tiga masalah utama yang konsisten menyebabkan kerugian:

| Masalah | Dampak |
|---|---|
| **Overtrading emosional** | Trader membuka posisi berulang setelah rugi (revenge trading), memperbesar loss |
| **Ketidakhadiran analisa** | Harga bergerak saat trader tidur/sibuk — peluang terlewat, posisi kebobolan |
| **Manajemen risiko buruk** | SL/TP ditentukan asal-asalan, risk/reward ratio tidak diperhitungkan |

Data menunjukkan bahwa **80-90% trader retail kehilangan uang** dalam 6 bulan pertama — bukan karena strategi buruk, tapi karena faktor emosional dan operasional.

### 1.2 Kegagalan Model "Signal Group" Tradisional

Grup sinyal Telegram manual memiliki kelemahan struktural:

- Admin grup tidak bisa 24/7
- Sinyal subjektif — berdasarkan "feeling" bukan analisis terstruktur
- Tidak ada risk/reward yang terukur
- Tidak ada integrasi broker — user harus ketik manual, rawan human error
- Tidak ada accountability — profit/loss tidak terverifikasi

### 1.3 Gap di Pasar Infrastruktur

Platform trading automation yang ada di Indonesia masih terbatas:

- **Capitalise.ai** — tidak support broker Indonesia, bahasa Inggris, harga $50+/bulan
- **3Commas/HaasOnline** — kompleksitas tinggi, cocok untuk power user
- **Platform kustom** — mahal (Rp 50-200 juta) dan butuh maintenance tim IT

Vilona mengisi gap: **AI trading infrastructure yang accessible, terjangkau, dan white-label-ready** untuk pasar Indonesia dan emerging market.

---

## 2. Solusi

### 2.1 Arsitektur Sistem

```
┌──────────────────────────────────────────────────────────────┐
│                     USER LAYER                                │
│  Telegram Bot   │   Dashboard   │   MT5 EA / Bridge           │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                     AI ANALYSIS LAYER                         │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │  DeepSeek   │  │   GPT-4o   │  │   Claude    │           │
│  │  (Analyst 1)│  │ (Analyst 2)│  │ (Analyst 3) │           │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘           │
│         └────────────────┼────────────────┘                   │
│                    ▼     ▼     ▼                              │
│               Voting Consensus (2/3)                          │
│                                                               │
│  6-Layer Quality Gate — filter volatilitas rendah,            │
│  konfirmasi trend, validasi support/resistance                │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                     EXECUTION LAYER                           │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐     │
│  │                    MT5 Bridge                         │     │
│  │  Signal → EA Bridge → MetaTrader 5 → Broker          │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                               │
│  User dapat memilih: Manual (via Telegram) atau Auto (via EA) │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 Multi-AI Voting System

Setiap sinyal trading melewati proses validasi oleh **tiga model AI independen**:

1. **DeepSeek V3** — Analisis teknikal, pola harga, struktur market
2. **GPT-4o** — Analisis sentimen, korelasi antar pasar, berita ekonomi
3. **Claude 3.5 Sonnet** — Analisis makro, risk assessment, validasi SMC

**Aturan voting:** Minimum 2/3 model harus setuju sebelum sinyal dikirim. Ini mencegah false positive dari satu model dan meningkatkan probability of success.

### 2.3 6-Layer Quality Gate

Sebelum sinyal sampai ke pengguna, sistem memfilter melalui 6 lapisan:

1. **Volatility Filter** — Tolak pasangan dengan volatilitas terlalu rendah/tinggi
2. **Trend Confirmation** — Verifikasi arah trend di multiple timeframes
3. **SMC Validation** — Smart Money Concept: konfirmasi liquidity zone
4. **Risk/Reward Gate** — Tolak sinyal dengan RR < 1:1.5
5. **Correlation Check** — Hindari sinyal redundan pada pair terkait
6. **Timing Gate** — Optimal entry window berdasarkan sesi trading

### 2.4 Risk Management Terstruktur

Setiap sinyal dikirimkan dengan parameter risiko eksplisit:

- **Entry Zone** — Range harga entry optimal (bukan single price)
- **Stop Loss** — Posisi di area ekstrim likuiditas (SMC)
- **Take Profit 1 & 2** — Partial take-profit untuk mengunci keuntungan
- **Risk/Reward Ratio** — Wajib ≥ 1:1.5, rata-rata 1:2.5
- **Position Size Recommendation** — Berdasarkan akun balance dan risk tolerance

---

## 3. Model Bisnis

### 3.1 Revenue Streams

| Stream | Model | Harga |
|---|---|---|
| **PRO Subscription** | Sinyal AI Forex & Crypto, akses manual | Rp 79.900/bln |
| **ELITE Subscription** | Semua PRO + Emas/Minyak + 1 Whitelabel Bot + MT5 Bridge | Rp 149.900/bln |
| **LIFETIME** | Akses selamanya + 3 Whitelabel Bot + prioritas | Rp 1.990.900 |
| **Whitelabel Commission** | 10% komisi hingga 3 level referral | B2B |

### 3.2 Whitelabel Model (Capitalise Playbook)

Inti skalabilitas Vilona ada di model whitelabel:

- Partner (trader/agency) bisa membuat **bot dengan brand sendiri**
- Server, AI, dan infrastructure dikelola Vilona — partner **zero maintenance**
- Setiap pelanggan yang direkrut partner memberi komisi 10% × 3 level
- Simulasi: 100 pelanggan × Rp 79.900 = **Rp 7.990.000/bulan passive income** per partner

Ini membuat Vilona menjual **infrastruktur**, bukan return. Mirip Capitalise yang white-label ke broker.

### 3.3 Unit Economics

| Metrik | Nilai |
|---|---|
| **CAC (estimasi awal)** | ~Rp 0 (organic Telegram, referral) |
| **CAC (dengan iklan)** | Rp 15.000 - 25.000 per user |
| **ARPU (PRO)** | Rp 79.900/bln |
| **ARPU (ELITE)** | Rp 149.900/bln |
| **LTV (asumsi 8 bulan)** | Rp 639.200 - 1.199.200 |
| **Gross Margin** | ~80% (server + AI API cost) |
| **Infrastructure Cost/user** | ~Rp 15.000/bln |

---

## 4. Perbandingan Pasar

### 4.1 Competitive Landscape

| Fitur | **Vilona** | Capitalise.ai | 3Commas | Grup Sinyal |
|---|---|---|---|---|
| **Harga** | Rp 79.900 | $50+ | $29+ | Rp 50-500K |
| **Bahasa Indonesia** | ✅ | ❌ | ❌ | ✅ |
| **Multi-AI Voting** | ✅ 3 Model | ❌ | ❌ | ❌ |
| **MT5 Integration** | ✅ Bridge | ✅ | ✅ | ❌ |
| **Whitelabel** | ✅ | ✅ (B2B) | ❌ | ❌ |
| **Risk Gate (≥1:1.5)** | ✅ Wajib | ❌ | Opsional | ❌ |
| **24/7 Analysis** | ✅ AI | ✅ | ❌ | ❌ |
| **Komisi Partner** | ✅ 3 level | ❌ | ❌ | Opsional |
| **Pembayaran Lokal** | ✅ GoPay/QRIS | ❌ | ❌ | ✅ |

### 4.2 Market Positioning

Vilona Trade FX bukan:
- ❌ **Bukan** platform investasi dengan janji return (%)
- ❌ **Bukan** robot trading yang "pasti profit"
- ❌ **Bukan** MAM/PAMM/manager fund

Vilona adalah:
- ✅ **Infrastruktur AI trading** — seperti Capitalise untuk pasar Indonesia
- ✅ **Tool analisis** — probabilitas, bukan kepastian
- ✅ **Platform whitelabel** — partner bisa jual dengan brand sendiri
- ✅ **Risk management first** — setiap sinyal terukur

### 4.3 Kompetitor Global & Diferensiasi

Selain Capitalise.ai dan 3Commas, lanskap kompetitor global yang relevan:

| Platform | Tipe | AI Multi-Model | Whitelabel | Risk Gate Wajib |
|---|---|---|---|---|
| **Vilona Trade FX** | AI Infrastructure | ✅ 3 model voting | ✅ Ya | ✅ Wajib &#8805;1:1.5 |
| **Pionex** | Exchange Bot | ❌ Grid/DCA only | ❌ | ❌ |
| **GoodCryptoX** | Telegram Bot | ❌ Single signal | ❌ | ❌ |
| **Bitsgap** | Grid + Arbitrage | ❌ No AI voting | ❌ | Opsional |
| **Zignaly** | Copy Trading | ❌ Community-based | ✅ Ya | ❌ |

**Diferensiasi utama Vilona:**
1. **Multi-AI Voting (3 model)** — Bukan grid/DCA bot kaku, tapi analisis paralel oleh DeepSeek, GPT-4o, dan Claude dengan mekanisme konsensus 2/3 untuk validasi setiap sinyal sebelum dikirimkan ke user
2. **Whitelabel Infrastructure** — Partner dapat membuat bot dengan brand sendiri, zero maintenance, komisi 3 level — model Capitalise untuk pasar Indonesia
3. **Risk Gate Wajib** — Setiap sinyal wajib melewati 6-layer quality gate dengan minimum risk/reward 1:1.5, bukan fitur opsional — perlindungan konsisten untuk semua user

---

## 5. Traction & Milestone

| Metrik | Nilai |
|---|---|
| **Telegram Bot Users** | Live — [@berkahkaryaforexbotbot](https://t.me/berkahkaryaforexbotbot) |
| **MT5 Bridge** | Production — error 4756 resolved |
| **Broker Integration** | Exness, IC Markets (+ broker MT5 lainnya) |
| **Backtesting** | XAUUSD M15 — multiple win rate scenarios |
| **AI Models** | DeepSeek + GPT-4o + Claude — voting live |
| **Platform Status** | **phantomfx.aitradepulse.com** ✅ Live |

### 5.1 Roadmap

| Phase | Timeline | Milestone |
|---|---|---|
| **V1 — MVP** | ✅ Rilis | Telegram bot + sinyal AI manual |
| **V2 — Bridge** | ✅ Live | MT5 EA Bridge eksekusi otomatis |
| **V3 — Whitelabel** | ✅ Live | Multi-bot, komisi partner, brand kustom |
| **V4 — Scale** | Q3 2026 | 500+ active subscribers, B2B partnerships |
| **V5 — Broker API** | Q4 2026 | Direct broker API integration (tanpa MT5) |
| **V6 — Institutional** | Q1 2027 | Licensing ke broker/Platform putih untuk institusi |


### 5.2 Market Context

Vilona beroperasi di pasar dengan pertumbuhan eksponensial:

- **21,37 juta pengguna kripto terdaftar** di Indonesia (OJK, Maret 2026) — naik dari 14,16 juta (April 2025), pertumbuhan **+50% dalam 11 bulan**
- **Volume transaksi kripto 2025 mencapai Rp482,23 triliun** — menunjukkan adopsi massal yang terus meningkat
- **TAM Vilona** mencakup puluhan juta trader retail di Indonesia dan emerging market — total pasar tumbuh **+50% YoY**
---

## 6. Regulasi & Kepatuhan

Vilona Trade FX beroperasi dalam kerangka **SaaS infrastruktur**, bukan pengelolaan dana:

1. **Tidak memegang dana user** — User deposit di broker mereka sendiri
2. **Tidak menjanjikan return** — Semua indikasi "profit" adalah simulasi/backtest
3. **Tidak memberikan advice personal** — Sinyal adalah data analisis, bukan rekomendasi
4. **Disclaimer risiko eksplisit** — Setiap interaksi menampilkan peringatan risiko


### 6.1 Kerangka Regulasi Terkini

**POJK 3/2024 tentang ITSK** (Inovasi Teknologi Sektor Keuangan):
- Mengatur penyelenggaraan inovasi teknologi di sektor keuangan Indonesia
- Mewajibkan pelaku ITSK terdaftar di OJK melalui mekanisme **Regulatory Sandbox**
- Sandbox berlaku maksimal **1 tahun masa uji coba**, dapat diperpanjang dengan evaluasi
- Peserta sandbox harus memiliki: rencana uji coba, kebaruan/manfaat, dan kesiapan infrastruktur

**POJK 27/2024 tentang Aset Kripto sebagai Instrumen Keuangan Digital**:
- Menetapkan aset kripto sebagai **instrumen keuangan digital** yang diatur OJK
- Peralihan pengawasan dari Bappebti ke OJK untuk aset kripto
- Menetapkan persyaratan untuk penyelenggara perdagangan aset kripto
- **31 entitas berlisensi** di bawah OJK per April 2026

**Catatan:** Forex masih di bawah Bappebti dan belum beralih ke OJK.

### 6.2 Posisi Vilona vs. Kompetitor Bermasalah

Berbeda dengan platform yang bermasalah secara regulasi:
- **AlgosOne.ai** — Pool of funds + janji return &#8594; blacklist FSMA Belgia (HYIP)
- **Robot trading ilegal** — Menjanjikan profit tetap &#8594; ranah OJK/Bappebti

Vilona tetap pada posisi SaaS infrastruktur yang tidak memerlukan izin pengelolaan dana. Namun, untuk jangka panjang, pendaftaran di **OJK Innovation Hub / Regulatory Sandbox** akan menjadi diferensiator kompetitif.

**Keamanan API Key:** Vilona hanya membutuhkan izin trading (no withdrawal access) — dana user tetap aman di broker masing-masing.
---

## 7. Tim

**BerkahKarya — 1-Man AI Company**

| Peran | Nama | Catatan |
|---|---|---|
| **Founder & AI Architect** | veris | Operator tunggal, 13 layanan otonom |
| **AI Agents** | DeepSeek, GPT-4o, Claude | Koordinasi via 1ai-hub + Hermes GM |
| **Infrastructure** | OmniRoute AI Gateway | 160+ provider, auto-failover |
| **Ops** | AI Agents | 24/7 operational tanpa tim tambahan |

---

## 8. Ringkasan

Vilona Trade FX adalah **infrastruktur trading AI white-label** untuk pasar Indonesia yang:

- ✅ **Telah live** dengan produk berbayar (PRO/ELITE/LIFETIME)
- ✅ **Mengikuti model Capitalise** — SaaS tools, bukan pool dana
- ✅ **Memiliki moat** — Multi-AI voting + MT5 Bridge + risk gate
- ✅ **Scalable** — Whitelabel model dengan komisi 3 level
- ✅ **Clear revenue** — Subscription + partner commission
- ✅ **Regulatory safe** — Tidak menjamin return, tidak pegang dana

**Market Context:** Pasar Indonesia mencatat 21,37 juta pengguna kripto (OJK, Mar 2026) dengan volume transaksi Rp482,23 triliun di 2025 — pertumbuhan pasar +50% YoY. Vilona diposisikan untuk menangkap pangsa dari infrastruktur trading AI di pasar yang berkembang pesat ini.

---

## Lampiran

### A. Disclaimer

> Perdagangan valuta asing dan aset kripto membawa tingkat risiko yang sangat tinggi bagi modal Anda. Jangan pernah gunakan dana yang Anda tidak siap untuk kehilangannya. Seluruh sinyal yang disediakan Vilona Trade FX adalah hasil analisis AI dan probabilitas — bukan jaminan profit. Keputusan trading sepenuhnya ada di tangan pengguna.

### B. Referensi

1. Capitalise.ai — Company Overview, Crunchbase
2. Kraken Acquires Capitalise.ai — August 2025
3. AlgosOne.ai — FSMA Warning Blacklist, June 2025
4. POJK 3/2024 — Penyelenggaraan Inovasi Teknologi Sektor Keuangan (ITSK)
5. POJK 27/2024 — Penetapan Aset Kripto sebagai Instrumen Keuangan Digital
6. OJK — Perkembangan Inovasi Digital dan Aset Keuangan Digital, April 2026
7. OJK Innovation Hub — Regulatory Sandbox — Periode Uji Coba Maksimal 1 Tahun
8. Pionex, GoodCryptoX, Bitsgap, Zignaly — Platform Kompetitor Global Trading Automation

---

*Dokumen ini disusun oleh BerkahKarya AI Ecosystem. Untuk pertanyaan lebih lanjut: [Telegram](https://t.me/berkahkarya_saas_bot)*
