'use client'

import { C } from '@/lib/theme'
import { FORMATS, OP_PERF, TOP_ERRORS } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Throughput } from '@/components/Throughput'
import { PlatformTable } from '@/components/PlatformTable'
import { ActivityMap } from '@/components/ActivityMap'
import { Kpis } from '@/components/Kpis'
import { Bar, Head, Row } from '@/components/ui'

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
      {({ vals }) => (
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
              {OP_PERF.map((o, i) => (
                <Row key={o.op} last={i === OP_PERF.length - 1}>
                  <span style={{ width: 88, color: C.accHi }}>{o.op}</span>
                  <span style={{ width: 54, textAlign: 'right', color: C.inkLo }}>{o.n.toLocaleString('en-US')}</span>
                  <span style={{ flex: 1 }}>
                    <Bar pct={o.ok} width={11} color={o.ok >= 95 ? C.acc : C.warn} />
                  </span>
                  <span style={{ width: 46, textAlign: 'right', color: C.inkLo }}>{o.p50}</span>
                  <span style={{ width: 54, textAlign: 'right', color: C.inkDim }}>{o.p95}</span>
                </Row>
              ))}
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.warn, letterSpacing: '.06em', lineHeight: 1.7 }}>
                downloads create no Job row — this card counts upload-side ops only.
              </div>
            </Section>
          </div>

          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
            <Section label="TOP ERRORS" sigil="☠" labelColor={C.bad} edge={C.errEdge} bg={C.errBg} right="grouped verbatim" pad="22px 14px 12px">
              {TOP_ERRORS.map((e, i) => (
                <div
                  key={e.msg}
                  style={{
                    display: 'flex',
                    gap: 9,
                    padding: '6px 0',
                    fontSize: 10.5,
                    borderBottom: i === TOP_ERRORS.length - 1 ? undefined : `1px solid ${C.errRow}`,
                    alignItems: 'baseline',
                  }}
                >
                  <span style={{ color: C.badSoft, width: 34 }}>{e.n}×</span>
                  <span style={{ color: C.errInk, flex: 1, minWidth: 0, wordBreak: 'break-word' }}>{e.msg}</span>
                </div>
              ))}
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.7 }}>
                job.error carries no size, on purpose: a varying number would make every row a unique
                key with count 1 and this card would never surface the class.
              </div>
            </Section>

            <Section label="OUTPUT FORMATS" sigil="◨" right="src: files" pad="22px 14px 12px">
              {FORMATS.map((f, i) => (
                <Row key={f.ext} last={i === FORMATS.length - 1}>
                  <span style={{ width: 62, color: EXT_HUE[f.ext] ?? C.inkMid }}>{f.ext}</span>
                  <span style={{ flex: 1 }}>
                    <Bar pct={f.pct * 2} width={18} color={EXT_HUE[f.ext] ?? C.acc} />
                  </span>
                  <span style={{ width: 34, textAlign: 'right', color: EXT_HUE[f.ext] ?? C.acc }}>{f.pct}%</span>
                  <span style={{ width: 58, textAlign: 'right', color: C.inkLo }}>
                    {f.n.toLocaleString('en-US')}
                  </span>
                </Row>
              ))}
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.7 }}>
                from the files table, so downloads are included here — unlike the ops card.
              </div>
            </Section>
          </div>

          <ActivityMap heat={vals.heat} />
        </>
      )}
    </Shell>
  )
}
