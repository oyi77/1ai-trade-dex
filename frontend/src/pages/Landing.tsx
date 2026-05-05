import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'

const navLinks = [
  { label: 'Dashboard', to: '/dashboard', external: false },
  { label: 'Docs', to: 'https://polyedge.aitradepulse.com/docs/', external: true },
  { label: 'Research', to: 'https://polyedge.aitradepulse.com/docs/research/pitch-deck', external: true },
]

const landingCta = {
  primaryLabel: import.meta.env.VITE_LANDING_CTA_LABEL || 'Apply for Allocation',
  primaryUrl: import.meta.env.VITE_LANDING_CTA_URL || 'https://www.aipolymarket.xyz/',
  secondaryLabel: import.meta.env.VITE_LANDING_SECONDARY_CTA_LABEL || 'Read Investor Paper',
  secondaryUrl: import.meta.env.VITE_LANDING_SECONDARY_CTA_URL || 'https://polyedge.aitradepulse.com/docs/research/pitch-deck',
}

const tickerItems = [
  'LIVE',
  'AGI TRADING SYSTEM',
  'DOI 10.5281/ZENODO.16966978',
  '14+ STRATEGIES',
  '25 AUTONOMOUS EXPERIMENTS',
  '162 TRADES TRACKED',
  'PAPER · TESTNET · LIVE',
  'ON-CHAIN / DASHBOARD AUDIT',
]

const proofMetrics = [
  { label: 'Strategies', value: '14+', detail: 'registered strategy surface plus AGI Orchestrator' },
  { label: 'Experiments', value: '25', detail: 'autonomous lifecycle candidates under governance' },
  { label: 'Trades', value: '162', detail: 'tracked through decision, attempt, and settlement records' },
  { label: 'Paper', value: '33p', detail: 'research paper with 15 references and supplement' },
]

const problemCards = [
  {
    numeral: 'I',
    title: 'Regimes shift faster than hardcoded bots adapt.',
    body: 'A static strategy can look brilliant until liquidity, volatility, or event timing changes the market it was tuned for.',
  },
  {
    numeral: 'II',
    title: 'Human operators sleep while prediction markets move.',
    body: 'News, weather, CEX lead-lag, and whale flows can reprice markets long before a manual workflow responds.',
  },
  {
    numeral: 'III',
    title: 'Signals fragment across venues and evidence trails.',
    body: 'Allocators need to know why capital moved, not just that a bot clicked buy after a black-box score changed.',
  },
]

const superiorityPillars = [
  {
    title: 'AGI Strategy Factory',
    body: 'Creates, mutates, scores, promotes, and retires strategies through DRAFT → SHADOW → PAPER → LIVE stages.',
  },
  {
    title: 'Debate Before Capital',
    body: 'MiroFish bull/bear/judge validation challenges trades before execution so conviction has an inspectable adversary.',
  },
  {
    title: 'Self-Improving Risk Loop',
    body: 'Forensics, health checks, bankroll allocation, and deterministic gates convert outcomes into the next generation.',
  },
]

const decisionFlow = [
  { step: '01', action: 'Market signal detected', confidence: '0.74', edge: '+6.2%', verdict: 'candidate', gate: 'observe' },
  { step: '02', action: 'Strategy proposes trade', confidence: '0.79', edge: '+7.8%', verdict: 'bull case formed', gate: 'debate' },
  { step: '03', action: 'Debate validates or rejects', confidence: '0.81', edge: '+5.9%', verdict: 'judge: pass', gate: 'risk' },
  { step: '04', action: 'Risk manager sizes or blocks', confidence: '0.81', edge: '+5.9%', verdict: 'bounded Kelly', gate: 'size' },
  { step: '05', action: 'Order attempt is logged', confidence: '0.81', edge: '+5.9%', verdict: 'attempt recorded', gate: 'audit' },
  { step: '06', action: 'Forensics feed evolution', confidence: 'settled', edge: 'post-trade', verdict: 'learn', gate: 'evolve' },
]

const researchAssets = [
  { label: 'Paper PDF', meta: '33 pages · 15 references', href: 'https://polyedge.aitradepulse.com/paper/paper.pdf' },
  { label: 'Supplementary PDF', meta: 'proofs · genome grammar · code listings', href: 'https://polyedge.aitradepulse.com/paper/supplementary.pdf' },
  { label: 'Abstract Video', meta: '50-second research overview', href: 'https://polyedge.aitradepulse.com/paper/abstract_video.mp4' },
  { label: 'Dashboard Audit', meta: 'operator-facing evidence surface', href: '/dashboard' },
]

const allocationChecks = [
  'Governed autonomy, not blind bot execution',
  'Research artifacts for technical diligence',
  'Deterministic risk gates before capital deployment',
  'Trade attempts and outcomes captured as structured evidence',
]

const trustAnchors = ['PolyEdge v4.0', 'Polymarket', 'Kalshi', 'MiroFish', 'StrategyGenome', 'Deterministic risk gates']

const isExternalUrl = (href: string) => href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('tel:')

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
  const repeatedTicker = [...tickerItems, ...tickerItems]

  return (
    <div className="min-h-screen overflow-hidden bg-[#050403] text-stone-200 selection:bg-emerald-400/30 selection:text-emerald-50">
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
                <span className="block text-[8px] font-bold uppercase tracking-[0.34em] text-stone-500">Allocation memo</span>
              </span>
            </Link>

            <div className="ml-auto flex items-center justify-end gap-2 sm:gap-3">
              {navLinks.map(link => (
                link.external ? (
                  <ExternalLink
                    key={link.label}
                    href={link.to}
                    className="border border-stone-800 bg-black/40 px-3 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-stone-400 transition-all hover:border-amber-300/40 hover:bg-amber-300/10 hover:text-amber-100 sm:px-4"
                  >
                    {link.label}
                  </ExternalLink>
                ) : (
                  <Link
                    key={link.label}
                    to={link.to}
                    className="border border-emerald-300/35 bg-emerald-300/10 px-3 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-emerald-200 transition-all hover:bg-emerald-300/20 sm:px-4"
                  >
                    {link.label}
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
              <span className="border border-emerald-300/25 bg-emerald-300/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.3em] text-emerald-200">AGI Trading System</span>
              <span className="border border-amber-300/25 bg-amber-300/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.3em] text-amber-200">Investor dossier</span>
              <span className="border border-stone-800 bg-black/35 px-3 py-1 text-[10px] font-black uppercase tracking-[0.3em] text-stone-500">Paper · dashboard · risk gates</span>
            </div>

            <p className="mb-5 text-[11px] font-black uppercase tracking-[0.5em] text-amber-300/70">Static bots die when regimes shift</p>
            <h1 className="max-w-5xl font-serif text-6xl font-black leading-[0.86] tracking-[-0.075em] text-stone-50 sm:text-8xl lg:text-9xl">
              PolyEdge evolves.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-stone-300 sm:text-xl">
              Not a trading bot. An AGI Trading System that creates strategies, debates trades, sizes capital, executes under deterministic risk gates, diagnoses losses, and evolves the next generation.
            </p>
            <p className="mt-5 max-w-2xl text-sm leading-7 text-stone-500">
              Built for prediction-market allocators who need proof, governance, and audit trails before capital touches Polymarket or Kalshi.
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
            <p className="mt-3 text-[10px] uppercase tracking-[0.24em] text-stone-700">CTA configured through VITE_LANDING_* environment variables.</p>
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
                <span className="text-[10px] font-black uppercase tracking-[0.32em] text-stone-500">Dossier evidence</span>
                <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.24em] text-emerald-300">
                  <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.85)]" />
                  Live thesis
                </span>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3">
                {proofMetrics.map((metric, index) => (
                  <motion.div
                    key={metric.label}
                    initial={{ opacity: 0, y: 18 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.45, delay: 0.22 + index * 0.08 }}
                    className="border border-stone-800 bg-black/45 p-4"
                  >
                    <div className="font-serif text-4xl font-black tracking-[-0.08em] text-amber-200">{metric.value}</div>
                    <div className="mt-2 text-[10px] font-black uppercase tracking-[0.22em] text-stone-400">{metric.label}</div>
                    <div className="mt-2 text-[10px] leading-5 text-stone-600">{metric.detail}</div>
                  </motion.div>
                ))}
              </div>

              <div className="mt-5 border border-emerald-300/20 bg-emerald-300/10 p-5">
                <div className="text-[10px] font-black uppercase tracking-[0.28em] text-emerald-200">Primary claim</div>
                <p className="mt-3 font-serif text-2xl leading-8 text-stone-100">
                  Governed autonomy: staged, measured, debated, and audited before capital scales.
                </p>
              </div>
            </div>
          </motion.aside>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionLabel number="01" label="Problem" />
          <div className="grid gap-4 lg:grid-cols-3">
            {problemCards.map((card, index) => (
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
          <SectionLabel number="02" label="Breakthrough" />
          <div className="grid gap-8 border border-amber-300/20 bg-gradient-to-br from-amber-300/10 via-[#090805] to-black p-6 sm:p-9 lg:grid-cols-[0.9fr_1.1fr]">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.38em] text-emerald-200">Best superiority</p>
              <h2 className="mt-5 max-w-3xl font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                AGI Trading Systems beat static bots.
              </h2>
              <p className="mt-6 text-sm leading-7 text-stone-400">
                Static bots execute a rule. PolyEdge runs a governed research loop: form hypotheses, challenge them, deploy only under gates, diagnose failures, and compound what survives.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {superiorityPillars.map((pillar, index) => (
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
            <SectionLabel number="03" label="Mechanism" />
            <h2 className="font-serif text-5xl font-black leading-[0.92] tracking-[-0.06em] text-stone-50 sm:text-6xl">
              Every trade becomes an audit row.
            </h2>
            <p className="mt-6 text-sm leading-7 text-stone-500">
              The mechanism is designed for diligence: signal, proposal, debate, risk sizing, order attempt, settlement, and forensics stay legible.
            </p>
          </div>

          <div className="overflow-hidden border border-stone-800 bg-[#070604]/88">
            <div className="grid grid-cols-[56px_1.3fr_0.62fr_0.62fr_0.82fr_0.58fr] border-b border-stone-800 bg-stone-950/80 px-4 py-3 text-[9px] font-black uppercase tracking-[0.22em] text-stone-500">
              <span>ID</span>
              <span>Decision flow</span>
              <span>Conf.</span>
              <span>Edge</span>
              <span>Verdict</span>
              <span>Gate</span>
            </div>
            {decisionFlow.map((row, index) => (
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
          <SectionLabel number="04" label="Proof" />
          <div className="grid gap-8 lg:grid-cols-[1.03fr_0.97fr]">
            <div className="border border-stone-800 bg-black/45 p-6 sm:p-9">
              <p className="text-[10px] font-black uppercase tracking-[0.38em] text-emerald-200">Research-backed diligence</p>
              <h2 className="mt-5 font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                Read the paper before you wire.
              </h2>
              <p className="mt-6 text-sm leading-7 text-stone-500">
                The research package documents the bounded AGI autonomy framework, StrategyGenome grammar, dual-debate validation, and operational evidence. It states limitations instead of pretending autonomy is magic.
              </p>
              <div className="mt-8 grid grid-cols-2 gap-3">
                {proofMetrics.map(metric => (
                  <div key={metric.label} className="border border-stone-800 bg-stone-950/60 p-4">
                    <div className="font-serif text-3xl font-black tracking-[-0.06em] text-emerald-200">{metric.value}</div>
                    <div className="mt-1 text-[10px] font-black uppercase tracking-[0.2em] text-stone-500">{metric.label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              {researchAssets.map(asset => (
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
                <SectionLabel number="05" label="Allocation" />
                <h2 className="max-w-4xl font-serif text-5xl font-black leading-[0.9] tracking-[-0.06em] text-stone-50 sm:text-7xl">
                  Back the AGI trading system that explains itself.
                </h2>
                <p className="mt-6 max-w-2xl text-sm leading-7 text-stone-400">
                  PolyEdge is an allocation funnel for governed autonomy: evidence-first dashboards, research artifacts, and deterministic promotion gates from experiment to capital deployment.
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
                  <span>Diligence checklist</span>
                  <span>No fabricated performance claims</span>
                </div>
                <div className="space-y-3">
                  {allocationChecks.map((check, index) => (
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
          <span>Bounded autonomy with deterministic risk gates</span>
        </div>
      </footer>
    </div>
  )
}
