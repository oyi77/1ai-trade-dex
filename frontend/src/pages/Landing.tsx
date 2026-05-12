import type { ReactNode } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'

type LandingLanguage = 'en' | 'id' | 'ru' | 'ch'

type Translation = {
  nav: { dashboard: string; docs: string; research: string }
  brandSubtitle: string
  tickerItems: string[]
  hero: {
    badges: string[]
    eyebrow: string
    headline: string
    body: string
    support: string
  }
  proofMetrics: { label: string; value: string; detail: string }[]
  dossier: { label: string; live: string; claimLabel: string; claim: string }
  sectionLabels: { problem: string; breakthrough: string; mechanism: string; proof: string; allocation: string }
  problemCards: { numeral: string; title: string; body: string }[]
  breakthrough: { eyebrow: string; title: string; body: string }
  superiorityPillars: { title: string; body: string }[]
  mechanism: { title: string; body: string; headers: string[] }
  decisionFlow: { step: string; action: string; confidence: string; edge: string; verdict: string; gate: string }[]
  proof: { eyebrow: string; title: string; body: string }
  researchAssets: { label: string; meta: string; href: string }[]
  allocation: { title: string; body: string; checklistLabel: string; claimGuard: string }
  allocationChecks: string[]
  footerRisk: string
}

const LANGUAGE_STORAGE_KEY = 'polyedge.landing.language'

const languages: { code: LandingLanguage; shortLabel: string; label: string }[] = [
  { code: 'en', shortLabel: 'EN', label: 'English' },
  { code: 'id', shortLabel: 'ID', label: 'Bahasa Indonesia' },
  { code: 'ru', shortLabel: 'RU', label: 'Русский' },
  { code: 'ch', shortLabel: 'CH', label: '中文' },
]

const navTargets = [
  { key: 'dashboard' as const, to: '/dashboard', external: false },
  { key: 'docs' as const, to: 'https://polyedge.aitradepulse.com/docs/', external: true },
  { key: 'research' as const, to: 'https://polyedge.aitradepulse.com/docs/research/pitch-deck', external: true },
]

const landingCta = {
  primaryLabel: import.meta.env.VITE_LANDING_CTA_LABEL || 'Apply for Allocation',
  primaryUrl: import.meta.env.VITE_LANDING_CTA_URL || 'https://www.aipolymarket.xyz/',
  secondaryLabel: import.meta.env.VITE_LANDING_SECONDARY_CTA_LABEL || 'Read Investor Paper',
  secondaryUrl: import.meta.env.VITE_LANDING_SECONDARY_CTA_URL || 'https://polyedge.aitradepulse.com/docs/research/pitch-deck',
}

const translations: Record<LandingLanguage, Translation> = {
  en: {
    nav: { dashboard: 'Dashboard', docs: 'Docs', research: 'Research' },
    brandSubtitle: 'Allocation memo',
    tickerItems: ['LIVE', 'AGI TRADING SYSTEM', 'DOI 10.5281/ZENODO.16966978', '14+ STRATEGIES', '25 AUTONOMOUS EXPERIMENTS', '162 TRADES TRACKED', 'PAPER · TESTNET · LIVE', 'ON-CHAIN / DASHBOARD AUDIT'],
    hero: {
      badges: ['AGI Trading System', 'Investor dossier', 'Paper · dashboard · risk gates'],
      eyebrow: 'Static bots die when regimes shift',
      headline: 'PolyEdge evolves.',
      body: 'Not a trading bot. An AGI Trading System that creates strategies, debates trades, sizes capital, executes under deterministic risk gates, diagnoses losses, and evolves the next generation.',
      support: 'Built for prediction-market allocators who need proof, governance, and audit trails before capital touches Polymarket or Kalshi.',
    },
    proofMetrics: [
      { label: 'Strategies', value: '14+', detail: 'registered strategy surface plus AGI Orchestrator' },
      { label: 'Experiments', value: '25', detail: 'autonomous lifecycle candidates under governance' },
      { label: 'Trades', value: '162', detail: 'tracked through decision, attempt, and settlement records' },
      { label: 'Paper', value: '33p', detail: 'research paper with 15 references and supplement' },
    ],
    dossier: { label: 'Dossier evidence', live: 'Live thesis', claimLabel: 'Primary claim', claim: 'Governed autonomy: staged, measured, debated, and audited before capital scales.' },
    sectionLabels: { problem: 'Problem', breakthrough: 'Breakthrough', mechanism: 'Mechanism', proof: 'Proof', allocation: 'Allocation' },
    problemCards: [
      { numeral: 'I', title: 'Regimes shift faster than hardcoded bots adapt.', body: 'A static strategy can look brilliant until liquidity, volatility, or event timing changes the market it was tuned for.' },
      { numeral: 'II', title: 'Human operators sleep while prediction markets move.', body: 'News, weather, CEX lead-lag, and whale flows can reprice markets long before a manual workflow responds.' },
      { numeral: 'III', title: 'Signals fragment across venues and evidence trails.', body: 'Allocators need to know why capital moved, not just that a bot clicked buy after a black-box score changed.' },
    ],
    breakthrough: { eyebrow: 'Best superiority', title: 'AGI Trading Systems beat static bots.', body: 'Static bots execute a rule. PolyEdge runs a governed research loop: form hypotheses, challenge them, deploy only under gates, diagnose failures, and compound what survives.' },
    superiorityPillars: [
      { title: 'AGI Strategy Factory', body: 'Creates, mutates, scores, promotes, and retires strategies through DRAFT → SHADOW → PAPER → LIVE stages.' },
      { title: 'Debate Before Capital', body: 'MiroFish bull/bear/judge validation challenges trades before execution so conviction has an inspectable adversary.' },
      { title: 'Self-Improving Risk Loop', body: 'Forensics, health checks, bankroll allocation, and deterministic gates convert outcomes into the next generation.' },
    ],
    mechanism: { title: 'Every trade becomes an audit row.', body: 'The mechanism is designed for diligence: signal, proposal, debate, risk sizing, order attempt, settlement, and forensics stay legible.', headers: ['ID', 'Decision flow', 'Conf.', 'Edge', 'Verdict', 'Gate'] },
    decisionFlow: [
      { step: '01', action: 'Market signal detected', confidence: '0.74', edge: '+6.2%', verdict: 'candidate', gate: 'observe' },
      { step: '02', action: 'Strategy proposes trade', confidence: '0.79', edge: '+7.8%', verdict: 'bull case formed', gate: 'debate' },
      { step: '03', action: 'Debate validates or rejects', confidence: '0.81', edge: '+5.9%', verdict: 'judge: pass', gate: 'risk' },
      { step: '04', action: 'Risk manager sizes or blocks', confidence: '0.81', edge: '+5.9%', verdict: 'bounded Kelly', gate: 'size' },
      { step: '05', action: 'Order attempt is logged', confidence: '0.81', edge: '+5.9%', verdict: 'attempt recorded', gate: 'audit' },
      { step: '06', action: 'Forensics feed evolution', confidence: 'settled', edge: 'post-trade', verdict: 'learn', gate: 'evolve' },
    ],
    proof: { eyebrow: 'Research-backed diligence', title: 'Read the paper before you wire.', body: 'The research package documents the bounded AGI autonomy framework, StrategyGenome grammar, dual-debate validation, and operational evidence. It states limitations instead of pretending autonomy is magic.' },
    researchAssets: [
      { label: 'Paper PDF', meta: '33 pages · 15 references', href: 'https://polyedge.aitradepulse.com/paper/paper.pdf' },
      { label: 'Supplementary PDF', meta: 'proofs · genome grammar · code listings', href: 'https://polyedge.aitradepulse.com/paper/supplementary.pdf' },
      { label: 'Abstract Video', meta: '50-second research overview', href: 'https://polyedge.aitradepulse.com/paper/abstract_video.mp4' },
      { label: 'Dashboard Audit', meta: 'operator-facing evidence surface', href: '/dashboard' },
    ],
    allocation: { title: 'Back the AGI trading system that explains itself.', body: 'PolyEdge is an allocation funnel for governed autonomy: evidence-first dashboards, research artifacts, and deterministic promotion gates from experiment to capital deployment.', checklistLabel: 'Diligence checklist', claimGuard: 'No fabricated performance claims' },
    allocationChecks: ['Governed autonomy, not blind bot execution', 'Research artifacts for technical diligence', 'Deterministic risk gates before capital deployment', 'Trade attempts and outcomes captured as structured evidence'],
    footerRisk: 'Bounded autonomy with deterministic risk gates',
  },
  id: {
    nav: { dashboard: 'Dasbor', docs: 'Dokumen', research: 'Riset' },
    brandSubtitle: 'Memo alokasi',
    tickerItems: ['LIVE', 'SISTEM TRADING AGI', 'DOI 10.5281/ZENODO.16966978', '14+ STRATEGI', '25 EKSPERIMEN OTONOM', '162 TRADE TERCATAT', 'PAPER · TESTNET · LIVE', 'AUDIT ON-CHAIN / DASBOR'],
    hero: {
      badges: ['Sistem Trading AGI', 'Dossier investor', 'Paper · dasbor · gerbang risiko'],
      eyebrow: 'Bot statis mati saat rezim pasar berubah',
      headline: 'PolyEdge berevolusi.',
      body: 'Bukan bot trading. PolyEdge adalah Sistem Trading AGI yang menciptakan strategi, mendebat trade, mengukur modal, mengeksekusi di bawah gerbang risiko deterministik, mendiagnosis kerugian, dan mengembangkan generasi berikutnya.',
      support: 'Dibangun untuk allocator pasar prediksi yang membutuhkan bukti, tata kelola, dan jejak audit sebelum modal menyentuh Polymarket atau Kalshi.',
    },
    proofMetrics: [
      { label: 'Strategi', value: '14+', detail: 'permukaan strategi terdaftar plus AGI Orchestrator' },
      { label: 'Eksperimen', value: '25', detail: 'kandidat lifecycle otonom dalam tata kelola' },
      { label: 'Trade', value: '162', detail: 'terlacak melalui keputusan, percobaan order, dan settlement' },
      { label: 'Paper', value: '33h', detail: 'paper riset dengan 15 referensi dan suplemen' },
    ],
    dossier: { label: 'Bukti dossier', live: 'Tesis live', claimLabel: 'Klaim utama', claim: 'Otonomi terkendali: bertahap, terukur, diperdebatkan, dan diaudit sebelum modal diperbesar.' },
    sectionLabels: { problem: 'Masalah', breakthrough: 'Terobosan', mechanism: 'Mekanisme', proof: 'Bukti', allocation: 'Alokasi' },
    problemCards: [
      { numeral: 'I', title: 'Rezim pasar berubah lebih cepat daripada bot hardcoded beradaptasi.', body: 'Strategi statis bisa tampak hebat sampai likuiditas, volatilitas, atau waktu event mengubah pasar yang menjadi targetnya.' },
      { numeral: 'II', title: 'Operator manusia tidur saat pasar prediksi bergerak.', body: 'Berita, cuaca, lead-lag CEX, dan aliran whale dapat mengubah harga jauh sebelum workflow manual merespons.' },
      { numeral: 'III', title: 'Sinyal terpecah di banyak venue dan jejak bukti.', body: 'Allocator perlu tahu mengapa modal bergerak, bukan hanya bahwa bot menekan beli setelah skor black-box berubah.' },
    ],
    breakthrough: { eyebrow: 'Keunggulan utama', title: 'Sistem Trading AGI mengalahkan bot statis.', body: 'Bot statis menjalankan aturan. PolyEdge menjalankan loop riset terkendali: membentuk hipotesis, menantangnya, deploy hanya lewat gerbang, mendiagnosis kegagalan, dan menggabungkan yang bertahan.' },
    superiorityPillars: [
      { title: 'Pabrik Strategi AGI', body: 'Mencipta, memutasi, menilai, mempromosikan, dan memensiunkan strategi melalui tahap DRAFT → SHADOW → PAPER → LIVE.' },
      { title: 'Debat Sebelum Modal', body: 'Validasi MiroFish bull/bear/judge menantang trade sebelum eksekusi sehingga conviction punya lawan yang dapat diperiksa.' },
      { title: 'Loop Risiko yang Belajar', body: 'Forensik, health check, alokasi bankroll, dan gerbang deterministik mengubah hasil menjadi generasi berikutnya.' },
    ],
    mechanism: { title: 'Setiap trade menjadi baris audit.', body: 'Mekanismenya dibuat untuk due diligence: sinyal, proposal, debat, sizing risiko, percobaan order, settlement, dan forensik tetap terbaca.', headers: ['ID', 'Alur keputusan', 'Conf.', 'Edge', 'Vonis', 'Gate'] },
    decisionFlow: [
      { step: '01', action: 'Sinyal pasar terdeteksi', confidence: '0.74', edge: '+6.2%', verdict: 'kandidat', gate: 'observe' },
      { step: '02', action: 'Strategi mengusulkan trade', confidence: '0.79', edge: '+7.8%', verdict: 'bull case dibuat', gate: 'debate' },
      { step: '03', action: 'Debat memvalidasi atau menolak', confidence: '0.81', edge: '+5.9%', verdict: 'judge: pass', gate: 'risk' },
      { step: '04', action: 'Risk manager sizing atau blokir', confidence: '0.81', edge: '+5.9%', verdict: 'Kelly terbatas', gate: 'size' },
      { step: '05', action: 'Percobaan order dicatat', confidence: '0.81', edge: '+5.9%', verdict: 'attempt tercatat', gate: 'audit' },
      { step: '06', action: 'Forensik memberi evolusi', confidence: 'settled', edge: 'post-trade', verdict: 'learn', gate: 'evolve' },
    ],
    proof: { eyebrow: 'Due diligence berbasis riset', title: 'Baca paper sebelum menempatkan modal.', body: 'Paket riset mendokumentasikan kerangka otonomi AGI terbatas, grammar StrategyGenome, validasi dual-debate, dan bukti operasional. Ia menyatakan batasan alih-alih berpura-pura otonomi adalah sihir.' },
    researchAssets: [
      { label: 'Paper PDF', meta: '33 halaman · 15 referensi', href: 'https://polyedge.aitradepulse.com/paper/paper.pdf' },
      { label: 'PDF Suplemen', meta: 'proof · grammar genome · listing kode', href: 'https://polyedge.aitradepulse.com/paper/supplementary.pdf' },
      { label: 'Video Abstrak', meta: 'ringkasan riset 50 detik', href: 'https://polyedge.aitradepulse.com/paper/abstract_video.mp4' },
      { label: 'Audit Dasbor', meta: 'permukaan bukti untuk operator', href: '/dashboard' },
    ],
    allocation: { title: 'Dukung sistem trading AGI yang dapat menjelaskan dirinya sendiri.', body: 'PolyEdge adalah funnel alokasi untuk otonomi terkendali: dasbor evidence-first, artefak riset, dan gerbang promosi deterministik dari eksperimen ke deployment modal.', checklistLabel: 'Checklist due diligence', claimGuard: 'Tanpa klaim performa palsu' },
    allocationChecks: ['Otonomi terkendali, bukan eksekusi bot buta', 'Artefak riset untuk due diligence teknis', 'Gerbang risiko deterministik sebelum deployment modal', 'Percobaan trade dan hasil ditangkap sebagai bukti terstruktur'],
    footerRisk: 'Otonomi terbatas dengan gerbang risiko deterministik',
  },
  ru: {
    nav: { dashboard: 'Панель', docs: 'Документы', research: 'Исследование' },
    brandSubtitle: 'Мемо аллокации',
    tickerItems: ['LIVE', 'AGI TRADING SYSTEM', 'DOI 10.5281/ZENODO.16966978', '14+ СТРАТЕГИЙ', '25 АВТОНОМНЫХ ЭКСПЕРИМЕНТОВ', '162 СДЕЛКИ ОТСЛЕЖЕНЫ', 'PAPER · TESTNET · LIVE', 'ON-CHAIN / DASHBOARD AUDIT'],
    hero: { badges: ['AGI Trading System', 'Инвесторское досье', 'Paper · панель · риск-гейты'], eyebrow: 'Статичные боты умирают при смене режима', headline: 'PolyEdge эволюционирует.', body: 'Не торговый бот. Это AGI Trading System, которая создает стратегии, проводит дебаты по сделкам, распределяет капитал, исполняет только через детерминированные риск-гейты, диагностирует убытки и развивает следующее поколение.', support: 'Для аллокаторов рынков предсказаний, которым нужны доказательства, управление и аудит до того, как капитал попадет в Polymarket или Kalshi.' },
    proofMetrics: [{ label: 'Стратегии', value: '14+', detail: 'зарегистрированные стратегии плюс AGI Orchestrator' }, { label: 'Эксперименты', value: '25', detail: 'автономные кандидаты под управлением' }, { label: 'Сделки', value: '162', detail: 'отслежены через решения, попытки ордера и расчеты' }, { label: 'Paper', value: '33с', detail: 'исследовательская работа с 15 источниками и приложением' }],
    dossier: { label: 'Доказательства досье', live: 'Live-тезис', claimLabel: 'Главный тезис', claim: 'Управляемая автономия: поэтапная, измеряемая, обсуждаемая и аудируемая до масштабирования капитала.' },
    sectionLabels: { problem: 'Проблема', breakthrough: 'Прорыв', mechanism: 'Механизм', proof: 'Доказательства', allocation: 'Аллокация' },
    problemCards: [{ numeral: 'I', title: 'Режимы меняются быстрее, чем адаптируются захардкоженные боты.', body: 'Статичная стратегия может выглядеть сильной, пока ликвидность, волатильность или тайминг события не изменят рынок.' }, { numeral: 'II', title: 'Люди спят, пока рынки предсказаний движутся.', body: 'Новости, погода, lead-lag CEX и потоки китов переоценивают рынки быстрее ручных процессов.' }, { numeral: 'III', title: 'Сигналы распадаются по площадкам и следам доказательств.', body: 'Аллокаторам нужно знать, почему капитал двинулся, а не только видеть покупку после изменения черного ящика.' }],
    breakthrough: { eyebrow: 'Главное преимущество', title: 'AGI Trading Systems превосходят статичных ботов.', body: 'Статичный бот исполняет правило. PolyEdge запускает управляемый исследовательский цикл: гипотезы, проверка, деплой через гейты, диагностика ошибок и усиление того, что выживает.' },
    superiorityPillars: [{ title: 'Фабрика стратегий AGI', body: 'Создает, мутирует, оценивает, продвигает и выводит стратегии через DRAFT → SHADOW → PAPER → LIVE.' }, { title: 'Дебаты до капитала', body: 'MiroFish bull/bear/judge оспаривает сделки до исполнения, делая conviction проверяемым.' }, { title: 'Самоулучшающийся риск-цикл', body: 'Форензика, health checks, аллокация bankroll и детерминированные гейты превращают результаты в новое поколение.' }],
    mechanism: { title: 'Каждая сделка становится строкой аудита.', body: 'Механизм создан для due diligence: сигнал, предложение, дебаты, риск-сайзинг, попытка ордера, расчет и форензика остаются читаемыми.', headers: ['ID', 'Поток решения', 'Conf.', 'Edge', 'Вердикт', 'Gate'] },
    decisionFlow: [{ step: '01', action: 'Рыночный сигнал найден', confidence: '0.74', edge: '+6.2%', verdict: 'кандидат', gate: 'observe' }, { step: '02', action: 'Стратегия предлагает сделку', confidence: '0.79', edge: '+7.8%', verdict: 'bull case', gate: 'debate' }, { step: '03', action: 'Дебаты валидируют или отклоняют', confidence: '0.81', edge: '+5.9%', verdict: 'judge: pass', gate: 'risk' }, { step: '04', action: 'Risk manager сайзит или блокирует', confidence: '0.81', edge: '+5.9%', verdict: 'bounded Kelly', gate: 'size' }, { step: '05', action: 'Попытка ордера записана', confidence: '0.81', edge: '+5.9%', verdict: 'attempt recorded', gate: 'audit' }, { step: '06', action: 'Форензика питает эволюцию', confidence: 'settled', edge: 'post-trade', verdict: 'learn', gate: 'evolve' }],
    proof: { eyebrow: 'Due diligence на основе исследования', title: 'Прочитайте paper до перевода капитала.', body: 'Исследовательский пакет описывает bounded AGI autonomy, StrategyGenome grammar, dual-debate validation и операционные доказательства. Он фиксирует ограничения, а не выдает автономию за магию.' },
    researchAssets: [{ label: 'Paper PDF', meta: '33 страницы · 15 источников', href: 'https://polyedge.aitradepulse.com/paper/paper.pdf' }, { label: 'Supplementary PDF', meta: 'доказательства · genome grammar · код', href: 'https://polyedge.aitradepulse.com/paper/supplementary.pdf' }, { label: 'Abstract Video', meta: '50 секунд обзора исследования', href: 'https://polyedge.aitradepulse.com/paper/abstract_video.mp4' }, { label: 'Dashboard Audit', meta: 'поверхность доказательств для оператора', href: '/dashboard' }],
    allocation: { title: 'Поддержите AGI trading system, которая объясняет себя.', body: 'PolyEdge — аллокационная воронка для управляемой автономии: evidence-first dashboards, исследовательские артефакты и детерминированные promotion gates от эксперимента до капитала.', checklistLabel: 'Чеклист due diligence', claimGuard: 'Без выдуманных claims о доходности' },
    allocationChecks: ['Управляемая автономия, а не слепое исполнение ботом', 'Исследовательские артефакты для технической проверки', 'Детерминированные риск-гейты до деплоя капитала', 'Попытки сделок и исходы сохраняются как структурированные доказательства'],
    footerRisk: 'Bounded autonomy с детерминированными risk gates',
  },
  ch: {
    nav: { dashboard: '仪表盘', docs: '文档', research: '研究' },
    brandSubtitle: '配置备忘录',
    tickerItems: ['LIVE', 'AGI 交易系统', 'DOI 10.5281/ZENODO.16966978', '14+ 策略', '25 个自主实验', '162 笔交易追踪', '论文 · 测试网 · 实盘', '链上 / 仪表盘审计'],
    hero: { badges: ['AGI 交易系统', '投资者档案', '论文 · 仪表盘 · 风控门'], eyebrow: '市场 regime 变化时，静态机器人会失效', headline: 'PolyEdge 会进化。', body: '不是交易机器人，而是 AGI 交易系统：创建策略、辩论交易、分配资本、在确定性风控门下执行、诊断亏损，并进化下一代策略。', support: '为预测市场资金配置者而建：在资本进入 Polymarket 或 Kalshi 前，先提供证据、治理与审计轨迹。' },
    proofMetrics: [{ label: '策略', value: '14+', detail: '已注册策略面，加上 AGI Orchestrator' }, { label: '实验', value: '25', detail: '受治理约束的自主生命周期候选' }, { label: '交易', value: '162', detail: '通过决策、下单尝试与结算记录追踪' }, { label: '论文', value: '33页', detail: '含 15 个参考文献和补充材料' }],
    dossier: { label: '档案证据', live: '实时 thesis', claimLabel: '核心主张', claim: '受治理的自主性：分阶段、可度量、可辩论、可审计，然后再扩大资本。' },
    sectionLabels: { problem: '问题', breakthrough: '突破', mechanism: '机制', proof: '证据', allocation: '配置' },
    problemCards: [{ numeral: 'I', title: '市场 regime 变化快于硬编码机器人的适应速度。', body: '静态策略可能看起来很强，直到流动性、波动率或事件时点改变了它所适配的市场。' }, { numeral: 'II', title: '人在休息时，预测市场仍在移动。', body: '新闻、天气、CEX lead-lag 和 whale 流向都可能在人工流程响应前重新定价。' }, { numeral: 'III', title: '信号分散在多个场所与证据链中。', body: '资金配置者需要知道资本为什么移动，而不是只看到黑箱分数变化后的买入动作。' }],
    breakthrough: { eyebrow: '核心优势', title: 'AGI 交易系统胜过静态机器人。', body: '静态机器人执行规则。PolyEdge 运行受治理的研究循环：形成假设、挑战假设、只在通过风控门后部署、诊断失败，并复利留下来的优势。' },
    superiorityPillars: [{ title: 'AGI 策略工厂', body: '通过 DRAFT → SHADOW → PAPER → LIVE 阶段创建、变异、评分、晋升和淘汰策略。' }, { title: '资本前辩论', body: 'MiroFish bull/bear/judge 在执行前挑战交易，让 conviction 可被检查。' }, { title: '自我改进风险循环', body: '取证、健康检查、bankroll 配置和确定性风控门，将结果转化为下一代策略。' }],
    mechanism: { title: '每笔交易都会成为审计行。', body: '机制为 due diligence 而设计：信号、提案、辩论、风险 sizing、下单尝试、结算和取证都保持可读。', headers: ['ID', '决策流', '置信度', 'Edge', '结论', 'Gate'] },
    decisionFlow: [{ step: '01', action: '检测到市场信号', confidence: '0.74', edge: '+6.2%', verdict: '候选', gate: 'observe' }, { step: '02', action: '策略提出交易', confidence: '0.79', edge: '+7.8%', verdict: 'bull case formed', gate: 'debate' }, { step: '03', action: '辩论验证或拒绝', confidence: '0.81', edge: '+5.9%', verdict: 'judge: pass', gate: 'risk' }, { step: '04', action: '风控经理 sizing 或阻断', confidence: '0.81', edge: '+5.9%', verdict: 'bounded Kelly', gate: 'size' }, { step: '05', action: '记录下单尝试', confidence: '0.81', edge: '+5.9%', verdict: 'attempt recorded', gate: 'audit' }, { step: '06', action: '取证反馈进化', confidence: 'settled', edge: 'post-trade', verdict: 'learn', gate: 'evolve' }],
    proof: { eyebrow: '研究支持的 due diligence', title: '配置资金前，先读论文。', body: '研究包记录 bounded AGI autonomy framework、StrategyGenome grammar、dual-debate validation 与运营证据。它说明限制，而不是把自主性包装成魔法。' },
    researchAssets: [{ label: '论文 PDF', meta: '33 页 · 15 个参考文献', href: 'https://polyedge.aitradepulse.com/paper/paper.pdf' }, { label: '补充 PDF', meta: '证明 · genome grammar · 代码列表', href: 'https://polyedge.aitradepulse.com/paper/supplementary.pdf' }, { label: '摘要视频', meta: '50 秒研究概览', href: 'https://polyedge.aitradepulse.com/paper/abstract_video.mp4' }, { label: '仪表盘审计', meta: '面向操作者的证据界面', href: '/dashboard' }],
    allocation: { title: '支持一个能够解释自己的 AGI 交易系统。', body: 'PolyEdge 是受治理自主性的配置漏斗：证据优先的仪表盘、研究材料，以及从实验到资本部署的确定性 promotion gates。', checklistLabel: 'Due diligence 清单', claimGuard: '不编造业绩 claims' },
    allocationChecks: ['受治理的自主性，而不是盲目机器人执行', '用于技术 due diligence 的研究材料', '资本部署前的确定性风险门', '交易尝试和结果被记录为结构化证据'],
    footerRisk: '带确定性风控门的 bounded autonomy',
  },
}

const trustAnchors = ['PolyEdge v4.0', 'Polymarket', 'Kalshi', 'MiroFish', 'StrategyGenome', 'Deterministic risk gates']

const isExternalUrl = (href: string) => href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('tel:')

const isLandingLanguage = (value: string | null): value is LandingLanguage => (
  value === 'en' || value === 'id' || value === 'ru' || value === 'ch'
)

function languageFromLocale(locale: string | undefined): LandingLanguage | null {
  const normalized = locale?.toLowerCase()
  if (!normalized) return null
  if (normalized.startsWith('id') || normalized.startsWith('in')) return 'id'
  if (normalized.startsWith('ru')) return 'ru'
  if (normalized.startsWith('zh') || normalized.startsWith('cn')) return 'ch'
  if (normalized.startsWith('en')) return 'en'
  return null
}

function languageFromCountry(countryCode: string | undefined): LandingLanguage | null {
  const normalized = countryCode?.toUpperCase()
  if (!normalized) return null
  if (normalized === 'ID') return 'id'
  if (normalized === 'RU' || normalized === 'BY' || normalized === 'KZ') return 'ru'
  if (['CN', 'HK', 'TW', 'MO', 'SG'].includes(normalized)) return 'ch'
  return null
}

function getBrowserLanguage(): LandingLanguage {
  const locales = typeof navigator === 'undefined' ? [] : [navigator.language, ...(navigator.languages || [])]
  for (const locale of locales) {
    const language = languageFromLocale(locale)
    if (language) return language
  }
  return 'en'
}

async function detectLanguageByIp(): Promise<LandingLanguage | null> {
  try {
    const response = await fetch('https://api.country.is/')
    if (!response.ok) return null
    const data = await response.json() as { country?: string }
    return languageFromCountry(data.country)
  } catch {
    return null
  }
}

function ExternalLink({ href, children, className }: { href: string; children: ReactNode; className: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  )
}

function SmartLink({ href, children, className }: { href: string; children: ReactNode; className: string }) {
  if (isExternalUrl(href)) {
    return (
      <ExternalLink href={href} className={className}>
        {children}
      </ExternalLink>
    )
  }

  return (
    <Link to={href} className={className}>
      {children}
    </Link>
  )
}

function SectionLabel({ number, label }: { number: string; label: string }) {
  return (
    <div className="mb-7 flex items-center gap-4 text-[10px] font-black uppercase tracking-[0.32em] text-amber-300/80">
      <span className="grid h-8 w-8 place-items-center border border-amber-300/30 bg-amber-300/10 text-amber-200">{number}</span>
      <span>{label}</span>
      <span className="h-px flex-1 bg-gradient-to-r from-amber-300/30 to-transparent" />
    </div>
  )
}

export default function Landing() {
  const [language, setLanguage] = useState<LandingLanguage>(() => {
    const savedLanguage = typeof localStorage === 'undefined' ? null : localStorage.getItem(LANGUAGE_STORAGE_KEY)
    return isLandingLanguage(savedLanguage) ? savedLanguage : getBrowserLanguage()
  })
  const t = translations[language]
  const [stats, setStats] = useState({ trades: "162", strategies: "14+", experiments: "25" })

  useEffect(() => {

    Promise.all([

      fetch("/api/v1/stats").then(r => r.json()).catch(() => ({})),

      fetch("/api/v1/strategies").then(r => r.json()).catch(() => ({})),

      fetch("/api/v1/agi/experiments").then(r => r.json()).catch(() => ({}))

    ]).then(([statsData, stratsData, expsData]) => {

      setStats({

        trades: statsData.total_trades !== undefined ? String(statsData.total_trades) : "162",

        strategies: stratsData.strategies ? String(stratsData.strategies.length) + "+" : "14+",

        experiments: expsData.experiments ? String(expsData.experiments.length) : "25"

      });

    });

  }, []);


  const repeatedTicker = useMemo(() => [...t.tickerItems, ...t.tickerItems], [t.tickerItems])

  useEffect(() => {
    let cancelled = false
    const savedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (isLandingLanguage(savedLanguage)) return

    detectLanguageByIp().then(detectedLanguage => {
      if (!cancelled && detectedLanguage) {
        setLanguage(detectedLanguage)
      }
    })

    return () => {
      cancelled = true
    }
  }, [])

  const chooseLanguage = (nextLanguage: LandingLanguage) => {
    setLanguage(nextLanguage)
    localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage)
  }

  return (
    <div lang={language === 'ch' ? 'zh' : language} className="min-h-screen overflow-hidden bg-[#050403] text-stone-200 selection:bg-emerald-400/30 selection:text-emerald-50">
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_14%,rgba(245,158,11,0.17),transparent_28%),radial-gradient(circle_at_82%_18%,rgba(16,185,129,0.15),transparent_30%),linear-gradient(115deg,rgba(5,4,3,0.7),rgba(0,0,0,0.96))]" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(245,158,11,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(245,158,11,0.05)_1px,transparent_1px)] [background-size:72px_72px] opacity-40" />
        <div className="absolute inset-0 opacity-[0.06] [background-image:radial-gradient(circle_at_1px_1px,#ffffff_1px,transparent_0)] [background-size:5px_5px]" />
        <div className="absolute left-8 top-0 hidden h-full w-px bg-gradient-to-b from-transparent via-amber-300/25 to-transparent lg:block" />
        <div className="absolute right-8 top-0 hidden h-full w-px bg-gradient-to-b from-transparent via-emerald-300/20 to-transparent lg:block" />
      </div>

      <header className="relative z-20">
        <div className="border-b border-amber-300/15 bg-black/80 py-2 text-[10px] font-black uppercase tracking-[0.28em] text-amber-100/75 backdrop-blur-xl">
          <div className="flex overflow-hidden whitespace-nowrap">
            <motion.div
              className="flex min-w-max gap-8 pr-8"
              animate={{ x: ['0%', '-50%'] }}
              transition={{ duration: 30, repeat: Infinity, ease: 'linear' }}
            >
              {repeatedTicker.map((item, index) => (
                <span key={`${item}-${index}`} className="inline-flex items-center gap-8">
                  <span>{item}</span>
                  <span className="h-1 w-1 rounded-full bg-emerald-300 shadow-[0_0_14px_rgba(110,231,183,0.9)]" />
                </span>
              ))}
            </motion.div>
          </div>
        </div>

        <nav className="sticky top-0 z-30 border-b border-white/10 bg-[#050403]/86 px-5 py-4 backdrop-blur-2xl sm:px-8">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-6">
            <Link to="/" className="group flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center border border-amber-300/30 bg-amber-300/10 font-serif text-sm font-black text-amber-200 shadow-[0_0_32px_rgba(245,158,11,0.18)]">PE</span>
              <span>
                <span className="block font-serif text-lg uppercase leading-none tracking-[0.18em] text-stone-50 transition-colors group-hover:text-amber-200">PolyEdge</span>
                <span className="block text-[8px] font-bold uppercase tracking-[0.34em] text-stone-500">{t.brandSubtitle}</span>
              </span>
            </Link>

            <div className="ml-auto flex flex-wrap items-center justify-end gap-2 sm:gap-3">
              <label className="relative flex items-center border border-stone-800 bg-black/35 px-3 py-2 text-[10px] font-black uppercase tracking-[0.16em] text-stone-500 transition-all focus-within:border-amber-300/50 focus-within:text-amber-100 hover:border-amber-300/30">
                <span className="mr-2 text-amber-300">{language.toUpperCase()}</span>
                <span className="sr-only">Landing language</span>
                <select
                  value={language}
                  onChange={event => chooseLanguage(event.target.value as LandingLanguage)}
                  aria-label="Landing language"
                  className="cursor-pointer appearance-none bg-transparent pr-6 text-stone-200 outline-none"
                >
                  {languages.map(option => (
                    <option key={option.code} value={option.code} className="bg-[#050403] text-stone-100">
                      {option.shortLabel} · {option.label}
                    </option>
                  ))}
                </select>
                <span className="pointer-events-none absolute right-3 text-amber-300/80">⌄</span>
              </label>
              {navTargets.map(link => (
                link.external ? (
                  <ExternalLink
                    key={link.key}
                    href={link.to}
                    className="border border-stone-800 bg-black/40 px-3 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-stone-400 transition-all hover:border-amber-300/40 hover:bg-amber-300/10 hover:text-amber-100 sm:px-4"
                  >
                    {t.nav[link.key]}
                  </ExternalLink>
                ) : (
                  <Link
                    key={link.key}
                    to={link.to}
                    className="border border-emerald-300/35 bg-emerald-300/10 px-3 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-emerald-200 transition-all hover:bg-emerald-300/20 sm:px-4"
                  >
                    {t.nav[link.key]}
                  </Link>
                )
              ))}
            </div>
          </div>
        </nav>
      </header>

      <main className="relative z-10">
        <section className="mx-auto grid max-w-7xl gap-12 px-5 pb-20 pt-16 sm:px-8 lg:grid-cols-[1.08fr_0.92fr] lg:pb-28 lg:pt-24">
          <motion.div initial={{ opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8 }}>
            <div className="mb-8 flex flex-wrap gap-3">
              {t.hero.badges.map((badge, index) => (
                <span key={badge} className={`${index === 0 ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200' : index === 1 ? 'border-amber-300/25 bg-amber-300/10 text-amber-200' : 'border-stone-800 bg-black/35 text-stone-500'} border px-3 py-1 text-[10px] font-black uppercase tracking-[0.3em]`}>
                  {badge}
                </span>
              ))}
            </div>

            <p className="mb-5 text-[11px] font-black uppercase tracking-[0.5em] text-amber-300/70">{t.hero.eyebrow}</p>
            <h1 className="max-w-5xl font-serif text-6xl font-black leading-[0.86] tracking-[-0.075em] text-stone-50 sm:text-8xl lg:text-9xl">
              {t.hero.headline}
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-stone-300 sm:text-xl">
              {t.hero.body}
            </p>
            <p className="mt-5 max-w-2xl text-sm leading-7 text-stone-500">
              {t.hero.support}
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <SmartLink
                href={landingCta.primaryUrl}
                className="group inline-flex items-center justify-center border border-amber-300/50 bg-amber-300 px-6 py-4 text-xs font-black uppercase tracking-[0.25em] text-black transition-all hover:bg-amber-100 hover:shadow-[0_0_42px_rgba(245,158,11,0.35)]"
              >
                {landingCta.primaryLabel}
                <span className="ml-3 transition-transform group-hover:translate-x-1">→</span>
              </SmartLink>
              <SmartLink
                href={landingCta.secondaryUrl}
                className="inline-flex items-center justify-center border border-stone-700 bg-black/55 px-6 py-4 text-xs font-black uppercase tracking-[0.25em] text-stone-200 transition-all hover:border-emerald-300/40 hover:text-emerald-200"
              >
                {landingCta.secondaryLabel}
              </SmartLink>
            </div>
          </motion.div>

          <motion.aside
            initial={{ opacity: 0, y: 26, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.8, delay: 0.12 }}
            className="relative"
          >
            <div className="absolute -inset-4 border border-amber-300/10 bg-amber-300/[0.03]" />
            <div className="relative overflow-hidden border border-stone-800 bg-[#080705]/88 p-5 shadow-[0_50px_140px_rgba(0,0,0,0.68)]">
              <div className="flex items-center justify-between border-b border-stone-800 pb-4">
                <span className="text-[10px] font-black uppercase tracking-[0.32em] text-stone-500">{t.dossier.label}</span>
                <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.24em] text-emerald-300">
                  <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.85)]" />
                  {t.dossier.live}
                </span>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3">
                {t.proofMetrics.map((metric, index) => (
                  <motion.div
                    key={metric.label}
                    initial={{ opacity: 0, y: 18 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.45, delay: 0.22 + index * 0.08 }}
                    className="border border-stone-800 bg-black/45 p-4"
                  >
                    <div className="font-serif text-4xl font-black tracking-[-0.08em] text-amber-200">{metric.label === "Trades" || metric.label === "Trade" || metric.label === "Сделки" || metric.label === "交易" ? stats.trades : metric.label === "Strategies" || metric.label === "Strategi" || metric.label === "Стратегии" || metric.label === "策略" ? stats.strategies : metric.label === "Experiments" || metric.label === "Eksperimen" || metric.label === "Эксперименты" || metric.label === "实验" ? stats.experiments : metric.value}</div>
                    <div className="mt-2 text-[10px] font-black uppercase tracking-[0.22em] text-stone-400">{metric.label}</div>
                    <div className="mt-2 text-[10px] leading-5 text-stone-600">{metric.detail}</div>
                  </motion.div>
                ))}
              </div>

              <div className="mt-5 border border-emerald-300/20 bg-emerald-300/10 p-5">
                <div className="text-[10px] font-black uppercase tracking-[0.28em] text-emerald-200">{t.dossier.claimLabel}</div>
                <p className="mt-3 font-serif text-2xl leading-8 text-stone-100">
                  {t.dossier.claim}
                </p>
              </div>
            </div>
          </motion.aside>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionLabel number="01" label={t.sectionLabels.problem} />
          <div className="grid gap-4 lg:grid-cols-3">
            {t.problemCards.map((card, index) => (
              <motion.article
                key={card.numeral}
                initial={{ opacity: 0, y: 28 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-80px' }}
                transition={{ duration: 0.55, delay: index * 0.08 }}
                className="group min-h-[330px] border border-stone-800 bg-black/45 p-6 transition-all hover:-translate-y-1 hover:border-amber-300/35 hover:bg-stone-950/90"
              >
                <div className="flex items-start justify-between">
                  <span className="font-serif text-7xl font-black leading-none tracking-[-0.08em] text-stone-800 transition-colors group-hover:text-amber-300/25">{card.numeral}</span>
                  <span className="h-2 w-2 bg-amber-300/70 shadow-[0_0_18px_rgba(245,158,11,0.7)]" />
                </div>
                <h2 className="mt-12 font-serif text-3xl font-black leading-8 tracking-[-0.04em] text-stone-100">{card.title}</h2>
                <p className="mt-5 text-sm leading-7 text-stone-500">{card.body}</p>
              </motion.article>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionLabel number="02" label={t.sectionLabels.breakthrough} />
          <div className="grid gap-8 border border-amber-300/20 bg-gradient-to-br from-amber-300/10 via-[#090805] to-black p-6 sm:p-9 lg:grid-cols-[0.9fr_1.1fr]">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.38em] text-emerald-200">{t.breakthrough.eyebrow}</p>
              <h2 className="mt-5 max-w-3xl font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                {t.breakthrough.title}
              </h2>
              <p className="mt-6 text-sm leading-7 text-stone-400">
                {t.breakthrough.body}
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {t.superiorityPillars.map((pillar, index) => (
                <motion.div
                  key={pillar.title}
                  initial={{ opacity: 0, y: 18 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.45, delay: index * 0.08 }}
                  className="border border-stone-800 bg-black/45 p-5 transition-all hover:border-emerald-300/30 hover:bg-emerald-300/[0.04]"
                >
                  <span className="text-[10px] font-black uppercase tracking-[0.24em] text-amber-300">0{index + 1}</span>
                  <h3 className="mt-8 text-sm font-black uppercase tracking-[0.08em] text-stone-100">{pillar.title}</h3>
                  <p className="mt-4 text-xs leading-6 text-stone-500">{pillar.body}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto grid max-w-7xl gap-8 px-5 py-16 sm:px-8 lg:grid-cols-[0.72fr_1.28fr]">
          <div>
            <SectionLabel number="03" label={t.sectionLabels.mechanism} />
            <h2 className="font-serif text-5xl font-black leading-[0.92] tracking-[-0.06em] text-stone-50 sm:text-6xl">
              {t.mechanism.title}
            </h2>
            <p className="mt-6 text-sm leading-7 text-stone-500">
              {t.mechanism.body}
            </p>
          </div>

          <div className="overflow-hidden border border-stone-800 bg-[#070604]/88">
            <div className="grid grid-cols-[56px_1.3fr_0.62fr_0.62fr_0.82fr_0.58fr] border-b border-stone-800 bg-stone-950/80 px-4 py-3 text-[9px] font-black uppercase tracking-[0.22em] text-stone-500">
              {t.mechanism.headers.map(header => <span key={header}>{header}</span>)}
            </div>
            {t.decisionFlow.map((row, index) => (
              <motion.div
                key={row.step}
                initial={{ opacity: 0, x: 18 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.38, delay: index * 0.05 }}
                className="grid grid-cols-[56px_1.3fr_0.62fr_0.62fr_0.82fr_0.58fr] items-center border-b border-stone-900 px-4 py-4 text-xs text-stone-400 last:border-b-0 hover:bg-emerald-300/[0.04]"
              >
                <span className="font-black text-amber-300">{row.step}</span>
                <span className="font-semibold text-stone-200">{row.action}</span>
                <span>{row.confidence}</span>
                <span className="text-emerald-300">{row.edge}</span>
                <span>{row.verdict}</span>
                <span className="uppercase tracking-[0.16em] text-amber-200/80">{row.gate}</span>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionLabel number="04" label={t.sectionLabels.proof} />
          <div className="grid gap-8 lg:grid-cols-[1.03fr_0.97fr]">
            <div className="border border-stone-800 bg-black/45 p-6 sm:p-9">
              <p className="text-[10px] font-black uppercase tracking-[0.38em] text-emerald-200">{t.proof.eyebrow}</p>
              <h2 className="mt-5 font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                {t.proof.title}
              </h2>
              <p className="mt-6 text-sm leading-7 text-stone-500">
                {t.proof.body}
              </p>
              <div className="mt-8 grid grid-cols-2 gap-3">
                {t.proofMetrics.map(metric => (
                  <div key={metric.label} className="border border-stone-800 bg-stone-950/60 p-4">
                    <div className="font-serif text-3xl font-black tracking-[-0.06em] text-emerald-200">{metric.label === "Trades" || metric.label === "Trade" || metric.label === "Сделки" || metric.label === "交易" ? stats.trades : metric.label === "Strategies" || metric.label === "Strategi" || metric.label === "Стратегии" || metric.label === "策略" ? stats.strategies : metric.label === "Experiments" || metric.label === "Eksperimen" || metric.label === "Эксперименты" || metric.label === "实验" ? stats.experiments : metric.value}</div>
                    <div className="mt-1 text-[10px] font-black uppercase tracking-[0.2em] text-stone-500">{metric.label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              {t.researchAssets.map(asset => (
                <SmartLink
                  key={asset.label}
                  href={asset.href}
                  className="group flex items-center justify-between border border-stone-800 bg-[#080705]/80 p-5 transition-all hover:border-amber-300/40 hover:bg-amber-300/10"
                >
                  <span>
                    <span className="block text-sm font-black uppercase tracking-[0.18em] text-stone-100 group-hover:text-amber-100">{asset.label}</span>
                    <span className="mt-2 block text-[10px] uppercase tracking-[0.2em] text-stone-600">{asset.meta}</span>
                  </span>
                  <span className="text-amber-200 transition-transform group-hover:translate-x-1">→</span>
                </SmartLink>
              ))}
              <ExternalLink
                href="https://doi.org/10.5281/zenodo.16966978"
                className="block border border-emerald-300/35 bg-emerald-300 px-5 py-4 text-center text-xs font-black uppercase tracking-[0.24em] text-black transition-all hover:bg-emerald-100"
              >
                DOI: 10.5281/zenodo.16966978
              </ExternalLink>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
          <div className="relative overflow-hidden border border-amber-300/25 bg-gradient-to-br from-amber-300/12 via-[#080705] to-emerald-950/20 p-6 sm:p-10">
            <div className="absolute right-0 top-0 h-full w-1/3 bg-[radial-gradient(circle_at_80%_20%,rgba(16,185,129,0.18),transparent_48%)]" />
            <div className="relative grid gap-10 lg:grid-cols-[1fr_0.82fr]">
              <div>
                <SectionLabel number="05" label={t.sectionLabels.allocation} />
                <h2 className="max-w-4xl font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                  {t.allocation.title}
                </h2>
                <p className="mt-6 max-w-2xl text-sm leading-7 text-stone-400">
                  {t.allocation.body}
                </p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <SmartLink href={landingCta.primaryUrl} className="border border-amber-300/50 bg-amber-300 px-7 py-4 text-center text-xs font-black uppercase tracking-[0.24em] text-black transition-all hover:bg-amber-100">
                    {landingCta.primaryLabel}
                  </SmartLink>
                  <SmartLink href={landingCta.secondaryUrl} className="border border-stone-700 bg-black/55 px-7 py-4 text-center text-xs font-black uppercase tracking-[0.24em] text-stone-200 transition-all hover:border-emerald-300/40 hover:text-emerald-200">
                    {landingCta.secondaryLabel}
                  </SmartLink>
                </div>
              </div>

              <div className="border border-stone-800 bg-black/45 p-5">
                <div className="mb-5 flex items-center justify-between text-[10px] font-black uppercase tracking-[0.24em] text-stone-500">
                  <span>{t.allocation.checklistLabel}</span>
                  <span>{t.allocation.claimGuard}</span>
                </div>
                <div className="space-y-3">
                  {t.allocationChecks.map((check, index) => (
                    <div key={check} className="flex items-start gap-3 border border-stone-800 bg-stone-950/60 p-4 text-xs leading-6 text-stone-300">
                      <span className="mt-1 grid h-5 w-5 shrink-0 place-items-center border border-emerald-300/30 bg-emerald-300/10 text-[10px] font-black text-emerald-200">{index + 1}</span>
                      <span>{check}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-stone-900 px-5 py-8 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 text-[10px] font-black uppercase tracking-[0.22em] text-stone-700 lg:flex-row lg:items-center lg:justify-between">
          <span>{trustAnchors.join(' · ')}</span>
          <span>{t.footerRisk}</span>
        </div>
      </footer>
    </div>
  )
}
