'use client'

import { C } from '@/lib/theme'
import { usePageData, type TrafficPage } from '@/lib/api'
import { Shell, type ShellCtx } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Throughput } from '@/components/Throughput'
import { PlatformTable } from '@/components/PlatformTable'
import { ActivityMap } from '@/components/ActivityMap'
import { Kpis } from '@/components/Kpis'
import { Bar, Empty, Fa, Head, Row } from '@/components/ui'

/** رنگِ هر پسوند — همان استدلالِ رنگِ پلتفرم: رنگ داده است، نه تزئین. */
const EXT_HUE: Record<string, string> = {
  mp4: '#FF5C5C', mp3: '#FF9F1C', jpg: '#4CC9F0',
  pdf: '#C77DFF', zip: '#8CFFD6', other: '#7C9189',
}

/**
 * ۰۲ TRAFFIC — پاسخِ «در N روزِ گذشته چه گذشت؟»
 *
 * **نکتهٔ باربر، و در پنلِ فارسی هم برچسب خورده:** کارت‌هایی که از جدولِ
 * `jobs` می‌آیند هیچ دانلودی نمی‌بینند، چون `run_download` ردیفِ `Job`
 * نمی‌سازد. با اعدادِ تولید یعنی ~۷۹٪ کار در «کاراییِ عملیات» نامرئی است.
 * پس مرزِ **منبعِ داده** روی خودِ کارت نوشته شده، نه در یک پاورقی — کارتِ
 * بی‌برچسب همان چیزی است که یک‌بار اپراتور را گمراه کرد.
 */
export default function Page() {
  return (
    <Shell active="02" cmd="./ctl stats --range" ranges>
      {({ vals }) => <Body vals={vals} />}
    </Shell>
  )
}

function Body({ vals }: { vals: ShellCtx['vals'] }) {
  // بازه از پوسته می‌آید تا هر دو فراخوانی (`/api/console` و این یکی) یک
  // پنجره را بخوانند؛ دو بازهٔ مستقل یعنی KPI و جدول دربارهٔ دو چیز حرف بزنند.
  const state = usePageData<TrafficPage>('traffic', `range=${encodeURIComponent(vals.range)}`)
  const d = state.data
  return (
        <>
          <Kpis kpis={vals.kpis} />

          <Throughput
            rangeLabel={vals.range}
            trend={vals.trend}
            peak={vals.trendPeak}
            avg={vals.trendAvg}
            axis={vals.axis}
            latSpark={vals.latSpark}
            latNow={vals.latNow}
          />

          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
            <PlatformTable rows={vals.platformRows} />

            <Section label="OP PERFORMANCE" sigil="⌾" right="src: jobs · no downloads" rightColor={C.warn} pad="22px 14px 12px">
              <Head
                cols={[
                  { w: 88, label: 'OP' },
                  { w: 54, label: 'N', right: true },
                  { label: 'OK' },
                  { w: 46, label: 'P50', right: true },
                  { w: 54, label: 'P95', right: true },
                ]}
              />
              <PageState state={state}>
                {(d?.op_perf ?? []).map((o, i) => (
                  <Row key={o.op} last={i === (d?.op_perf.length ?? 0) - 1}>
                    <span style={{ width: 88, color: C.accHi }}>
                      <Fa>{o.op}</Fa>
                    </span>
                    <span style={{ width: 54, textAlign: 'right', color: C.inkLo }}>
                      {o.n.toLocaleString('en-US')}
                    </span>
                    <span style={{ flex: 1 }}>
                      {o.rate === null ? (
                        <span style={{ color: C.inkFaint, fontSize: 10 }}>—</span>
                      ) : (
                        <Bar pct={o.rate} width={11} color={o.rate >= 95 ? C.acc : C.warn} />
                      )}
                    </span>
                    <span style={{ width: 46, textAlign: 'right', color: C.inkLo }}>
                      <Fa>{o.avg}</Fa>
                    </span>
                    <span style={{ width: 54, textAlign: 'right', color: C.inkDim }}>
                      <Fa>{o.p95}</Fa>
                    </span>
                  </Row>
                ))}
                {d && !d.op_perf.length && <Empty>NO OPS IN THIS RANGE</Empty>}
              </PageState>
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.warn, letterSpacing: '.06em', lineHeight: 1.7 }}>
                downloads create no Job row — this card counts upload-side ops only.
              </div>
            </Section>
          </div>

          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
            <Section label="TOP ERRORS" sigil="☠" labelColor={C.bad} edge={C.errEdge} bg={C.errBg} right="grouped verbatim" pad="22px 14px 12px">
              <PageState state={state}>
                {(d?.errors ?? []).map((e, i) => (
                  <div
                    key={e.msg}
                    style={{
                      display: 'flex',
                      gap: 9,
                      padding: '6px 0',
                      fontSize: 10.5,
                      borderBottom: i === (d?.errors.length ?? 0) - 1 ? undefined : `1px solid ${C.errRow}`,
                      alignItems: 'baseline',
                    }}
                  >
                    <span style={{ color: C.badSoft, width: 34 }}>{e.n}×</span>
                    <span style={{ color: C.errInk, flex: 1, minWidth: 0, wordBreak: 'break-word' }}>
                      <Fa>{e.msg}</Fa>
                    </span>
                  </div>
                ))}
                {d && !d.errors.length && <Empty>NO ERRORS IN THIS RANGE</Empty>}
              </PageState>
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.7 }}>
                job.error carries no size, on purpose: a varying number would make every row a unique
                key with count 1 and this card would never surface the class.
              </div>
            </Section>

            <Section label="OUTPUT FORMATS" sigil="◨" right="src: files" pad="22px 14px 12px">
              <PageState state={state}>
                {(d?.by_ext ?? []).map((f, i) => (
                  <Row key={f.key} last={i === (d?.by_ext.length ?? 0) - 1}>
                    <span style={{ width: 62, color: EXT_HUE[f.key] ?? C.inkMid }}>{f.key || '—'}</span>
                    <span style={{ flex: 1 }}>
                      <Bar pct={f.pct} width={18} color={EXT_HUE[f.key] ?? C.acc} />
                    </span>
                    <span style={{ width: 34, textAlign: 'right', color: EXT_HUE[f.key] ?? C.acc }}>
                      {f.pct}%
                    </span>
                    <span style={{ width: 58, textAlign: 'right', color: C.inkLo }}>
                      {f.n.toLocaleString('en-US')}
                    </span>
                  </Row>
                ))}
                {d && !d.by_ext.length && <Empty>NO FILES IN THIS RANGE</Empty>}
              </PageState>
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.7 }}>
                from the files table, so downloads are included here — unlike the ops card.
              </div>
            </Section>
          </div>

          <ActivityMap heat={vals.heat} />
        </>
  )
}
